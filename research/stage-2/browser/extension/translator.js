// Informational: Chrome's built-in Translator needs a user gesture to download its language
// pack. run-browser.mjs clicks the button through CDP Input events (a real user activation).
const status = document.getElementById("status");
globalThis.translatorResult = null;
globalThis.translatorLines = [];
document.getElementById("start").addEventListener("click", async () => {
  const pair = {sourceLanguage: "ja", targetLanguage: "en"};
  try {
    const availability = await Translator.availability(pair);
    const started = performance.now();
    let loaded = 0;
    const translator = await Translator.create({...pair, monitor(m) { m.addEventListener("downloadprogress", e => { loaded = e.loaded; status.textContent = `download ${e.loaded}`; }); }});
    const createMs = performance.now() - started;
    const rows = [];
    for (const line of globalThis.translatorLines) {
      const t = performance.now();
      rows.push({id: line.id, output: await translator.translate(line.text), ms: performance.now() - t});
    }
    translator.destroy();
    globalThis.translatorResult = {availabilityBefore: availability, createMs, downloadProgress: loaded, rows};
  } catch (error) {
    globalThis.translatorResult = {error: String(error?.message ?? error)};
  }
});
