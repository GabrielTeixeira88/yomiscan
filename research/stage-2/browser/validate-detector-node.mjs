// Stage 2 spike: JS detector (onnxruntime-node) vs the production PyTorch detector report.
//   node validate-detector-node.mjs [detector.onnx|detector-fp16.onnx]
// Writes .cache/stage2/node-detector-<variant>.json in the vision_benchmark page/regions shape.
import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";
import {PNG} from "pngjs";
import * as ort from "onnxruntime-node";
import {detect} from "./detector.mjs";

const repo = path.resolve("../../.."), root = path.join(repo, ".cache/stage2");
const model = process.argv[2] ?? "detector.onnx";
const manifest = JSON.parse(await readFile(path.join(repo, "samples/vision/pages.json"), "utf8"));
const reference = JSON.parse(await readFile(path.join(repo, "reports/stage1-detect-current.json"), "utf8"));
const session = await ort.InferenceSession.create(path.join(root, "detector-onnx", model), {executionProviders: ["cpu"], intraOpNumThreads: 4});
const pages = [];
let identical = 0, total = 0;
for (const page of manifest.pages) {
  // Pillow-decoded PNG (dump_pages.py), so this checks the model port, not JPEG decoders.
  const {data, width, height} = PNG.sync.read(await readFile(path.join(root, "pages", `${page.id}.png`)));
  const t = performance.now();
  const {regions} = await detect(ort, session, data, width, height);
  const ms = performance.now() - t;
  const expected = reference.pages.find(p => p.id === page.id).regions.map(r => JSON.stringify(r.bbox));
  const got = regions.map(r => JSON.stringify(r.bbox));
  const same = got.filter(b => expected.includes(b)).length;
  identical += same; total += expected.length;
  if (same !== expected.length || got.length !== expected.length) console.log(`${page.id}: ${same}/${expected.length} identical boxes, js found ${got.length}`);
  pages.push({id: page.id, split: page.split, regions, warm_ms: [ms]});
}
console.log(`${model}: ${identical}/${total} PyTorch boxes reproduced exactly`);
await writeFile(path.join(root, `node-${model.replace(".onnx", "")}.json`), JSON.stringify({engine: `node-${model}`, load_ms: 0, pages}, null, 1));
