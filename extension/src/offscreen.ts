import {CHUNK, MAX_INPUT, encodeChunk, decodeChunk} from "./chapter/wire";
import {readRenderResponse} from './chapter/render-response';
import {imageHash} from './chapter/reports';
import {validateTranslationOptions,type ReaderTranslationOptions} from './chapter/translation-options';
import {fontScale} from './chapter/font-settings';

// Serialize across chapter tabs too. Study requests still use the backend busy guard.
let tail: Promise<void> = Promise.resolve();
let ports = 0;
chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "yomiscan-page-render" || port.sender?.id !== chrome.runtime.id || port.sender.frameId !== 0 || !port.sender.tab) return;
  if (ports >= 8) { port.postMessage({type:"error",error:"Too many active chapter tabs"}); return; }
  ports++;
  let parts: Uint8Array<ArrayBuffer>[] = [], size = 0, expected = 0, submitted = false, connected = true, mime='image/png';
  let refresh=false,configuration:string|undefined;
  let scale=1,renderOnly=false;
  let job:string|undefined;
  let translation:ReaderTranslationOptions|undefined;
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
        if(message.fontScale!==undefined)scale=fontScale(message.fontScale);
        if(message.renderOnly!==undefined&&typeof message.renderOnly!=='boolean')throw new Error('Invalid render-only request');
        renderOnly=message.renderOnly===true;
        if(message.job_id!==undefined){if(typeof message.job_id!=='string'||!/^[a-f0-9-]{36}$/.test(message.job_id))throw new Error('Invalid job identity');job=message.job_id;}
        if(message.translation!==undefined)translation=validateTranslationOptions(message.translation);
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
            const inputHash=await imageHash(blob);
            const query=new URLSearchParams({diagnostics:'true'});
            if(renderOnly)query.set('refresh','render');else if(refresh)query.set('refresh','translation');
            query.set('font_scale',String(scale));
            if(configuration)query.set('configuration',configuration);
            if(job)query.set('job_id',job);
            const responsePromise=fetch("http://127.0.0.1:8765/api/v1/render-page?"+query,{method:"POST",body:form,
              headers:{"X-YomiScan-Client":"study-extension-v1"},signal:controller.signal,credentials:"omit",redirect:"error",cache:"no-store"});
            let polling=true;
            const poll=async()=>{
              while(polling&&connected&&!controller.signal.aborted){
                try{const response=await fetch('http://127.0.0.1:8765/api/v1/jobs/'+job,{method:'GET',
                  headers:{'X-YomiScan-Client':'study-extension-v1'},signal:AbortSignal.any([controller.signal,AbortSignal.timeout(2000)]),
                  credentials:'omit',redirect:'error',cache:'no-store'});
                  if(response.ok){const text=await response.text();if(text.length<=16*1024&&polling)send({type:'progress',data:JSON.parse(text)});}
                }catch{/* Status is optional; the render response remains authoritative. */}
                if(polling)await new Promise(resolve=>setTimeout(resolve,800));
              }
            };
            if(job)void poll();
            const response=await responsePromise.finally(()=>{polling=false;});
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
