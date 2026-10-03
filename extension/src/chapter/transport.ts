import {CHUNK, MAX_INPUT, MAX_OUTPUT, encodeChunk, decodeChunk} from "./wire";
import {parseCoverage,type PageCoverage} from './coverage';
export interface RenderedPage { blob: Blob; rendered: number; skipped: number;coverage?:PageCoverage }
export async function renderPage(blob: Blob, signal: AbortSignal): Promise<RenderedPage> {
  if (blob.size > MAX_INPUT) throw new Error("Page exceeds the backend's 10 MiB limit");
  const ready = await chrome.runtime.sendMessage({type: "chapter-prepare"});
  if (!ready?.ok) throw new Error(ready?.error || "Could not start local page transport");
  signal.throwIfAborted();
  return new Promise((resolve,reject) => {
    const port = chrome.runtime.connect({name: "yomiscan-page-render"});
    let done = false, size = 0, parts: Uint8Array<ArrayBuffer>[] = [];
    const finish = (error?: Error, result?: RenderedPage) => {
      if (done) return; done = true;
      clearTimeout(timer); signal.removeEventListener("abort", abort); port.disconnect(); parts = [];
      if (error) reject(error); else resolve(result!);
    };
    const abort = () => finish(new Error("Page request cancelled; backend may still be finishing"));
    const timer = setTimeout(() => finish(new Error("Page rendering timed out after five minutes; retry after the backend finishes")), 310_000);
    signal.addEventListener("abort", abort, {once:true});
    port.onDisconnect.addListener(() => finish(new Error("Page transport disconnected. Reload the extension/page and retry.")));
    port.onMessage.addListener(message => {
      if (done) return;
      try {
        if (message.type === "ready") void (async () => {
          port.postMessage({type:"begin", bytes:blob.size, mime:blob.type});
          for(let offset=0; offset<blob.size; offset+=CHUNK) {
            const data = await encodeChunk(blob.slice(offset,offset+CHUNK));
            if(done) return; port.postMessage({type:"chunk", data});
          }
          if(!done) port.postMessage({type:"end"});
        })().catch(error=>finish(error));
        else if (message.type === "chunk") {
          const bytes = decodeChunk(message.data); size += bytes.length;
          if(size>MAX_OUTPUT) throw new Error("Rendered page exceeds memory limit");
          parts.push(bytes);
        } else if(message.type === "result") {
          if (!size || !Number.isInteger(message.rendered) || message.rendered<0 || !Number.isInteger(message.skipped) || message.skipped<0)
            throw new Error("Invalid rendered page response");
          finish(undefined, {blob:new Blob(parts,{type:"image/png"}), rendered:message.rendered, skipped:message.skipped,coverage:parseCoverage(message.coverage)});
        } else if(message.type === "error") finish(new Error(message.error));
      } catch(error) { finish(error instanceof Error ? error : new Error("Invalid image transfer")); }
    });
  });
}
