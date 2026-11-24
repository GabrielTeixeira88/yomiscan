import test from "node:test";
import assert from "node:assert/strict";
import {analyzeLexical, chooseMatches, findGrammar, findUnits, hiragana, inflectionLabels, loadGrammar, loadUnitRules, lookupCandidates,
  symbolic, type DictionaryEntry, type JapaneseToken} from "../src/engine/lexical";
import {decodeEntry, fromLindera, toAnalysis} from "../src/engine/lexicon";

const token = (surface: string, pos: string | null, extra: Partial<JapaneseToken> = {}): JapaneseToken => ({surface, lemma: surface, reading: null,
  part_of_speech: pos, conjugation_type: null, conjugation_form: null, orthographic_base: surface, lemma_reading: null, ...extra});
const entry = (id: number, spellings: string[], readings: string[], pos: string[][], priority: Record<string, string[]> = {}): DictionaryEntry =>
  ({entry_id: id, spellings, readings: readings.map(text => ({text, spellings: [], no_kanji: false})),
    senses: pos.map(p => ({glosses: ['g' + id], parts_of_speech: p, spellings: [], readings: [], notes: [], labels: []})), form_priority: priority});

test("kana helpers match japanese.py", () => {
  assert.equal(hiragana("カタカナｶﾞ"), "かたかなが");
  assert.ok(symbolic("！？…　") && symbolic("") && !symbolic("猫！"));
});

test("lookup candidates: orthographic base, lemma, surface, base reading; none for punctuation", () => {
  assert.deepEqual(lookupCandidates(token("食べ", "動詞", {lemma: "食べる", orthographic_base: "食べる", lemma_reading: "たべる"})), ["食べる", "食べ", "たべる"]);
  assert.deepEqual(lookupCandidates(token("。", "補助記号")), []);
});

test("particles keep only agreeing entries; a later form wins only on better POS agreement", () => {
  const dict = new Map<string, DictionaryEntry[]>([
    ["は", [entry(1, ["歯"], ["は"], [["noun (common) (futsuumeishi)"]]), entry(2, [], ["は"], [["particle"]])]],
    ["ん", [entry(3, [], ["ん"], [["interjection (kandoushi)"], ["particle"]])]], ["の", [entry(4, [], ["の"], [["particle"]])]]]);
  const lookup = (form: string) => dict.get(form) ?? [];
  assert.deepEqual(chooseMatches(token("は", "助詞 / 係助詞"), ["は"], lookup)[1].map(e => e.entry_id), [2]);
  const [form, ranked] = chooseMatches(token("ん", "助詞 / 準体助詞", {lemma: "の", orthographic_base: "ん"}), ["ん", "の"], lookup);
  assert.equal(form, "の");assert.deepEqual(ranked.map(e => e.entry_id), [4]);
});

test("ranking: kanji lemma spelling, then POS, headword, reading, common, nf band, order", () => {
  const candidates = [entry(10, ["件"], ["こと"], [["noun (common) (futsuumeishi)"]]), entry(11, ["事"], ["こと"], [["noun (common) (futsuumeishi)"]]),
    entry(12, [], ["こと"], [["noun (common) (futsuumeishi)"]], {"こと": ["ichi1", "nf05"]})];
  const [, ranked] = chooseMatches(token("こと", "名詞 / 普通名詞", {lemma: "事", orthographic_base: "こと"}), ["こと"], () => candidates);
  assert.deepEqual(ranked.map(e => e.entry_id), [11, 12, 10]);
});

test("units: global longest match, functional edges only, verb spans exclude bare particles", () => {
  const tokens = [token("そう", "副詞"), token("か", "助詞 / 終助詞"), token("も", "助詞 / 係助詞"), token("しれ", "動詞", {lemma: "知れる", orthographic_base: "知れる", conjugation_form: "未然形"}),
    token("ない", "助動詞", {lemma: "ない", orthographic_base: "ない"})];
  const dict = new Map<string, DictionaryEntry[]>([["そうか", [entry(20, [], ["そうか"], [["expressions (phrases, clauses, etc.)"]])]],
    ["かもしれない", [entry(21, [], ["かもしれない"], [["expressions (phrases, clauses, etc.)"]])]]]);
  const units = findUnits(tokens, f => dict.get(f) ?? [], loadUnitRules());
  assert.deepEqual(units.map(([u]) => [u.start, u.end, u.lookup_form]), [[1, 5, "かもしれない"]]);
  const pigeon = new Map([["はと", [entry(22, ["鳩"], ["はと"], [["noun (common) (futsuumeishi)"]])]]]);
  assert.equal(findUnits([token("は", "助詞 / 係助詞"), token("と", "助詞 / 格助詞")], f => pigeon.get(f) ?? []).length, 0);
});

test("grammar: longest match per start, nested matches dropped, 'after' constraint honoured", () => {
  const patterns = loadGrammar({schema_version: 1, patterns: [
    {id: "te-mo", name: "〜ても", forms: ["ても"], meaning: "even if", alternatives: [[{surface: ["て"]}, {surface: ["も"]}]], after: {pos: ["動詞"]}},
    {id: "te-mo-ii", name: "〜てもいい", forms: ["てもいい"], meaning: "may", alternatives: [[{surface: ["て"]}, {surface: ["も"]}, {base: ["良い"]}]], after: {pos: ["動詞"]}},
    {id: "mo", name: "も", forms: ["も"], meaning: "also", alternatives: [[{surface: ["も"]}]]}]});
  const tokens = [token("食べ", "動詞"), token("て", "助詞"), token("も", "助詞"), token("いい", "形容詞", {lemma: "良い", orthographic_base: "いい"})];
  assert.deepEqual(findGrammar(tokens, patterns), [{pattern: "te-mo-ii", start: 1, end: 4}]);
  assert.deepEqual(findGrammar([token("僕", "代名詞"), token("て", "助詞"), token("も", "助詞")], patterns), [{pattern: "mo", start: 2, end: 3}]);
});

test("inflection: labels on the head, followers consumed (高くなかった is one word)", () => {
  const labels = inflectionLabels([token("高く", "形容詞", {lemma: "高い", orthographic_base: "高い", conjugation_form: "連用形-一般"}),
    token("なかっ", "助動詞", {lemma: "ない", orthographic_base: "ない", conjugation_form: "連用形-促音便"}),
    token("た", "助動詞", {lemma: "た", orthographic_base: "た", conjugation_form: "終止形-一般"})]);
  assert.deepEqual(labels, [["negative", "past"], [], []]);
});

test("lindera fields map to the backend token shape; JMdict payloads and the Study response decode", () => {
  const t = fromLindera({surface: "食べ", details: ["動詞", "一般", "*", "*", "下一段-バ行", "連用形-一般", "タベル", "食べる", "食べ", "タベ", "食べる", "和"]});
  assert.deepEqual(t, {surface: "食べ", lemma: "食べる", reading: "たべ", part_of_speech: "動詞 / 一般", conjugation_type: "下一段-バ行",
    conjugation_form: "連用形-一般", orthographic_base: "食べる", lemma_reading: "たべる"});
  const decoded = decodeEntry(JSON.stringify({entry_id: 7, spellings: ["食べる"], readings: [{text: "たべる", spellings: [], no_kanji: false}],
    senses: [{glosses: ["to eat"], parts_of_speech: ["Ichidan verb", "transitive verb"]}], form_priority: {"食べる": ["ichi1"]}}));
  assert.deepEqual(decoded.senses[0].notes, []);
  const result = analyzeLexical("食べ", [t], form => form === "食べる" ? [decoded] : []);
  const analysis = toAnalysis(result, null);
  assert.equal(analysis.tokens[0].dictionary_form, "食べる");
  assert.equal(analysis.tokens[0].meanings[0].glosses[0], "to eat");
  assert.equal(analysis.provenance?.engine_kind, "browser");
});
