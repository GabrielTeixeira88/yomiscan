// Opt-in (needs data/jmdict.sqlite3; no models): run the browser lexical engine in Node over
// the lexical golden set and write tokens + analysis for scripts/compare_browser_lexical.py.
// Build and run from extension/: node build.mjs --test && node .test/lexical-parity.mjs
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {initSync, TokenizerBuilder, getVersion} from 'lindera-wasm-unidic';
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';
import {analyzeLexical} from '../src/engine/lexical';
import {JmdictDatabase, fromLindera, type LinderaToken, type Sqlite3} from '../src/engine/lexicon';

const repo = path.resolve('..');
initSync({module: await readFile('node_modules/lindera-wasm-unidic/lindera_wasm_unidic_bg.wasm')});
const builder = new TokenizerBuilder();
builder.setDictionary('embedded://unidic'); builder.setMode('normal');
const tokenizer = builder.build();
const sqlite3 = await (sqlite3InitModule as unknown as () => Promise<Sqlite3>)();
const dictionary = JmdictDatabase.open(sqlite3, new Uint8Array(await readFile(path.join(repo, process.env.YOMISCAN_DICTIONARY ?? 'data/jmdict.sqlite3'))));
const texts = (await readFile(path.join(repo, 'benchmarks/lexical-golden.jsonl'), 'utf8')).split(/\r?\n/).filter(Boolean).map(l => JSON.parse(l).text as string);
const started = performance.now();
const sentences: Record<string, unknown> = {};
for (const text of [...new Set(texts)]) {
  const tokens = (tokenizer.tokenize(text) as LinderaToken[]).map(fromLindera);
  const result = analyzeLexical(text, tokens, form => dictionary.lookup(form));
  sentences[text] = {tokens, analysis: {tokens: result.tokens.map(t => ({lookup_form: t.lookup_form, entry_ids: t.entry_ids, inflection: t.inflection})),
    units: result.units, grammar: result.grammar}};
}
const ms = performance.now() - started;
await mkdir(path.join(repo, '.cache/stage5a'), {recursive: true});
await writeFile(path.join(repo, '.cache/stage5a/lexical-browser.json'), JSON.stringify({tokenizer: `lindera-wasm-unidic ${getVersion()}`,
  schema: dictionary.schema, ms, sentences}, null, 1));
console.log(`${Object.keys(sentences).length} sentences analyzed in ${ms.toFixed(0)} ms (schema ${dictionary.schema})`);
dictionary.close();
