import {MAX_INPUT,decodeChunk} from './wire';
import type {PagePixels} from './acquisition';

export function fetchFromExtension(id: string, signal: AbortSignal): Promise<PagePixels> {
  signal.throwIfAborted();
  return new Promise((resolve,reject) => {
    const port = chrome.runtime.connect({name:'yomiscan-source-image'});
    let done=false, size=0; let parts:Uint8Array<ArrayBuffer>[]=[];
    const finish=(error?:Error,result?:PagePixels) => {
      if(done)return; done=true; clearTimeout(timer);signal.removeEventListener('abort',abort);
      port.disconnect();parts=[];if(error)reject(error);else resolve(result!);
    };
    const abort=()=>finish(new Error('Image acquisition cancelled'));
    const timer=setTimeout(()=>finish(new Error('Source image fetch timed out')),28_000);
    signal.addEventListener('abort',abort,{once:true});
    port.onDisconnect.addListener(()=>finish(new Error('Source image transport disconnected')));
    port.onMessage.addListener(message=>{
      if(done)return;
      try {
        if(message.type==='chunk') {
          const data=decodeChunk(message.data);size+=data.length;
          if(size>MAX_INPUT)throw new Error('Source image exceeds 10 MiB');parts.push(data);
        } else if(message.type==='result') {
          if(!size || !Number.isInteger(message.width) || !Number.isInteger(message.height) ||
             message.width<=0 || message.height<=0 || message.width*message.height>12_000_000 ||
             !['image/png','image/jpeg','image/webp'].includes(message.mime))throw new Error('Invalid source image response');
          finish(undefined,{blob:new Blob(parts,{type:message.mime}),width:message.width,height:message.height});
        } else if(message.type==='error')finish(new Error(message.error));
      } catch(error){finish(error instanceof Error?error:new Error('Invalid image transfer'));}
    });
    port.postMessage({id});
  });
}
