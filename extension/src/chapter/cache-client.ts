/** Fixed loopback operations only. Never accepts a filesystem path or arbitrary URL. */
export interface CacheStatus {
  persistent_enabled:boolean;memory_bytes:number;memory_limit:number;disk_bytes:number;disk_limit:number;
  evictions:number;configuration_id?:string;error_code?:string|null;
}
export async function cacheRequest(operation:'read'|'settings'|'clear',enabled?:boolean):Promise<CacheStatus> {
  const suffix=operation==='read'?'':operation==='settings'?'/settings':'/clear';
  const response=await fetch('http://127.0.0.1:8765/api/v1/cache'+suffix,{
    method:operation==='read'?'GET':'POST',credentials:'omit',redirect:'error',cache:'no-store',
    signal:AbortSignal.timeout(10_000),headers:{'X-YomiScan-Client':'study-extension-v1','Content-Type':'application/json'},
    body:operation==='settings'?JSON.stringify({enabled}):undefined,
  });
  if(!response.ok)throw new Error(response.status===429?'The backend is processing a page. Try cache controls after it finishes.':
    'Cache controls unavailable. Start the updated local backend and check its storage permissions.');
  const data=await response.json();
  if(typeof data.persistent_enabled!=='boolean' || !['memory_bytes','memory_limit','disk_bytes','disk_limit','evictions'].every(
    key=>Number.isSafeInteger(data[key])&&data[key]>=0) || (data.configuration_id!==undefined &&
      (typeof data.configuration_id!=='string'||!/^[a-f0-9]{64}$/.test(data.configuration_id))))throw new Error('Invalid cache status');
  return data;
}
