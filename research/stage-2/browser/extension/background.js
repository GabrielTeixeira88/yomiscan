// Driven over CDP by run-browser.mjs: open/close the offscreen document that runs the models.
globalThis.openOffscreen = async () => {
  if (await chrome.offscreen.hasDocument()) return "exists";
  await chrome.offscreen.createDocument({url: "offscreen.html", reasons: ["WORKERS"],
    justification: "Stage 2 spike: measure ONNX Runtime Web OCR in an offscreen document"});
  return "created";
};
globalThis.closeOffscreen = async () => {
  if (await chrome.offscreen.hasDocument()) await chrome.offscreen.closeDocument();
  return "closed";
};
