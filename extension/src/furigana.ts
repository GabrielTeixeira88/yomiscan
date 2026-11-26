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

/** Card setting: furigana over the Japanese sentence for no words, unknown words only (the
 * default: words not marked known), or all words. */
export type FuriganaMode = 'off' | 'unknown' | 'all';
export const FURIGANA_KEY = 'yomiscanFurigana';
export const furiganaMode = (value: unknown): FuriganaMode => value === 'off' || value === 'all' ? value : 'unknown';

/**
 * The whole sentence as segments, with furigana over the tokens `wanted` picks. Each token is
 * found in the text from where the previous one ended; text the tokens do not cover (spaces, line
 * breaks, or a token the tokenizer normalized) stays plain, so the segments always join back to
 * exactly `text`.
 */
export function sentenceFurigana(text: string, tokens: {surface: string; reading: string | null}[],
  wanted: (index: number) => boolean): FuriganaSegment[] {
  const segments: FuriganaSegment[] = [];
  const plain = (part: string) => {
    if (!part) return;
    const last = segments.at(-1);
    if (last && last.reading === undefined) last.text += part; else segments.push({text: part});
  };
  let at = 0;
  tokens.forEach((token, index) => {
    const found = token.surface ? text.indexOf(token.surface, at) : -1;
    if (found < 0) return;
    plain(text.slice(at, found));
    for (const segment of wanted(index) ? furigana(token.surface, token.reading) : [{text: token.surface}])
      if (segment.reading === undefined) plain(segment.text); else segments.push(segment);
    at = found + token.surface.length;
  });
  plain(text.slice(at));
  return segments;
}
