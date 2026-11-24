import test from "node:test";
import assert from "node:assert/strict";
import {furigana, hiragana} from "../src/furigana";

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
