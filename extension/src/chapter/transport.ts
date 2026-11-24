import {backendBase} from '../backend';
import {CHUNK, MAX_INPUT, MAX_OUTPUT, encodeChunk, decodeChunk} from "./wire";
import {parseCoverage} from './coverage';
import {parseSnapshot} from './reports';
import type {RenderedPage} from './render-response';
import type {ReaderTranslationOptions} from './translation-options';
import {ProgressTracker,type JobProgress} from './progress';
export type {RenderedPage} from './render-response';
export class ConfigurationChanged extends Error {}
interface PageRequestOptions {configuration?:string;translation?:ReaderTranslationOptions;progress?:(status:JobProgress)=>void;
  refresh?:boolean;renderOnly?:boolean;fontScale?:number}

/** Upload one page through the offscreen document (one job at a time across tabs) and collect
 * its reply: a rendered PNG ("render") or Reading mode's JSON text analysis ("analyze"). */
async function pageRequest<T>(kind:'render'|'analyze'|'browser',blob:Blob,signal:AbortSignal,options:PageRequestOptions,
  reply:(message:{type:string;[key:string]:unknown},parts:Uint8Array<ArrayBuffer>[],size:number)=>T|undefined):Promise<T> {
  if (blob.size > MAX_INPUT) throw new Error("Page exceeds the backend's 10 MiB limit");
  const ready = await chrome.runtime.sendMessage({type: "chapter-prepare"});
  if (!ready?.ok) throw new Error(ready?.error || "Could not start local page transport");
  const backend = await backendBase();
  signal.throwIfAborted();
  return new Promise((resolve,reject) => {
    const job=crypto.randomUUID(),tracker=new ProgressTracker(job),{progress,...wireOptions}=options;
    const port = chrome.runtime.connect({name: "yomiscan-page-render"});
    let done = false, size = 0, parts: Uint8Array<ArrayBuffer>[] = [];
    const finish = (error?: Error, result?: T) => {
      if (done) return; done = true;
      clearTimeout(timer); signal.removeEventListener("abort", abort); port.disconnect(); parts = [];
      if (error) reject(error); else resolve(result!);
    };
    const abort = () => finish(new Error("Page request cancelled; backend may still be finishing"));
    const timer = setTimeout(() => finish(new Error("Page processing timed out after five minutes; retry after the backend finishes")), 310_000);
    signal.addEventListener("abort", abort, {once:true});
    port.onDisconnect.addListener(() => finish(new Error("Page transport disconnected. Reload the extension/page and retry.")));
    port.onMessage.addListener(message => {
      if (done) return;
      try {
        if (message.type === "ready") void (async () => {
          port.postMessage({type:"begin", kind, bytes:blob.size, mime:blob.type,job_id:job,backend,...wireOptions});
          for(let offset=0; offset<blob.size; offset+=CHUNK) {
            const data = await encodeChunk(blob.slice(offset,offset+CHUNK));
            if(done) return; port.postMessage({type:"chunk", data});
          }
          if(!done) port.postMessage({type:"end"});
        })().catch(error=>finish(error));
        else if(message.type==='progress'){const status=tracker.accept(message.data);if(status)progress?.(status);}
        else if (message.type === "chunk") {
          const bytes = decodeChunk(message.data); size += bytes.length;
          if(size>MAX_OUTPUT) throw new Error("Rendered page exceeds memory limit");
          parts.push(bytes);
        } else if(message.type === "error") finish(message.code==='configuration_changed'?new ConfigurationChanged(message.error):new Error(message.error));
        else {const result=reply(message,parts,size);if(result!==undefined)finish(undefined,result);}
      } catch(error) { finish(error instanceof Error ? error : new Error("Invalid image transfer")); }
    });
  });
}

export async function renderPage(blob: Blob, signal: AbortSignal,
  options:PageRequestOptions={}): Promise<RenderedPage> {
  return pageRequest('render',blob,signal,options,(message,parts,size)=>{
    if(message.type!=="result")return undefined;
    if (!size || !Number.isInteger(message.rendered) || Number(message.rendered)<0 || !Number.isInteger(message.skipped) || Number(message.skipped)<0)
      throw new Error("Invalid rendered page response");
    return {blob:new Blob(parts,{type:"image/png"}), rendered:Number(message.rendered), skipped:Number(message.skipped),
      coverage:parseCoverage(message.coverage),snapshot:message.snapshot===undefined?undefined:parseSnapshot(message.snapshot),
      input_sha256:typeof message.input_sha256==='string'?message.input_sha256:undefined};
  });
}

/** Reading mode: detection, OCR and study analysis as JSON, without masking or typesetting.
 * The caller validates the payload with parseReadingPage. */
export async function analyzePage(blob:Blob,signal:AbortSignal,options:Omit<PageRequestOptions,'renderOnly'|'fontScale'>&{browser?:boolean}={}):Promise<unknown> {
  // With `browser`, the in-browser engine (Stage 5a) reads the page instead of the backend.
  const {browser,...rest}=options;
  return pageRequest<{data:unknown}>(browser?'browser':'analyze',blob,signal,rest,message=>message.type==='analysis'?{data:message.data}:undefined).then(r=>r.data);
}
