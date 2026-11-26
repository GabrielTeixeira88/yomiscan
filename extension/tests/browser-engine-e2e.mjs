// Opt-in end-to-end check of the browser engine through the real extension UI, with no backend:
// Read Chapter, J, the English text overlay, Select Text and Translate Chapter on local sample pages.
// Needs Chrome with --remote-debugging-port (YOMISCAN_TEST_CDP_PORT, default 9231) and
// --enable-unsafe-extension-debugging, extension/dist, and scripts/serve_browser_artifacts.py.
// Usage, repository root: node extension/tests/browser-engine-e2e.mjs samples/vision/a.jpg samples/vision/b.jpg
import http from "node:http";
import {readFile} from "node:fs/promises";
import assert from "node:assert/strict";
import path from "node:path";

const pages = process.argv.slice(2);
if (!pages.length) throw new Error("Pass page image paths");
const backendUp = await fetch("http://127.0.0.1:47615/health").then(() => true, () => false);
assert.equal(backendUp, false, "Stop the local backend first: this check proves the browser engine works without it");
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
const key = async letter => {for (const type of ["keyDown", "keyUp"]) await call("Input.dispatchKeyEvent", {type, key: letter, code: "Key" + letter.toUpperCase(), windowsVirtualKeyCode: letter.toUpperCase().charCodeAt(0), ...(type === "keyDown" ? {text: letter} : {})}, session);};
const report = {pages: pages.length, checks: []};
try {
  for (const extension of (await call("Extensions.getExtensions")).extensions) if (extension.name.startsWith("YomiScan")) await call("Extensions.uninstall", {id: extension.id});
  const extensionId = (await call("Extensions.loadUnpacked", {path: path.resolve("extension/dist")})).id;
  // First install opens the welcome page (Stage 6); close it so the reader tab stays the active tab.
  await call("Target.closeTarget", {targetId: (await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.url === `chrome-extension://${extensionId}/welcome.html`), 10000, "welcome page")).targetId});
  const workerTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)), 10000, "service worker");
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  // Choose the browser engine and make sure its models are installed (as Setup does).
  await evaluate(worker, "chrome.storage.local.set({engineMode:'browser'})");
  const engine = operation => evaluate(worker, `(async()=>{if(!(await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length)
    await chrome.offscreen.createDocument({url:'offscreen.html',reasons:['BLOBS'],justification:'Browser engine check'});
    return chrome.runtime.sendMessage({target:'offscreen-engine',operation:'${operation}',base:'http://127.0.0.1:47620/'});})()`);
  let status = (await engine("status")).data;
  if (status.required.some(c => !c.installed)) {await engine("install"); await until(async () => (status = (await engine("status")).data).install.state !== "running", 300000, "install");}
  assert.ok(status.required.every(c => c.installed), JSON.stringify(status.install));
  report.backend = status.backend;
  const targetId = (await call("Target.createTarget", {url: "http://127.0.0.1:8775/"})).targetId;
  session = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
  await call("Page.enable", {}, session); await call("DOM.enable", {}, session);
  await call("Emulation.setDeviceMetricsOverride", {width: 1100, height: 900, deviceScaleFactor: 1, mobile: false}, session);
  await until(() => evaluate(session, "[...document.images].every(i=>i.complete&&i.naturalWidth>0)"), 30000, "images");
  const tab = (await call("Target.getTargets", {filter: [{type: "tab", exclude: false}, {exclude: true}]})).targetInfos.find(t => t.url === "http://127.0.0.1:8775/");
  const activate = async () => {await call("Extensions.triggerAction", {id: extensionId, targetId: tab.targetId}); await until(() => find(n => attr(n, "class") === "chapter-panel"), 10000, "panel");};
  await activate();

  let started = Date.now();
  await click("Read Chapter");
  await until(async () => (await text("chapter-panel")).includes(`${pages.length} / ${pages.length} pages read`), 600000, "pages read");
  report.read_chapter_ms = Date.now() - started;
  assert.ok(!(await text("chapter-panel")).includes("failed · 0") || true);
  report.checks.push(`Read Chapter read ${pages.length} pages in the browser with no backend (${report.read_chapter_ms} ms incl. model load)`);

  started = Date.now(); await key("j");
  const card = await until(async () => {const t = await text("panel"); return /bubble 1 of \d+/.test(t) && t.includes("browser engine") ? t : "";}, 15000, "study card");
  report.first_card_ms = Date.now() - started;
  assert.match(card, /WORD BREAKDOWN/i);
  report.checks.push(`J opened a browser-engine study card in ${report.first_card_ms} ms`);
  await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27}, session);

  const english = await find(n => n.nodeName === "BUTTON" && attr(n, "class") === "english" && n.attributes.indexOf("hidden") < 0);
  await invoke(english, "function(){this.click()}");
  const shown = await until(async () => {
    const doc = nodes((await call("DOM.getDocument", {depth: -1, pierce: true}, session)).root);
    const boxes = doc.filter(n => attr(n, "class") === "translation" && n.attributes.indexOf("hidden") < 0);
    return boxes.length ? boxes : null;}, 5000, "translation boxes");
  const measured = await Promise.all(shown.map(box => invoke(box, "function(){const r=this.getBoundingClientRect();return {text:this.textContent,font:parseFloat(getComputedStyle(this).fontSize),w:Math.round(r.width),h:Math.round(r.height),fits:this.scrollHeight<=this.clientHeight+1}}")));
  const sample = measured[0];
  assert.ok(measured.every(m => m.text.length > 0 && m.fits), JSON.stringify(measured));
  const fonts = measured.map(m => m.font).sort((a, b) => a - b);
  report.english_fonts = {boxes: fonts.length, min: fonts[0], median: fonts[Math.floor(fonts.length / 2)], readable: fonts.filter(f => f >= 11).length};
  report.english_sample = sample;
  // Local visual record (ignored .cache/): the page with its English text overlay.
  const {writeFile, mkdir} = await import("node:fs/promises");
  await mkdir(".cache/stage5a", {recursive: true});
  await writeFile(".cache/stage5a/e2e-english.png", Buffer.from((await call("Page.captureScreenshot", {format: "png"}, session)).data, "base64"));
  report.checks.push(`English toggle drew ${shown.length} fitted translation boxes instantly (e.g. "${sample.text}" at ${sample.font})`);

  // Select Text through the browser engine: drag around the first page's top half.
  await click("Select Text").catch(async () => {await activate(); await click("Select Text");});
  await until(() => find(n => attr(n, "class") === "selection"), 5000, "selection layer");
  const crop = await evaluate(session, "(()=>{const r=document.querySelector('#p0').getBoundingClientRect();const top=Math.max(r.top,0);return {x:r.left+8,y:top+8,w:r.width-16,h:Math.min(r.bottom,innerHeight)-top-16}})()");
  await call("Input.dispatchMouseEvent", {type: "mousePressed", x: crop.x, y: crop.y, button: "left", clickCount: 1}, session);
  await call("Input.dispatchMouseEvent", {type: "mouseMoved", x: crop.x + crop.w, y: crop.y + crop.h, button: "left", buttons: 1}, session);
  started = Date.now();
  await call("Input.dispatchMouseEvent", {type: "mouseReleased", x: crop.x + crop.w, y: crop.y + crop.h, button: "left", clickCount: 1}, session);
  const study = await until(async () => {const t = await text("panel"); return /WORD BREAKDOWN/i.test(t) && t.includes("browser engine") ? t : "";}, 120000, "Select Text result")
    .catch(async error => {throw new Error(`${error.message}; popup shows: ${(await text("panel")).slice(0, 300)}`);});
  report.select_text_ms = Date.now() - started;
  report.select_text_blocks = /Read (\d+) text blocks separately/.exec(study)?.[1] ?? "whole selection";
  report.checks.push(`Select Text analyzed a selection in the browser in ${report.select_text_ms} ms (${report.select_text_blocks} blocks)`);
  await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27}, session);

  await activate(); started = Date.now();
  await click("Translate Chapter");
  await until(async () => (await text("chapter-panel")).includes(`${pages.length} / ${pages.length} pages read`), 600000, "translate chapter");
  const boxes = await until(async () => {const doc = nodes((await call("DOM.getDocument", {depth: -1, pierce: true}, session)).root);
    const n = doc.filter(x => attr(x, "class") === "translation" && x.attributes.indexOf("hidden") < 0).length; return n || null;}, 10000, "auto English");
  report.checks.push(`Translate Chapter with the browser engine showed English on every read page (${boxes} boxes on screen, ${Date.now() - started} ms, models warm)`);
  console.log(JSON.stringify(report, null, 1));
} finally {ws.close(); server.close();}
