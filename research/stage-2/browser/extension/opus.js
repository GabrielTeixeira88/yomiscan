// Informational: OPUS-MT ja-en in an extension page. Transformers.js provides only the Marian
// tokenizer; inference uses the spike's ONNX Runtime Web build and opus.mjs (transformers-exact
// beam search with KV cache). Files come from the local spike server, never from Hugging Face.
import {AutoTokenizer, env} from "./tjs/transformers.min.js";
import {OpusTranslator} from "./opus.mjs";

// Transformers.js 4.3.2's local-path loader never requested tokenizer files from an extension
// page; its remote loader does. "Remote" here is the local spike server.
env.allowLocalModels = false;
env.allowRemoteModels = true;
env.remoteHost = "http://127.0.0.1:8790/hf/";
env.remotePathTemplate = "{model}/";
env.useBrowserCache = false;
const MODEL = "Xenova/opus-mt-ja-en", BASE = `http://127.0.0.1:8790/hf/${MODEL}`;

const bytes = async url => {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
};

globalThis.runOpus = async ({device, dtype, decoding = "beam", lines, threads = 8}) => {
  const ort = await import(device === "webgpu" ? "./ort/ort.webgpu.min.mjs" : "./ort/ort.wasm.min.mjs");
  ort.env.wasm.wasmPaths = chrome.runtime.getURL("ort/");
  ort.env.wasm.numThreads = crossOriginIsolated ? Math.min(navigator.hardwareConcurrency, threads) : 1;
  const suffix = dtype === "fp32" ? "" : `_${dtype}`;
  const options = {executionProviders: [device], graphOptimizationLevel: "all"};
  if (device === "webgpu") options.preferredOutputLocation = "cpu";
  const started = performance.now();
  const translator = new OpusTranslator({ort,
    tokenizer: await AutoTokenizer.from_pretrained(MODEL),
    encoder: await ort.InferenceSession.create(await bytes(`${BASE}/onnx/encoder_model${suffix}.onnx`), options),
    decoder: await ort.InferenceSession.create(await bytes(`${BASE}/onnx/decoder_model_merged${suffix}.onnx`), options),
    config: await (await fetch(`${BASE}/config.json`)).json(),
    generation: await (await fetch(`${BASE}/generation_config.json`)).json()});
  const loadMs = performance.now() - started;
  const rows = [];
  for (const line of lines) {
    const t = performance.now();
    const result = await translator.translate(line.text, {decoding});
    rows.push({id: line.id, output: result.text, ms: performance.now() - t});
  }
  return {device, dtype, decoding, threads: ort.env.wasm.numThreads, loadMs, rows};
};
globalThis.opusReady = true;
