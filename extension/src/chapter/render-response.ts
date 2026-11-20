import {MAX_OUTPUT} from './wire';
import {unpackZip} from './zip';
import {MAX_SNAPSHOT,parseSnapshot,type PageSnapshot} from './reports';
import {parseCoverage,type PageCoverage} from './coverage';

export interface RenderedPage {blob:Blob;rendered:number;skipped:number;coverage?:PageCoverage;snapshot?:PageSnapshot;input_sha256?:string}
export async function readRenderResponse(response:Response,inputHash:string):Promise<RenderedPage> {
  if(!response.ok)throw new Error(response.status===429?'Backend is busy. Retry after the current operation finishes.':
    response.status===503?'Backend resources unavailable. Check the server terminal.':`Local page rendering failed (HTTP ${response.status}).`);
  const mime=response.headers.get('content-type')?.split(';')[0];
  if(mime!=='image/png'&&mime!=='application/zip')throw new Error('Backend returned an unsupported page response');
  const limit=mime==='application/zip'?MAX_OUTPUT+MAX_SNAPSHOT+4096:MAX_OUTPUT;
  const output:Uint8Array<ArrayBuffer>[]=[],reader=response.body?.getReader();let bytes=0;
  if(!reader)throw new Error('Empty rendered page response');
  try {
    while(true) {
      const item=await reader.read();if(item.done)break;bytes+=item.value.length;
      if(bytes>limit)throw new Error('Rendered page response exceeds memory limit');
      output.push(new Uint8Array(item.value));
    }
  } finally {await reader.cancel();reader.releaseLock();}
  const payload=new Blob(output,{type:mime});output.length=0;
  if(mime==='application/zip') {
    const entries=await unpackZip(payload,limit),png=entries.get('rendered.png'),metadata=entries.get('snapshot.json');
    if(entries.size!==2||!png?.length||!metadata||metadata.length>MAX_SNAPSHOT||png.length>MAX_OUTPUT)
      throw new Error('Invalid diagnostic page bundle');
    const snapshot=parseSnapshot(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(metadata)));
    if(snapshot.image.input_sha256!==inputHash)throw new Error('Backend diagnostic page identity mismatch');
    const rendered=snapshot.counts.rendered,skipped=snapshot.counts.preserved;
    if(!Number.isInteger(rendered)||Number(rendered)<0||!Number.isInteger(skipped)||Number(skipped)<0)
      throw new Error('Invalid diagnostic counts');
    return {blob:new Blob([png],{type:'image/png'}),rendered:Number(rendered),skipped:Number(skipped),
      coverage:parseCoverage(snapshot.coverage),snapshot,input_sha256:inputHash};
  }
  const rendered=response.headers.get('X-YomiScan-Blocks-Rendered'),skipped=response.headers.get('X-YomiScan-Blocks-Skipped');
  if(rendered===null||skipped===null||!/^\d+$/.test(rendered)||!/^\d+$/.test(skipped))throw new Error('Backend returned invalid rendering metadata');
  const rawCoverage=response.headers.get('X-YomiScan-Coverage');
  return {blob:payload,rendered:Number(rendered),skipped:Number(skipped),
    coverage:parseCoverage(rawCoverage===null?undefined:JSON.parse(rawCoverage)),input_sha256:inputHash};
}
