export async function readinessRequest():Promise<unknown> {
  const response=await fetch('http://127.0.0.1:8765/api/v1/readiness',{headers:{'X-YomiScan-Client':'study-extension-v1'},
    credentials:'omit',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw new Error('Readiness unavailable. Start the updated backend with yomiscan-server.');
  const text=await response.text();if(new TextEncoder().encode(text).length>256*1024)throw new Error('Readiness response too large');
  return JSON.parse(text);
}
