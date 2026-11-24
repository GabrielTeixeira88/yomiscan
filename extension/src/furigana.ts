// Furigana alignment: split a word into kanji runs (with their reading) and kana runs.
// 食べ + たべ -> 食(た) べ; 気を付ける + きをつける -> 気(き) を 付(つ) ける. Kana runs anchor the
// reading; each kanji run takes the reading between its anchors. If the reading cannot be
// aligned (irregular readings such as 今日 inside a kana-anchored word), the whole word gets one
// reading instead of a wrong split. Pure and DOM-free, so a browser engine can reuse it.

export interface FuriganaSegment { text: string; reading?: string }

const KANJI = /[\p{Script=Han}々〆ヶ]/u;

/** Katakana to hiragana (readings and kana anchors are compared in hiragana). ヵ/ヶ are counters
 * (ヶ月), treated like kanji, so they stay unchanged. */
export function hiragana(text: string): string {
  return text.replace(/[ァ-ヴ]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60));
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function furigana(surface: string, reading: string | null | undefined): FuriganaSegment[] {
  if (!reading || !KANJI.test(surface)) return [{text: surface}];
  const runs: {text: string; kanji: boolean}[] = [];
  for (const ch of surface) {
    const kanji = KANJI.test(ch), last = runs.at(-1);
    if (last && last.kanji === kanji) last.text += ch; else runs.push({text: ch, kanji});
  }
  const target = hiragana(reading);
  const pattern = new RegExp("^" + runs.map(run => run.kanji ? "(.+?)" : escape(hiragana(run.text))).join("") + "$", "u");
  const match = target.match(pattern);
  if (!match) return [{text: surface, reading: target}];
  let group = 1;
  return runs.map(run => run.kanji ? {text: run.text, reading: match[group++]} : {text: run.text});
}
