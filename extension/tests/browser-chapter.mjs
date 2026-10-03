// Opt-in integration check against an isolated Chrome profile and real local backend.
// Run from repository root after building extension/dist. No browser-test dependencies.
import http from "node:http";
import {readFile,writeFile,mkdir} from "node:fs/promises";
import assert from "node:assert/strict";
import path from "node:path";

const server=http.createServer(async(req,res)=>{
  try {
    const js=req.url.split("?")[0]==="/reader.js";
    res.setHeader("Content-Type",js?"text/javascript; charset=utf-8":"text/html; charset=utf-8");
    res.end(await readFile(`extension/fixtures/reader.${js?"js":"html"}`));
  }catch{res.writeHead(500);res.end();}
});
let crossPNG;const sourceRequests=[];
const crossServer=http.createServer((req,res)=>{
  sourceRequests.push({path:req.url,destination:req.headers['sec-fetch-dest'],cookie:req.headers.cookie});
  if(req.url.startsWith('/page.png')) {
    res.setHeader('Content-Type','image/png');res.setHeader('Set-Cookie','yomiscan_fixture=yes; SameSite=Lax; Path=/');res.end(crossPNG);return;
  }
  res.setHeader("Content-Type","image/svg+xml");
  res.end('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1100"><rect width="800" height="1100" fill="white"/><rect x="20" y="20" width="760" height="1060" fill="none" stroke="black" stroke-width="5"/><ellipse cx="400" cy="250" rx="210" ry="150" fill="white" stroke="black"/><text x="260" y="265" font-size="48">でも大丈夫</text></svg>');
});
await new Promise(resolve=>server.listen(8772,"127.0.0.1",resolve));
await new Promise(resolve=>crossServer.listen(8773,"127.0.0.1",resolve));
const version=await(await fetch("http://127.0.0.1:9231/json/version")).json();
const ws=new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve=>ws.addEventListener("open",resolve,{once:true}));
let next=0;const callbacks=new Map();
ws.addEventListener("message",event=>{const m=JSON.parse(event.data);if(m.id){const c=callbacks.get(m.id);callbacks.delete(m.id);m.error?c.reject(new Error(JSON.stringify(m.error))):c.resolve(m.result);}});
function call(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++next;callbacks.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params,sessionId}));});}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function evaluate(session,expression){const r=await call("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true},session);if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function until(check,timeout=60000){const end=Date.now()+timeout;while(Date.now()<end){const value=await check();if(value)return value;await wait(100);}throw new Error("Timed out");}
function nodes(root){return [root,...(root.children??[]).flatMap(nodes),...(root.shadowRoots??[]).flatMap(nodes)];}
let session,worker,extensionId,offscreen;
async function find(predicate){const doc=await call("DOM.getDocument",{depth:-1,pierce:true},session);return nodes(doc.root).find(predicate);}
async function invoke(node,fn){const o=await call("DOM.resolveNode",{nodeId:node.nodeId},session);const r=await call("Runtime.callFunctionOn",{objectId:o.object.objectId,functionDeclaration:fn,returnByValue:true},session);return r.result.value;}
const byClass=name=>n=>n.attributes?.includes(name);
let panelObject;
async function panel(){
  // Keep a reference to the stable control panel. Repeated full DOM snapshots copy
  // every fixture data URL and distort the long-chapter performance being tested.
  if(!panelObject){
    const n=await find(byClass("chapter-panel"));if(!n)return "";
    panelObject=(await call("DOM.resolveNode",{nodeId:n.nodeId},session)).object.objectId;
  }
  return (await call("Runtime.callFunctionOn",{objectId:panelObject,functionDeclaration:"function(){return this.innerText}",returnByValue:true},session)).result.value;
}
async function click(text){const n=await find(n=>n.nodeName==="BUTTON"&&n.children?.some(c=>c.nodeValue===text));assert.ok(n,`Button ${text}`);await invoke(n,"function(){this.click()}");}
const report={browser:version.Browser,checks:[]};
try {
  assert.equal((await fetch("http://127.0.0.1:8765/health")).status,200);
  const extensions=await call("Extensions.getExtensions");
  for(const extension of extensions.extensions)if(extension.name.startsWith("YomiScan"))await call("Extensions.uninstall",{id:extension.id});
  extensionId=(await call("Extensions.loadUnpacked",{path:path.resolve("extension/dist")})).id;
  const targetId=(await call("Target.createTarget",{url:"http://127.0.0.1:8772"})).targetId;
  session=(await call("Target.attachToTarget",{targetId,flatten:true})).sessionId;
  await call("Page.enable",{},session);await call("DOM.enable",{},session);
  await call("Emulation.setDeviceMetricsOverride",{width:1100,height:900,deviceScaleFactor:1,mobile:false},session);
  await until(()=>evaluate(session,"document.querySelector('#page-5')?.complete"));
  crossPNG=Buffer.from((await evaluate(session,"document.querySelector('#page-5').src")).split(',')[1],'base64');
  const workerTarget=await until(async()=>(await call("Target.getTargets")).targetInfos.find(t=>t.type==="service_worker"&&t.url.includes(extensionId)));
  worker=(await call("Target.attachToTarget",{targetId:workerTarget.targetId,flatten:true})).sessionId;
  const tabTarget=(await call("Target.getTargets",{filter:[{type:"tab",exclude:false},{exclude:true}]})).targetInfos.find(t=>t.url==="http://127.0.0.1:8772/"&&t.embedderData?.tabActive);
  async function activate(){await call("Extensions.triggerAction",{id:extensionId,targetId:tabTarget.targetId});await until(()=>find(byClass("chapter-panel")));}
  await activate();await evaluate(session,"document.querySelector('#page-3').scrollIntoView()");await click("Translate Chapter");
  await until(async()=>(await panel()).includes("Page 3 processing"));report.checks.push("Visible page 3 prioritized before pages 1/2; avatars/logos excluded");
  await click("Stop Translation");
  await evaluate(session,"document.querySelector('#page-4').scrollIntoView()");
  await until(async()=>(await panel()).includes("1 / 5 pages translated"));
  report.checks.push("Stop cancels queued work; scrolling during in-flight real inference works and its result is retained");
  const offTarget=await until(async()=>(await call("Target.getTargets")).targetInfos.find(t=>t.url.includes(extensionId+"/offscreen.html")));
  offscreen=(await call("Target.attachToTarget",{targetId:offTarget.targetId,flatten:true})).sessionId;
  await evaluate(offscreen,`globalThis.testCalls=[];globalThis.failPage2=true;const nativeFetch=fetch;globalThis.fetch=async(url,options)=>{
    const bitmap=await createImageBitmap(options.body.get('file'));const canvas=new OffscreenCanvas(bitmap.width,bitmap.height);const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0);bitmap.close();
    const id=ctx.getImageData(0,0,1,1).data[0];testCalls.push(id);
    if(id===2&&failPage2){failPage2=false;return new Response('',{status:500});}
    return nativeFetch(url,options);};`);
  await click("Translate Chapter");await until(async()=>(await panel()).includes("4 / 5 pages translated")&&(await panel()).includes("1 failed"),120000);
  report.checks.push("Progressive real page rendering; injected page-2 HTTP failure does not stop later pages");
  const count=await evaluate(offscreen,"testCalls.length");await click("Original");await wait(100);
  assert.equal(await evaluate(session,"getComputedStyle(document.querySelector('[data-yomiscan=overlays]')).visibility"),"hidden");
  await click("English");await wait(100);
  assert.equal(await evaluate(session,"getComputedStyle(document.querySelector('[data-yomiscan=overlays]')).visibility"),"visible");
  await click("Original");await click("English");
  await wait(300);assert.equal(await evaluate(offscreen,"testCalls.length"),count);report.checks.push("Original/English toggles reuse cached results");
  await click("Retry Failed / Skipped");await until(async()=>(await panel()).includes("5 / 5 pages translated"),60000);
  report.checks.push("Explicit retry recovers failed page");
  await evaluate(session,"document.querySelector('#lazy').click();document.querySelector('#append').click()");
  await until(async()=>(await panel()).includes("7 / 7 pages translated"),120000);report.checks.push("data-src load and appended page discovered without restarting session");
  await call("Emulation.setDeviceMetricsOverride",{width:900,height:900,deviceScaleFactor:1,mobile:false},session);
  await evaluate(session,"document.querySelector('#page-4').scrollIntoView()");await wait(300);
  const overlays=await find(n=>n.attributes?.includes("overlays"));assert.ok(overlays);
  const doc=await call("DOM.getDocument",{depth:-1,pierce:true},session);
  const images=nodes(doc.root).filter(n=>n.nodeName==="IMG"&&n.attributes?.includes("aria-hidden"));
  assert.ok(images.length>=7);
  const originalRect=await evaluate(session,"(()=>{const r=document.querySelector('#page-4').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()");
  const overlayRects=await Promise.all(images.map(image=>invoke(image,"function(){const r=this.getBoundingClientRect();return [r.x,r.y,r.width,r.height]}")));
  assert.ok(overlayRects.some(r=>r.every((v,i)=>Math.abs(v-originalRect[i])<.6)));
  report.checks.push("Responsive overlay matches original bounds within 0.6 CSS px after resize/scroll");
  await writeFile(".cache/phase-7-reader.png",Buffer.from((await call("Page.captureScreenshot",{format:"png"},session)).data,"base64"));
  await click("Select Text");await until(()=>find(byClass("selection")));
  assert.equal(await evaluate(session,"getComputedStyle(document.querySelector('[data-yomiscan=overlays]')).visibility"),"hidden");
  await call("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27},session);
  await until(async()=>!await find(byClass("selection")));report.checks.push("Study activation stops chapter queue, restores Original; Escape works");
  await activate();await click("Select Text");await until(()=>find(byClass("selection")));
  const crop=await evaluate(session,"(()=>{const r=document.querySelector('#page-4').getBoundingClientRect();return {x:r.x+r.width*450/800,y:r.y+r.height*150/1100,width:r.width*250/800,height:r.height*90/1100}})()");
  await call("Input.dispatchMouseEvent",{type:"mousePressed",x:crop.x,y:crop.y,button:"left",clickCount:1},session);
  await call("Input.dispatchMouseEvent",{type:"mouseMoved",x:crop.x+crop.width,y:crop.y+crop.height,button:"left",buttons:1},session);
  await call("Input.dispatchMouseEvent",{type:"mouseReleased",x:crop.x+crop.width,y:crop.y+crop.height,button:"left",clickCount:1},session);
  await until(async()=>{const p=await find(byClass("panel"));return p&&(await invoke(p,"function(){return this.innerText}")).includes("WORD BREAKDOWN");},30000);
  assert.ok((await invoke(await find(byClass("panel")),"function(){return this.innerText}")).includes("大丈夫"),"Study must OCR Japanese, not the English overlay");
  report.checks.push("Study captures ORIGINAL Japanese and returns actual OCR/translation/dictionary popup after chapter rendering");
  await call("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27},session);
  await activate();await click("Translate Chapter");await evaluate(session,"document.querySelector('#swap').click()");
  await until(async()=>await evaluate(offscreen,"testCalls.includes(99)"),30000);
  await until(async()=>(await panel()).includes("7 / 7 pages translated"));report.checks.push("Changed currentSrc invalidates only the replaced page's cached result");
  assert.equal(await evaluate(offscreen,"testCalls.filter(id=>id===99).length"),1,"source change must not submit both attribute/load jobs");
  await evaluate(session,"document.querySelector('#navigate').click()");await until(async()=>!await find(n=>n.attributes?.includes("overlays")));
  report.checks.push("SPA URL navigation destroys chapter overlays/session");
  await click("Clear Session");await until(async()=>!await find(n=>n.attributes?.includes("overlays")));
  report.checks.push("Clear removes overlays and releases session results");
  await call("Network.enable",{},worker);await call("Network.setBlockedURLs",{urls:["http://127.0.0.1:8765/*"]},worker);
  await click("Translate Chapter");await until(async()=>(await panel()).includes("not running"));report.checks.push("Offline health check fails before queuing chapter requests");
  await call("Network.setBlockedURLs",{urls:[]},worker);
  await click("Clear Session");
  await evaluate(session,"document.querySelector('main').replaceChildren();const image=new Image();image.id='cross-page';image.src='http://127.0.0.1:8773/page.svg';document.querySelector('main').append(image)");
  await until(()=>evaluate(session,"document.querySelector('#cross-page').complete"));
  await evaluate(session,"document.querySelector('#cross-page').scrollIntoView()");
  await click("Translate Chapter");await until(async()=>(await panel()).includes("1 / 1 pages translated"),60000);
  report.checks.push("Cross-origin tainted canvas uses verified whole-page visible-tab screenshot fallback");
  await click("Clear Session");
  await call("Emulation.setDeviceMetricsOverride",{width:900,height:500,deviceScaleFactor:1.25,mobile:false},session);
  await click("Translate Chapter");await until(async()=>(await panel()).includes("1 skipped"));
  const scrollBefore=await evaluate(session,'scrollY');
  const scrollOption=await find(n=>n.nodeName==='INPUT'&&n.attributes?.includes('checkbox'));
  await invoke(scrollOption,"function(){this.click()}");
  await click('Retry Failed / Skipped');
  await until(async()=>(await panel()).includes("1 / 1 pages translated"),60000);
  assert.equal(await evaluate(session,'scrollY'),scrollBefore);
  report.checks.push("Tall restricted image uses opt-in stitched capture at fractional DPR without zooming and restores scroll position");
  await click('Clear Session');
  await call('Emulation.setDeviceMetricsOverride',{width:900,height:350,deviceScaleFactor:1,mobile:false},session);
  const cancelScroll=await evaluate(session,'scrollY');
  await click('Translate Chapter');
  await until(async()=>await evaluate(session,'scrollY')!==cancelScroll);
  await call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27},session);
  await until(async()=>(await panel()).includes('1 skipped'));
  assert.equal(await evaluate(session,'scrollY'),cancelScroll);
  report.checks.push('Escape interrupts stitched capture, restores scroll and preserves the original');
  await click('Clear Session');
  await evaluate(session,"document.querySelector('#cross-page').src='http://127.0.0.1:8773/page.png'");
  await until(()=>evaluate(session,"document.querySelector('#cross-page').complete"));
  await click('Translate Chapter');
  await until(async()=>(await panel()).includes('1 / 1 pages translated'),60000);
  const directRequests=sourceRequests.filter(r=>r.path==='/page.png'&&r.destination!=='image');
  assert.ok(directRequests.length>0,'cross-origin PNG must use extension fetch despite being taller than viewport');
  assert.ok(directRequests.some(r=>r.cookie?.includes('yomiscan_fixture=yes')),'eligible source cookies must accompany fetch');
  report.checks.push('Cross-origin PNG acquired by extension fetch at source resolution with cookies, no zoom or scrolling');
  await call('Emulation.setDeviceMetricsOverride',{width:900,height:900,deviceScaleFactor:1,mobile:false},session);
  await click('Clear Session');
  await evaluate(session,"document.querySelector('#cross-page').src='http://localhost:8773/page.png'");
  await until(()=>evaluate(session,"document.querySelector('#cross-page').complete"));
  await evaluate(session,"document.querySelector('#cross-page').scrollIntoView()");
  await click('Translate Chapter');
  const accessTarget=await until(async()=>(await call('Target.getTargets')).targetInfos.find(t=>t.url.includes(extensionId+'/image-access.html')));
  assert.ok((await panel()).includes('0 / 0 pages translated'),'queue must wait for permission choice');
  const accessSession=(await call('Target.attachToTarget',{targetId:accessTarget.targetId,flatten:true})).sessionId;
  await until(()=>evaluate(accessSession,"Boolean(document.querySelector('#hosts')?.textContent)"));
  assert.equal(await evaluate(accessSession,"document.querySelector('#hosts').innerText.trim()"),'http://localhost/*');
  await evaluate(accessSession,"document.querySelector('#fallback').click()");
  await until(async()=>(await panel()).includes('1 / 1 pages translated'),60000);
  report.checks.push('Missing host permission opens a narrowly scoped access window; choosing capture fallbacks resumes the reader');
  await click("Clear Session");
  // Exercise a longer queue without claiming 24 additional neural-render evaluations.
  await evaluate(offscreen,`globalThis.fetch=async(url,options)=>{await new Promise(r=>setTimeout(r,20));return new Response(options.body.get('file'),{status:200,headers:{'Content-Type':'image/png','X-YomiScan-Blocks-Rendered':'0','X-YomiScan-Blocks-Skipped':'0'}});};`);
  await evaluate(session,"document.querySelector('main').replaceChildren();for(let i=0;i<24;i++)document.querySelector('#append').click()");
  await until(()=>evaluate(session,"[...document.querySelectorAll('main img')].every(i=>i.complete)"));
  const longStarted=performance.now();
  await click("Translate Chapter");await until(async()=>(await panel()).includes("24 / 24 pages translated"),120000);
  report.mockedLongQueueMs=Math.round(performance.now()-longStarted);
  await click("Clear Session");
  report.checks.push("24-page synthetic queue and cleanup (mocked render responses; not a model-quality benchmark)");
  report.status=await panel();report.requestOrder=await evaluate(offscreen,"testCalls");
  await mkdir(".cache",{recursive:true});await writeFile(".cache/phase-7-browser.json",JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}catch(error){console.error(error);if(session)console.error("Controls:",await panel());process.exitCode=1;}
finally{ws.close();server.closeAllConnections();server.close();crossServer.closeAllConnections();crossServer.close();}
