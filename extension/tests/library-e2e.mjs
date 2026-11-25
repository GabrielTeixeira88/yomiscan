// Opt-in end-to-end check of saved words and sentences (Stage 6 increment 1) in real Chrome with a
// real engine: Read Chapter, open a bubble with J, save words and the sentence from the study card,
// then on the Saved page: the old Study history moved into saved sentences, words show their
// dictionary form and reading, search, CSV export, backup, Delete all and restore, and a saved
// sentence reopens in the study card. With 10,000 saved words it times the card's saved-word lookup.
// Needs: extension/dist built; an engine Automatic can use (the installed companion, the browser
// models or the developer backend); Chrome started with --remote-debugging-port (YOMISCAN_TEST_CDP_PORT,
// default 9231) and --enable-unsafe-extension-debugging, with an isolated profile.
// Usage, repository root: node extension/tests/library-e2e.mjs samples/vision/a.jpg [more pages]
import http from "node:http";
import {mkdtemp, readFile, readdir, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import assert from "node:assert/strict";
import path from "node:path";

const pages = process.argv.slice(2);
if (!pages.length) throw new Error("Pass page image paths");
const server = http.createServer(async (req, res) => {
  if (req.url === "/") {
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.end(`<!doctype html><title>Reader</title><style>body{margin:0;background:#ddd}main{width:min(720px,95vw);margin:20px auto}img{display:block;width:100%;height:auto;margin:0 0 16px}</style><main>${
      pages.map((_, i) => `<img src="/page/${i}${path.extname(pages[i])}">`).join("")}</main>`);
    return;
  }
  const match = /^\/page\/(\d+)/.exec(req.url ?? "");
  if (!match || !pages[Number(match[1])]) {res.writeHead(404); res.end(); return;}
  res.setHeader("Content-Type", pages[Number(match[1])].endsWith(".png") ? "image/png" : "image/jpeg");
  res.end(await readFile(pages[Number(match[1])]));
});
await new Promise(resolve => server.listen(8777, "127.0.0.1", resolve));

const version = await (await fetch(`http://127.0.0.1:${process.env.YOMISCAN_TEST_CDP_PORT ?? 9231}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener("open", resolve, {once: true}));
let next = 0; const callbacks = new Map(), listeners = [];
ws.addEventListener("message", event => {
  const m = JSON.parse(event.data);
  if (m.id) {const c = callbacks.get(m.id); callbacks.delete(m.id); m.error ? c.reject(new Error(JSON.stringify(m.error))) : c.resolve(m.result);}
  else for (const listener of listeners) listener(m);
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
const button = (session, label) => find(session, n => n.nodeName === "BUTTON" && n.children?.some(c => c.nodeValue === label));
const click = async (session, label) => {const n = await button(session, label); assert.ok(n, `Button ${label}`); await invoke(session, n, "function(){this.click()}");};
const key = (session, k) => call("Input.dispatchKeyEvent", {type: "keyDown", key: k, text: k, code: "Key" + k.toUpperCase()}, session);

const report = {pages: pages.length, checks: []};
const downloads = await mkdtemp(path.join(tmpdir(), "yomiscan-library-e2e-"));
try {
  for (const extension of (await call("Extensions.getExtensions")).extensions) if (extension.name.startsWith("YomiScan")) await call("Extensions.uninstall", {id: extension.id});
  const extensionId = (await call("Extensions.loadUnpacked", {path: path.resolve("extension/dist")})).id;
  const workerTarget = await until(async () => (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)), 10000, "service worker");
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  // A clean library, and one entry of the old opt-in Study history (plus a broken one) to migrate.
  const history = {id: "0b8e4bc4-91c2-4d33-9e57-3a0a8c5f6d21", created_at: "2025-12-01T00:00:00.000Z", analysis: {original_text: "昔の文です",
    translation: "An old sentence.", target_language: "en", processing: {ocr_ms: 0, translation_ms: 0, analysis_ms: 0, total_ms: 0}, tokens: []}};
  await evaluate(worker, `new Promise(r=>{const q=indexedDB.deleteDatabase('yomiscan-library');q.onsuccess=q.onerror=q.onblocked=()=>r(true)})`);
  await evaluate(worker, `Promise.all([chrome.storage.local.clear(),chrome.storage.session.clear()]).then(()=>chrome.storage.local.set({yomiscanStudyHistoryV1:${
    JSON.stringify({schema: 1, enabled: true, entries: [history, {id: "broken"}]})}}))`);

  const targetId = (await call("Target.createTarget", {url: "http://127.0.0.1:8777/"})).targetId;
  const reader = (await call("Target.attachToTarget", {targetId, flatten: true})).sessionId;
  await call("Page.enable", {}, reader); await call("DOM.enable", {}, reader);
  await call("Emulation.setDeviceMetricsOverride", {width: 1100, height: 900, deviceScaleFactor: 1, mobile: false}, reader);
  await until(() => evaluate(reader, "[...document.images].every(i=>i.complete&&i.naturalWidth>0)"), 30000, "images");
  const tab = (await call("Target.getTargets", {filter: [{type: "tab", exclude: false}, {exclude: true}]})).targetInfos.find(t => t.url === "http://127.0.0.1:8777/");
  await call("Extensions.triggerAction", {id: extensionId, targetId: tab.targetId});
  await until(() => find(reader, n => attr(n, "class") === "chapter-panel"), 10000, "panel");
  await until(async () => (await text(reader, "chapter-panel")).includes("Nothing saved yet"), 10000, "empty Saved summary");

  let started = Date.now();
  await click(reader, "Read Chapter");
  await until(async () => (await text(reader, "chapter-panel")).includes(`${pages.length} / ${pages.length} pages read`), 600000, "pages read");
  report.read_chapter_ms = Date.now() - started;
  // Step through bubbles (J) to the first card with at least two words.
  let card = "", saveButtons = [];
  for (let bubble = 1; bubble <= 15 && saveButtons.length < 2; bubble++) {
    await key(reader, "j");
    card = await until(async () => {const t = await text(reader, "panel"); return new RegExp(`bubble ${bubble} of \\d+`).test(t) && t.includes("Save word") ? t : "";}, 20000, `study card ${bubble}`);
    saveButtons = await findAll(reader, n => n.nodeName === "BUTTON" && attr(n, "class")?.includes("save-word"));
  }
  assert.ok(saveButtons.length >= 2, card);
  const [, pageNumber, bubbleNumber] = /Page (\d+) · bubble (\d+) of/.exec(card);
  const labels = [];
  for (const node of saveButtons.slice(0, 2)) {
    labels.push(attr(node, "aria-label").replace(/^Save /, ""));
    await invoke(reader, node, "function(){this.click()}");
  }
  await until(async () => (await text(reader, "panel")).includes(`Saved ${labels[1]}.`), 10000, "second word saved");
  await click(reader, "Save sentence");
  await until(async () => (await text(reader, "panel")).includes("Sentence saved."), 10000, "sentence saved");
  report.checks.push(`A real study card (page ${pageNumber}, bubble ${bubbleNumber}; ${pages.length} pages read in ${(report.read_chapter_ms / 1000).toFixed(1)} s) saved ${labels.join(" and ")} and its sentence`);

  // Reopen the same bubble from its outline: the words show as saved.
  await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27}, reader);
  await until(async () => !(await find(reader, n => attr(n, "class") === "panel")), 5000, "card closed");
  const outline = await find(reader, n => n.nodeName === "BUTTON" && attr(n, "aria-label")?.startsWith(`Study page ${pageNumber} bubble ${bubbleNumber}:`));
  assert.ok(outline, "bubble outline");
  await invoke(reader, outline, "function(){this.click()}");
  await until(async () => ((await text(reader, "panel")).match(/★ Saved/g) ?? []).length >= 2, 20000, "saved marks on reopen");
  report.checks.push("Reopening the bubble marks both words ★ Saved");

  const library = (await call("Target.attachToTarget", {targetId: (await call("Target.createTarget", {url: `chrome-extension://${extensionId}/library.html`})).targetId, flatten: true})).sessionId;
  await call("Page.enable", {}, library); await call("DOM.enable", {}, library);
  await call("Browser.setDownloadBehavior", {behavior: "allow", downloadPath: downloads, eventsEnabled: true});
  const page = () => evaluate(library, "document.body.innerText");
  const migrated = await until(async () => {const t = await page(); return t.includes("Your 1 Study history entry is now saved sentences") ? t : "";}, 15000, "migration");
  assert.match(migrated, /2 words · 2 sentences/);
  for (const label of labels) assert.ok(migrated.includes(label), `${label} listed`);
  const words = await evaluate(library, "[...document.querySelectorAll('.item')].map(i=>({expression:i.querySelector('.expression').innerText,reading:i.querySelector('.reading')?.innerText??null,meaning:i.querySelector('li')?.innerText??'',sentence:i.querySelector('.sentence').innerText,mark:i.querySelector('mark')?.innerText??null}))");
  report.saved_words = words;
  assert.equal(await evaluate(worker, "chrome.storage.local.get('yomiscanStudyHistoryV1').then(d=>Object.keys(d).length)"), 0);
  report.checks.push(`The Saved page lists both words with reading, meaning and the marked word in its sentence; the old Study history entry became a saved sentence (the broken one was skipped)`);

  await evaluate(library, `(()=>{const s=document.getElementById('search');s.value=${JSON.stringify(labels[0])};s.dispatchEvent(new Event('input'));})()`);
  assert.ok((await evaluate(library, "document.querySelectorAll('.item').length")) >= 1);
  await evaluate(library, "(()=>{const s=document.getElementById('search');s.value='zzzz-no-match';s.dispatchEvent(new Event('input'));})()");
  assert.ok((await page()).includes("Nothing matches this search."));
  await evaluate(library, "(()=>{const s=document.getElementById('search');s.value='';s.dispatchEvent(new Event('input'));})()");

  const downloaded = async prefix => until(async () => (await readdir(downloads)).find(n => n.startsWith(prefix) && !n.endsWith(".crdownload")), 10000, prefix);
  await click(library, "Export CSV");
  const wordsCsv = await readFile(path.join(downloads, await downloaded("yomiscan-words-")), "utf8");
  assert.ok(wordsCsv.startsWith("﻿\"Expression\",\"Reading\",\"Meaning\""));
  assert.equal(wordsCsv.trim().split("\r\n").length, 3);
  for (const label of labels) assert.ok(wordsCsv.includes(`\r\n"${label}",`), `${label} in the CSV`);
  await click(library, "Sentences");
  assert.ok((await page()).includes("昔の文です"));
  await click(library, "Export CSV");
  const sentencesCsv = await readFile(path.join(downloads, await downloaded("yomiscan-sentences-")), "utf8");
  assert.ok(sentencesCsv.includes("\"昔の文です\",\"An old sentence.\",\"2025-12-01\""));
  report.checks.push("CSV export: words (header, 2 rows, UTF-8 with BOM) and sentences, including the migrated one");

  // Open the saved real sentence in the study card.
  const openButtons = await findAll(library, n => n.nodeName === "BUTTON" && n.children?.some(c => c.nodeValue === "Open"));
  await invoke(library, openButtons[0], "function(){this.click()}");
  const reopened = await until(async () => {const t = await text(library, "panel"); return t.includes("WORD BREAKDOWN") || /Word breakdown/i.test(t) ? t : "";}, 10000, "saved sentence card");
  assert.ok(((reopened.match(/★ Saved/g)) ?? []).length >= 2, "the reopened card marks the saved words");
  await call("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27}, library);
  report.checks.push("Open shows the saved sentence in the same study card, with its saved words marked");

  await click(library, "Back up all");
  const backupName = await downloaded("yomiscan-backup-");
  const backup = JSON.parse(await readFile(path.join(downloads, backupName), "utf8"));
  assert.equal(backup.words.length, 2); assert.equal(backup.sentences.length, 2);
  assert.ok(!JSON.stringify(backup).includes("127.0.0.1"), "no page URL in the backup");
  listeners.push(m => {if (m.method === "Page.javascriptDialogOpening" && m.sessionId === library) void call("Page.handleJavaScriptDialog", {accept: true}, library);});
  await click(library, "Delete all…");
  await until(async () => (await page()).includes("0 words · 0 sentences"), 10000, "deleted all");
  const input = await find(library, n => attr(n, "id") === "restore");
  await call("DOM.setFileInputFiles", {files: [path.join(downloads, backupName)], backendNodeId: input.backendNodeId}, library);
  await until(async () => (await page()).includes("Restored 2 words and 2 sentences"), 10000, "restored");
  assert.ok((await page()).includes("2 words · 2 sentences"));
  report.checks.push("Back up all, Delete all (after confirming) and Restore backup bring back both words and both sentences; the backup holds no page URL");

  // 10,000 saved words: the card's lookup (one message, up to 60 keys) and the Saved page load.
  await evaluate(library, `new Promise((resolve,reject)=>{const q=indexedDB.open('yomiscan-library');q.onsuccess=()=>{const t=q.result.transaction('words','readwrite'),s=t.objectStore('words');
    for(let i=0;i<10000;i++)s.put({key:'word:bulk'+i+'|',expression:'bulk'+i,reading:null,surface:'bulk'+i,meanings:['m'],parts_of_speech:[],entry_id:null,sentence:'s',sentence_translation:null,created_at:new Date(Date.UTC(2020,0,1,0,0,i)).toISOString()});
    t.oncomplete=()=>{q.result.close();resolve(true)};t.onerror=()=>reject(t.error)};q.onerror=()=>reject(q.error)})`);
  const keys = JSON.stringify([...Array.from({length: 58}, (_, i) => `word:bulk${i * 97}|`), "word:absent|", "jmdict:1"]);
  const timings = await evaluate(library, `(async()=>{const out=[];for(let i=0;i<20;i++){const t=performance.now();const r=await chrome.runtime.sendMessage({type:'library',operation:'saved',keys:${keys}});if(!r.ok||r.data.length!==58)throw new Error(JSON.stringify(r));out.push(performance.now()-t)}return out.sort((a,b)=>a-b)})()`);
  report.lookup_ms = {median: +timings[10].toFixed(1), max: +timings.at(-1).toFixed(1)};
  assert.ok(report.lookup_ms.median <= 50, `lookup median ${report.lookup_ms.median} ms`);
  started = Date.now();
  await call("Page.reload", {}, library);
  await until(async () => (await evaluate(library, "document.body.innerText")).includes("10,002 words"), 30000, "10,002 words listed");
  report.saved_page_10k_ms = Date.now() - started;
  report.checks.push(`With 10,002 saved words the card's lookup of 60 words takes ${report.lookup_ms.median} ms (median of 20, max ${report.lookup_ms.max} ms); the Saved page loads in ${report.saved_page_10k_ms} ms`);
  console.log(JSON.stringify(report, null, 1));
} finally {ws.close(); server.close();}
