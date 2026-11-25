// Saved words and sentences (Stage 6). Everything stays in the extension's own IndexedDB
// (library-idb.ts); nothing is stored without an explicit Save click, and no page URL or image is
// ever kept. Storage sits behind LibraryStore so the rules here are tested without a browser.
import {parseAnalysis, type Analysis, type Meaning, type Token, type Unit} from './api';

export const WORD_LIMIT = 50_000, SENTENCE_LIMIT = 2_000, SENTENCE_BYTES = 128 * 1024;
/** The opt-in Study history (before Stage 6), moved into saved sentences once. */
export const HISTORY_KEY = 'yomiscanStudyHistoryV1';
export const BACKUP_FORMAT = 'yomiscan-library';

export interface SavedWord {
  /** jmdict:<entry id> when the dictionary matched, else word:<expression>|<reading>. */
  key: string;
  expression: string;
  reading: string | null;
  /** As it appeared in the sentence (食べた for 食べる). */
  surface: string;
  /** One line per sense of the best dictionary entry, up to five. */
  meanings: string[];
  parts_of_speech: string[];
  entry_id: number | null;
  sentence: string;
  sentence_translation: string | null;
  created_at: string;
}
export interface SavedSentence {id: string; created_at: string; analysis: Analysis}
export interface SentenceSummary {id: string; created_at: string; original_text: string; translation: string | null}
export type StoreName = 'words' | 'sentences';
type Records = {words: SavedWord; sentences: SavedSentence};

export interface LibraryStore {
  get<S extends StoreName>(store: S, key: string): Promise<Records[S] | undefined>;
  all<S extends StoreName>(store: S): Promise<Records[S][]>;
  /** Writes every value in one transaction (all or nothing). */
  put<S extends StoreName>(store: S, values: Records[S][]): Promise<void>;
  delete(store: StoreName, key: string): Promise<void>;
  clear(store: StoreName): Promise<void>;
  count(store: StoreName): Promise<number>;
  /** Which of these keys exist. */
  has(store: StoreName, keys: string[]): Promise<string[]>;
}

const bytes = (data: unknown) => new TextEncoder().encode(JSON.stringify(data)).length;
const copyMeaning = (m: Meaning): Meaning => ({entry_id: m.entry_id, glosses: [...m.glosses], parts_of_speech: [...m.parts_of_speech],
  spellings: [...m.spellings], readings: [...m.readings], notes: [...m.notes], labels: [...m.labels]});
const PROVENANCE = ['engine', 'model', 'revision', 'expected_revision', 'requested_target', 'target_language', 'grammar_contract',
  'translation_mode', 'context_policy', 'glossary_application', 'analysis_origin'];

/** The card's text and analysis only: transport fields, URLs and pixels are dropped. */
export function savedAnalysis(value: unknown): Analysis {
  const data = parseAnalysis(value);
  const result: Analysis = {original_text: data.original_text, translation: data.translation,
    target_language: data.target_language ?? 'en', dictionary_language: 'en',
    processing: {ocr_ms: data.processing.ocr_ms, translation_ms: data.processing.translation_ms,
      analysis_ms: data.processing.analysis_ms, total_ms: data.processing.total_ms},
    tokens: data.tokens.map(t => ({surface: t.surface, reading: t.reading, lemma: t.lemma, dictionary_form: t.dictionary_form,
      part_of_speech: t.part_of_speech, conjugation_type: t.conjugation_type, conjugation_form: t.conjugation_form,
      ...(t.inflection ? {inflection: [...t.inflection]} : {}),
      ...(t.dictionary_reading !== undefined ? {dictionary_reading: t.dictionary_reading} : {}),
      meanings: t.meanings.map(copyMeaning)}))};
  if (data.units) result.units = data.units.map(u => ({surface: u.surface, dictionary_form: u.dictionary_form,
    start_token: u.start_token, end_token: u.end_token,
    ...(u.dictionary_reading !== undefined ? {dictionary_reading: u.dictionary_reading} : {}), meanings: u.meanings.map(copyMeaning)}));
  if (data.grammar) result.grammar = data.grammar.map(g => ({id: g.id, name: g.name, meaning: g.meaning, start_token: g.start_token, end_token: g.end_token}));
  if (data.provenance) result.provenance = Object.fromEntries(Object.entries(data.provenance).filter(([key, value]) =>
    PROVENANCE.includes(key) && typeof value === 'string' && value.length <= 160 && /^[\w.-]+(?:\/[\w.-]+)?$/.test(value)));
  if (bytes(result) > SENTENCE_BYTES) throw new Error('This sentence is too large to save (over 128 KiB); nothing was saved.');
  return result;
}

export function wordKey(entryId: number | null, expression: string, reading: string | null): string {
  return entryId !== null ? `jmdict:${entryId}` : `word:${expression}|${reading ?? ''}`;
}

/** The senses of the best-ranked dictionary entry, one line each. */
function senseLines(meanings: Meaning[]): {lines: string[]; pos: string[]; entry: number | null} {
  const entry = meanings[0]?.entry_id ?? null, best = meanings.filter(m => m.entry_id === entry).slice(0, 5);
  return {lines: best.map(m => m.glosses.join('; ')), pos: [...new Set(best.flatMap(m => m.parts_of_speech))], entry};
}

type WordDraft = Omit<SavedWord, 'created_at'>;

/** A word of the card's breakdown, as it would be saved. */
export function tokenWord(token: Token, analysis: Analysis): WordDraft {
  const expression = token.dictionary_form || token.lemma || token.surface;
  const reading = token.dictionary_reading ?? (expression === token.surface ? token.reading : null);
  const {lines, pos, entry} = senseLines(token.meanings);
  return {key: wordKey(entry, expression, reading), expression, reading, surface: token.surface, meanings: lines,
    parts_of_speech: pos.length ? pos : token.part_of_speech ? [token.part_of_speech] : [], entry_id: entry,
    sentence: analysis.original_text, sentence_translation: analysis.translation};
}

/** An expression of the card (かもしれない), as it would be saved. */
export function unitWord(unit: Unit, analysis: Analysis): WordDraft {
  const {lines, pos, entry} = senseLines(unit.meanings);
  const reading = unit.dictionary_reading ?? null;
  return {key: wordKey(entry, unit.dictionary_form, reading), expression: unit.dictionary_form, reading, surface: unit.surface,
    meanings: lines, parts_of_speech: pos, entry_id: entry, sentence: analysis.original_text, sentence_translation: analysis.translation};
}

const isString = (v: unknown): v is string => typeof v === 'string';
const shortString = (v: unknown, max: number) => isString(v) && v.length <= max;
const strings = (v: unknown, count: number, max: number) => Array.isArray(v) && v.length <= count && v.every(x => shortString(x, max));
const date = (v: unknown) => isString(v) && Number.isFinite(Date.parse(v));

/** A saved word from the card or a backup, checked field by field (unknown fields dropped). */
export function validWord(value: unknown): SavedWord {
  const w = value as Record<string, unknown>;
  const reading = w?.reading ?? null, translation = w?.sentence_translation ?? null, entry = w?.entry_id ?? null;
  if (!w || typeof w !== 'object' || !shortString(w.expression, 200) || !(w.expression as string).length || !shortString(w.surface, 200)
    || !(reading === null || shortString(reading, 200)) || !strings(w.meanings, 5, 2000) || !strings(w.parts_of_speech, 20, 200)
    || !(entry === null || Number.isInteger(entry)) || !shortString(w.sentence, 1000)
    || !(translation === null || shortString(translation, 4000)))
    throw new Error('Invalid saved word.');
  const word: SavedWord = {key: wordKey(entry as number | null, w.expression as string, reading as string | null),
    expression: w.expression as string, reading: reading as string | null, surface: w.surface as string,
    meanings: [...w.meanings as string[]], parts_of_speech: [...w.parts_of_speech as string[]], entry_id: entry as number | null,
    sentence: w.sentence as string, sentence_translation: translation as string | null,
    created_at: w.created_at as string};
  if (!date(word.created_at)) throw new Error('Invalid saved word date.');
  return word;
}

export function validSentence(value: unknown): SavedSentence {
  const s = value as Record<string, unknown>;
  if (!s || typeof s !== 'object' || !isString(s.id) || !/^[a-f0-9-]{36}$/.test(s.id) || !date(s.created_at))
    throw new Error('Invalid saved sentence.');
  return {id: s.id, created_at: s.created_at as string, analysis: savedAnalysis(s.analysis)};
}

export const summary = (s: SavedSentence): SentenceSummary =>
  ({id: s.id, created_at: s.created_at, original_text: s.analysis.original_text, translation: s.analysis.translation});

export interface Backup {format: typeof BACKUP_FORMAT; schema: 1; exported_at: string; words: SavedWord[]; sentences: SavedSentence[]}

export class Library {
  constructor(private store: LibraryStore, private now: () => Date = () => new Date()) {}

  /** Which of these word keys are saved (the card marks them). */
  saved(keys: string[]): Promise<string[]> {
    if (keys.length > 500 || !keys.every(k => shortString(k, 420))) return Promise.reject(new Error('Invalid word lookup.'));
    return this.store.has('words', keys);
  }

  /** Saves a word; saving it again keeps the first date and takes the newest sentence. */
  async saveWord(value: unknown): Promise<SavedWord> {
    const draft = validWord({...(value as object), created_at: this.now().toISOString()});
    const existing = await this.store.get('words', draft.key);
    if (!existing && await this.store.count('words') >= WORD_LIMIT)
      throw new Error(`You have ${WORD_LIMIT.toLocaleString('en')} saved words, the limit. Export and delete some first.`);
    const word = existing ? {...draft, created_at: existing.created_at} : draft;
    await this.store.put('words', [word]);
    return word;
  }

  deleteWord(key: string): Promise<void> {return this.store.delete('words', key);}

  async saveSentence(analysis: unknown): Promise<SentenceSummary> {
    const sentence: SavedSentence = {id: crypto.randomUUID(), created_at: this.now().toISOString(), analysis: savedAnalysis(analysis)};
    if (await this.store.count('sentences') >= SENTENCE_LIMIT)
      throw new Error(`You have ${SENTENCE_LIMIT.toLocaleString('en')} saved sentences, the limit. Export and delete some first.`);
    await this.store.put('sentences', [sentence]);
    return summary(sentence);
  }

  sentence(id: string): Promise<SavedSentence | undefined> {return this.store.get('sentences', id);}
  deleteSentence(id: string): Promise<void> {return this.store.delete('sentences', id);}

  /** Newest first. */
  async words(): Promise<SavedWord[]> {return (await this.store.all('words')).sort((a, b) => b.created_at.localeCompare(a.created_at));}
  async sentences(): Promise<SentenceSummary[]> {
    return (await this.store.all('sentences')).map(summary).sort((a, b) => b.created_at.localeCompare(a.created_at));
  }
  async counts(): Promise<{words: number; sentences: number}> {
    return {words: await this.store.count('words'), sentences: await this.store.count('sentences')};
  }

  async backup(): Promise<Backup> {
    return {format: BACKUP_FORMAT, schema: 1, exported_at: this.now().toISOString(), words: await this.words(),
      sentences: (await this.store.all('sentences')).sort((a, b) => b.created_at.localeCompare(a.created_at))};
  }

  /** Adds a backup's words and sentences; a word already saved keeps its current version. Checks everything before writing. */
  async restore(value: unknown): Promise<{words: number; sentences: number}> {
    const data = value as Partial<Backup>;
    if (!data || data.format !== BACKUP_FORMAT || data.schema !== 1 || !Array.isArray(data.words) || !Array.isArray(data.sentences))
      throw new Error('This is not a YomiScan backup file.');
    const words = data.words.map(w => validWord(w)), sentences = data.sentences.map(validSentence);
    const existing = new Set(await this.store.has('words', words.map(w => w.key)));
    const newWords = [...new Map(words.filter(w => !existing.has(w.key)).map(w => [w.key, w])).values()];
    const known = new Set(await this.store.has('sentences', sentences.map(s => s.id)));
    const newSentences = sentences.filter(s => !known.has(s.id));
    const counts = await this.counts();
    if (counts.words + newWords.length > WORD_LIMIT || counts.sentences + newSentences.length > SENTENCE_LIMIT)
      throw new Error('The backup would go over the saved-item limits; nothing was restored.');
    await this.store.put('words', newWords);
    await this.store.put('sentences', newSentences);
    return {words: newWords.length, sentences: newSentences.length};
  }

  async clear(): Promise<void> {await this.store.clear('words'); await this.store.clear('sentences');}

  /** Moves the old opt-in Study history into saved sentences, once. Invalid old entries are skipped and counted. */
  async migrateHistory(storage: {get(key: string): Promise<Record<string, unknown>>; remove(key: string): Promise<void>}):
    Promise<{moved: number; skipped: number} | null> {
    const raw = (await storage.get(HISTORY_KEY))[HISTORY_KEY] as {entries?: unknown} | undefined;
    if (raw === undefined) return null;
    const entries = Array.isArray(raw?.entries) ? raw.entries : [];
    const sentences: SavedSentence[] = [];
    for (const entry of entries) {
      try {sentences.push(validSentence(entry));} catch {/* counted below as skipped */}
    }
    const known = new Set(await this.store.has('sentences', sentences.map(s => s.id)));
    await this.store.put('sentences', sentences.filter(s => !known.has(s.id)));
    await storage.remove(HISTORY_KEY);
    return {moved: sentences.length, skipped: entries.length - sentences.length};
  }
}

/** What content scripts (the study card, the panel) may ask the service worker. The Saved page
 * opens the database itself. */
export type LibraryRequest =
  | {operation: 'saved'; keys: string[]}
  | {operation: 'save-word'; word: unknown}
  | {operation: 'delete-word'; key: string}
  | {operation: 'save-sentence'; analysis: unknown}
  | {operation: 'counts'};

export function libraryRequest(library: Library, request: LibraryRequest): Promise<unknown> {
  switch (request?.operation) {
    case 'saved': return library.saved(Array.isArray(request.keys) ? request.keys : []);
    case 'save-word': return library.saveWord(request.word);
    case 'delete-word':
      if (!shortString(request.key, 420)) return Promise.reject(new Error('Choose a saved word to remove.'));
      return library.deleteWord(request.key).then(() => null);
    case 'save-sentence': return library.saveSentence(request.analysis);
    case 'counts': return library.counts();
    default: return Promise.reject(new Error('Unknown saved-word operation.'));
  }
}

// ---- CSV -------------------------------------------------------------------------------------

/** RFC 4180: every field quoted, CRLF rows, with a byte-order mark so spreadsheet programs read UTF-8. */
export function csv(rows: (string | null)[][]): string {
  return '﻿' + rows.map(row => row.map(cell => `"${(cell ?? '').replace(/"/g, '""')}"`).join(',')).join('\r\n') + '\r\n';
}

const day = (iso: string) => iso.slice(0, 10);

export function wordsCsv(words: SavedWord[]): string {
  return csv([['Expression', 'Reading', 'Meaning', 'Part of speech', 'Sentence', 'Sentence translation', 'Added'],
    ...words.map(w => [w.expression, w.reading, w.meanings.join(' / '), w.parts_of_speech.join(', '), w.sentence,
      w.sentence_translation, day(w.created_at)])]);
}

export function sentencesCsv(sentences: SentenceSummary[]): string {
  return csv([['Japanese', 'Translation', 'Added'], ...sentences.map(s => [s.original_text, s.translation, day(s.created_at)])]);
}

// ---- in-memory store (tests and fallbacks) ---------------------------------------------------

export class MemoryStore implements LibraryStore {
  private data = {words: new Map<string, SavedWord>(), sentences: new Map<string, SavedSentence>()};
  private id = (store: StoreName, value: SavedWord | SavedSentence) => store === 'words' ? (value as SavedWord).key : (value as SavedSentence).id;
  async get<S extends StoreName>(store: S, key: string) {return structuredClone(this.data[store].get(key)) as Records[S] | undefined;}
  async all<S extends StoreName>(store: S) {return structuredClone([...this.data[store].values()]) as Records[S][];}
  async put<S extends StoreName>(store: S, values: Records[S][]) {
    for (const value of values) (this.data[store] as Map<string, Records[S]>).set(this.id(store, value), structuredClone(value));
  }
  async delete(store: StoreName, key: string) {this.data[store].delete(key);}
  async clear(store: StoreName) {this.data[store].clear();}
  async count(store: StoreName) {return this.data[store].size;}
  async has(store: StoreName, keys: string[]) {return keys.filter(k => this.data[store].has(k));}
}
