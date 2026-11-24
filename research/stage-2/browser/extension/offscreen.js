// Stage 2 spike: runs inside the extension's offscreen document. run-browser.mjs calls
// globalThis.spike.* over CDP. Models are fetched from the local spike server once and kept
// in Cache Storage, which is how a shipped build would hold downloaded artifacts.
import {MangaOcr} from "./ocr.mjs";
import {detect} from "./detector.mjs";

const SERVER = "http://127.0.0.1:8790";
const CACHE = "stage2-models";
const folderFor = variant => variant === "fp32" ? "manga-ocr-onnx" : `manga-ocr-onnx-${variant}`;
let ort = null, bundle = null;

// config.threads caps WASM threads (laptop approximation); config.power picks the WebGPU adapter.
async function loadRuntime(kind, config = {}) {
  if (bundle === kind) return ort;
  if (bundle) throw new Error(`Runtime ${bundle} already loaded; reopen the offscreen document`);
  ort = await import(kind === "webgpu" ? "./ort/ort.webgpu.min.mjs" : "./ort/ort.wasm.min.mjs");
  ort.env.wasm.wasmPaths = chrome.runtime.getURL("ort/");
  ort.env.wasm.numThreads = crossOriginIsolated ? Math.min(navigator.hardwareConcurrency, config.threads ?? 8) : 1;
  if (kind === "webgpu" && config.power) {
    const adapter = await navigator.gpu.requestAdapter({powerPreference: config.power});
    if (!adapter) throw new Error(`No ${config.power} WebGPU adapter`);
    ort.env.webgpu.adapter = adapter;
    adapterUsed = {vendor: adapter.info?.vendor, architecture: adapter.info?.architecture, shaderF16: adapter.features.has("shader-f16")};
  }
  bundle = kind;
  return ort;
}
let adapterUsed = null;

async function cachedBytes(url, {prime = false} = {}) {
  const cache = await caches.open(CACHE);
  let response = await cache.match(url);
  if (!response) {
    if (!prime) throw new Error(`Not in Cache Storage (prime first): ${url}`);
    const fetched = await fetch(url);
    if (!fetched.ok) throw new Error(`${url}: HTTP ${fetched.status}`);
    await cache.put(url, fetched.clone());
    response = fetched;
  }
  return new Uint8Array(await response.arrayBuffer());
}

async function adapterInfo() {
  if (!navigator.gpu) return null;
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) return null;
  const info = adapter.info ?? {};
  return {vendor: info.vendor, architecture: info.architecture, device: info.device, description: info.description,
          shaderF16: adapter.features.has("shader-f16")};
}

// Informational: the existing JMdict SQLite database inside the extension via sqlite-wasm
// (in-memory deserialize; a shipped build would persist it in OPFS from a worker).
async function dictionaryCheck(config) {
  const started = performance.now();
  const {default: init} = await import("./sqlite/index.mjs");
  const sqlite3 = await init();
  const bytes = await cachedBytes(`${SERVER}/dict/jmdict.sqlite3`, {prime: true});
  const fetchedMs = performance.now() - started;
  const db = new sqlite3.oo1.DB(":memory:");
  const pointer = sqlite3.wasm.allocFromTypedArray(bytes);
  const rc = sqlite3.capi.sqlite3_deserialize(db.pointer, "main", pointer, bytes.byteLength, bytes.byteLength,
    sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE | sqlite3.capi.SQLITE_DESERIALIZE_RESIZEABLE);
  if (rc) throw new Error(`sqlite3_deserialize failed: ${rc}`);
  const openMs = performance.now() - started;
  const forms = config.forms;
  const statement = db.prepare("SELECT e.payload FROM forms f JOIN entries e USING (entry_id) WHERE f.form = ? ORDER BY e.entry_id");
  let hits = 0, payloadBytes = 0;
  const t = performance.now();
  for (const form of forms) {
    statement.bind([form]);
    while (statement.step()) { hits++; payloadBytes += statement.get(0).length; }
    statement.reset();
  }
  const lookupMs = performance.now() - t;
  statement.finalize(); db.close();
  return {bytes: bytes.byteLength, fetchedMs, openMs, lookups: forms.length, hits, payloadBytes,
          perLookupMs: lookupMs / forms.length, sqlite: sqlite3.version.libVersion};
}

// Informational, optional/experimental provider only: Chrome's built-in Translator API.
async function chromeTranslator({lines}) {
  if (typeof Translator === "undefined") return {available: "api-missing"};
  const pair = {sourceLanguage: "ja", targetLanguage: "en"};
  const availability = await Translator.availability(pair);
  if (availability === "unavailable") return {available: availability};
  const started = performance.now();
  let downloaded = 0;
  let translator;
  try {
    translator = await Translator.create({...pair, monitor(m) { m.addEventListener("downloadprogress", e => { downloaded = e.loaded; }); }});
  } catch (error) {
    return {available: availability, createError: String(error?.message ?? error)};
  }
  const createMs = performance.now() - started;
  const rows = [];
  for (const line of lines) {
    const t = performance.now();
    rows.push({id: line.id, output: await translator.translate(line.text), ms: performance.now() - t});
  }
  translator.destroy();
  return {available: availability, createMs, downloadProgress: downloaded, rows};
}

// G8 / realistic page timing: detector + OCR in one document over N pages. Crops are the raw
// detected boxes padded by 4 px (production grouping is not ported in the spike).
async function pipeline(config) {
  const started = performance.now();
  const runtime = await loadRuntime(config.backend, config);
  const options = {executionProviders: [config.backend], graphOptimizationLevel: "all"};
  if (config.backend === "webgpu") options.preferredOutputLocation = "cpu";
  const detector = await runtime.InferenceSession.create(await cachedBytes(`${SERVER}/detector-onnx/${config.detector}.onnx`), options);
  const folder = `${SERVER}/${folderFor(config.variant)}`;
  const vocabulary = new TextDecoder().decode(await cachedBytes(`${folder}/vocab.txt`)).split(/\r?\n/);
  if (vocabulary.at(-1) === "") vocabulary.pop();
  const ocr = new MangaOcr({ort: runtime, vocabulary,
    encoder: await runtime.InferenceSession.create(await cachedBytes(`${folder}/encoder.onnx`), options),
    decoder: await runtime.InferenceSession.create(await cachedBytes(`${folder}/decoder.onnx`), options),
    generation: JSON.parse(new TextDecoder().decode(await cachedBytes(`${folder}/generation.json`)))});
  const loadMs = performance.now() - started;
  const pages = (await (await fetch(`${SERVER}/pages/pages.json`)).json()).slice(0, config.pages ?? 10);
  const results = [];
  for (const page of pages) {
    const t = performance.now();
    const bitmap = await createImageBitmap(await (await fetch(`${SERVER}/pages/${page.original}`)).blob());
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(bitmap, 0, 0);
    const {data} = context.getImageData(0, 0, bitmap.width, bitmap.height);
    const {regions} = await detect(runtime, detector, data, bitmap.width, bitmap.height);
    const detectMs = performance.now() - t;
    for (const region of regions) {
      const {left, top, right, bottom} = region.bbox;
      const x = Math.max(0, left - 4), y = Math.max(0, top - 4);
      const w = Math.min(bitmap.width, right + 4) - x, h = Math.min(bitmap.height, bottom + 4) - y;
      const crop = context.getImageData(x, y, w, h);
      await ocr.recognize(crop.data, w, h, {decoding: config.decoding});
    }
    results.push({id: page.id, blocks: regions.length, detectMs, pageMs: performance.now() - t});
  }
  return {config, loadMs, threads: runtime.env.wasm.numThreads, pages: results};
}

globalThis.spike = {
  dictionaryCheck,
  pipeline,
  chromeTranslator,
  async info() {
    return {crossOriginIsolated, hardwareConcurrency: navigator.hardwareConcurrency, userAgent: navigator.userAgent,
            webgpu: await adapterInfo(), deviceMemory: navigator.deviceMemory ?? null};
  },

  async prime(variant) {
    if (variant.startsWith("detector")) {
      return {variant, bytes: (await cachedBytes(`${SERVER}/detector-onnx/${variant}.onnx`, {prime: true})).byteLength};
    }
    const folder = `${SERVER}/${folderFor(variant)}`;
    let bytes = 0;
    for (const name of ["encoder.onnx", "decoder.onnx", "vocab.txt", "generation.json"]) {
      bytes += (await cachedBytes(`${folder}/${name}`, {prime: true})).byteLength;
    }
    return {variant, bytes};
  },

  // config: {variant: "detector"|"detector-fp16", backend, source: "png"|"original", limit}
  async detect(config) {
    const started = performance.now();
    const runtime = await loadRuntime(config.backend, config);
    const options = {executionProviders: [config.backend], graphOptimizationLevel: "all"};
    if (config.backend === "webgpu") options.preferredOutputLocation = "cpu";
    const session = await runtime.InferenceSession.create(await cachedBytes(`${SERVER}/detector-onnx/${config.variant}.onnx`), options);
    const loadMs = performance.now() - started;
    const pages = (await (await fetch(`${SERVER}/pages/pages.json`)).json()).slice(0, config.limit ?? 1000);
    const results = [];
    let firstPageMs = null;
    for (const page of pages) {
      const blob = await (await fetch(`${SERVER}/pages/${config.source === "original" ? page.original : page.png}`)).blob();
      const t = performance.now();
      const bitmap = await createImageBitmap(blob, {colorSpaceConversion: "none", premultiplyAlpha: "none"});
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
      const context = canvas.getContext("2d", {willReadFrequently: true});
      context.drawImage(bitmap, 0, 0);
      const {data} = context.getImageData(0, 0, bitmap.width, bitmap.height);
      const decodeMs = performance.now() - t;
      const result = await detect(runtime, session, data, bitmap.width, bitmap.height);
      const ms = performance.now() - t;
      if (firstPageMs === null) firstPageMs = performance.now() - started;
      results.push({id: page.id, split: page.split, regions: result.regions, warm_ms: [ms], decode_ms: decodeMs, timings: result.timings});
    }
    await session.release();
    return {engine: `browser-${config.variant}-${config.backend}-${config.source}`, config, load_ms: loadMs, firstPageMs,
            threads: runtime.env.wasm.numThreads, adapter: adapterUsed, pages: results};
  },

  // config: {variant, backend: "webgpu"|"wasm", decoding: "beam"|"greedy", limit, files?}
  async run(config) {
    const started = performance.now();
    const runtime = await loadRuntime(config.backend, config);
    const folder = `${SERVER}/${folderFor(config.variant)}`;
    const options = {executionProviders: [config.backend], graphOptimizationLevel: "all"};
    if (config.backend === "webgpu") options.preferredOutputLocation = "cpu";
    const encoderBytes = await cachedBytes(`${folder}/encoder.onnx`);
    const decoderBytes = await cachedBytes(`${folder}/decoder.onnx`);
    const vocabulary = new TextDecoder().decode(await cachedBytes(`${folder}/vocab.txt`)).split(/\r?\n/);
    if (vocabulary.at(-1) === "") vocabulary.pop();
    const generation = JSON.parse(new TextDecoder().decode(await cachedBytes(`${folder}/generation.json`)));
    const readMs = performance.now() - started;
    const encoder = await runtime.InferenceSession.create(encoderBytes, options);
    const decoder = await runtime.InferenceSession.create(decoderBytes, options);
    const loadMs = performance.now() - started;
    const ocr = new MangaOcr({ort: runtime, encoder, decoder, vocabulary, generation});
    const crops = await (await fetch(`${SERVER}/crops/crops.json`)).json();
    const selected = crops.slice(0, config.limit ?? crops.length);
    const rows = [];
    let firstBlockMs = null;
    for (const crop of selected) {
      const blob = await (await fetch(`${SERVER}/crops/${crop.file}`)).blob();
      const bitmap = await createImageBitmap(blob);
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
      const context = canvas.getContext("2d", {willReadFrequently: true});
      context.drawImage(bitmap, 0, 0);
      const {data} = context.getImageData(0, 0, bitmap.width, bitmap.height);
      const t = performance.now();
      const result = await ocr.recognize(data, bitmap.width, bitmap.height, {decoding: config.decoding});
      const ms = performance.now() - t;
      if (firstBlockMs === null) firstBlockMs = performance.now() - started;
      rows.push({...crop, output: result.text, tokens: result.tokens, ms, timings: result.timings});
    }
    await encoder.release(); await decoder.release();
    return {config, readMs, loadMs, firstBlockMs, crossOriginIsolated,
            threads: runtime.env.wasm.numThreads, adapter: adapterUsed, rows};
  },
};
