// Opt-in end-to-end check of first-run setup (Stage 5a increment 5), with no backend and no models:
// the panel offers the download with its size and source, nothing downloads before the click, the
// click installs and verifies every file, Automatic then reads a chapter in the browser, memory is
// measured with every model loaded, and models that Chrome removed are offered again.
// Needs Chrome with --remote-debugging-port (YOMISCAN_TEST_CDP_PORT, default 9231) and
// --enable-unsafe-extension-debugging, and extension/dist. Models come from the build's default
// source (the published Hugging Face commit) unless YOMISCAN_MODEL_SOURCE overrides it, e.g. the
// loopback server from scripts/serve_browser_artifacts.py. YOMISCAN_TEST_THREADS=4 emulates a
// 4-core CPU for the WASM path (run Chrome with --disable-gpu for that path).
// Usage, repository root: node extension/tests/first-run-e2e.mjs samples/vision/a.jpg samples/vision/b.jpg
import http from "node:http";
import {readFile} from "node:fs/promises";
import assert from "node:assert/strict";
import path from "node:path";

const pages = process.argv.slice(2);
if (!pages.length) throw new Error("Pass page image paths");
const backendUp = await fetch("http://127.0.0.1:47615/health").then(() => true, () => false);
assert.equal(backendUp, false, "Stop the local backend first: first-run setup appears only when no engine can serve");
const server = http.createServer(async (req, res) => {
  if (req.url === "/") {
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.end(`<!doctype html><title>Reader</title><style>body{margin:0;background:#ddd}main{width:min(720px,95vw);margin:20px auto}img{display:block;width:100%;height:auto;margin:0 0 16px}</style><main>${
      pages.map((_, i) => `<img id="p${i}" src="/page/${i}${path.extname(pages[i])}">`).join("")}</main>`);
    return;
  }
  const match = /^\/page\/(\d+)/.exec(req.url ?? "");
  if (!match || !pages[Number(match[1])]) {res.writeHead(404); res.end(); return;}
  res.setHeader("Content-Type", pages[Number(match[1])].endsWith(".png") ? "image/png" : "image/jpeg");
  res.end(await readFile(pages[Number(match[1])]));
});
await new Promise(resolve => server.listen(8775, "127.0.0.1", resolve));

const version = await (await fetch(`http://127.0.0.1:${process.env.YOMISCAN_TEST_CDP_PORT ?? 9231}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener("open", resolve, {once: true}));
let next = 0; const callbacks = new Map();
ws.addEventListener("message", event => {const m = JSON.parse(event.data); if (m.id) {const c = callbacks.get(m.id); callbacks.delete(m.id); m.error ? c.reject(new Error(JSON.stringify(m.error))) : c.resolve(m.result);}});
const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {const id = ++next; callbacks.set(id, {resolve, reject}); ws.send(JSON.stringify({id, method, params, sessionId}));});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function evaluate(session, expression) {const r = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}, session); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;}
async function until(check, timeout = 60000, label = "condition") {const end = Date.now() + timeout; while (Date.now() < end) {const v = await check(); if (v) return v; await wait(200);} throw new Error(`Timed out: ${label}`);}
const nodes = root => [root, ...(root.children ?? []).flatMap(nodes), ...(root.shadowRoots ?? []).flatMap(nodes)];
const attr = (n, name) => {const i = n.attributes?.indexOf(name) ?? -1; return i >= 0 ? n.attributes[i + 1] : undefined;};
let session;
const find = async predicate => nodes((await call("DOM.getDocument", {depth: -1, pierce: true}, session)).root).find(predicate);
async function invoke(node, fn) {const o = await call("DOM.resolveNode", {backendNodeId: node.backendNodeId}, session); const r = await call("Runtime.callFunctionOn", {objectId: o.object.objectId, functionDeclaration: fn, returnByValue: true, awaitPromise: true, userGesture: true}, session); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;}
const text = async className => {const n = await find(n => attr(n, "class") === className); return n ? invoke(n, "function(){return this.innerText}") : "";};
const click = async label => {const n = await find(n => n.nodeName === "BUTTON" && n.children?.some(c => c.nodeValue === label)); assert.ok(n, `Button ${label}`); await invoke(n, "function(){this.click()}");};
/** The setup card's text while it is shown, otherwise "". */
const card = async () => {const n = await find(n => attr(n, "class") === "setup"); return n ? invoke(n, "function(){return this.hidden?'':this.innerText}") : "";};
const report = {pages: pages.length, checks: []};
try {
  for (const extension of (await call("Extensions.getExtensions")).extensions) if (extension.name.startsWith("YomiScan")) await call("Extensions.uninstall", {id: extension.id});
  const extensionId = (await call("Extensions.loadUnpacked", {path: path.resolve("extension/dist")})).id;
  // First install opens the welcome page (Stage 6); close it so the reader tab stays the active tab.
  await call("Target.closeTarget", {targetId: (await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.url === `chrome-extension://${extensionId}/welcome.html`), 10000, "welcome page")).targetId});
  const workerTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)), 10000, "service worker");
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  // A first run: Automatic engine, no models (an earlier run's files are removed), only the source override if given.
  await evaluate(worker, `chrome.storage.local.clear().then(()=>${process.env.YOMISCAN_MODEL_SOURCE ? `chrome.storage.local.set({engineArtifactSource:${JSON.stringify(process.env.YOMISCAN_MODEL_SOURCE)}})` : "0"})`);
  await evaluate(worker, "caches.delete('yomiscan-artifacts-v1')");
  report.source = process.env.YOMISCAN_MODEL_SOURCE ?? "build default";

  const targetId = (await call("Target.createTarget", {url: "http://127.0.0.1:8775/"})).targetId;
  session = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
  await call("Page.enable", {}, session); await call("DOM.enable", {}, session);
  await call("Emulation.setDeviceMetricsOverride", {width: 1100, height: 900, deviceScaleFactor: 1, mobile: false}, session);
  await until(() => evaluate(session, "[...document.images].every(i=>i.complete&&i.naturalWidth>0)"), 30000, "images");
  const tab = (await call("Target.getTargets", {filter: [{type: "tab", exclude: false}, {exclude: true}]})).targetInfos.find(t => t.url === "http://127.0.0.1:8775/");
  const activate = async () => {await call("Extensions.triggerAction", {id: extensionId, targetId: tab.targetId}); await until(() => find(n => attr(n, "class") === "chapter-panel"), 10000, "panel");};
  await activate();

  const offer = await until(card, 15000, "setup card");
  const size = /Download \(([\d,]+) MB\)/.exec(offer)?.[1];
  assert.ok(size, offer);
  assert.match(offer, /From .+\. Each file is checked against a fingerprint/);
  report.offer = offer.split("\n").filter(Boolean).slice(0, 3).join(" | ");
  const offscreenTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.url.endsWith("/offscreen.html")), 10000, "offscreen");
  const offscreen = (await call("Target.attachToTarget", {targetId: offscreenTarget.targetId, flatten: true})).sessionId;
  if (process.env.YOMISCAN_TEST_THREADS) await call("Emulation.setHardwareConcurrencyOverride", {hardwareConcurrency: Number(process.env.YOMISCAN_TEST_THREADS)}, offscreen);
  const stored = () => evaluate(offscreen, "caches.open('yomiscan-artifacts-v1').then(c=>c.keys()).then(k=>k.length)");
  assert.equal(await stored(), 0, "nothing is downloaded before consent");
  report.checks.push(`Panel offered the download before anything was fetched: ${size} MB`);

  await click("Not now");
  assert.equal(await card(), "", "Not now hides the card");
  await click("Read Chapter");
  await until(async () => (await text("chapter-panel")).includes("Download the reading models above"), 10000, "read without models");
  assert.ok(await card(), "Read Chapter shows the card again");
  assert.equal(await stored(), 0);
  report.checks.push("Read Chapter without models asked for the download again and started nothing");

  let started = Date.now();
  await click(`Download (${size} MB)`);
  let peak = "";
  await until(async () => {const t = await card(); if (/Downloading the/.test(t)) peak = t.match(/Downloading[^\n]+/)[0]; return t === "" && (await text("chapter-panel")).includes("Reading models installed");}, 1800000, "download");
  report.download_ms = Date.now() - started;
  report.checks.push(`Download (${size} MB) verified and stored in ${(report.download_ms / 1000).toFixed(1)} s; progress showed e.g. "${peak}"`);

  started = Date.now();
  await click("Read Chapter");
  await until(async () => (await text("chapter-panel")).includes(`${pages.length} / ${pages.length} pages read`), 600000, "pages read");
  report.read_chapter_ms = Date.now() - started;
  assert.match(await text("chapter-panel"), /in the browser/);
  report.checks.push(`Automatic chose the browser engine; Read Chapter read ${pages.length} pages in ${report.read_chapter_ms} ms incl. model load`);

  // Memory with detector, OCR, tokenizer, JMdict and OPUS loaded (measureUserAgentSpecificMemory
  // needs cross-origin isolation, which the engine page has). GPU buffers are not included.
  const status = await evaluate(worker, "chrome.runtime.sendMessage({target:'offscreen-engine',operation:'status'}).then(r=>r.data)");
  assert.ok(status.loaded);
  const memory = await evaluate(offscreen, "performance.measureUserAgentSpecificMemory().then(m=>m.bytes)");
  report.memory_mib = Math.round(memory / 2 ** 20);
  report.storage_mib = Math.round(status.storage.usage / 2 ** 20);
  report.device = `${status.backend}, ${status.threads} threads`;
  report.persisted = status.persisted;
  report.checks.push(`Engine page holds ${report.memory_mib} MiB (JS + WASM heaps) with every model loaded on ${report.device}; Cache Storage ${report.storage_mib} MiB`);

  // Chrome clearing storage (e.g. a full disk) is explained, not shown as a first run.
  await evaluate(offscreen, "caches.delete('yomiscan-artifacts-v1')");
  await activate();
  const again = await until(async () => {const t = await card(); return t.startsWith("Download the reading models again") ? t : "";}, 15000, "evicted card");
  assert.match(again, /no longer stored/);
  started = Date.now();
  await click(`Download (${/Download \(([\d,]+) MB\)/.exec(again)[1]} MB)`);
  await until(async () => (await card()) === "" && (await text("chapter-panel")).includes("Reading models installed"), 1800000, "download again");
  report.checks.push(`Removed models were offered again ("Download the reading models again") and reinstalled in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  console.log(JSON.stringify(report, null, 1));
} finally {ws.close(); server.close();}
