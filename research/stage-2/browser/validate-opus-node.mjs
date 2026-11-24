// Stage 2 spike: JS OPUS (onnxruntime-node) vs the Python backend's OPUS outputs on the 100 real lines.
//   node validate-opus-node.mjs [fp32|quantized|fp16] [beam|greedy]
import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import * as ort from "onnxruntime-node";
import {AutoTokenizer, env} from "@huggingface/transformers";
import {OpusTranslator} from "./opus.mjs";

const root = path.resolve("../../../.cache/stage2"), model = path.join(root, "hf/Xenova/opus-mt-ja-en");
const [dtype = "fp32", decoding = "beam"] = process.argv.slice(2);
const suffix = dtype === "fp32" ? "" : `_${dtype}`;
env.allowRemoteModels = false;
env.localModelPath = path.join(root, "hf") + "/";
const tokenizer = await AutoTokenizer.from_pretrained("Xenova/opus-mt-ja-en");
const options = {executionProviders: ["cpu"], intraOpNumThreads: 4};
const translator = new OpusTranslator({ort, tokenizer,
  encoder: await ort.InferenceSession.create(path.join(model, `onnx/encoder_model${suffix}.onnx`), options),
  decoder: await ort.InferenceSession.create(path.join(model, `onnx/decoder_model_merged${suffix}.onnx`), options),
  config: JSON.parse(await readFile(path.join(model, "config.json"), "utf8")),
  generation: JSON.parse(await readFile(path.join(model, "generation_config.json"), "utf8"))});
// {id: translation} exported from translate-opus.ratings.csv (benchmark_translation, Python beam 4).
const python = JSON.parse(await readFile(path.join(root, "opus-python.json"), "utf8"));
const lines = (await readFile(path.join(root, "translation-real.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean).map(l => JSON.parse(l));
const rows = [];
let same = 0;
for (const line of lines) {
  const result = await translator.translate(line.texts[0], {decoding});
  const equal = result.text === python[line.id];
  same += equal;
  if (!equal && process.argv.includes("--show")) console.log(`DIFF ${line.id}
  py ${python[line.id]}
  js ${result.text}`);
  rows.push({id: line.id, output: result.text, ms: result.timings.encoder + result.timings.decoder});
}
const ms = rows.map(r => r.ms).sort((a, b) => a - b);
console.log(`${dtype}/${decoding}: ${same}/${rows.length} identical to Python OPUS (beam 4); median ${ms[Math.floor(ms.length / 2)].toFixed(0)} ms`);
await writeFile(path.join(root, `opus-node-${dtype}-${decoding}.json`), JSON.stringify({dtype, decoding, rows}, null, 1));
