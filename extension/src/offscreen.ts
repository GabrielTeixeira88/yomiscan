import {CHUNK, MAX_INPUT, MAX_OUTPUT, encodeChunk, decodeChunk} from "./chapter/wire";
import {parseCoverage} from './chapter/coverage';

// Serialize across chapter tabs too. Study requests still use the backend busy guard.
let tail: Promise<void> = Promise.resolve();
let ports = 0;
chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "yomiscan-page-render" || port.sender?.id !== chrome.runtime.id || port.sender.frameId !== 0 || !port.sender.tab) return;
  if (ports >= 8) { port.postMessage({type:"error",error:"Too many active chapter tabs"}); return; }
  ports++;
  let parts: Uint8Array<ArrayBuffer>[] = [], size = 0, expected = 0, submitted = false, connected = true, mime='image/png';
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
            const response=await fetch("http://127.0.0.1:8765/api/v1/render-page",{method:"POST",body:form,
              headers:{"X-YomiScan-Client":"study-extension-v1"},signal:controller.signal,credentials:"omit",redirect:"error",cache:"no-store"});
            if(!response.ok) throw new Error(response.status===429 ? "Backend is busy. Retry after the current operation finishes." :
              response.status===503 ? "Backend resources unavailable. Check the server terminal." : `Local page rendering failed (HTTP ${response.status}).`);
            if(response.headers.get("content-type")?.split(";")[0]!=="image/png") throw new Error("Backend did not return a PNG image");
            const rendered=response.headers.get("X-YomiScan-Blocks-Rendered"),skipped=response.headers.get("X-YomiScan-Blocks-Skipped");
            const rawCoverage=response.headers.get('X-YomiScan-Coverage');
            const coverage=parseCoverage(rawCoverage===null?undefined:JSON.parse(rawCoverage));
            if(rendered===null || skipped===null || !/^\d+$/.test(rendered) || !/^\d+$/.test(skipped))throw new Error("Backend returned invalid rendering metadata");
            const reader=response.body!.getReader(); const output: Uint8Array<ArrayBuffer>[]=[]; let bytes=0;
            while(true) { const item=await reader.read(); if(item.done) break; bytes+=item.value.length;
              if(bytes>MAX_OUTPUT) { await reader.cancel(); throw new Error("Rendered page exceeds 32 MiB"); }
              output.push(new Uint8Array(item.value)); }
            const result=new Blob(output,{type:"image/png"}); output.length=0;
            for(let offset=0; connected && offset<result.size; offset+=CHUNK) send({type:"chunk",data:await encodeChunk(result.slice(offset,offset+CHUNK))});
            send({type:"result", rendered:Number(rendered), skipped:Number(skipped),coverage});
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
