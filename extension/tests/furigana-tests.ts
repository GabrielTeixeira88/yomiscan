import test from "node:test";
import assert from "node:assert/strict";
import {furigana, furiganaMode, hiragana, sentenceFurigana} from "../src/furigana";

test("furigana keeps okurigana outside the ruby", () => {
  assert.deepEqual(furigana("食べ", "たべ"), [{text: "食", reading: "た"}, {text: "べ"}]);
  assert.deepEqual(furigana("気を付ける", "きをつける"),
    [{text: "気", reading: "き"}, {text: "を"}, {text: "付", reading: "つ"}, {text: "ける"}]);
  assert.deepEqual(furigana("美味しかっ", "おいしかっ"), [{text: "美味", reading: "おい"}, {text: "しかっ"}]);
});

test("furigana: whole kanji runs, katakana readings and kana-only words", () => {
  assert.deepEqual(furigana("時間跳躍", "ジカンチョウヤク"), [{text: "時間跳躍", reading: "じかんちょうやく"}]);
  assert.deepEqual(furigana("ねこ", "ねこ"), [{text: "ねこ"}]);
  assert.deepEqual(furigana("猫", null), [{text: "猫"}]);
  assert.equal(hiragana("ヶ月ヴ"), "ヶ月ゔ");
});

test("unalignable readings fall back to one reading for the whole word", () => {
  // The kana anchor る is missing from the reading, so no split is guessed.
  assert.deepEqual(furigana("来る", "きた"), [{text: "来る", reading: "きた"}]);
});

test("sentence furigana covers only the wanted tokens and always joins back to the exact text", () => {
  const tokens = [{surface: "猫", reading: "ネコ"}, {surface: "が", reading: "ガ"}, {surface: "魚", reading: "サカナ"},
    {surface: "を", reading: "ヲ"}, {surface: "食べ", reading: "タベ"}, {surface: "た", reading: "タ"}];
  const text = "猫が 魚を\n食べた！";
  const all = sentenceFurigana(text, tokens, () => true);
  assert.deepEqual(all, [{text: "猫", reading: "ねこ"}, {text: "が "}, {text: "魚", reading: "さかな"}, {text: "を\n"},
    {text: "食", reading: "た"}, {text: "べた！"}]);
  const unknown = sentenceFurigana(text, tokens, i => i !== 0);
  assert.deepEqual(unknown.slice(0, 2), [{text: "猫が "}, {text: "魚", reading: "さかな"}]);
  assert.deepEqual(sentenceFurigana(text, tokens, () => false), [{text}]);
  // A token the tokenizer changed (here: not in the text) is skipped; nothing is lost or repeated.
  const odd = sentenceFurigana("ＡＢ猫", [{surface: "AB", reading: null}, {surface: "猫", reading: "ねこ"}], () => true);
  assert.equal(odd.map(s => s.text).join(""), "ＡＢ猫");
  assert.deepEqual(odd.at(-1), {text: "猫", reading: "ねこ"});
});

test("the furigana setting defaults to unknown words only", () => {
  assert.equal(furiganaMode(undefined), "unknown"); assert.equal(furiganaMode("bogus"), "unknown");
  assert.equal(furiganaMode("off"), "off"); assert.equal(furiganaMode("all"), "all");
});
