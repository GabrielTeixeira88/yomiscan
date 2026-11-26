// Opt-in real-model check of the Stage 5a browser engine against the Python backend.
// Needs: Chrome with --remote-debugging-port (YOMISCAN_TEST_CDP_PORT, default 9231) and
// --enable-unsafe-extension-debugging; the built extension (extension/dist); the artifact
// server (scripts/serve_browser_artifacts.py, port 47620); the backend (port 47615).
// Usage, from the repository root: node extension/tests/browser-engine.mjs samples/vision/a.jpg ...
// Writes .cache/stage5a/vision-parity.json. Pages and outputs stay local (ignored .cache/).
import {readFile, writeFile, mkdir} from "node:fs/promises";
import path from "node:path";

const pages = process.argv.slice(2);
if (!pages.length) throw new Error("Pass page image paths");
const BACKEND = "http://127.0.0.1:47615", ARTIFACTS = "http://127.0.0.1:47620/";
const version = await (await fetch(`http://127.0.0.1:${process.env.YOMISCAN_TEST_CDP_PORT ?? 9231}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener("open", resolve, {once: true}));
let next = 0; const callbacks = new Map();
ws.addEventListener("message", event => {const m = JSON.parse(event.data); if (m.id) {const c = callbacks.get(m.id); callbacks.delete(m.id); m.error ? c.reject(new Error(JSON.stringify(m.error))) : c.resolve(m.result);}});
const call = (method, params = {}, sessionId) => new Promise((resolve, reject) => {const id = ++next; callbacks.set(id, {resolve, reject}); ws.send(JSON.stringify({id, method, params, sessionId}));});
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
async function evaluate(session, expression) {
  const r = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true}, session);
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value;
}

function cer(reference, hypothesis) {
  const a = [...reference], b = [...hypothesis];
  let row = Array.from({length: b.length + 1}, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    for (let j = 1; j <= b.length; j++) current[j] = Math.min(row[j] + 1, current[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    row = current;
  }
  return {edits: row[b.length], length: a.length};
}
const iou = (x, y) => {
  const w = Math.min(x.right, y.right) - Math.max(x.left, y.left), h = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
  if (w <= 0 || h <= 0) return 0;
  const area = b => (b.right - b.left) * (b.bottom - b.top), inter = w * h;
  return inter / (area(x) + area(y) - inter);
};

try {
  for (const extension of (await call("Extensions.getExtensions")).extensions) if (extension.name.startsWith("YomiScan")) await call("Extensions.uninstall", {id: extension.id});
  const extensionId = (await call("Extensions.loadUnpacked", {path: path.resolve("extension/dist")})).id;
  // First install opens the welcome page (Stage 6); close it so the reader tab stays the active tab.
  for (let tries = 0; tries < 50; tries++) {const welcome = (await call("Target.getTargets")).targetInfos.find(t => t.url === `chrome-extension://${extensionId}/welcome.html`); if (welcome) {await call("Target.closeTarget", {targetId: welcome.targetId}); break;} await new Promise(r => setTimeout(r, 200));}
  const workerTarget = await (async () => {for (let i = 0; i < 100; i++) {const t = (await call("Target.getTargets")).targetInfos.find(t => t.type === "service_worker" && t.url.includes(extensionId)); if (t) return t; await wait(100);} throw new Error("No service worker");})();
  const worker = (await call("Target.attachToTarget", {targetId: workerTarget.targetId, flatten: true})).sessionId;
  const engine = async (operation, extra = {}) => {
    const reply = await evaluate(worker, `(async()=>{
      if(!(await chrome.runtime.getContexts({contextTypes:['OFFSCREEN_DOCUMENT']})).length)
        await chrome.offscreen.createDocument({url:'offscreen.html',reasons:['BLOBS'],justification:'Browser engine check'});
      return chrome.runtime.sendMessage({target:'offscreen-engine',operation:${JSON.stringify(operation)},...${JSON.stringify(extra)}});})()`);
    if (!reply?.ok) throw new Error(`${operation}: ${reply?.error}`); return reply.data;
  };
  let status = await engine("status");
  console.log(`backend ${status.backend}, isolated ${status.isolated}, threads ${status.threads}`);
  const installStarted = Date.now();
  if (status.required.some(c => !c.installed)) {
    await engine("install", {base: ARTIFACTS});
    while ((status = await engine("status")).install.state === "running") await wait(500);
    if (status.install.state !== "done") throw new Error(`Install failed: ${status.install.error}`);
  }
  const installMs = Date.now() - installStarted;
  const rows = [], lexicalMs = [], lexical = {compared: 0, surfaces: 0, forms: 0, units: 0, grammar: 0, examples: []};
  const translationMs = [], translation = {compared: 0, identical: 0, examples: []};
  for (const file of pages) {
    const bytes = await readFile(file), mime = file.endsWith(".png") ? "image/png" : file.endsWith(".webp") ? "image/webp" : "image/jpeg";
    const form = new FormData(); form.append("file", new Blob([bytes], {type: mime}), path.basename(file));
    const reference = await (await fetch(BACKEND + "/api/v1/analyze-page", {method: "POST", body: form, headers: {"X-YomiScan-Client": "study-extension-v1"}})).json();
    const started = Date.now();
    const browser = await engine("recognize", {data: bytes.toString("base64"), mime});
    const wallMs = Date.now() - started;
    const used = new Set(); let edits = 0, length = 0, matched = 0, exact = 0;
    for (const ref of reference.text_blocks) {
      let best = -1, score = .5;
      browser.blocks.forEach((b, i) => {const s = iou(ref.bbox, b.bbox); if (!used.has(i) && s >= score) {best = i; score = s;}});
      if (best < 0) continue;
      used.add(best); matched++;
      const d = cer(ref.original_text, browser.blocks[best].text); edits += d.edits; length += d.length; if (!d.edits) exact++;
      if (!d.edits && ref.status === 'success' && ref.tokens.length) {
        // Same text in both engines: compare the browser lexical engine with the backend's analysis.
        const t = Date.now(), analysis = await engine("analyze-text", {text: ref.original_text});
        lexicalMs.push(Date.now() - t);
        const view = a => ({surfaces: a.tokens.map(x => x.surface).join('|'), forms: a.tokens.map(x => `${x.dictionary_form}:${x.meanings[0]?.entry_id ?? '-'}`).join('|'),
          units: a.units.map(u => `${u.start_token}-${u.end_token}:${u.dictionary_form}`).join('|'), grammar: a.grammar.map(g => g.id).join('|')});
        const b = view(analysis), p = view(ref);
        lexical.compared++;
        for (const key of ['surfaces', 'forms', 'units', 'grammar']) if (b[key] === p[key]) lexical[key]++;
        if (b.forms !== p.forms) lexical.examples.push({text: ref.original_text, browser: b.forms, backend: p.forms});
        if (ref.translation && ref.provenance?.engine === 'marian-mt') {
          // Backend OPUS (one page batch) against browser OPUS (one line at a time).
          const translated = await engine("translate", {text: ref.original_text});
          translationMs.push(Math.round(translated.ms));
          translation.compared++;
          if (translated.translation === ref.translation) translation.identical++;
          else translation.examples.push({text: ref.original_text, browser: translated.translation, backend: ref.translation});
        }
      }
    }
    rows.push({page: path.basename(file), backend_blocks: reference.text_blocks.length, browser_blocks: browser.blocks.length, matched, exact,
      cer: length ? edits / length : 0, edits, length, browser_ms: wallMs, load_ms: Math.round(browser.load_ms),
      detection_ms: Math.round(browser.timings.detection_ms), ocr_ms: Math.round(browser.timings.ocr_ms),
      same_order: reference.text_blocks.map(b => b.bbox.left + ',' + b.bbox.top).join('|') === browser.blocks.map(b => b.bbox.left + ',' + b.bbox.top).join('|')});
    const r = rows.at(-1);
    console.log(`${r.page}: blocks ${r.backend_blocks}→${r.browser_blocks}, matched ${r.matched}, exact ${r.exact}, CER ${(100 * r.cer).toFixed(2)}%, ${r.browser_ms} ms (detect ${r.detection_ms}, OCR ${r.ocr_ms}, load ${r.load_ms})`);
  }
  const total = rows.reduce((t, r) => ({edits: t.edits + r.edits, length: t.length + r.length, backend: t.backend + r.backend_blocks, matched: t.matched + r.matched, exact: t.exact + r.exact}), {edits: 0, length: 0, backend: 0, matched: 0, exact: 0});
  const times = rows.slice(1).map(r => r.browser_ms).sort((a, b) => a - b);
  const summary = {backend: status.backend, isolated: status.isolated, threads: status.threads, install_ms: installMs, pages: rows.length,
    backend_blocks: total.backend, matched_blocks: total.matched, exact_blocks: total.exact, cer: total.length ? total.edits / total.length : 0,
    median_page_ms_after_first: times.length ? times[Math.floor(times.length / 2)] : null,
    lexical: {...lexical, examples: lexical.examples.length, first_ms: lexicalMs[0],
      median_ms_after_first: lexicalMs.length > 1 ? lexicalMs.slice(1).sort((a, b) => a - b)[Math.floor((lexicalMs.length - 1) / 2)] : null}};
  const sorted = translationMs.slice(1).sort((a, b) => a - b);
  summary.translation = {compared: translation.compared, identical: translation.identical, first_ms: translationMs[0],
    median_ms_after_first: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null, p95_ms: sorted.length ? sorted[Math.floor(sorted.length * .95)] : null};
  for (const example of lexical.examples.slice(0, 8)) console.log(`  lexical difference: ${example.text}\n    browser ${example.browser}\n    backend ${example.backend}`);
  for (const example of translation.examples) console.log(`  translation difference: ${example.text}\n    browser ${example.browser}\n    backend ${example.backend}`);
  console.log(JSON.stringify(summary));
  await mkdir(".cache/stage5a", {recursive: true});
  await writeFile(`.cache/stage5a/vision-parity-${status.backend}.json`, JSON.stringify({summary, rows, lexical_examples: lexical.examples, translation_examples: translation.examples}, null, 1));
} finally {ws.close();}
