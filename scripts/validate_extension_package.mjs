// Load the actual extracted ZIP in a fresh, task-owned Chrome profile. No dependencies/models.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {access,mkdir,mkdtemp,readFile,writeFile} from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';

const args=process.argv.slice(2),value=name=>{const index=args.indexOf(name);return index<0?undefined:args[index+1];};
if(!value('--extension'))throw new Error('Usage: node scripts/validate_extension_package.mjs --extension <unpacked ZIP> [--chrome <executable>] [--report <json>] [--no-sandbox]');
const extension=path.resolve(value('--extension'));
await access(path.join(extension,'manifest.json'));
const chrome=value('--chrome')??process.env.CHROME_PATH??(process.platform==='win32'?'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe':'/usr/bin/google-chrome');
const cache=path.resolve('.cache');await mkdir(cache,{recursive:true});
const profile=await mkdtemp(path.join(cache,'package-chrome-'));
const flags=['--headless=new','--remote-debugging-port=0','--enable-unsafe-extension-debugging','--no-first-run',
  '--no-default-browser-check','--disable-background-networking','--user-data-dir='+profile,'about:blank'];
if(args.includes('--no-sandbox'))flags.push('--no-sandbox');
const processChrome=spawn(chrome,flags,{stdio:'ignore',windowsHide:true});
let spawnError;processChrome.on('error',error=>{spawnError=error;});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check){const deadline=Date.now()+20000;while(Date.now()<deadline){if(spawnError)throw spawnError;
  if(processChrome.exitCode!==null)throw new Error('Isolated Chrome exited early');const result=await check();if(result)return result;await pause(100);}throw new Error('Packaged extension Chrome smoke timed out');}
const server=http.createServer((_req,res)=>{res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>YomiScan package smoke</title><p>Authorized synthetic reader</p>');});
let ws;const pending=new Map();let sequence=0;
function call(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++sequence;
  const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('Chrome command timed out: '+method));},10000);
  pending.set(id,{resolve,reject,timeout});ws.send(JSON.stringify({id,method,params,sessionId}));});}
const nodes=root=>[root,...(root.children??[]).flatMap(nodes),...(root.shadowRoots??[]).flatMap(nodes)];
try{
  const port=await until(async()=>{try{return Number((await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);}catch(error){if(error.code==='ENOENT')return null;throw error;}});
  const version=await(await fetch(`http://127.0.0.1:${port}/json/version`)).json();
  ws=new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  ws.addEventListener('message',event=>{const message=JSON.parse(event.data),task=pending.get(message.id);if(!task)return;
    clearTimeout(task.timeout);pending.delete(message.id);message.error?task.reject(new Error(JSON.stringify(message.error))):task.resolve(message.result);});
  const id=(await call('Extensions.loadUnpacked',{path:extension})).id;
  assert.ok((await call('Extensions.getExtensions')).extensions.some(item=>item.id===id&&item.name.startsWith('YomiScan')));
  const target=await until(async()=>(await call('Target.getTargets')).targetInfos.find(t=>t.type==='service_worker'&&t.url===`chrome-extension://${id}/background.js`));
  const worker=(await call('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;
  await call('Runtime.enable',{},worker);
  const manifest=await until(async()=>{
    const response=await call('Runtime.evaluate',{expression:'typeof chrome!=="undefined"&&chrome.runtime&&chrome.runtime.getManifest()',returnByValue:true},worker);
    return response.result?.value||null;
  });
  assert.equal(manifest.manifest_version,3);assert.ok(manifest.permissions.includes('storage'));
  // First install opens the welcome page from the package.
  await until(async()=>(await call('Target.getTargets')).targetInfos.find(t=>t.type==='page'&&t.url===`chrome-extension://${id}/welcome.html`));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const url=`http://127.0.0.1:${server.address().port}/`;
  const page=(await call('Target.createTarget',{url})).targetId;
  const session=(await call('Target.attachToTarget',{targetId:page,flatten:true})).sessionId;
  await call('DOM.enable',{},session);
  const tab=await until(async()=>(await call('Target.getTargets',{filter:[{type:'tab',exclude:false},{exclude:true}]})).targetInfos.find(t=>t.url===url));
  await call('Extensions.triggerAction',{id,targetId:tab.targetId});
  await until(async()=>nodes((await call('DOM.getDocument',{depth:-1,pierce:true},session)).root).some(n=>n.attributes?.includes('chapter-panel')));
  const report={browser:version.Browser,extension_version:manifest.version,checks:['actual ZIP loads as MV3','packaged service worker starts','install opens the welcome page','packaged content opens reader controls'],model_inference:false};
  if(value('--report'))await writeFile(path.resolve(value('--report')),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}finally{
  server.closeAllConnections();server.close();
  if(ws?.readyState===WebSocket.OPEN){try{await call('Browser.close');}catch{/* Only the fresh task-owned browser is terminated below. */}ws.close();}
  for(const task of pending.values()){clearTimeout(task.timeout);task.reject(new Error('Chrome smoke closed'));}pending.clear();
  if(processChrome.exitCode===null){await pause(500);if(processChrome.exitCode===null)processChrome.kill();}
}
