// Opt-in end-to-end check of the local engine companion (Stage 5b increment 4), in real Chrome:
// the extension ID Chrome assigns equals the one the registration computed, Automatic starts the
// companion through native messaging (no browser models, no developer backend), Read Chapter and
// Translate Chapter run through it with its per-launch token, the engine exits when idle, and the
// next action launches it again.
// Needs: the frozen engine (scripts/build_engine.py) with its models (yomiscan-engine.exe --prepare),
// registered for extension/dist (yomiscan-engine.exe --register --extension-path extension/dist);
// the developer backend stopped; Chrome started with --remote-debugging-port (YOMISCAN_TEST_CDP_PORT,
// default 9231) and --enable-unsafe-extension-debugging, from an environment where
// YOMISCAN_IDLE_SECONDS is short (e.g. 20) so the idle exit can be observed.
// Usage, repository root: node extension/tests/companion-e2e.mjs <expected-extension-id> samples/vision/a.jpg ...
import http from "node:http";
import {readFile} from "node:fs/promises";
import assert from "node:assert/strict";
import path from "node:path";

const [expectedId, ...pages] = process.argv.slice(2);
if (!/^[a-p]{32}$/.test(expectedId ?? "") || !pages.length) throw new Error("Pass the registered extension ID and page image paths");
const backendUp = await fetch("http://127.0.0.1:47615/health").then(() => true, () => false);
assert.equal(backendUp, false, "Stop the developer backend first: only the companion may serve this run");
const statePath = path.join(process.env.LOCALAPPDATA, "YomiScan", "engine-state.json");
const engineState = async () => {try {return JSON.parse(await readFile(statePath, "utf8"));} catch {return null;}};
const engineAnswers = async state => state && await fetch(`http://127.0.0.1:${state.port}/api/v1/readiness`, {headers: {
  "X-YomiScan-Client": "study-extension-v1", "X-YomiScan-Token": state.token}, signal: AbortSignal.timeout(2000)}).then(r => r.ok, () => false);

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
await new Promise(resolve => server.listen(8776, "127.0.0.1", resolve));

const version = await (await fetch(`http://127.0.0.1:${process.env.YOMISCAN_TEST_CDP_PORT ?? 9231}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener("open", resolve, {once: true}));
let next = 0; const callbacks = new Map();
ws.addEventListener("message", event => {const m = JSON.parse(event.data); if (m.id) {const c = callbacks.get(m.id); callbacks.delete(m.id); m.error ? c.reject(new Error(JSON.stringify(m.error))) : c.resolve(m.result);}});
const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {const id = ++next; callbacks.set(id, {resolve, reject}); ws.send(JSON.stringify({id, method, params, sessionId}));});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function evaluate(session, expression) {const r = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}, session); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;}
async function until(check, timeout = 60000, label = "condition") {const end = Date.now() + timeout; while (Date.now() < end) {const v = await check(); if (v) return v; await wait(250);} throw new Error(`Timed out: ${label}`);}
const nodes = root => [root, ...(root.children ?? []).flatMap(nodes), ...(root.shadowRoots ?? []).flatMap(nodes)];
const attr = (n, name) => {const i = n.attributes?.indexOf(name) ?? -1; return i >= 0 ? n.attributes[i + 1] : undefined;};
let session;
const find = async predicate => nodes((await call("DOM.getDocument", {depth: -1, pierce: true}, session)).root).find(predicate);
async function invoke(node, fn) {const o = await call("DOM.resolveNode", {backendNodeId: node.backendNodeId}, session); const r = await call("Runtime.callFunctionOn", {objectId: o.object.objectId, functionDeclaration: fn, returnByValue: true, awaitPromise: true, userGesture: true}, session); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;}
const panel = async () => {const n = await find(n => attr(n, "class") === "chapter-panel"); return n ? invoke(n, "function(){return this.innerText}") : "";};
const click = async label => {const n = await find(n => n.nodeName === "BUTTON" && n.children?.some(c => c.nodeValue === label)); assert.ok(n, `Button ${label}`); await invoke(n, "function(){this.click()}");};
const report = {pages: pages.length, checks: []};
try {
  for (const extension of (await call("Extensions.getExtensions")).extensions) if (extension.name.startsWith("YomiScan")) await call("Extensions.uninstall", {id: extension.id});
  const extensionId = (await call("Extensions.loadUnpacked", {path: path.resolve("extension/dist")})).id;
  assert.equal(extensionId, expectedId, "Chrome's unpacked extension ID differs from the registered one");
  report.checks.push(`Chrome assigned ${extensionId}, the ID the registration computed from the folder path`);
  const workerTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)), 10000, "service worker");
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  await evaluate(worker, "Promise.all([chrome.storage.local.clear(),chrome.storage.session.clear()])");  // Automatic, no browser models
  const status = await evaluate(worker, "chrome.runtime.sendNativeMessage('com.yomiscan.engine',{type:'status'})");
  assert.ok(status.ok && status.models.ready, JSON.stringify(status));
  report.checks.push(`Native host answers status: version ${status.version}, models ready`);

  const targetId = (await call("Target.createTarget", {url: "http://127.0.0.1:8776/"})).targetId;
  session = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
  await call("Page.enable", {}, session); await call("DOM.enable", {}, session);
  await call("Emulation.setDeviceMetricsOverride", {width: 1100, height: 900, deviceScaleFactor: 1, mobile: false}, session);
  await until(() => evaluate(session, "[...document.images].every(i=>i.complete&&i.naturalWidth>0)"), 30000, "images");
  const tab = (await call("Target.getTargets", {filter: [{type: "tab", exclude: false}, {exclude: true}]})).targetInfos.find(t => t.url === "http://127.0.0.1:8776/");
  const activate = async () => {await call("Extensions.triggerAction", {id: extensionId, targetId: tab.targetId}); await until(() => find(n => attr(n, "class") === "chapter-panel"), 10000, "panel");};
  await activate();

  let started = Date.now();
  await click("Read Chapter");
  await until(async () => (await panel()).includes(`${pages.length} / ${pages.length} pages read`), 300000, "pages read");
  report.read_chapter_ms = Date.now() - started;
  const first = await engineState();
  assert.ok(first && await engineAnswers(first), "the companion engine runs after the host exited");
  report.checks.push(`Automatic started the companion (pid ${first.pid}, random port) and Read Chapter read ${pages.length} pages in ${(report.read_chapter_ms / 1000).toFixed(1)} s incl. engine start and model load`);

  started = Date.now();
  await click("Translate Chapter");
  await until(async () => (await panel()).includes(`${pages.length} / ${pages.length} pages translated`), 600000, "pages translated");
  report.translate_chapter_ms = Date.now() - started;
  report.checks.push(`Translate Chapter rendered ${pages.length} pages with the pixel renderer in ${(report.translate_chapter_ms / 1000).toFixed(1)} s`);

  started = Date.now();
  // Watch the process, not the API: a readiness probe would itself count as activity.
  const alive = pid => {try {process.kill(pid, 0); return true;} catch {return false;}};
  await until(async () => !alive(first.pid), 180000, "idle exit");
  report.checks.push(`The engine exited by itself ${((Date.now() - started) / 1000).toFixed(0)} s after the last request (YOMISCAN_IDLE_SECONDS=${process.env.YOMISCAN_IDLE_SECONDS ?? "unset"})`);

  started = Date.now();
  await click("Read Chapter");
  await until(async () => (await panel()).includes(`${pages.length} / ${pages.length} pages read`), 300000, "pages read again");
  const second = await engineState();
  assert.ok(second && second.pid !== first.pid && await engineAnswers(second), "a new engine was launched");
  report.checks.push(`The next Read Chapter launched a new engine (pid ${second.pid}) and finished in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  console.log(JSON.stringify(report, null, 1));
} finally {ws.close(); server.close();}
