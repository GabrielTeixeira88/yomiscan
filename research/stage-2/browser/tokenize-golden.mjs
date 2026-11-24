// Stage 2 spike (informational): tokenize the lexical golden set with lindera-wasm-unidic.
// Output feeds research/stage-2/evaluate_js_tokenizer.py, which replays these tokens through the
// unchanged Python TextAnalyzer + JMdict ranking.
import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {initSync, TokenizerBuilder, getVersion} from "lindera-wasm-unidic";

const repo = path.resolve("../../..");
initSync({module: await readFile("node_modules/lindera-wasm-unidic/lindera_wasm_unidic_bg.wasm")});
const builder = new TokenizerBuilder();
builder.setDictionary("embedded://unidic");
builder.setMode("normal");
const tokenizer = builder.build();
const value = v => v && v !== "*" ? v : null;
const texts = (await readFile(path.join(repo, "benchmarks/lexical-golden.jsonl"), "utf8"))
  .split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line).text);
const result = {tokenizer: `lindera-wasm-unidic ${getVersion()}`, sentences: {}};
const t0 = performance.now();
for (const text of texts) {
  result.sentences[text] = tokenizer.tokenize(text).map(token => {
    const d = token.details;
    // UniDic fields: pos1-4, cType, cForm, lForm, lemma, orth, pron, orthBase, pronBase, goshu, ...
    // fugashi's adapter reads kana/kanaBase, which this build lacks: pron and lForm are the nearest.
    return {surface: token.surface, lemma: value(d[7]), reading: value(d[9]),
            part_of_speech: [d[0], d[1], d[2], d[3]].map(value).filter(Boolean).join(" / ") || null,
            conjugation_type: value(d[4]), conjugation_form: value(d[5]), orthographic_base: value(d[10]),
            lemma_reading: value(d[6])};
  });
}
result.ms = performance.now() - t0;
await writeFile(path.join(repo, ".cache/stage2/lindera-golden.json"), JSON.stringify(result, null, 1));
console.log(`${texts.length} sentences tokenized in ${result.ms.toFixed(0)} ms`);
