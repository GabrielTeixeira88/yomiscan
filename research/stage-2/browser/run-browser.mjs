// Stage 2 spike driver: real Chrome, the spike extension's offscreen document, ONNX Runtime Web.
//   node run-browser.mjs --configs fp32:webgpu:beam,q4:wasm:greedy [--limit N] [--headful] [--out name]
// Serves .cache/stage2 on 127.0.0.1:8790, launches Chrome with a fresh profile and CDP on 9241,
// loads the unpacked extension, and runs each config in a fresh offscreen document after priming
// Cache Storage (so loading measures "artifacts already downloaded"). Windows process memory of
// the extension renderer and GPU process is sampled during each run.
import http from "node:http";
import {spawn, execFileSync} from "node:child_process";
import {cp, mkdir, readFile, writeFile, readdir, rm} from "node:fs/promises";
import path from "node:path";

const args = process.argv.slice(2), flag = name => args.includes(name);
const value = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback; };
const root = path.resolve("../../../.cache/stage2");
// OCR config: variant:backend:decoding. Detector config: detector[-fp16]:backend:png|original.
// Optional extra fields: low-power|high-performance (WebGPU adapter) and tN (WASM thread cap).
// Pipeline config: pipeline:backend:decoding:<ocr variant>:<detector>[:tN]
const configs = value("--configs", "fp32:webgpu:beam").split(",").map(text => {
  const [variant, backend, third, ...extra] = text.split(":");
  if (variant === "pipeline") {
    const [ocrVariant, detector, ...rest] = extra;
    const config = {variant, backend, decoding: third, ocrVariant, detector, pages: 10};
    for (const field of rest) if (/^t\d+$/.test(field)) config.threads = Number(field.slice(1));
    return config;
  }
  const config = variant.startsWith("detector") ? {variant, backend, source: third} : {variant, backend, decoding: third};
  for (const field of extra) {
    if (/^t\d+$/.test(field)) config.threads = Number(field.slice(1));
    else config.power = field;
  }
  return config;
});
const limit = value("--limit") ? Number(value("--limit")) : undefined;
const chrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";

// 1. Assemble the extension.
const extension = path.join(root, "extension");
await rm(extension, {recursive: true, force: true});
await cp("extension", extension, {recursive: true});
await cp("ocr.mjs", path.join(extension, "ocr.mjs"));
await cp("beam.mjs", path.join(extension, "beam.mjs"));
await cp("opus.mjs", path.join(extension, "opus.mjs"));
await cp("detector.mjs", path.join(extension, "detector.mjs"));
await cp("node_modules/@sqlite.org/sqlite-wasm/dist", path.join(extension, "sqlite"), {recursive: true});
// Transformers.js bundle + the onnxruntime-web build it depends on (separate page, separate runtime).
await mkdir(path.join(extension, "tjs"), {recursive: true});
await cp("node_modules/@huggingface/transformers/dist/transformers.min.js", path.join(extension, "tjs", "transformers.min.js"));
const tjsOrt = "node_modules/@huggingface/transformers/node_modules/onnxruntime-web/dist";
for (const name of await readdir(tjsOrt)) if (/^ort-wasm-simd-threaded.*\.(mjs|wasm)$/.test(name)) await cp(path.join(tjsOrt, name), path.join(extension, "tjs", name));
await mkdir(path.join(extension, "ort"), {recursive: true});
for (const name of await readdir("node_modules/onnxruntime-web/dist")) {
  if (/^ort-wasm-simd-threaded.*\.(mjs|wasm)$/.test(name) || ["ort.webgpu.min.mjs", "ort.wasm.min.mjs"].includes(name)) {
    await cp(path.join("node_modules/onnxruntime-web/dist", name), path.join(extension, "ort", name));
  }
}

// 2. Static server for models and crops.
const types = {".json": "application/json", ".png": "image/png", ".txt": "text/plain; charset=utf-8"};
const server = http.createServer(async (req, res) => {
  try {
    if (flag("--probe") && req.url.startsWith("/hf/")) console.log("REQ", req.method, req.url);
    const file = path.join(root, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!file.startsWith(root)) throw new Error("outside root");
    const body = await readFile(file);
    res.writeHead(200, {"Content-Type": types[path.extname(file)] ?? "application/octet-stream",
      "Access-Control-Allow-Origin": "*", "Cross-Origin-Resource-Policy": "cross-origin", "Content-Length": body.length});
    res.end(body);
  } catch { if (flag("--probe")) console.log("404", req.method, req.url); res.writeHead(404); res.end(); }
});
await new Promise(resolve => server.listen(8790, "127.0.0.1", resolve));

// 3. Chrome with a fresh profile.
const profile = path.join(root, `profile-${Date.now()}`);
const browser = spawn(chrome, [`--user-data-dir=${profile}`, "--remote-debugging-port=9241", "--enable-unsafe-extension-debugging",
  "--no-first-run", "--no-default-browser-check", "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
  ...(flag("--headful") ? ["--window-position=-2400,0", "--window-size=800,600"] : ["--headless=new"]),
  ...(value("--chrome-args") ? value("--chrome-args").split(" ") : []), "about:blank"], {stdio: "ignore"});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let version;
for (let i = 0; i < 100 && !version; i++) { try { version = await (await fetch("http://127.0.0.1:9241/json/version")).json(); } catch { await wait(200); } }
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener("open", resolve, {once: true}));
let next = 0; const callbacks = new Map();
ws.addEventListener("message", event => { const m = JSON.parse(event.data); if (m.id) { const c = callbacks.get(m.id); callbacks.delete(m.id); m.error ? c.reject(new Error(JSON.stringify(m.error))) : c.resolve(m.result); } });
const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => { const id = ++next; callbacks.set(id, {resolve, reject}); ws.send(JSON.stringify({id, method, params, sessionId})); });
async function until(check, timeout = 30000) { const end = Date.now() + timeout; while (Date.now() < end) { const v = await check(); if (v) return v; await wait(100); } throw new Error("Timed out"); }
async function evaluate(sessionId, expression) {
  const r = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}, sessionId);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? JSON.stringify(r.exceptionDetails));
  return r.result.value;
}

// 4. Memory sampler: Chrome's child processes (extension renderer, GPU process).
function sampleMemory() {
  const script = `$root=${browser.pid}; Get-CimInstance Win32_Process -Filter "ParentProcessId=$root" | ForEach-Object { $t = if ($_.CommandLine -match '--extension-process') {'extension'} elseif ($_.CommandLine -match '--type=gpu-process') {'gpu'} else {'other'}; "$($_.ProcessId) $t $($_.PrivatePageCount)" }`;
  const out = execFileSync("powershell.exe", ["-NoProfile", "-Command", script], {encoding: "utf8"});
  const peaks = {extension: 0, gpu: 0};
  for (const line of out.trim().split(/\r?\n/)) { const [, type, bytes] = line.split(" "); if (type in peaks) peaks[type] = Math.max(peaks[type], Number(bytes)); }
  return peaks;
}

const report = {browser: version.Browser, headless: !flag("--headful"), runs: []};
try {
  const extensionId = (await call("Extensions.loadUnpacked", {path: extension})).id;
  const workerTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)));
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  // The worker target can appear before its module has defined the helpers.
  await until(() => evaluate(worker, "typeof openOffscreen === 'function' && typeof closeOffscreen === 'function'"));
  async function offscreen() {
    await evaluate(worker, "closeOffscreen()");
    await evaluate(worker, "openOffscreen()");
    const target = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.url.includes(`${extensionId}/offscreen.html`)));
    const session = (await call("Target.attachToTarget", {targetId: target.targetId, flatten: true})).sessionId;
    await until(() => evaluate(session, "typeof globalThis.spike === 'object'"));
    return session;
  }
  let session = await offscreen();
  report.environment = await evaluate(session, "spike.info()");
  console.log(JSON.stringify(report.environment));
  if (value("--opus")) {
    // --opus webgpu:fp16,wasm:q8 ; each in a fresh tab
    const lines = (await readFile(path.join(root, "translation-real.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean)
      .map(l => JSON.parse(l)).map(c => ({id: c.id, text: c.texts[0]}));
    report.opus = [];
    for (const spec of value("--opus").split(",")) {
      // device:dtype[:beam|greedy][:tN]
      const [device, dtype, ...extra] = spec.split(":");
      const decoding = extra.find(e => e === "beam" || e === "greedy") ?? "beam";
      const threadText = extra.find(e => /^t\d+$/.test(e));
      const {targetId} = await call("Target.createTarget", {url: `chrome-extension://${extensionId}/opus.html${value("--opus-model") ? "?model=" + encodeURIComponent(value("--opus-model")) : ""}`});
      const page = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
      await until(() => evaluate(page, "globalThis.opusReady === true").catch(error => {
        if (String(error.message).includes("Cannot find default execution context")) return false;
        throw error;
      }));
      if (flag("--probe")) console.log("probe", JSON.stringify(await evaluate(page, "probeTokenizer()")));
      let result;
      try { result = await evaluate(page, `runOpus(${JSON.stringify({device, dtype, decoding, lines, threads: threadText ? Number(threadText.slice(1)) : 8})})`); }
      catch (error) { result = {device, dtype, error: String(error.message ?? error)}; }
      report.opus.push(result);
      await call("Target.closeTarget", {targetId});
      if (result.error) { console.log(`opus ${spec} ERROR ${result.error.slice(0, 300)}`); continue; }
      const ms = result.rows.slice(1).map(r => r.ms).sort((a, b) => a - b);
      console.log(`opus ${spec} threads=${result.threads} load=${result.loadMs.toFixed(0)}ms median=${ms[Math.floor(ms.length / 2)].toFixed(0)}ms p95=${ms[Math.ceil(.95 * ms.length) - 1].toFixed(0)}ms`);
      await writeFile(path.join(root, `opus-browser-${spec.replaceAll(":", "-")}.json`), JSON.stringify(result, null, 1));
    }
  }
  if (flag("--translator-page")) {
    const lines = (await readFile(path.join(root, "translation-real.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean)
      .map(l => JSON.parse(l)).map(c => ({id: c.id, text: c.texts[0]}));
    const {targetId} = await call("Target.createTarget", {url: `chrome-extension://${extensionId}/translator.html`});
    const page = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
    // A freshly attached tab has no execution context until the page loads; retry only that error.
    await until(() => evaluate(page, "Array.isArray(globalThis.translatorLines)").catch(error => {
      if (String(error.message).includes("Cannot find default execution context")) return false;
      throw error;
    }));
    await evaluate(page, `globalThis.translatorLines = ${JSON.stringify(lines)}; true`);
    for (const type of ["mousePressed", "mouseReleased"]) {
      await call("Input.dispatchMouseEvent", {type, x: 100, y: 50, button: "left", clickCount: 1}, page);
    }
    report.chromeTranslator = await until(() => evaluate(page, "globalThis.translatorResult"), 15 * 60 * 1000);
    const {rows, ...summary} = report.chromeTranslator;
    console.log("chrome translator (page, user gesture)", JSON.stringify(summary), rows ? `${rows.length} lines` : "");
    if (rows) await writeFile(path.join(root, "chrome-translator.json"), JSON.stringify(report.chromeTranslator, null, 1));
  }
  if (flag("--translator")) {
    const lines = (await readFile(path.join(root, "translation-real.jsonl"), "utf8")).split(/\r?\n/).filter(Boolean)
      .map(l => JSON.parse(l)).map(c => ({id: c.id, text: c.texts[0]}));
    report.chromeTranslator = await evaluate(session, `spike.chromeTranslator(${JSON.stringify({lines})})`);
    const {rows, ...summary} = report.chromeTranslator;
    console.log("chrome translator", JSON.stringify(summary), rows ? `${rows.length} lines` : "");
  }
  if (flag("--dictionary")) {
    const golden = JSON.parse(await readFile(path.join(root, "lindera-golden.json"), "utf8"));
    const forms = [...new Set(Object.values(golden.sentences).flat().flatMap(t => [t.surface, t.lemma, t.orthographic_base]).filter(Boolean))];
    report.dictionary = await evaluate(session, `spike.dictionaryCheck(${JSON.stringify({forms})})`);
    console.log("dictionary", JSON.stringify(report.dictionary));
  }
  for (const config of configs) {
    session = await offscreen();
    const isPipeline = config.variant === "pipeline";
    const primeList = isPipeline ? [config.ocrVariant, config.detector] : [config.variant];
    let primedBytes = 0;
    for (const item of primeList) primedBytes += (await evaluate(session, `spike.prime(${JSON.stringify(item)})`)).bytes;
    session = await offscreen(); // fresh document: cold start reads only from Cache Storage
    let peaks = {extension: 0, gpu: 0}, sampling = true;
    const sampler = (async () => { while (sampling) { const s = sampleMemory(); peaks = {extension: Math.max(peaks.extension, s.extension), gpu: Math.max(peaks.gpu, s.gpu)}; await wait(500); } })();
    let result;
    const method = isPipeline ? "pipeline" : config.variant.startsWith("detector") ? "detect" : "run";
    const argument = isPipeline ? {...config, variant: config.ocrVariant} : {...config, limit};
    try { result = await evaluate(session, `spike.${method}(${JSON.stringify(argument)})`); }
    catch (error) { result = {config, error: String(error.message ?? error)}; }
    sampling = false; await sampler;
    result.primedBytes = primedBytes; result.peakPrivateBytes = peaks;
    report.runs.push(result);
    const label = Object.values(config).join(":");
    if (result.error) { console.log(`${label} ERROR ${result.error.slice(0, 400)}`); continue; }
    if (isPipeline) {
      const ms = result.pages.map(p => p.pageMs).sort((a, b) => a - b);
      const blocks = result.pages.reduce((n, p) => n + p.blocks, 0);
      console.log(`${label} load=${result.loadMs.toFixed(0)}ms pages=${result.pages.length} blocks=${blocks} median page=${ms[Math.floor(ms.length / 2)].toFixed(0)}ms ` +
        `max page=${ms.at(-1).toFixed(0)}ms peak ext=${(peaks.extension / 2 ** 20).toFixed(0)}MiB gpu=${(peaks.gpu / 2 ** 20).toFixed(0)}MiB`);
      continue;
    }
    if (method === "detect") {
      const ms = result.pages.slice(1).map(p => p.warm_ms[0]).sort((a, b) => a - b);
      console.log(`${label} load=${result.load_ms.toFixed(0)}ms first=${result.firstPageMs.toFixed(0)}ms median=${ms[Math.floor(ms.length / 2)].toFixed(0)}ms ` +
        `peak ext=${(peaks.extension / 2 ** 20).toFixed(0)}MiB gpu=${(peaks.gpu / 2 ** 20).toFixed(0)}MiB`);
      await writeFile(path.join(root, `browser-${label.replaceAll(":", "-")}.json`), JSON.stringify(result, null, 1));
      continue;
    }
    const ms = result.rows.slice(1).map(r => r.ms).sort((a, b) => a - b);
    const q = p => ms.length ? ms[Math.min(ms.length - 1, Math.ceil(p * ms.length) - 1)] : NaN;
    const same = result.rows.filter(r => r.output === r.reference_output).length;
    console.log(`${config.variant}:${config.backend}:${config.decoding} threads=${result.threads} coi=${result.crossOriginIsolated} load=${result.loadMs.toFixed(0)}ms first=${result.firstBlockMs.toFixed(0)}ms ` +
      `median=${q(.5).toFixed(0)}ms p95=${q(.95).toFixed(0)}ms same-as-reference=${same}/${result.rows.length} ` +
      `peak ext=${(peaks.extension / 2 ** 20).toFixed(0)}MiB gpu=${(peaks.gpu / 2 ** 20).toFixed(0)}MiB`);
  }
} finally {
  const name = value("--out", `browser-${Date.now()}`);
  await writeFile(path.join(root, `${name}.json`), JSON.stringify(report, null, 1));
  try { await call("Browser.close"); } catch {}
  browser.kill(); server.close(); ws.close();
}
