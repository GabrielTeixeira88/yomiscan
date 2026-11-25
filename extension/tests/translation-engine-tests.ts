import test from "node:test";
import assert from "node:assert/strict";
import {beamSearch, type NextLogits} from "../src/engine/translation";
import {combineAnalyses} from "../src/engine/engine";
import {parseEngineChoice} from "../src/engine-mode";
import type {Analysis} from "../src/api";

test("Study blocks combine as analyze_recognized_blocks: joined text, shifted unit and grammar spans", () => {
  const part = (text: string, translation: string | null, tokens: number): Analysis => ({original_text: text, translation,
    processing: {ocr_ms: 0, translation_ms: 10, analysis_ms: 1, total_ms: 11},
    tokens: Array.from({length: tokens}, (_, i) => ({surface: text[i] ?? 'x', reading: null, lemma: null, dictionary_form: null, part_of_speech: null,
      conjugation_type: null, conjugation_form: null, meanings: []})),
    units: [{surface: 'u', dictionary_form: 'u', start_token: 0, end_token: 2, meanings: []}],
    grammar: [{id: 'g', name: 'g', meaning: 'm', start_token: 1, end_token: 2}], provenance: {engine_kind: 'browser'}});
  const combined = combineAnalyses([part("あいう", "A", 3), part("えお", "B", 2)]);
  assert.equal(combined.original_text, "あいう\nえお");
  assert.equal(combined.translation, "A\nB");
  assert.equal(combined.tokens.length, 5);
  assert.deepEqual(combined.units!.map(u => [u.start_token, u.end_token]), [[0, 2], [3, 5]]);
  assert.deepEqual(combined.grammar!.map(g => [g.start_token, g.end_token]), [[1, 2], [4, 5]]);
  assert.equal(combined.processing.translation_ms, 20);
  assert.equal(combineAnalyses([part("あ", "A", 1), part("い", null, 1)]).translation, null, "a missing translation is never invented");
});

test("engine choice is Automatic unless the user picked an engine", () => {
  assert.equal(parseEngineChoice('browser'), 'browser');
  assert.equal(parseEngineChoice('local'), 'local');
  for (const value of [undefined, null, 'auto', 'gpu', 1]) assert.equal(parseEngineChoice(value), 'auto');
});

// Toy decoder: vocab 0 = pad, 1 = eos, 2..4 words. Logits depend only on the last token.
const table: Record<number, number[]> = {0: [9, 0, 3, 2.9, 1], 2: [9, 0, 0, 0, 4], 3: [9, 5, 0, 0, 0], 4: [9, 6, 0, 0, 0]};
const toy: NextLogits = async sequences => Float32Array.from(sequences.flatMap(s => table[s[s.length - 1]]));

test("beam search bans the pad token and returns the best finished hypothesis", async () => {
  const result = await beamSearch({next: toy, vocabSize: 5, numBeams: 2, startId: 0, eosId: 1, maxLength: 10, bannedTokens: [0], renormalize: true});
  assert.equal(result.done, true);
  assert.equal(result.tokens[0], 0);
  assert.equal(result.tokens.at(-1), 1);
  assert.ok(!result.tokens.slice(1).includes(0), "the banned pad token never appears after the start token");
  // 0 → 2 → 4 → eos scores higher than 0 → 3 → eos despite 2 and 3 starting almost even.
  assert.deepEqual(result.tokens, [0, 2, 4, 1]);
});

test("beam search stops at the length limit and reports an unfinished hypothesis there", async () => {
  const loop: NextLogits = async sequences => Float32Array.from(sequences.flatMap(() => [0, -50, 5, 0, 0]));
  const result = await beamSearch({next: loop, vocabSize: 5, numBeams: 2, startId: 0, eosId: 1, maxLength: 4});
  assert.equal(result.tokens.length, 4);
  assert.notEqual(result.tokens.at(-1), 1);
});

test("parents identify which running beam each next step continues", async () => {
  const seen: (number[] | null)[] = [];
  const recording: NextLogits = async (sequences, parents) => {seen.push(parents && [...parents]); return toy(sequences, parents);};
  await beamSearch({next: recording, vocabSize: 5, numBeams: 2, startId: 0, eosId: 1, maxLength: 10, bannedTokens: [0], renormalize: true});
  assert.equal(seen[0], null);
  assert.ok(seen.slice(1).every(p => p !== null && p.length === 2 && p.every(i => i === 0 || i === 1)));
});
