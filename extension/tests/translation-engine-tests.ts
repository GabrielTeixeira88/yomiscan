import test from "node:test";
import assert from "node:assert/strict";
import {beamSearch, type NextLogits} from "../src/engine/translation";

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
