// Stage 2 spike: validate the JS manga-ocr port in Node (onnxruntime-node, CPU) against the
// reference PyTorch arm, and the JS preprocessing against manga-ocr's own processor.
//   node validate-node.mjs [variant=fp32] [decoding=beam] [limit]
import {readFile, writeFile, readdir} from "node:fs/promises";
import {existsSync} from "node:fs";
import path from "node:path";
import {PNG} from "pngjs";
import * as ort from "onnxruntime-node";
import {MangaOcr, pixelValues} from "./ocr.mjs";

const root = path.resolve("../../../.cache/stage2");
const [variant = "fp32", decoding = "beam", limitText] = process.argv.slice(2);
const folder = path.join(root, variant === "fp32" ? "manga-ocr-onnx" : `manga-ocr-onnx-${variant}`);
const crops = JSON.parse(await readFile(path.join(root, "crops/crops.json"), "utf8"));
const limit = limitText ? Number(limitText) : crops.length;

const load = async file => {
  const png = PNG.sync.read(await readFile(path.join(root, "crops", file)));
  return {rgba: png.data, width: png.width, height: png.height};
};

// 1. Preprocessing parity.
const pixelDir = path.join(root, "pixels");
if (existsSync(pixelDir)) {
  let worst = 0, checked = 0;
  for (const name of (await readdir(pixelDir)).sort()) {
    const expected = new Float32Array((await readFile(path.join(pixelDir, name))).buffer.slice(0));
    const {rgba, width, height} = await load(name.replace(".f32", ".png"));
    const got = pixelValues(rgba, width, height);
    for (let i = 0; i < got.length; i++) worst = Math.max(worst, Math.abs(got[i] - expected[i]));
    checked++;
  }
  console.log(`preprocess: ${checked} crops, max abs diff ${worst}`);
}

// 2. Recognition parity.
const options = {executionProviders: ["cpu"], intraOpNumThreads: 4};
const ocr = new MangaOcr({
  ort,
  encoder: await ort.InferenceSession.create(path.join(folder, "encoder.onnx"), options),
  decoder: await ort.InferenceSession.create(path.join(folder, "decoder.onnx"), options),
  vocabulary: (await readFile(path.join(folder, "vocab.txt"), "utf8")).split(/\r?\n/).filter((t, i, a) => i < a.length - 1 || t),
  generation: JSON.parse(await readFile(path.join(folder, "generation.json"), "utf8")),
});
const rows = [];
let same = 0;
for (const crop of crops.slice(0, limit)) {
  const {rgba, width, height} = await load(crop.file);
  const result = await ocr.recognize(rgba, width, height, {decoding});
  const equal = result.text === crop.reference_output;
  same += equal;
  if (!equal) console.log(`DIFF ${crop.id}\n  ref ${crop.reference_output}\n  js  ${result.text}`);
  rows.push({...crop, output: result.text, tokens: result.tokens, timings: result.timings});
}
const ms = rows.map(r => r.timings.encoder + r.timings.decoder + r.timings.preprocess).sort((a, b) => a - b);
console.log(`${variant}/${decoding}: ${same}/${rows.length} identical to PyTorch reference; median ${ms[Math.floor(ms.length / 2)].toFixed(0)} ms`);
await writeFile(path.join(root, `node-${variant}-${decoding}.json`), JSON.stringify({variant, decoding, backend: "onnxruntime-node cpu", rows}, null, 1));
