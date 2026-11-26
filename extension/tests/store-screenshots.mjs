// Chrome Web Store screenshots (1280 x 800) and the small promo tile (440 x 280), made from an
// original synthetic manga page (drawn here with HTML and CSS: scenery and speech bubbles with
// vertical Japanese text; no third-party artwork) read by the real extension and engine.
// Needs extension/dist, an engine Automatic can use (the installed companion or the browser models),
// and Chrome with --remote-debugging-port (YOMISCAN_TEST_CDP_PORT, default 9231) and
// --enable-unsafe-extension-debugging. Usage, repository root:
//   node extension/tests/store-screenshots.mjs [--out docs/store/screenshots]
import http from "node:http";
import {mkdir, readFile, writeFile} from "node:fs/promises";
import assert from "node:assert/strict";
import path from "node:path";

const args = process.argv.slice(2), at = args.indexOf("--out");
const out = path.resolve(at >= 0 ? args[at + 1] : "docs/store/screenshots");
await mkdir(out, {recursive: true});

const bubble = (text, style) => `<div class="bubble" style="${style}"><p>${text}</p></div>`;
/** One original page: three panels of simple scenery, with speech bubbles. */
const SYNTHETIC_PAGE = `<!doctype html><meta charset="utf-8"><style>
  body{margin:0;width:900px;height:1260px;background:#fff;font-family:"Yu Gothic","Meiryo","Hiragino Sans","Noto Sans CJK JP",sans-serif}
  .panel{position:absolute;border:5px solid #111;overflow:hidden;background:#fff}
  .bubble{position:absolute;background:#fff;border:4px solid #111;border-radius:50%;display:flex;align-items:center;justify-content:center}
  .bubble p{margin:0;writing-mode:vertical-rl;font-size:34px;font-weight:600;line-height:1.35;color:#111;letter-spacing:.06em}
  .sun{position:absolute;width:120px;height:120px;border-radius:50%;border:5px solid #111;background:repeating-radial-gradient(circle,#fff 0 6px,#e9e9e9 6px 9px)}
  .hill{position:absolute;border:5px solid #111;border-radius:50% 50% 0 0;background:repeating-linear-gradient(45deg,#fff 0 7px,#dcdcdc 7px 10px)}
  .cloud{position:absolute;height:60px;border:5px solid #111;border-radius:40px;background:#f2f2f2}
  .rain{position:absolute;width:4px;height:44px;background:#555;transform:rotate(14deg)}
</style>
<div class="panel" style="left:24px;top:24px;width:842px;height:520px">
  <div class="sun" style="left:60px;top:50px"></div>
  <div class="hill" style="left:-60px;top:330px;width:560px;height:260px"></div>
  <div class="hill" style="left:380px;top:390px;width:600px;height:220px"></div>
  ${bubble("今日は<br>いい天気<br>だね", "left:560px;top:40px;width:230px;height:300px")}
</div>
<div class="panel" style="left:24px;top:568px;width:409px;height:668px">
  <div class="hill" style="left:-80px;top:470px;width:560px;height:260px"></div>
  ${bubble("散歩に<br>行こうか", "left:150px;top:50px;width:200px;height:290px")}
</div>
<div class="panel" style="left:457px;top:568px;width:409px;height:668px">
  <div class="cloud" style="left:30px;top:40px;width:170px"></div><div class="cloud" style="left:150px;top:90px;width:200px"></div>
  ${[60, 130, 200, 270, 340].map((x, i) => `<div class="rain" style="left:${x}px;top:${200 + (i % 2) * 40}px"></div>`).join("")}
  ${bubble("雨が<br>降るかも<br>しれない", "left:100px;top:300px;width:230px;height:320px")}
</div>`;
const READER = `<!doctype html><meta charset="utf-8"><title>Synthetic chapter</title>
<style>body{margin:0;background:#2b2f2d}main{width:min(620px,90vw);margin:24px auto}img{display:block;width:100%;height:auto}</style>
<main><img src="/page/1.png" alt="Synthetic page"></main>`;
const PROMO = (icon) => `<!doctype html><meta charset="utf-8"><style>
  body{margin:0;width:440px;height:280px;display:flex;align-items:center;gap:22px;padding:0 30px;box-sizing:border-box;
    background:linear-gradient(135deg,#235d3c,#1a4630);color:#fffdf8;font-family:system-ui,"Segoe UI",sans-serif}
  img{width:112px;height:112px}h1{margin:0;font-size:40px;letter-spacing:.01em}p{margin:8px 0 0;font-size:17px;line-height:1.4;color:#d8e8dc}
</style><img src="data:image/png;base64,${icon}"><div><h1>YomiScan</h1><p>Read manga in Japanese.<br>Study every bubble, on your computer.</p></div>`;

let pagePng = null;
const server = http.createServer((req, res) => {
  const send = (type, body) => {res.setHeader("Content-Type", type); res.end(body);};
  if (req.url === "/source") return send("text/html; charset=utf-8", SYNTHETIC_PAGE);
  if (req.url === "/") return send("text/html; charset=utf-8", READER);
  if (req.url === "/page/1.png" && pagePng) return send("image/png", pagePng);
  res.writeHead(404); res.end();
});
await new Promise(resolve => server.listen(8778, "127.0.0.1", resolve));

const version = await (await fetch(`http://127.0.0.1:${process.env.YOMISCAN_TEST_CDP_PORT ?? 9231}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener("open", resolve, {once: true}));
let next = 0; const callbacks = new Map();
ws.addEventListener("message", event => {
  const m = JSON.parse(event.data);
  if (m.id) {const c = callbacks.get(m.id); callbacks.delete(m.id); m.error ? c.reject(new Error(JSON.stringify(m.error))) : c.resolve(m.result);}
});
const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {const id = ++next; callbacks.set(id, {resolve, reject}); ws.send(JSON.stringify({id, method, params, sessionId}));});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function evaluate(session, expression) {const r = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}, session); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;}
async function until(check, timeout = 60000, label = "condition") {const end = Date.now() + timeout; while (Date.now() < end) {const v = await check(); if (v) return v; await wait(250);} throw new Error(`Timed out: ${label}`);}
const nodes = root => [root, ...(root.children ?? []).flatMap(nodes), ...(root.shadowRoots ?? []).flatMap(nodes)];
const attr = (n, name) => {const i = n.attributes?.indexOf(name) ?? -1; return i >= 0 ? n.attributes[i + 1] : undefined;};
const find = async (session, predicate) => nodes((await call("DOM.getDocument", {depth: -1, pierce: true}, session)).root).find(predicate);
const findAll = async (session, predicate) => nodes((await call("DOM.getDocument", {depth: -1, pierce: true}, session)).root).filter(predicate);
async function invoke(session, node, fn) {const o = await call("DOM.resolveNode", {backendNodeId: node.backendNodeId}, session); const r = await call("Runtime.callFunctionOn", {objectId: o.object.objectId, functionDeclaration: fn, returnByValue: true, awaitPromise: true, userGesture: true}, session); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;}
const text = async (session, className) => {const n = await find(session, n => attr(n, "class") === className); return n ? invoke(session, n, "function(){return this.innerText}") : "";};
const click = async (session, label) => {const n = await find(session, n => n.nodeName === "BUTTON" && n.children?.some(c => c.nodeValue === label)); assert.ok(n, `Button ${label}`); await invoke(session, n, "function(){this.click()}");};
async function open(url, width, height) {
  const targetId = (await call("Target.createTarget", {url: "about:blank"})).targetId;
  const session = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
  await call("Page.enable", {}, session); await call("DOM.enable", {}, session);
  await call("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 1, mobile: false}, session);
  await call("Emulation.setEmulatedMedia", {features: [{name: "prefers-color-scheme", value: "light"}]}, session);
  await call("Page.navigate", {url}, session);
  await until(() => evaluate(session, "document.readyState === 'complete'"), 15000, url);
  return {targetId, session};
}
const shot = async (session, name, clip) => {
  const {data} = await call("Page.captureScreenshot", {format: "png", ...clip ? {clip: {...clip, scale: 1}} : {}}, session);
  await writeFile(path.join(out, name), Buffer.from(data, "base64"));
  console.log("wrote", name);
};

try {
  // 1. The synthetic page as an image, like a reader's page.
  const source = await open("http://127.0.0.1:8778/source", 900, 1260);
  await wait(300);
  pagePng = Buffer.from((await call("Page.captureScreenshot", {format: "png"}, source.session)).data, "base64");

  // 2. A fresh extension, without the first-install welcome tab in the way.
  for (const extension of (await call("Extensions.getExtensions")).extensions) if (extension.name.startsWith("YomiScan")) await call("Extensions.uninstall", {id: extension.id});
  const extensionId = (await call("Extensions.loadUnpacked", {path: path.resolve("extension/dist")})).id;
  const welcome = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.url === `chrome-extension://${extensionId}/welcome.html`), 10000, "welcome page");
  const welcomeSession = (await call("Target.attachToTarget", {targetId: welcome.targetId, flatten: true})).sessionId;
  await call("Emulation.setDeviceMetricsOverride", {width: 1280, height: 800, deviceScaleFactor: 1, mobile: false}, welcomeSession);
  await call("Emulation.setEmulatedMedia", {features: [{name: "prefers-color-scheme", value: "light"}]}, welcomeSession);
  await wait(500);
  await shot(welcomeSession, "5-welcome.png");
  const workerTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)), 10000, "service worker");
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  await evaluate(worker, `new Promise(r=>{const q=indexedDB.deleteDatabase('yomiscan-library');q.onsuccess=q.onerror=q.onblocked=()=>r(true)})`);

  // 3. Read Chapter on the synthetic page, then a study card.
  const reader = await open("http://127.0.0.1:8778/", 1280, 800);
  await until(() => evaluate(reader.session, "[...document.images].every(i=>i.complete&&i.naturalWidth>0)"), 15000, "page image");
  const tab = (await call("Target.getTargets", {filter: [{type: "tab", exclude: false}, {exclude: true}]})).targetInfos.find(t => t.url === "http://127.0.0.1:8778/");
  await call("Extensions.triggerAction", {id: extensionId, targetId: tab.targetId});
  await until(() => find(reader.session, n => attr(n, "class") === "chapter-panel"), 10000, "panel");
  await click(reader.session, "Read Chapter");
  await until(async () => (await text(reader.session, "chapter-panel")).includes("1 / 1 pages read"), 300000, "page read");
  // The rain bubble: かもしれない is an expression, 降る a verb with furigana.
  const outlines = await until(async () => {const all = await findAll(reader.session, n => n.nodeName === "BUTTON" && attr(n, "aria-label")?.startsWith("Study page 1 bubble")); return all.length >= 3 ? all : null;}, 20000, "bubble outlines");
  const rain = outlines.find(n => /雨|降|しれない/.test(attr(n, "aria-label"))) ?? outlines.at(-1);
  await invoke(reader.session, rain, "function(){this.click()}");
  await until(async () => /Word breakdown/i.test(await text(reader.session, "panel")), 30000, "study card");
  for (const node of (await findAll(reader.session, n => n.nodeName === "BUTTON" && attr(n, "class")?.includes("save-word"))).slice(0, 3))
    await invoke(reader.session, node, "function(){this.click()}");
  await wait(800);
  await shot(reader.session, "1-study-card.png");

  // 4. The word breakdown further down the same card.
  const body = await find(reader.session, n => attr(n, "class") === "body");
  await invoke(reader.session, body, "function(){const h=[...this.querySelectorAll('h2')].find(e=>/word breakdown/i.test(e.textContent));if(h)this.scrollTop=h.offsetTop-12}");
  await wait(300);
  await shot(reader.session, "2-word-breakdown.png");

  // 5. Translate Chapter: English over the bubbles.
  await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27}, reader.session);
  await click(reader.session, "Translate Chapter");
  await until(async () => (await text(reader.session, "chapter-panel")).includes("1 / 1 pages translated"), 300000, "page translated");
  await wait(1500);
  await shot(reader.session, "3-translate-chapter.png");

  // 6. The Saved page with the words saved above.
  const saved = await open(`chrome-extension://${extensionId}/library.html`, 1280, 800);
  await until(async () => /\d+ words?/.test(await evaluate(saved.session, "document.getElementById('counts').innerText")), 10000, "saved words");
  await wait(300);
  await shot(saved.session, "4-saved-words.png");

  // 7. The small promo tile.
  const icon = (await readFile("extension/icons/icon-128.png")).toString("base64");
  const promo = await open("data:text/html;charset=utf-8," + encodeURIComponent(PROMO(icon)), 440, 280);
  await shot(promo.session, "promo-440x280.png");
} finally {ws.close(); server.closeAllConnections(); server.close();}
