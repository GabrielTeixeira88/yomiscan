import {backendBase} from '../backend';
import {validateProfile,type TranslationProfile} from './translation-options';
export type TranslationOperation='profile'|'create-series'|'delete-series'|'save-term'|'delete-term';
const endpoints:Record<TranslationOperation,string>={profile:'translation-profile','create-series':'glossaries/series',
  'delete-series':'glossaries/delete-series','save-term':'glossaries/term','delete-term':'glossaries/delete-term'};
/** Fixed local endpoints, bounded JSON, no paths, URLs or implicit model downloads. */
export async function translationRequest(operation:TranslationOperation,payload:Record<string,unknown>):Promise<unknown> {
  if(!Object.hasOwn(endpoints,operation)||JSON.stringify(payload).length>1800)throw new Error('Invalid translation settings request');
  let url=await backendBase()+'/api/v1/'+endpoints[operation];
  if(operation==='profile'){
    const query=new URLSearchParams();
    if(typeof payload.scope==='string')query.set('scope',payload.scope);
    if(typeof payload.target==='string')query.set('target',payload.target);
    url+='?'+query;
  }
  const response=await fetch(url,{method:operation==='profile'?'GET':'POST',credentials:'omit',redirect:'error',cache:'no-store',
    signal:AbortSignal.timeout(10_000),headers:{'Content-Type':'application/json','X-YomiScan-Client':'study-extension-v1'},
    body:operation==='profile'?undefined:JSON.stringify(payload)});
  if(!response.ok){
    if(response.status===429)throw new Error('A page is processing. Stop translation, wait for it to finish, then edit settings.');
    let detail='Local translation settings unavailable. Start the updated backend and check its user-data directory.';
    if(response.status===422){const data=await response.json();if(typeof data.detail==='string'&&data.detail.length<250)detail=data.detail;}
    throw new Error(detail);
  }
  const length=Number(response.headers.get('Content-Length')??0);
  if(length>2*1024*1024)throw new Error('Translation profile exceeds its size limit');
  const encoded=await response.text();if(new TextEncoder().encode(encoded).length>2*1024*1024)throw new Error('Translation profile exceeds its size limit');
  const data=JSON.parse(encoded);
  return operation==='profile'?validateProfile(data):data;
}
