import test from "node:test";
import assert from "node:assert/strict";
import {blocksFromRegions, containedDuplicate, containsJapanese, groupRegions, readingOrder, type Region} from "../src/engine/geometry";
import {decodeDetections, decodeTokens, postProcess, resizeBilinear} from "../src/engine/vision-models";
import {cropRGBA} from "../src/engine/vision";
import {ArtifactStore, artifactKey, parseManifest, sha256Hex, type ArtifactComponent} from "../src/engine/artifacts";
import {requiredComponents} from "../src/engine/engine";
import {engineSummary} from "../src/chapter/engine-controls";
import pinned from "../src/engine/artifact-manifest.json";

const region = (id: number, [left, top, right, bottom]: number[], extra: Partial<Region> = {}): Region =>
  ({id, bbox: {left, top, right, bottom}, confidence: .9, orientation: 'unknown', granularity: 'block', class: 'text_bubble', ...extra});

test("engine geometry: contained same-class duplicates share one block; neighbours never merge", () => {
  const outer = region(1, [10, 10, 100, 100], {confidence: .9}), inner = region(2, [20, 20, 60, 60], {confidence: .8});
  assert.ok(containedDuplicate(outer, inner));
  assert.ok(!containedDuplicate(outer, {...inner, confidence: .95}), "a more confident inner box stays separate");
  assert.ok(!containedDuplicate(outer, {...inner, class: 'text_free'}));
  const groups = groupRegions([inner, outer, region(3, [101, 10, 150, 100])]);
  assert.deepEqual(groups.map(g => g.regions.map(r => r.id)), [[3], [1, 2]]);
  assert.deepEqual(groups.find(g => g.regions.length === 2)!.bbox, {left: 10, top: 10, right: 100, bottom: 100});
});

test("engine geometry: bands top to bottom, right to left inside a band (Python reading_order)", () => {
  const order = readingOrder(groupRegions([region(1, [0, 0, 50, 100]), region(2, [200, 5, 250, 100]), region(3, [100, 300, 150, 400])]));
  assert.deepEqual(order.map(g => g.regions[0].id), [2, 1, 3]);
});

test("engine geometry: blocks are clipped, filtered below 3 px and numbered in reading order", () => {
  const {blocks, filtered} = blocksFromRegions([region(1, [0, 0, 50, 100]), region(2, [200, 5, 260, 100]), region(3, [10, 10, 12, 50]),
    region(4, [100, 300, 150, 400], {confidence: null})], 240, 500);
  assert.deepEqual([...filtered.keys()], [3]);
  assert.deepEqual(blocks.map(b => [b.id, b.readingOrder, b.regionIds]), [[1, 1, [2]], [2, 2, [1]], [3, 3, [4]]]);
  assert.equal(blocks[0].bbox.right, 240, "clipped to the image");
  assert.equal(blocks[2].confidence, null);
});

test("engine: Japanese filter matches the backend (NFKC, script ranges)", () => {
  assert.ok(containsJapanese("ｶﾀｶﾅ"));
  assert.ok(containsJapanese("漢字"));
  assert.ok(!containsJapanese("！？…123"));
});

test("detector decoding: text classes above threshold, float32 corners, spatial order", () => {
  const logits = new Float32Array(900).fill(-10), boxes = new Float32Array(1200);
  const put = (query: number, label: number, score: number, box: number[]) => {logits[query * 3 + label] = Math.log(score / (1 - score)); boxes.set(box, query * 4);};
  put(0, 1, .9, [.5, .5, .2, .2]);   // bubble text
  put(1, 2, .8, [.8, .1, .1, .1]);   // free text, higher on the page
  put(2, 0, .99, [.5, .5, 1, 1]);    // bubble outline: dropped
  put(3, 1, .4, [.2, .2, .1, .1]);   // below threshold
  const regions = decodeDetections(logits, boxes, 1000, 2000);
  assert.deepEqual(regions.map(r => [r.id, r.class, r.bbox]), [
    [1, 'text_free', {left: 750, top: 100, right: 850, bottom: 300}],
    [2, 'text_bubble', {left: 400, top: 800, right: 600, bottom: 1200}]]);
  assert.equal(decodeDetections(logits, boxes, 1000, 2000, {bubble: .95, free: .5}).length, 1);
});

test("OCR text: manga_ocr post-processing and character-subword decoding", () => {
  assert.equal(postProcess("な に …  !?"), "なに．．．！？");
  assert.equal(postProcess("あ・・・"), "あ...".replace(/\./g, "．"));
  assert.equal(decodeTokens([2, 5, 6, 3], ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "x", "猫", "##だ"]), "猫だ");
});

test("PIL bilinear resize keeps a flat image flat and crops copy rows exactly", () => {
  assert.deepEqual([...resizeBilinear(new Uint8Array(30 * 20).fill(77), 30, 20, 7, 9)], new Array(63).fill(77));
  const rgba = Uint8ClampedArray.from({length: 4 * 4 * 4}, (_, i) => i);
  assert.deepEqual([...cropRGBA(rgba, 4, {left: 1, top: 2, right: 3, bottom: 3})], [...rgba.subarray(36, 44)]);
});

test("pinned artifact manifest is valid; each backend needs one OCR variant plus the shared components", () => {
  const manifest = parseManifest(pinned);
  const shared = ['tokenizer', 'dictionary', 'translation-opus-ja-en'];
  assert.deepEqual(requiredComponents('webgpu', manifest.components).map(c => c.id), ['detector', 'ocr-q4', ...shared]);
  assert.deepEqual(requiredComponents('wasm', manifest.components).map(c => c.id), ['detector', 'ocr-int8', ...shared]);
  assert.throws(() => parseManifest({...manifest, components: [{...manifest.components[0], files: [{path: '../x', bytes: 1, sha256: 'a'.repeat(64)}]}]}));
  assert.throws(() => parseManifest({...manifest, components: [manifest.components[0], manifest.components[0]]}));
});

test("artifact install verifies size and SHA-256, stores by content hash, and rejects tampered bytes", async () => {
  const good = new TextEncoder().encode("model bytes"), hash = await sha256Hex(good);
  const component: ArtifactComponent = {id: 'ocr-int8', kind: 'ocr', variant: 'int8', license: 'Apache-2.0', source: 'test',
    files: [{path: 'ocr-int8/vocab.txt', bytes: good.length, sha256: hash}]};
  const stored = new Map<string, Response>(), requested: string[] = [];
  const storage = {match: async (k: string) => stored.get(k)?.clone(), put: async (k: string, r: Response) => {stored.set(k, r);}, delete: async (k: string) => stored.delete(k)};
  let body: Uint8Array<ArrayBuffer> = good;
  const fetcher = (async (url: URL) => {requested.push(String(url)); return new Response(body);}) as unknown as typeof fetch;
  const store = new ArtifactStore(async () => storage, fetcher);
  await assert.rejects(store.install(component, 'file:///tmp/'), /http/);
  body = new TextEncoder().encode("model bytez");
  await assert.rejects(store.install(component, 'http://127.0.0.1:47620'), /SHA-256/);
  assert.equal(await store.installed(component), false);
  body = good;
  await store.install(component, 'http://127.0.0.1:47620');
  assert.deepEqual(requested.at(-1), 'http://127.0.0.1:47620/ocr-int8/vocab.txt');
  assert.ok(stored.has(artifactKey(component.files[0])));
  assert.equal(new TextDecoder().decode(await store.read(component.files[0])), "model bytes");
  const before = requested.length;await store.install(component, 'http://127.0.0.1:47620/');
  assert.equal(requested.length, before, "installed files are not downloaded again");
  await store.remove(component);assert.equal(await store.installed(component), false);
});

test("engine setup summary states device path, sizes and what must be downloaded", () => {
  const text = engineSummary({backend: 'wasm', isolated: true, threads: 8, bundle: 'b', loaded: false, install: {state: 'idle'},
    required: [{id: 'detector', kind: 'detector', variant: 'fp16', bytes: 80 * 2 ** 20, license: 'Apache-2.0', source: 's', installed: true},
      {id: 'ocr-int8', kind: 'ocr', variant: 'int8', bytes: 110 * 2 ** 20, license: 'Apache-2.0', source: 's', installed: false}]});
  assert.match(text, /CPU \(WASM, 8 threads\)/);
  assert.match(text, /Download needed: 110 of 190 MiB/);
});
