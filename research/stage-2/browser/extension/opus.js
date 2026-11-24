// Informational: OPUS-MT ja-en (Xenova ONNX conversion of the same Helsinki weights) through
// Transformers.js inside an extension page. Models are served from the local spike server only.
import {pipeline, env, AutoTokenizer} from "./tjs/transformers.min.js";

globalThis.probeTokenizer = async () => {
  try {
    const t = await AutoTokenizer.from_pretrained(MODEL);
    return {name: t?.constructor?.name ?? String(t)};
  } catch (error) {
    return {error: String(error?.stack ?? error).slice(0, 800)};
  }
};

// Transformers.js 4.3.2's local-path loader never requested tokenizer files from an extension
// page; its remote loader does. "Remote" here is the local spike server, not Hugging Face.
env.allowLocalModels = false;
env.allowRemoteModels = true;
env.remoteHost = "http://127.0.0.1:8790/hf/";
env.remotePathTemplate = "{model}/";
env.useBrowserCache = false;
env.backends.onnx.wasm.wasmPaths = chrome.runtime.getURL("tjs/");
const MODEL = new URLSearchParams(location.search).get("model") ?? "Xenova/opus-mt-ja-en";

globalThis.runOpus = async ({device, dtype, lines, threads = 8}) => {
  env.backends.onnx.wasm.numThreads = crossOriginIsolated ? Math.min(navigator.hardwareConcurrency, threads) : 1;
  const started = performance.now();
  const translator = await pipeline("translation", MODEL, {device, dtype});
  const loadMs = performance.now() - started;
  const rows = [];
  for (const line of lines) {
    const t = performance.now();
    const [result] = await translator(line.text, {max_new_tokens: 256});
    rows.push({id: line.id, output: result.translation_text, ms: performance.now() - t});
  }
  await translator.dispose();
  return {device, dtype, threads: env.backends.onnx.wasm.numThreads, loadMs, rows};
};
globalThis.opusReady = true;
