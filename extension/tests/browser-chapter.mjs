// Opt-in isolated Chrome check. --mock-backend runs entirely model-free on port 8774.
// Run from repository root after building extension/dist. No browser-test dependencies.
import http from "node:http";
import {readFile,writeFile,mkdir,readdir} from "node:fs/promises";
import {createHash,randomUUID} from 'node:crypto';
import assert from "node:assert/strict";
import path from "node:path";

const mocked=process.argv.includes('--mock-backend'),backend=`http://127.0.0.1:${mocked?8774:8765}`;
const {packZip,unpackZip}=await import('../.test/browser-support.mjs');
const reportDir=path.resolve('.cache/stage1-reports-'+Date.now());
let mockServer,mockRenders=0,mockRefreshes=0,persistentCache=false,mockConfiguration='f'.repeat(64),extensionPath=path.resolve('extension/dist');
const mockSeries=[{id:'global',label:'Global'}],mockTerms=[],translationCalls=[];
let experimentalCapabilities=false;
if(mocked) {
  extensionPath=path.resolve('.cache/stage1-browser-extension');
  await mkdir(extensionPath,{recursive:true});
  for(const name of await readdir('extension/dist')) {
    const source=await readFile(path.join('extension/dist',name),'utf8');
    await writeFile(path.join(extensionPath,name),source.replaceAll('127.0.0.1:8765','127.0.0.1:8774'));
  }
  mockServer=http.createServer(async(req,res)=>{
    try {
      if(req.url==='/health'){res.setHeader('Content-Type','application/json');res.setHeader('X-YomiScan-Configuration',mockConfiguration);res.end('{"status":"ok"}');return;}
      if(req.url.startsWith('/api/v1/translation-profile')){
        const query=new URL(backend+req.url).searchParams,scope=query.get('scope')??'global',target=query.get('target')??'en';
        const entries=mockTerms.filter(t=>t.scope===scope&&t.target_language===target);
        const effective=mockTerms.filter(t=>(t.scope===scope||t.scope==='global')&&t.target_language===target);
        res.setHeader('Content-Type','application/json');res.end(JSON.stringify({engine:{engine:'fixture'},
          capabilities:{targets:experimentalCapabilities?['en','pt-BR','es']:['en'],glossary_hints:experimentalCapabilities,
            structured:experimentalCapabilities,bounded_context:experimentalCapabilities,experimental_targets:experimentalCapabilities?['pt-BR','es']:[]},
          default_target:'en',series:mockSeries,scope,target_language:target,entries,
          glossary_version:createHash('sha256').update(JSON.stringify(effective)).digest('hex'),dictionary_language:'en',configuration_id:mockConfiguration}));return;
      }
      if(req.url.startsWith('/api/v1/glossaries/')){
        let encoded='';for await(const chunk of req)encoded+=chunk;const body=JSON.parse(encoded);let result={ok:true};
        if(req.url.endsWith('/series')){result={id:randomUUID()};mockSeries.push({id:result.id,label:body.label});}
        if(req.url.endsWith('/term')){const id=body.entry_id??randomUUID(),prior=mockTerms.findIndex(t=>t.id===id);
          const entry={id,scope:body.scope,target_language:body.target_language,source:body.source,preferred:body.preferred};
          if(prior<0)mockTerms.push(entry);else mockTerms[prior]=entry;result={id};}
        if(req.url.endsWith('/delete-term')){const prior=mockTerms.findIndex(t=>t.id===body.entry_id);if(prior>=0)mockTerms.splice(prior,1);}
        if(req.url.endsWith('/delete-series')){const prior=mockSeries.findIndex(s=>s.id===body.scope);if(prior>0)mockSeries.splice(prior,1);
          for(let i=mockTerms.length-1;i>=0;i--)if(mockTerms[i].scope===body.scope)mockTerms.splice(i,1);}
        res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result));return;
      }
      if(req.url.startsWith('/api/v1/cache')){
        if(req.url.endsWith('/settings')){let body='';for await(const chunk of req)body+=chunk;persistentCache=JSON.parse(body).enabled;}
        res.setHeader('Content-Type','application/json');res.end(JSON.stringify({persistent_enabled:persistentCache,
          memory_bytes:0,memory_limit:64*1024*1024,disk_bytes:0,disk_limit:512*1024*1024,evictions:0,configuration_id:mockConfiguration}));return;
      }
      const configuration=new URL(backend+req.url).searchParams.get('configuration');
      if(configuration && configuration!==mockConfiguration){req.resume();res.writeHead(409);res.end();return;}
      const request=new Request(backend+req.url,{method:'POST',headers:req.headers,body:req,duplex:'half'});
      const form=await request.formData(),file=form.get('file'),bytes=new Uint8Array(await file.arrayBuffer());
      if(form.has('options_json'))translationCalls.push(JSON.parse(form.get('options_json')));
      if(req.url.startsWith('/api/v1/render-page'))mockRenders++;
      if(req.url.includes('refresh=translation'))mockRefreshes++;
      await new Promise(resolve=>setTimeout(resolve,250));
      if(req.url.startsWith('/api/v1/analyze-image')) {
        res.setHeader('Content-Type','application/json');res.end(JSON.stringify({
          original_text:'でも大丈夫',translation:'But it is okay.',tokens:[],processing:{ocr_ms:0,translation_ms:0,analysis_ms:0,total_ms:0}}));return;
      }
      const width=(bytes[16]*2**24+bytes[17]*65536+bytes[18]*256+bytes[19])>>>0;
      const height=(bytes[20]*2**24+bytes[21]*65536+bytes[22]*256+bytes[23])>>>0;
      const snapshot={schema_version:1,build:{version:'fixture',revision:null},image:{
        width,height,input_sha256:createHash('sha256').update(bytes).digest('hex')},models:{},regions:[],
        blocks:[{id:1,region_ids:[],ocr:{status:'success',confidence:null},translation:{status:'success'},
          render:{status:'rendered',reason_code:'rendered'},text:{original:'でも大丈夫',translation:'But it is okay.'}}],
        timings:{analysis:{ocr_ms:0}},counts:{rendered:1,preserved:0,undetected:null}};
      const archive=packZip([{name:'rendered.png',data:bytes},
        {name:'snapshot.json',data:new TextEncoder().encode(JSON.stringify(snapshot))}]);
      res.setHeader('Content-Type','application/zip');res.end(Buffer.from(await archive.arrayBuffer()));
    } catch {res.writeHead(500);res.end();}
  });
  await new Promise(resolve=>mockServer.listen(8774,'127.0.0.1',resolve));
}

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
const version=await(await fetch(`http://127.0.0.1:${process.env.YOMISCAN_TEST_CDP_PORT??9231}/json/version`)).json();
const ws=new WebSocket(version.webSocketDebuggerUrl);
await new Promise(resolve=>ws.addEventListener("open",resolve,{once:true}));
let next=0;const callbacks=new Map(),contexts=[];
ws.addEventListener("message",event=>{const m=JSON.parse(event.data);if(m.id){const c=callbacks.get(m.id);callbacks.delete(m.id);m.error?c.reject(new Error(JSON.stringify(m.error))):c.resolve(m.result);}
  else if(m.method==='Runtime.executionContextCreated')contexts.push({session:m.sessionId,...m.params.context});});
function call(method,params={},sessionId){return new Promise((resolve,reject)=>{const id=++next;callbacks.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params,sessionId}));});}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function evaluate(session,expression,contextId){const r=await call("Runtime.evaluate",{expression,contextId,returnByValue:true,awaitPromise:true},session);if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function until(check,timeout=60000){const end=Date.now()+timeout;while(Date.now()<end){const value=await check();if(value)return value;await wait(100);}throw new Error("Timed out");}
function nodes(root){return [root,...(root.children??[]).flatMap(nodes),...(root.shadowRoots??[]).flatMap(nodes)];}
let session,worker,extensionId,offscreen;
async function find(predicate){const doc=await call("DOM.getDocument",{depth:-1,pierce:true},session);return nodes(doc.root).find(predicate);}
async function invoke(node,fn){const o=await call("DOM.resolveNode",{nodeId:node.nodeId},session);const r=await call("Runtime.callFunctionOn",{objectId:o.object.objectId,functionDeclaration:fn,returnByValue:true,awaitPromise:true,userGesture:true},session);if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
const byClass=name=>n=>{const index=n.attributes?.indexOf('class')??-1;return index>=0&&n.attributes[index+1].split(/\s+/).includes(name);};
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
const report={browser:version.Browser,mockedBackend:mocked,modelInference:!mocked,checks:[]};
try {
  assert.equal((await fetch(backend+"/health")).status,200);
  await mkdir(reportDir,{recursive:true});
  await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:reportDir});
  const extensions=await call("Extensions.getExtensions");
  for(const extension of extensions.extensions)if(extension.name.startsWith("YomiScan"))await call("Extensions.uninstall",{id:extension.id});
  extensionId=(await call("Extensions.loadUnpacked",{path:extensionPath})).id;
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
  if(mocked)await until(()=>mockRenders>0); // Stop after acquisition, while backend work is in flight.
  await click("Stop Translation");
  await evaluate(session,"document.querySelector('#page-4').scrollIntoView()");
  await until(async()=>(await panel()).includes("1 / 5 pages translated"));
  report.checks.push("Stop cancels queued work; scrolling during in-flight processing works and its result is retained");
  const offTarget=await until(async()=>(await call("Target.getTargets")).targetInfos.find(t=>t.url.includes(extensionId+"/offscreen.html")));
  offscreen=(await call("Target.attachToTarget",{targetId:offTarget.targetId,flatten:true})).sessionId;
  await evaluate(offscreen,`globalThis.testCalls=[];globalThis.failPage2=true;const nativeFetch=fetch;globalThis.fetch=async(url,options)=>{
    const bitmap=await createImageBitmap(options.body.get('file'));const canvas=new OffscreenCanvas(bitmap.width,bitmap.height);const ctx=canvas.getContext('2d');ctx.drawImage(bitmap,0,0);bitmap.close();
    const id=ctx.getImageData(0,0,1,1).data[0];testCalls.push(id);
    if(id===2&&failPage2){failPage2=false;return new Response('',{status:500});}
    return nativeFetch(url,options);};`);
  await click("Translate Chapter");await until(async()=>(await panel()).includes("4 / 5 pages translated")&&(await panel()).includes("1 failed"),120000);
  report.checks.push("Progressive page responses; injected page-2 HTTP failure does not stop later pages");
  const count=await evaluate(offscreen,"testCalls.length");await click("Original");await wait(100);
  assert.equal(await evaluate(session,"getComputedStyle(document.querySelector('[data-yomiscan=overlays]')).visibility"),"hidden");
  await click("English");await wait(100);
  assert.equal(await evaluate(session,"getComputedStyle(document.querySelector('[data-yomiscan=overlays]')).visibility"),"visible");
  await click("Original");await click("English");
  await wait(300);assert.equal(await evaluate(offscreen,"testCalls.length"),count);report.checks.push("Original/English toggles reuse cached results");
  await click("Retry Failed / Skipped");await until(async()=>(await panel()).includes("5 / 5 pages translated"),60000);
  report.checks.push("Explicit retry recovers failed page");
  if(mocked){
    const cacheSummary=await find(n=>n.nodeName==='SUMMARY'&&n.children?.some(c=>c.nodeValue==='Local processing cache'));
    await invoke(cacheSummary,'function(){this.click()}');
    await until(async()=>(await panel()).includes('Disk 0.0 / 512.0 MiB'));
    const consent=async()=>nodes((await call('DOM.getDocument',{depth:-1,pierce:true},session)).root)
      .find(n=>n.nodeName==='INPUT'&&n.attributes?.includes('persistent-cache'));
    assert.equal(await invoke(await consent(),'function(){return this.checked}'),false);
    await invoke(await consent(),'function(){this.click()}');await until(()=>persistentCache);
    await click('Clear Persistent Cache');await wait(200);assert.equal(persistentCache,true);
    await invoke(await consent(),'function(){this.click()}');await until(()=>!persistentCache);
    await invoke(await find(n=>n.nodeName==='SUMMARY'&&n.children?.some(c=>c.nodeValue==='Local processing cache')),'function(){this.click()}');
    report.checks.push('Persistence is off by default; explicit checkbox, usage and separate persistent clear work without clearing browser overlays');
  }
  const pageSelector=await find(n=>n.nodeName==='SELECT');
  await invoke(pageSelector,"function(){this.value='1'}");
  await evaluate(session,"document.querySelector('#page-1').scrollIntoView()");await wait(150);
  const beforeRefresh=await evaluate(offscreen,'testCalls.length');
  await click('Retranslate Page');
  await until(async()=>await evaluate(offscreen,'testCalls.length')===beforeRefresh+1);
  await until(async()=>(await panel()).includes('5 / 5 pages translated'));
  report.checks.push('Successful-page refresh reruns only the selected page');
  await evaluate(offscreen,`const refreshFetch=fetch;globalThis.failRefresh=true;globalThis.fetch=async(url,options)=>{
    if(failRefresh){failRefresh=false;return new Response('',{status:500});}return refreshFetch(url,options);};`);
  await click('Retranslate Page');
  await until(async()=>(await panel()).includes('Refresh failed; previous translation retained.'));
  assert.ok((await panel()).includes('5 / 5 pages translated'));
  await click('Original');await click('English');
  report.checks.push('Failed refresh retains usable translation and Original/English toggles');
  const callsBeforeExport=await evaluate(offscreen,'testCalls.length');
  await click('Export Page Report');
  const metadataFile=await until(async()=>(await readdir(reportDir)).find(name=>name.endsWith('.zip')));
  const exported=await unpackZip(new Blob([await readFile(path.join(reportDir,metadataFile))]));
  assert.deepEqual([...exported.keys()],['manifest.json','regions.json','timings.json']);
  const manifest=JSON.parse(new TextDecoder().decode(exported.get('manifest.json')));
  assert.equal(manifest.page.id,1);assert.equal(manifest.inclusions.text,false);
  assert.ok(!JSON.stringify(manifest).includes('127.0.0.1'));
  if(mocked) {
    await wait(1100); // Allow Chrome's one bounded download URL lease to expire.
    const options=nodes((await call('DOM.getDocument',{depth:-1,pierce:true},session)).root)
      .filter(n=>n.nodeName==='INPUT'&&['report-text','report-original','report-rendered'].some(p=>n.attributes?.includes(p)));
    for(const option of options)await invoke(option,"function(){this.checked=true;this.dispatchEvent(new Event('change'))}");
    const prior=new Set(await readdir(reportDir));await click('Export Page Report');
    const fullFile=await until(async()=>(await readdir(reportDir)).find(name=>name.endsWith('.zip')&&!prior.has(name)));
    const full=await unpackZip(new Blob([await readFile(path.join(reportDir,fullFile))]));
    assert.ok(full.has('optional/translation-debug.json'));assert.ok(full.has('optional/original.png'));assert.ok(full.has('optional/rendered.png'));
    assert.ok(new TextDecoder().decode(full.get('optional/translation-debug.json')).includes('大丈夫'));
  }
  assert.equal(await evaluate(offscreen,'testCalls.length'),callsBeforeExport);
  report.checks.push('Explicit local diagnostic download has metadata-only default; optional image/text inclusions tested in mock mode; export performs no inference');
  if(mocked) {
    await wait(1100);
    await call('Runtime.enable',{},session);
    const contentContext=contexts.find(c=>c.session===session&&c.origin===`chrome-extension://${extensionId}`);
    assert.ok(contentContext,'extension content execution context');
    // Hold optional PNG encoding while the same image receives a newer completed job.
    // Its image hash is unchanged: result ownership must still cancel the old export.
    await evaluate(session,`globalThis.holdReport=true;const convert=OffscreenCanvas.prototype.convertToBlob;
      OffscreenCanvas.prototype.convertToBlob=async function(options){
        if(holdReport){holdReport=false;await new Promise(resolve=>globalThis.releaseReport=resolve);}
        return convert.call(this,options);};`,contentContext.id);
    const downloadsBefore=new Set(await readdir(reportDir));
    await click('Export Page Report');
    await until(()=>evaluate(session,"typeof releaseReport==='function'",contentContext.id));
    const calls=await evaluate(offscreen,'testCalls.length');await click('Retranslate Page');
    await until(async()=>await evaluate(offscreen,'testCalls.length')===calls+1&&(await panel()).includes('5 / 5 pages translated'));
    await evaluate(session,'releaseReport()',contentContext.id);
    await until(async()=>(await panel()).includes('Page changed during report preparation; export cancelled.'));
    assert.deepEqual(new Set(await readdir(reportDir)),downloadsBefore);
    report.checks.push('Export cancelled when a newer job replaced its result, even with identical source pixels; no stale ZIP downloaded');
  }
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
  assert.ok((await invoke(await find(byClass("panel")),"function(){return this.innerText}")).includes("大丈夫"));
  report.checks.push(mocked?"Study selection/popup works with mocked analysis":"Study captures original Japanese with actual OCR/translation/dictionary");
  await call('Browser.grantPermissions',{permissions:['clipboardReadWrite','clipboardSanitizedWrite'],origin:'http://127.0.0.1:8772'});
  await click('Copy Japanese');
  await until(async()=>(await invoke(await find(byClass('panel')),"function(){return this.innerText}")).includes('Copied.'));
  assert.ok((await evaluate(session,'navigator.clipboard.readText()')).includes('大丈夫'));
  await click('Copy English');
  await until(async()=>!(await evaluate(session,'navigator.clipboard.readText()')).includes('大丈夫'));
  const popup=await find(byClass('panel')),header=popup.children.find(n=>n.nodeName==='HEADER');
  const headerRect=await invoke(header,"function(){const r=this.getBoundingClientRect();return {x:r.x+30,y:r.y+12}}");
  await call('Input.dispatchMouseEvent',{type:'mousePressed',...headerRect,button:'left',clickCount:1},session);
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:40,y:50,button:'left',buttons:1},session);
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:40,y:50,button:'left',clickCount:1},session);
  const oldBounds=await invoke(popup,"function(){const r=this.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}}");
  const corner=await find(n=>n.attributes?.includes('resize resize-corner'));
  const cornerPoint=await invoke(corner,"function(){const r=this.getBoundingClientRect();return {x:r.right-8,y:r.bottom-8}}");
  await call('Input.dispatchMouseEvent',{type:'mousePressed',...cornerPoint,button:'left',clickCount:1},session);
  await call('Input.dispatchMouseEvent',{type:'mouseMoved',x:cornerPoint.x+30,y:cornerPoint.y+20,button:'left',buttons:1},session);
  await call('Input.dispatchMouseEvent',{type:'mouseReleased',x:cornerPoint.x+30,y:cornerPoint.y+20,button:'left',clickCount:1},session);
  const resizedWidth=await invoke(await find(byClass('panel')),"function(){return this.getBoundingClientRect().width}");
  assert.ok(resizedWidth>oldBounds.width,JSON.stringify({oldBounds,cornerPoint,resizedWidth}));
  report.checks.push('Study Copy Japanese/English succeeds with clipboard user gesture; popup remains draggable/resizable');
  await call("Input.dispatchKeyEvent",{type:"keyDown",key:"Escape",code:"Escape",windowsVirtualKeyCode:27},session);
  await activate();await click("Translate Chapter");await evaluate(session,"document.querySelector('#swap').click()");
  await until(async()=>await evaluate(offscreen,"testCalls.includes(99)"),30000);
  await until(async()=>(await panel()).includes("7 / 7 pages translated"));report.checks.push("Changed currentSrc invalidates only the replaced page's cached result");
  assert.equal(await evaluate(offscreen,"testCalls.filter(id=>id===99).length"),1,"source change must not submit both attribute/load jobs");
  await evaluate(session,"document.querySelector('#navigate').click()");await until(async()=>!await find(n=>n.attributes?.includes("overlays")));
  report.checks.push("SPA URL navigation destroys chapter overlays/session");
  await click("Clear Session");await until(async()=>!await find(n=>n.attributes?.includes("overlays")));
  report.checks.push("Clear removes overlays and releases session results");
  await call("Network.enable",{},worker);await call("Network.setBlockedURLs",{urls:[backend+"/*"]},worker);
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
  await evaluate(offscreen,`globalThis.longCalls=0;globalThis.fetch=async(url,options)=>{
    longCalls++;const png=new Uint8Array(await options.body.get('file').arrayBuffer());
    const length=8*1024*1024,chunk=new Uint8Array(length+12),view=new DataView(chunk.buffer);
    view.setUint32(0,length);chunk.set([116,69,88,116],4);chunk.set(new TextEncoder().encode('fixture'),8);
    let crc=0xffffffff;for(let i=4;i<chunk.length-4;i++){crc^=chunk[i];for(let b=0;b<8;b++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
    view.setUint32(chunk.length-4,(crc^0xffffffff)>>>0);
    return new Response(new Blob([png.slice(0,-12),chunk,png.slice(-12)]),{status:200,headers:{'Content-Type':'image/png','X-YomiScan-Blocks-Rendered':'0','X-YomiScan-Blocks-Skipped':'0'}});};`);
  await evaluate(session,"document.querySelector('main').replaceChildren();for(let i=0;i<24;i++)document.querySelector('#append').click()");
  await until(()=>evaluate(session,"[...document.querySelectorAll('main img')].every(i=>i.complete)"));
  const longStarted=performance.now();
  await click("Translate Chapter");await until(async()=>(await panel()).includes("24 / 24 pages translated"),120000);
  report.mockedLongQueueMs=Math.round(performance.now()-longStarted);
  assert.match(await panel(),/Session [0-9.]+ \/ 128 MiB · [1-9][0-9]* evicted/);
  assert.equal(await evaluate(offscreen,'longCalls'),24);
  await evaluate(session,"document.querySelector('main img:last-child').scrollIntoView()");
  await wait(100);
  const callsBeforeRestore=await evaluate(offscreen,'longCalls');
  await evaluate(session,"document.querySelector('main img:nth-child(2)').scrollIntoView()");
  await until(async()=>await evaluate(offscreen,'longCalls')>callsBeforeRestore);
  await until(async()=>!(await panel()).includes('processing…'));
  assert.ok(!Number.isNaN(report.mockedLongQueueMs));
  report.checks.push('Over 192 MiB of actual PNG responses evict offscreen results within 128 MiB; scrolling restores an evicted page without a chapter-wide stop');
  if(mocked)assert.ok(mockRefreshes>0,'Retranslate must force backend translation/render refresh');
  await click("Clear Session");
  report.checks.push("24-page synthetic queue and cleanup (mocked render responses; not a model-quality benchmark)");
  if(mocked){
    await evaluate(offscreen,'globalThis.fetch=nativeFetch');
    await evaluate(session,"document.querySelector('main').replaceChildren();document.querySelector('#append').click()");
    await until(()=>evaluate(session,"document.querySelector('main img')?.complete"));
    await click('Translate Chapter');await until(async()=>(await panel()).includes('1 / 1 pages translated'));
    mockConfiguration='e'.repeat(64);
    await click('Retranslate Page');await until(async()=>(await panel()).includes('Backend settings changed'));
    assert.ok(!await find(n=>n.attributes?.includes('overlays')));
    await click('Translate Chapter');await until(async()=>(await panel()).includes('1 / 1 pages translated'));
    await click('Clear Session');
    report.checks.push('Backend configuration change rejects old generation, clears obsolete overlays and allows a fresh session');
    const summary=await find(n=>n.nodeName==='SUMMARY'&&n.children?.some(c=>c.nodeValue==='Translation & terminology'));
    await invoke(summary,'function(){this.click()}');
    await until(async()=>(await panel()).includes('does not use glossary hints'));
    const select=label=>find(n=>n.nodeName==='SELECT'&&n.attributes?.includes(label));
    const edit=async(placeholder,value)=>invoke(await find(n=>n.nodeName==='INPUT'&&n.attributes?.includes(placeholder)),
      `function(){this.value=${JSON.stringify(value)}}`);
    assert.equal(await invoke(await select('Sentence target language'),"function(){return this.querySelector('[value=es]').disabled}"),true);
    assert.equal(await invoke(await select('Translation contract'),"function(){return this.querySelector('[value=structured-page]').disabled}"),true);
    await edit('User-confirmed series name','Fixture series A');await click('Create Series');
    await until(()=>mockSeries.length===2);await until(async()=>await invoke(await select('Active series glossary'),'function(){return this.value}')===mockSeries[1].id);
    await edit('Exact Japanese term','霊力');await edit('Preferred target-language term','spirit energy');await click('Save Entry');
    await until(()=>mockTerms.length===1);await wait(150);
    await invoke(await select('Terminology entry'),`function(){this.value=${JSON.stringify(mockTerms[0].id)};this.dispatchEvent(new Event('change'))}`);
    await edit('Preferred target-language term','spiritual power');await click('Save Entry');await until(()=>mockTerms[0].preferred==='spiritual power');await wait(150);
    await click('Clear Persistent Cache');assert.equal(mockTerms.length,1);
    await invoke(await select('Active series glossary'),"function(){this.value='global';this.dispatchEvent(new Event('change'))}");
    await until(async()=>await invoke(await select('Terminology entry'),'function(){return this.options.length}')===1);
    report.checks.push('Glossary editor creates, persists, edits and isolates series entries; clearing processing cache preserves terminology; unsupported targets/contracts are disabled');
    experimentalCapabilities=true;await click('Reload Translation Settings');
    await until(async()=>(await panel()).includes('Matched terminology'));
    await invoke(await select('Sentence target language'),"function(){this.value='es';this.dispatchEvent(new Event('change'))}");
    await until(async()=>await invoke(await select('Sentence target language'),'function(){return this.value}')==='es');await wait(150);
    await click('Translate Chapter');await until(async()=>(await panel()).includes('1 / 1 pages translated'));
    assert.equal(translationCalls.at(-1).target_language,'es');
    await click('Español (experimental)');await wait(100);
    await invoke(await select('Sentence target language'),"function(){this.value='en';this.dispatchEvent(new Event('change'))}");
    await until(async()=>!await find(n=>n.attributes?.includes('overlays')));
    await invoke(await select('Translation contract'),"function(){this.value='structured-line';this.dispatchEvent(new Event('change'))}");
    await invoke(await select('Bounded dialogue context'),"function(){this.value='neighbor';this.dispatchEvent(new Event('change'))}");
    await click('Translate Chapter');await until(async()=>(await panel()).includes('1 / 1 pages translated'));
    assert.equal(translationCalls.at(-1).mode,'structured-line');assert.equal(translationCalls.at(-1).context,'neighbor');
    await click('Clear Session');
    await invoke(await select('Active series glossary'),`function(){this.value=${JSON.stringify(mockSeries[1].id)};this.dispatchEvent(new Event('change'))}`);await wait(150);
    await invoke(await select('Terminology entry'),`function(){this.value=${JSON.stringify(mockTerms[0].id)};this.dispatchEvent(new Event('change'))}`);
    await click('Delete Entry');await until(()=>mockTerms.length===0);await wait(150);
    await click('Delete Series Glossary');await until(()=>mockSeries.length===1);
    report.checks.push('Compatible experimental language, exact-ID contract and bounded context reach render transport; target change removes obsolete overlays; entry/series deletion works');
  }
  report.status=await panel();report.requestOrder=await evaluate(offscreen,"testCalls");
  await mkdir(".cache",{recursive:true});await writeFile(mocked?".cache/stage1-browser.json":".cache/phase-7-browser.json",JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}catch(error){console.error(error);console.error("Completed checks:",report.checks);if(session)console.error("Controls:",await panel());process.exitCode=1;}
finally{ws.close();server.closeAllConnections();server.close();crossServer.closeAllConnections();crossServer.close();mockServer?.closeAllConnections();mockServer?.close();}
