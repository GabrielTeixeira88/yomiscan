import {backendBase} from '../backend';
export async function readinessRequest():Promise<unknown> {
  const response=await fetch(await backendBase()+'/api/v1/readiness',{headers:{'X-YomiScan-Client':'study-extension-v1'},
    credentials:'omit',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw new Error('Readiness unavailable. Start the updated backend with yomiscan-server.');
  const text=await response.text();if(new TextEncoder().encode(text).length>256*1024)throw new Error('Readiness response too large');
  return JSON.parse(text);
}
/** Switch the backend's sentence translator to another installed engine (until it restarts). */
export async function selectTranslationEngine(engine:string):Promise<{selected:string}> {
  if(!/^[a-z0-9-]{1,32}$/.test(engine))throw new Error('Invalid engine name');
  const response=await fetch(await backendBase()+'/api/v1/translation-engine',{method:'POST',
    headers:{'X-YomiScan-Client':'study-extension-v1','Content-Type':'application/json'},body:JSON.stringify({engine}),
    credentials:'omit',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(120_000)});
  if(response.status===404)throw new Error('This backend cannot switch engines yet. Update and restart it.');
  if(response.status===429)throw new Error('YomiScan is busy. Switch engines after the current page finishes.');
  if(!response.ok){
    let detail='The engine could not be selected.';
    try{const body=await response.json() as {detail?:unknown};if(typeof body.detail==='string'&&body.detail.length<=300)detail=body.detail;}catch{/* keep generic */}
    throw new Error(detail);
  }
  const body=await response.json() as {selected?:unknown};
  if(body.selected!==engine)throw new Error('Unexpected engine switch response');
  return {selected:engine};
}
