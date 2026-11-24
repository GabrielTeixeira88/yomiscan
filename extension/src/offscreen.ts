import {parseBackendOrigin} from './backend';
import {CHUNK, MAX_INPUT, encodeChunk, decodeChunk} from "./chapter/wire";
import {readRenderResponse} from './chapter/render-response';
import {imageHash} from './chapter/reports';
import {validateTranslationOptions,type ReaderTranslationOptions} from './chapter/translation-options';
import {fontScale} from './chapter/font-settings';
import {MAX_READING_JSON} from './chapter/reading';
import {BrowserEngine} from './engine/engine';

// Browser engine (Stage 5a): created lazily; only the extension's own service worker may drive it.
let engine: BrowserEngine | null = null;
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.tab || sender.url !== chrome.runtime.getURL('background.js') || message?.target !== 'offscreen-engine') return;
  engine ??= new BrowserEngine();
  const current = engine;
  void (async () => {
    switch (message.operation) {
      case 'status': return current.status();
      case 'install':
        if (typeof message.base !== 'string' || message.base.length > 500) throw new Error('Invalid artifact source');
        current.startInstall(message.base); return current.status();
      case 'cancel': current.cancelInstall(); return current.status();
      case 'remove': await current.remove(); return current.status();
      case 'recognize': {
        if (typeof message.data !== 'string' || message.data.length > MAX_INPUT * 4 / 3 + 4 ||
          !['image/png', 'image/jpeg', 'image/webp'].includes(message.mime)) throw new Error('Invalid page image');
        const bytes = Uint8Array.from(atob(message.data), c => c.charCodeAt(0));
        return current.recognize(new Blob([bytes], {type: message.mime}));
      }
      case 'analyze-text':
        if (typeof message.text !== 'string' || !message.text.trim() || message.text.length > 1000) throw new Error('Text must be 1 to 1,000 characters');
        return current.analyzeText(message.text, {translate: message.translate === true});
      case 'translate':
        if (typeof message.text !== 'string' || !message.text.trim() || message.text.length > 1000) throw new Error('Text must be 1 to 1,000 characters');
        return current.translate(message.text);
      default: throw new Error('Unknown browser engine operation');
    }
  })().then(data => respond({ok: true, data}), error => respond({ok: false, error: error instanceof Error ? error.message : 'Browser engine failed'}));
  return true;
});

// Serialize across chapter tabs too. Study requests still use the backend busy guard.
let tail: Promise<void> = Promise.resolve();
let ports = 0;
type Send=(message:unknown)=>void;
const HEADERS={'X-YomiScan-Client':'study-extension-v1'};

/** Poll the job's stage status until stopped. Status is optional; the page response stays authoritative. */
function pollProgress(backend:string,job:string|undefined,signal:AbortSignal,send:Send,connected:()=>boolean):AbortController {
  const stop=new AbortController();
  if(job)void (async()=>{
    while(!stop.signal.aborted&&connected()&&!signal.aborted){
      try{const response=await fetch(backend+'/api/v1/jobs/'+job,{method:'GET',headers:HEADERS,
        signal:AbortSignal.any([signal,AbortSignal.timeout(2000)]),credentials:'omit',redirect:'error',cache:'no-store'});
        if(response.ok){const text=await response.text();if(text.length<=16*1024&&!stop.signal.aborted)send({type:'progress',data:JSON.parse(text)});}
      }catch{/* Missing or expired status never fails the page. */}
      if(!stop.signal.aborted)await new Promise(resolve=>setTimeout(resolve,800));
    }
  })();
  return stop;
}

/** Reading mode: POST analyze-page and return its bounded JSON as one message. */
async function analyzeRequest(backend:string,form:FormData,job:string|undefined,configuration:string|undefined,refresh:boolean,
  signal:AbortSignal,send:Send,connected:()=>boolean):Promise<unknown> {
  const query=new URLSearchParams();
  if(configuration)query.set('configuration',configuration);
  if(refresh)query.set('refresh','translation');
  if(job)query.set('job_id',job);
  const polling=pollProgress(backend,job,signal,send,connected);
  const response=await fetch(backend+'/api/v1/analyze-page?'+query,{method:'POST',body:form,headers:HEADERS,signal,
    credentials:'omit',redirect:'error',cache:'no-store'}).finally(()=>polling.abort());
  if(response.status===409)return {type:'error',code:'configuration_changed',error:'Backend settings changed. Start Read Chapter again.'};
  if(!response.ok)throw new Error(response.status===429?'Backend is busy. Retry after the current operation finishes.':
    response.status===503?'Backend resources unavailable. Check the server terminal.':`Local page analysis failed (HTTP ${response.status}).`);
  const text=await response.text();
  if(text.length>MAX_READING_JSON)throw new Error('Page analysis exceeds the memory limit');
  return {type:'analysis',data:JSON.parse(text)};
}
chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "yomiscan-page-render" || port.sender?.id !== chrome.runtime.id || port.sender.frameId !== 0 || !port.sender.tab) return;
  if (ports >= 8) { port.postMessage({type:"error",error:"Too many active chapter tabs"}); return; }
  ports++;
  let parts: Uint8Array<ArrayBuffer>[] = [], size = 0, expected = 0, submitted = false, connected = true, mime='image/png';
  let refresh=false,configuration:string|undefined,backend='';
  let scale=1,renderOnly=false;
  let job:string|undefined;
  let translation:ReaderTranslationOptions|undefined;
  let kind:'render'|'analyze'='render';
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),300_000);
  const send = (message: unknown) => { if(connected) port.postMessage(message); };
  const fail = (error: unknown) => { parts=[]; send({type:"error",error:error instanceof Error ? error.message : "Local page rendering failed"}); };
  port.onDisconnect.addListener(()=>{connected=false; ports--; clearTimeout(timer); controller.abort(); parts=[];});
  port.onMessage.addListener(message => {
    try {
      if(submitted) throw new Error("Image already submitted");
      if(message.type === "begin") {
        if(expected || !Number.isInteger(message.bytes) || message.bytes<=0 || message.bytes>MAX_INPUT) throw new Error("Invalid page size");
        expected=message.bytes;
        if(!['image/png','image/jpeg','image/webp'].includes(message.mime))throw new Error('Unsupported upload image type');
        mime=message.mime;
        if(message.refresh!==undefined && typeof message.refresh!=='boolean')throw new Error('Invalid refresh option');
        if(message.configuration!==undefined && (typeof message.configuration!=='string'||!/^[a-f0-9]{64}$/.test(message.configuration)))throw new Error('Invalid configuration identity');
        refresh=message.refresh===true;configuration=message.configuration;
        backend=parseBackendOrigin(message.backend);
        if(message.fontScale!==undefined)scale=fontScale(message.fontScale);
        if(message.renderOnly!==undefined&&typeof message.renderOnly!=='boolean')throw new Error('Invalid render-only request');
        renderOnly=message.renderOnly===true;
        if(message.job_id!==undefined){if(typeof message.job_id!=='string'||!/^[a-f0-9-]{36}$/.test(message.job_id))throw new Error('Invalid job identity');job=message.job_id;}
        if(message.translation!==undefined)translation=validateTranslationOptions(message.translation);
        if(message.kind!==undefined&&message.kind!=='render'&&message.kind!=='analyze')throw new Error('Invalid page request kind');
        kind=message.kind??'render';
      } else if(message.type === "chunk") {
        if(!expected) throw new Error("Missing image header");
        const data=decodeChunk(message.data); size+=data.length;
        if(size>expected) throw new Error("Page upload exceeds declared size");
        parts.push(data);
      } else if(message.type === "end") {
        if(!expected || size!==expected) throw new Error("Incomplete page image");
        submitted=true;
        const blob=new Blob(parts,{type:mime}); parts=[];
        tail = tail.then(async()=>{
          if(!connected) return;
          try {
            controller.signal.throwIfAborted();
            const form=new FormData(); form.append("file",blob,mime==='image/jpeg'?'page.jpg':mime==='image/webp'?'page.webp':'page.png');
            if(translation)form.append('options_json',JSON.stringify(translation));
            if(kind==='analyze'){send(await analyzeRequest(backend,form,job,configuration,refresh,controller.signal,send,()=>connected));return;}
            const inputHash=await imageHash(blob);
            const query=new URLSearchParams({diagnostics:'true'});
            if(renderOnly)query.set('refresh','render');else if(refresh)query.set('refresh','translation');
            query.set('font_scale',String(scale));
            if(configuration)query.set('configuration',configuration);
            if(job)query.set('job_id',job);
            const responsePromise=fetch(backend+"/api/v1/render-page?"+query,{method:"POST",body:form,
              headers:HEADERS,signal:controller.signal,credentials:"omit",redirect:"error",cache:"no-store"});
            const polling=pollProgress(backend,job,controller.signal,send,()=>connected);
            const response=await responsePromise.finally(()=>polling.abort());
            if(response.status===409){send({type:'error',code:'configuration_changed',error:'Backend settings changed. Start Translate Chapter again.'});return;}
            const page=await readRenderResponse(response,inputHash),result=page.blob;
            for(let offset=0; connected && offset<result.size; offset+=CHUNK) send({type:"chunk",data:await encodeChunk(result.slice(offset,offset+CHUNK))});
            send({type:"result", rendered:page.rendered, skipped:page.skipped,coverage:page.coverage,
              snapshot:page.snapshot,input_sha256:inputHash});
          } catch(error) {
            console.warn("YomiScan page request failed",error);
            fail(controller.signal.aborted ? new Error("Page request cancelled or timed out; backend may still be finishing") :
              error instanceof TypeError ? new Error("Cannot reach YomiScan local backend. Start the server and retry.") : error);
          }
        }).catch(error=>console.warn("YomiScan transport disconnected while reporting a result",error));
      }
    } catch(error) { submitted=true; fail(error); }
  });
  send({type:"ready"});
});
