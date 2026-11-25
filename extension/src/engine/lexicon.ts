// Browser lexicon adapters (Stage 5a increment 2):
// - JMdict: the backend's own SQLite database (schema 1 or 2) opened in memory with sqlite-wasm,
//   queried exactly as yomiscan.dictionary.sqlite.SQLiteDictionary.lookup does.
// - Tokenizer: lindera-wasm-unidic (UniDic), mapped to the backend's JapaneseToken fields as
//   validated in Stage 2 (research/stage-2/browser/tokenize-golden.mjs).
// - The Study response shape (api/models.py ImageAnalysisResponse.from_analysis).
import type {Analysis, GrammarNote, Meaning, Token, Unit} from '../api';
import {grammarPattern, hiragana, type DictionaryEntry, type JapaneseToken, type LexicalResult} from './lexical';

// ---- JMdict ----------------------------------------------------------------------------------

/** The subset of the sqlite-wasm oo1 API this adapter uses (browser and Node builds alike). */
export interface SqliteStatement {bind(values: unknown[]): unknown; step(): boolean; get(index: number): unknown; reset(): unknown; finalize(): unknown}
export interface SqliteDatabase {prepare(sql: string): SqliteStatement; selectValue(sql: string): unknown; close(): void; pointer?: number}
export interface Sqlite3 {oo1: {DB: new (name: string) => SqliteDatabase}; wasm: {allocFromTypedArray(bytes: Uint8Array): number};
  capi: {sqlite3_deserialize(db: number, schema: string, pointer: number, size: number, capacity: number, flags: number): number;
    SQLITE_DESERIALIZE_FREEONCLOSE: number; SQLITE_DESERIALIZE_READONLY: number}}

export const SUPPORTED_SCHEMAS = [1, 2];

export function decodeEntry(payload: string): DictionaryEntry {
  const data = JSON.parse(payload);
  return {entry_id: data.entry_id, spellings: data.spellings, readings: data.readings.map((r: DictionaryEntry['readings'][number]) =>
    ({text: r.text, spellings: r.spellings, no_kanji: r.no_kanji})),
    senses: data.senses.map((s: Record<string, string[]>) => ({glosses: s.glosses, parts_of_speech: s.parts_of_speech, spellings: s.spellings ?? [],
      readings: s.readings ?? [], notes: s.notes ?? [], labels: s.labels ?? []})),
    form_priority: data.form_priority ?? {}};
}

export class JmdictDatabase {
  private statement: SqliteStatement;
  readonly schema: number;
  private constructor(private db: SqliteDatabase) {
    this.schema = Number(db.selectValue('PRAGMA user_version'));
    if (!SUPPORTED_SCHEMAS.includes(this.schema)) {db.close(); throw new Error('Unsupported JMdict schema; rebuild the dictionary artifact.');}
    this.statement = db.prepare('SELECT e.payload FROM forms f JOIN entries e USING (entry_id) WHERE f.form = ? ORDER BY e.entry_id');
  }
  /** Open the database bytes in memory, read-only (sqlite3_deserialize). */
  static open(sqlite3: Sqlite3, bytes: Uint8Array): JmdictDatabase {
    const db = new sqlite3.oo1.DB(':memory:'), pointer = sqlite3.wasm.allocFromTypedArray(bytes);
    const rc = sqlite3.capi.sqlite3_deserialize(db.pointer!, 'main', pointer, bytes.byteLength, bytes.byteLength,
      sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_READONLY);
    if (rc) {db.close(); throw new Error(`Cannot open the JMdict database (sqlite3_deserialize ${rc})`);}
    return new JmdictDatabase(db);
  }
  lookup(text: string): DictionaryEntry[] {
    if (!text) return [];
    const out: DictionaryEntry[] = [];
    try {
      this.statement.bind([hiragana(text)]);
      while (this.statement.step()) out.push(decodeEntry(String(this.statement.get(0))));
    } finally {this.statement.reset();}
    return out;
  }
  close(): void {this.statement.finalize(); this.db.close();}
}

// ---- tokenizer -------------------------------------------------------------------------------

export interface LinderaToken {surface: string; details: string[]}
const value = (v: string | undefined) => v && v !== '*' ? v : null;

/** UniDic details: pos1-4, cType, cForm, lForm, lemma, orth, pron, orthBase, ... */
export function fromLindera(token: LinderaToken): JapaneseToken {
  const d = token.details, reading = value(d[9]), base = value(d[6]);
  return {surface: token.surface, lemma: value(d[7]), reading: reading ? hiragana(reading) : null,
    part_of_speech: [d[0], d[1], d[2], d[3]].map(value).filter(Boolean).join(' / ') || null,
    conjugation_type: value(d[4]), conjugation_form: value(d[5]), orthographic_base: value(d[10]),
    lemma_reading: base ? hiragana(base) : null};
}

// ---- Study response ------------------------------------------------------------------------

const KANJI = /[㐀-䶿一-鿿豈-﫿\u{20000}-\u{323af}々〆ヶ]/u;

/** headword.dictionary_reading: the JMdict reading of `form` in its best entry (食べた -> 食べる, たべる);
 * `hints` (hiragana readings) break ties, in order. Same cases: backend/tests/headword_cases.json. */
export function dictionaryReading(form: string | null, entry: DictionaryEntry | undefined, hints: readonly (string | null)[]): string | null {
  if (!form) return null;
  const known = hints.filter((hint): hint is string => !!hint);
  if (!KANJI.test(form)) return entry?.readings.find(r => hiragana(r.text) === hiragana(form))?.text ?? form;
  if (!entry || !entry.spellings.includes(form)) return known[0] ?? null;
  const candidates = entry.readings.filter(r => !r.no_kanji && (!r.spellings.length || r.spellings.includes(form))).map(r => r.text);
  for (const hint of known) {
    const match = candidates.find(candidate => hiragana(candidate) === hint);
    if (match) return match;
  }
  return candidates[0] ?? known[0] ?? null;
}

const meanings = (ids: readonly number[], entries: Map<number, DictionaryEntry>): Meaning[] =>
  ids.flatMap(id => entries.get(id)!.senses.map(sense => ({entry_id: id, glosses: sense.glosses, parts_of_speech: sense.parts_of_speech,
    spellings: sense.spellings, readings: sense.readings, notes: sense.notes, labels: sense.labels})));

/** ImageAnalysisResponse.from_analysis for a browser lexical result (translation added later). */
export function toAnalysis(result: LexicalResult, translation: string | null, provenance: Record<string, unknown> = {}): Analysis {
  const best = (ids: readonly number[]) => ids.length ? result.dictionary_entries.get(ids[0]) : undefined;
  const tokens: Token[] = result.tokens.map(item => {
    const form = item.lookup_form || item.token.orthographic_base || item.token.lemma;
    return {surface: item.token.surface, reading: item.token.reading, lemma: item.token.lemma,
      dictionary_form: form, part_of_speech: item.token.part_of_speech,
      conjugation_type: item.token.conjugation_type, conjugation_form: item.token.conjugation_form, inflection: item.inflection,
      meanings: meanings(item.entry_ids, result.dictionary_entries),
      dictionary_reading: dictionaryReading(form, best(item.entry_ids), [item.token.surface === form ? item.token.reading : null, item.token.lemma_reading])};
  });
  const units: Unit[] = result.units.map(u => {
    const parts = result.tokens.slice(u.start, u.end).map(item => item.token.reading);
    const spoken = u.surface === u.lookup_form && parts.every(Boolean) ? parts.join('') : null;
    return {surface: u.surface, dictionary_form: u.lookup_form, start_token: u.start, end_token: u.end,
      meanings: meanings(u.entry_ids, result.dictionary_entries), dictionary_reading: dictionaryReading(u.lookup_form, best(u.entry_ids), [spoken])};
  });
  const grammar: GrammarNote[] = result.grammar.map(g => {const p = grammarPattern(g.pattern)!;
    return {id: g.pattern, name: p.name, meaning: p.meaning, start_token: g.start, end_token: g.end};});
  return {original_text: result.original_text, translation, processing: {ocr_ms: 0, translation_ms: 0, analysis_ms: 0, total_ms: 0},
    tokens, units, grammar, target_language: 'en', dictionary_language: 'en', provenance: {...provenance, engine_kind: 'browser'}};
}
