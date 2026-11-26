import test from 'node:test';
import assert from 'node:assert/strict';
import type {Analysis, Meaning, Token} from '../src/api';
import {HISTORY_KEY, KNOWN_LIMIT, Library, MemoryStore, WORD_LIMIT, ankiCsv, knownForm, knownText, parseKnownList, csv, libraryRequest, savedAnalysis, sentencesAnki, sentencesCsv,
  tokenWord, unitWord, wordsAnki, wordsCsv, type SavedWord} from '../src/library';

const meaning = (entry_id: number, ...glosses: string[]): Meaning =>
  ({entry_id, glosses, parts_of_speech: ['verb'], spellings: [], readings: [], notes: [], labels: []});
const token = (extra: Partial<Token> = {}): Token => ({surface: '食べた', reading: 'たべた', lemma: '食べる', dictionary_form: '食べる',
  part_of_speech: '動詞', conjugation_type: null, conjugation_form: null, meanings: [], ...extra});
const analysis = (extra: Partial<Analysis> = {}): Analysis => ({original_text: '猫が魚を食べた', translation: 'The cat ate the fish.',
  target_language: 'en', processing: {ocr_ms: 1, translation_ms: 1, analysis_ms: 1, total_ms: 3}, tokens: [], ...extra});
const clock = (...isos: string[]) => {let i = 0; return () => new Date(isos[Math.min(i++, isos.length - 1)]);};

test('a saved word is the dictionary form with its reading, the best entry\'s senses and the sentence', () => {
  const word = tokenWord(token({dictionary_reading: 'たべる', meanings: [meaning(1, 'to eat'), meaning(1, 'to live on'), meaning(2, 'other word')]}), analysis());
  assert.deepEqual(word, {key: 'jmdict:1', expression: '食べる', reading: 'たべる', surface: '食べた', meanings: ['to eat', 'to live on'],
    parts_of_speech: ['verb'], entry_id: 1, sentence: '猫が魚を食べた', sentence_translation: 'The cat ate the fish.'});
  // Older backends send no dictionary_reading: an inflected surface's reading is never used for the dictionary form.
  assert.equal(tokenWord(token(), analysis()).reading, null);
  assert.equal(tokenWord(token({surface: '猫', reading: 'ねこ', dictionary_form: '猫'}), analysis()).reading, 'ねこ');
  assert.equal(tokenWord(token({meanings: []}), analysis()).key, 'word:食べる|');
  const six = Array.from({length: 7}, (_, i) => meaning(5, 'sense ' + i));
  assert.equal(tokenWord(token({meanings: six}), analysis()).meanings.length, 5);
  const unit = unitWord({surface: 'かもしれない', dictionary_form: 'かもしれない', start_token: 0, end_token: 1, dictionary_reading: 'かもしれない',
    meanings: [meaning(9, 'might')]}, analysis());
  assert.equal(unit.key, 'jmdict:9'); assert.equal(unit.reading, 'かもしれない');
});

test('saving a word again keeps its first date, takes the newest sentence, and removing it works', async () => {
  const library = new Library(new MemoryStore(), clock('2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z'));
  const word = tokenWord(token({dictionary_reading: 'たべる', meanings: [meaning(1, 'to eat')]}), analysis());
  await library.saveWord(word);
  const again = await library.saveWord({...word, sentence: '魚を食べた'});
  assert.equal(again.created_at, '2026-01-01T00:00:00.000Z'); assert.equal(again.sentence, '魚を食べた');
  assert.deepEqual(await library.saved(['jmdict:1', 'jmdict:2']), ['jmdict:1']);
  assert.equal((await library.words()).length, 1);
  await library.deleteWord('jmdict:1');
  assert.deepEqual(await library.saved(['jmdict:1']), []);
});

test('saved words are checked field by field; the key is always recomputed', async () => {
  const library = new Library(new MemoryStore());
  const word = tokenWord(token({meanings: [meaning(1, 'to eat')]}), analysis());
  const saved = await library.saveWord({...word, key: 'jmdict:999', private: 'C:/secret'});
  assert.equal(saved.key, 'jmdict:1'); assert.ok(!JSON.stringify(saved).includes('secret'));
  for (const broken of [{...word, expression: ''}, {...word, meanings: 'to eat'}, {...word, entry_id: 1.5}, {...word, sentence: 'x'.repeat(1001)}, null])
    await assert.rejects(library.saveWord(broken), /Invalid saved word/);
});

test('the word limit refuses a new word but still updates a saved one', async () => {
  const store = new MemoryStore();
  const library = new Library(store);
  const word = tokenWord(token({meanings: [meaning(1, 'to eat')]}), analysis());
  await library.saveWord(word);
  store.count = async () => WORD_LIMIT;
  await library.saveWord(word);
  await assert.rejects(library.saveWord({...word, meanings: [], entry_id: null, expression: '猫'}), /limit/);
});

test('saved sentences keep only text and analysis, never URLs, paths or pixels', async () => {
  const library = new Library(new MemoryStore());
  const saved = await library.saveSentence({...analysis(), source_url: 'https://private', image: 'data:private',
    processing: {...analysis().processing, path: 'C:/private'}, provenance: {engine: 'current', artifact: 'C:/private', model: '/home/private/file'}});
  const full = await library.sentence(saved.id);
  assert.ok(full && !JSON.stringify(full).includes('private'));
  assert.deepEqual(full!.analysis.provenance, {engine: 'current'});
  await assert.rejects(library.saveSentence({...analysis(), original_text: '猫'.repeat(60_000)}), /128 KiB/);
  assert.deepEqual((await library.sentences()).map(s => s.original_text), ['猫が魚を食べた']);
});

test('the sentence sanitizer keeps expressions, grammar and dictionary readings and drops unknown fields', () => {
  const t = token({surface: '猫', dictionary_form: '猫', dictionary_reading: 'ねこ'});
  const unit = {surface: '猫', dictionary_form: '猫', start_token: 0, end_token: 1, dictionary_reading: 'ねこ', meanings: [meaning(7, 'cat')]};
  const note = {id: 'te-iru', name: '〜ている', meaning: 'ongoing', start_token: 0, end_token: 1};
  const saved = savedAnalysis({...analysis(), tokens: [{...t, extra: 'x'}], units: [{...unit, private: 'C:/x'}], grammar: [{...note, extra: 'x'}]});
  assert.deepEqual(saved.units, [unit]); assert.deepEqual(saved.grammar, [note]); assert.equal(saved.tokens[0].dictionary_reading, 'ねこ');
  assert.ok(!JSON.stringify(saved).includes('extra'));
  assert.equal(savedAnalysis(analysis()).units, undefined);
});

test('backup and restore round-trip; restore keeps what is already saved and checks everything before writing', async () => {
  const source = new Library(new MemoryStore(), clock('2026-03-01T00:00:00Z'));
  await source.saveWord(tokenWord(token({meanings: [meaning(1, 'to eat')]}), analysis()));
  await source.saveSentence(analysis());
  const backup = JSON.parse(JSON.stringify(await source.backup()));
  const target = new Library(new MemoryStore(), clock('2026-04-01T00:00:00Z'));
  await target.saveWord({...tokenWord(token({meanings: [meaning(1, 'to eat')]}), analysis()), sentence: 'mine'});
  assert.deepEqual(await target.restore(backup), {words: 0, sentences: 1, known: 0});
  assert.equal((await target.words())[0].sentence, 'mine');
  assert.deepEqual(await target.restore(backup), {words: 0, sentences: 0, known: 0});
  await assert.rejects(target.restore({...backup, format: 'other'}), /not a YomiScan backup/);
  const empty = new Library(new MemoryStore());
  await assert.rejects(empty.restore({...backup, words: [...backup.words, {expression: ''}]}), /Invalid saved word/);
  assert.deepEqual(await empty.counts(), {words: 0, sentences: 0, known: 0});
});

test('the old Study history moves into saved sentences once; broken entries are skipped and counted', async () => {
  const library = new Library(new MemoryStore());
  const entry = {id: '0b8e4bc4-91c2-4d33-9e57-3a0a8c5f6d21', created_at: '2025-12-01T00:00:00.000Z', analysis: analysis()};
  let data: Record<string, unknown> = {[HISTORY_KEY]: {schema: 1, enabled: true, entries: [entry, {id: 'bad'}]}};
  const storage = {get: async (key: string) => key in data ? {[key]: structuredClone(data[key])} : {},
    remove: async (key: string) => {const {[key]: _, ...rest} = data; data = rest;}};
  assert.deepEqual(await library.migrateHistory(storage), {moved: 1, skipped: 1});
  assert.equal(HISTORY_KEY in data, false);
  assert.deepEqual((await library.sentences()).map(s => [s.id, s.created_at]), [[entry.id, entry.created_at]]);
  assert.equal(await library.migrateHistory(storage), null);
});

test('CSV quotes every field, uses CRLF and starts with a byte-order mark', () => {
  assert.equal(csv([['a', 'b "c"'], ['line\nbreak', null]]), '\ufeff"a","b ""c"""\r\n"line\nbreak",""\r\n');
  const word: SavedWord = {key: 'jmdict:1', expression: '食べる', reading: 'たべる', surface: '食べた', meanings: ['to eat', 'to live on'],
    parts_of_speech: ['verb', 'transitive'], entry_id: 1, sentence: '食べた', sentence_translation: null, created_at: '2026-01-02T10:00:00.000Z'};
  assert.equal(wordsCsv([word]).split('\r\n')[1], '"食べる","たべる","to eat / to live on","verb, transitive","食べた","","2026-01-02"');
  assert.equal(sentencesCsv([{id: 'x', created_at: '2026-01-02T10:00:00.000Z', original_text: '猫', translation: 'Cat'}]).split('\r\n')[1],
    '"猫","Cat","2026-01-02"');
});

test('the Anki export starts with the header lines Anki reads and has no column-name row or date', () => {
  const word: SavedWord = {key: 'jmdict:1', expression: '食べる', reading: 'たべる', surface: '食べた', meanings: ['to eat', '<b>x</b>'],
    parts_of_speech: ['verb'], entry_id: 1, sentence: '食べた', sentence_translation: 'Ate "it".', created_at: '2026-01-02T10:00:00.000Z'};
  assert.equal(wordsAnki([word]), '﻿#separator:comma\r\n#html:false\r\n#tags:yomiscan\r\n' +
    '#columns:Expression,Reading,Meaning,Part of speech,Sentence,Sentence translation\r\n' +
    '"食べる","たべる","to eat / <b>x</b>","verb","食べた","Ate ""it""."\r\n');
  assert.equal(sentencesAnki([{id: 'x', created_at: '2026-01-02T10:00:00.000Z', original_text: '猫\n犬', translation: null}]),
    '﻿#separator:comma\r\n#html:false\r\n#tags:yomiscan\r\n#columns:Japanese,Translation\r\n"猫\n犬",""\r\n');
  assert.equal(wordsAnki([]).endsWith('Sentence translation\r\n'), true);
  assert.throws(() => ankiCsv(['a,b'], []), /commas/);
});

test('service-worker requests are checked before they reach storage', async () => {
  const library = new Library(new MemoryStore());
  await assert.rejects(libraryRequest(library, {operation: 'drop-database'} as never), /Unknown/);
  await assert.rejects(libraryRequest(library, {operation: 'saved', keys: Array(501).fill('k')}), /Invalid word lookup/);
  await assert.rejects(libraryRequest(library, {operation: 'delete-word', key: 42 as never}), /Choose/);
  assert.deepEqual(await libraryRequest(library, {operation: 'counts'}), {words: 0, sentences: 0, known: 0});
  await assert.rejects(libraryRequest(library, {operation: 'set-known', form: '猫', known: 'yes' as never}), /known or not/);
  await assert.rejects(libraryRequest(library, {operation: 'set-known', form: 'cat', known: true}), /Japanese word/);
  await assert.rejects(libraryRequest(library, {operation: 'known', forms: Array(1001).fill('猫')}), /Invalid known-word lookup/);
  await libraryRequest(library, {operation: 'set-known', form: '猫', known: true});
  assert.deepEqual(await libraryRequest(library, {operation: 'known', forms: ['猫', '犬']}), ['猫']);
});

test('known words are matched by their NFKC dictionary form; marking twice keeps the first date; undo removes it', async () => {
  assert.equal(knownForm(' 食べる '), '食べる'); assert.equal(knownForm('ｶﾞｯｺｳ'), 'ガッコウ');
  for (const bad of ['', 'cat', '123', '食 べる', '猫'.repeat(51), null, 7]) assert.equal(knownForm(bad), null, String(bad));
  const library = new Library(new MemoryStore(), clock('2026-05-01T00:00:00Z', '2026-06-01T00:00:00Z'));
  await library.setKnown('食べる', true);
  await library.setKnown('食べる', true);
  assert.deepEqual(await library.knownWords(), [{form: '食べる', created_at: '2026-05-01T00:00:00.000Z'}]);
  // Lookups keep the caller's spelling and skip forms that cannot be known words.
  assert.deepEqual(await library.known(['食べる', ' 食べる', 'cat', '猫']), ['食べる', ' 食べる']);
  await library.setKnown('食べる', false);
  assert.deepEqual(await library.known(['食べる']), []);
});

test('a known-word list: first column, # lines skipped, quotes, HTML and Anki bracket furigana removed', async () => {
  const text = '\ufeff#separator:tab\r\n#columns:Front\tBack\r\n食べる\tto eat\r\n"猫",cat\n<b>犬</b>;dog\n 食[た]べ 物[もの]\n'
    + '日本[にほん]\nhello\n\n食べる\n42\n';
  assert.deepEqual(parseKnownList(text), {forms: ['食べる', '猫', '犬', '食べ物', '日本'], skipped: 2});
  const library = new Library(new MemoryStore(), clock('2026-05-01T00:00:00Z'));
  await library.setKnown('猫', true);
  assert.deepEqual(await library.importKnown(text), {added: 4, already: 1, skipped: 2});
  assert.equal((await library.counts()).known, 5);
  assert.deepEqual(parseKnownList(knownText(await library.knownWords())).forms.sort(), ['犬', '日本', '猫', '食べ物', '食べる'].sort());
  const store = new MemoryStore(), full = new Library(store);
  store.count = async () => KNOWN_LIMIT;
  await assert.rejects(full.importKnown('猫'), /nothing was imported/);
  await assert.rejects(full.setKnown('猫', true), /limit/);
});

test('backups carry known words (schema 2); schema 1 backups still restore; Delete all clears known words', async () => {
  const source = new Library(new MemoryStore(), clock('2026-03-01T00:00:00Z'));
  await source.setKnown('猫', true);
  const backup = JSON.parse(JSON.stringify(await source.backup()));
  assert.equal(backup.schema, 2); assert.deepEqual(backup.known, [{form: '猫', created_at: '2026-03-01T00:00:00.000Z'}]);
  const target = new Library(new MemoryStore());
  assert.deepEqual(await target.restore(backup), {words: 0, sentences: 0, known: 1});
  assert.deepEqual(await target.restore({...backup, schema: 1, known: undefined}), {words: 0, sentences: 0, known: 0});
  await assert.rejects(target.restore({...backup, known: undefined}), /not a YomiScan backup/);
  await assert.rejects(new Library(new MemoryStore()).restore({...backup, known: [{form: 'cat', created_at: backup.exported_at}]}), /Invalid known word/);
  await target.clear();
  assert.deepEqual(await target.counts(), {words: 0, sentences: 0, known: 0});
});
