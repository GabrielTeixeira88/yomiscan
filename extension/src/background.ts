import {backendBase} from './backend';
import {companionPrepare,companionStatus} from './companion';
import {localConnection,localFetch} from './local';
import { analyzeCrop, analyzeText, parseAnalysis } from "./api";
import {ENGINE_INSTALLED_KEY,SETUP_NEEDED,engineChoice,engineSource,resolveEngine,type EngineChoice,type ResolvedEngine} from './engine-mode';
import type {EngineStatus} from './engine/engine';
import {installSourceFetch} from './chapter/source-fetch';
import {CaptureThrottle} from './chapter/capture-throttle';
import {cacheRequest} from './chapter/cache-client';
import {translationRequest,type TranslationOperation} from './chapter/translation-client';
import {Library,type LibraryRequest,libraryRequest} from './library';
import {IndexedDbStore} from './library-idb';
import {readinessRequest,selectTranslationEngine} from './chapter/readiness-client';
const library=new Library(new IndexedDbStore());
// The old opt-in Study history becomes saved sentences once; if moving fails, it stays where it was.
const migrated=library.migrateHistory({get:key=>chrome.storage.local.get(key),remove:key=>chrome.storage.local.remove(key)})
  .catch(error=>{console.error('YomiScan could not move Study history into saved sentences; it is kept as it was.',error);});
const captures=new CaptureThrottle();
installSourceFetch();
import { screenshotRect, validSelection, type Rect, type Viewport } from "./geometry";

interface CaptureRequest { type: "capture"; id: string; rect: Rect; viewport: Viewport }
const pending = new Map<number, {id: string; controller: AbortController}>();

async function activate(tab: chrome.tabs.Tab, study = false): Promise<void> {
  if (tab.id === undefined) return;
  try {
    await chrome.action.setBadgeText({tabId: tab.id, text: ""});
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["content.js"]});
    await chrome.tabs.sendMessage(tab.id, {type: study ? "activate" : "chapter-controls"}, {frameId: 0});
    await chrome.action.setTitle({tabId: tab.id, title: "YomiScan: Study / Translate Chapter"});
  } catch {
    await chrome.action.setBadgeText({tabId: tab.id, text: "!"});
    await chrome.action.setTitle({tabId: tab.id, title: "YomiScan cannot select here. Open a normal webpage; Chrome internal pages and the Web Store are restricted."});
  }
}
chrome.action.onClicked.addListener(tab=>{void activate(tab);});
chrome.commands.onCommand.addListener(async command=>{if(command==="select-text"){
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(tab)await activate(tab,true);
}});
let preparing: Promise<void>|null=null;
async function prepareTransport():Promise<void> {
  if(preparing)return preparing;
  preparing=(async()=>{
    const contexts=await chrome.runtime.getContexts({contextTypes:[chrome.runtime.ContextType.OFFSCREEN_DOCUMENT]});
    if(!contexts.length)await chrome.offscreen.createDocument({url:"offscreen.html",reasons:[chrome.offscreen.Reason.BLOBS],
      justification:"Transfer and process page image Blobs through the local renderer without service-worker fetch lifetime limits"});
  })().finally(()=>{preparing=null;});return preparing;
}
/** The local engine address for one chapter page upload. The offscreen document receives the
 * companion's token directly; content scripts only see the address. Browser-engine pages need no backend. */
async function pageBackend(kind:unknown):Promise<{backend:string}>{
  if(kind==='browser')return {backend:await backendBase()};
  const connection=await localConnection({verify:true});
  const reply=await chrome.runtime.sendMessage({target:'offscreen-credentials',origin:connection.base,
    token:connection.headers['X-YomiScan-Token']??null});
  if(!reply?.ok)throw new Error('Could not prepare the local page transport. Reload the extension and retry.');
  return {backend:connection.base};
}
/** One request to the browser engine in the offscreen document (created on demand). */
async function engineRequest(operation:string,extra:Record<string,unknown>={}):Promise<unknown>{
  await prepareTransport();
  const reply=await chrome.runtime.sendMessage({target:'offscreen-engine',operation,...extra});
  if(!reply?.ok)throw new Error(reply?.error??'Browser engine unavailable. Reload the extension.');
  return reply.data;
}
/** Which engine serves the next request (engine-mode.ts). Records a complete install so a later
 * disappearance (Chrome clearing storage) can be explained instead of looking like a first run. */
async function engineState():Promise<{choice:EngineChoice;mode:ResolvedEngine;status:EngineStatus|null;evicted:boolean;source:string}>{
  const choice=await engineChoice();let status:EngineStatus|null=null;
  const mode=await resolveEngine(choice,async()=>{
    status=await engineRequest('status') as EngineStatus;
    const ready=status.required.every(c=>c.installed);
    if(ready)await chrome.storage.local.set({[ENGINE_INSTALLED_KEY]:status.bundle});
    return ready;
  },backendRunning,async()=>{const companion=await companionStatus();return companion.installed&&companion.ready;});
  const installedBefore=typeof (await chrome.storage.local.get(ENGINE_INSTALLED_KEY))[ENGINE_INSTALLED_KEY]==='string';
  return {choice,mode,status,evicted:mode==='setup'&&installedBefore,source:await engineSource()};
}
async function backendRunning():Promise<boolean>{
  try {return (await fetch(await backendBase()+'/health',{signal:AbortSignal.timeout(1500),credentials:'omit',redirect:'error',cache:'no-store'})).ok;}
  catch {return false;}// Not running (or not answering) is an expected answer here, not a failure.
}
async function base64(blob:Blob):Promise<string>{
  const bytes=new Uint8Array(await blob.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(binary);
}
async function pageCapture(request:CaptureRequest,tab:chrome.tabs.Tab):Promise<unknown> {
  if(!request.rect || !request.viewport || !validSelection(request.rect,request.viewport) || request.viewport.scale!==1)throw new Error("Invalid page capture rectangle");
  const verify=async()=>{
    const [active]=await chrome.tabs.query({active:true,windowId:tab.windowId});
    if(active?.id!==tab.id || await chrome.tabs.sendMessage(tab.id!,{type:"verify-page-capture",id:request.id},{frameId:0})!==true)
      throw new Error("Page moved or active tab changed during capture");
  };
  const screenshot=await captures.run(async()=>{await verify();return chrome.tabs.captureVisibleTab(tab.windowId,{format:"png"});});await verify();
  const bitmap=await createImageBitmap(new Blob([Uint8Array.from(atob(screenshot.split(",")[1]),c=>c.charCodeAt(0))]));
  try {
    const r=screenshotRect(request.rect,request.viewport,bitmap);
    if(r.width*r.height>12_000_000)throw new Error("Page capture exceeds 12 megapixels");
    const canvas=new OffscreenCanvas(r.width,r.height);const ctx=canvas.getContext("2d");if(!ctx)throw new Error("Cannot crop page screenshot");
    ctx.drawImage(bitmap,r.x,r.y,r.width,r.height,0,0,r.width,r.height);
    const blob=await canvas.convertToBlob({type:"image/png"});if(blob.size>10*1024*1024)throw new Error("Page capture exceeds 10 MiB");
    const bytes=new Uint8Array(await blob.arrayBuffer());let binary="";
    for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
    const scaleX=bitmap.width/request.viewport.width,scaleY=bitmap.height/request.viewport.height;
    return {data:btoa(binary),width:r.width,height:r.height,capture:{scaleX,scaleY,
      x:request.rect.x*scaleX-r.x,y:request.rect.y*scaleY-r.y,width:request.rect.width*scaleX,height:request.rect.height*scaleY}};
  } finally {bitmap.close();}
}

async function capture(request: CaptureRequest, tab: chrome.tabs.Tab): Promise<unknown> {
  const tabId = tab.id!;
  if (!request.rect || !request.viewport || !validSelection(request.rect, request.viewport)
    || request.viewport.scale !== 1 || typeof request.id !== "string") {
    throw new Error("Invalid selection or pinch zoom. Reset pinch zoom and select again.");
  }
  pending.get(tabId)?.controller.abort();
  const controller = new AbortController();
  pending.set(tabId, {id: request.id, controller});
  const verify = async () => {
    const [active] = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (active?.id !== tabId || controller.signal.aborted) throw new Error("Selection cancelled because the active tab changed.");
    const valid = await chrome.tabs.sendMessage(tabId, {type: "verify-capture", id: request.id}, {frameId: 0});
    if (valid !== true) throw new Error("The page moved during capture. Select the region again.");
  };
  const engine = (await engineState()).mode;
  if (engine === "setup") throw new Error(SETUP_NEEDED);
  // The browser engine may load its models on the first request; allow it longer.
  const timer = setTimeout(() => controller.abort(), engine === "browser" ? 120_000 : 25_000);
  try {
    const screenshot = await captures.run(async()=>{await verify();return chrome.tabs.captureVisibleTab(tab.windowId, {format: "png"});});
    await verify();
    // The full screenshot stays here, in memory, and is never posted to Python.
    const bytes = Uint8Array.from(atob(screenshot.split(",")[1]), char => char.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([bytes], {type: "image/png"}));
    let crop: Blob;
    try {
      const rect = screenshotRect(request.rect, request.viewport, bitmap);
      if (rect.width * rect.height > 12_000_000) throw new Error("Select a smaller region (maximum 12 megapixels).");
      const canvas = new OffscreenCanvas(rect.width, rect.height);
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Chrome could not create the screenshot crop.");
      ctx.drawImage(bitmap, rect.x, rect.y, rect.width, rect.height, 0, 0, rect.width, rect.height);
      crop = await canvas.convertToBlob({type: "image/png"});
    } finally { bitmap.close(); }
    if (crop.size > 10 * 1024 * 1024) throw new Error("Select a smaller region (maximum 10 MiB).");
    await verify();
    await chrome.tabs.sendMessage(tabId, {type: "captured", id: request.id}, {frameId: 0});
    if (engine === "browser") return parseAnalysis(await engineRequest("study", {data: await base64(crop), mime: "image/png"}));
    return await analyzeCrop(crop, controller.signal);
  } finally {
    clearTimeout(timer);
    if (pending.get(tabId)?.id === request.id) pending.delete(tabId);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || sender.tab?.id === undefined) return;
  if(message?.type==='engine'){
    // Browser engine setup (Stage 5a). Page recognition is not exposed to content scripts here.
    // Install uses the published model host unless Advanced sets a development source.
    if(!['status','install','cancel','remove'].includes(message.operation)||(message.base!==undefined&&typeof message.base!=='string')){
      sendResponse({ok:false,error:'Invalid browser engine request'});return;}
    void (async()=>{
      const data=await engineRequest(message.operation,message.operation==='install'?{base:message.base??await engineSource()}:{});
      if(message.operation==='remove')await chrome.storage.local.remove(ENGINE_INSTALLED_KEY);
      return data;
    })().then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Browser engine unavailable'}));
    return true;
  }
  if(message?.type==='companion-prepare'){
    void companionPrepare().then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'The local engine could not start the download'}));
    return true;
  }
  if(message?.type==='companion-status'){
    void companionStatus(undefined,true).then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Local engine status unavailable'}));
    return true;
  }
  if(message?.type==='engine-resolve'){
    void engineState().then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Browser engine unavailable. Reload the extension.'}));
    return true;
  }
  if(message?.type==='chapter-readiness'){
    void readinessRequest().then(data=>sendResponse({ok:true,data}),()=>sendResponse({ok:false,error:'Readiness unavailable. Start the updated local backend.'}));return true;
  }
  if(message?.type==='chapter-translation-engine'){
    if(typeof message.engine!=='string'){sendResponse({ok:false,error:'Invalid engine'});return;}
    void selectTranslationEngine(message.engine).then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Engine switch failed'}));
    return true;
  }
  if(message?.type==='study-reanalyze'){
    if(typeof message.text!=='string'||message.text.length>1000){sendResponse({ok:false,error:'Edited text must be 1 to 1,000 characters.'});return;}
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25_000);
    void engineState().then(({mode})=>mode==='setup'?Promise.reject(new Error(SETUP_NEEDED)):mode==='browser'?engineRequest('analyze-text',{text:message.text.trim(),translate:true}).then(parseAnalysis):
      analyzeText(message.text,controller.signal)).then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Local analysis failed'})).finally(()=>clearTimeout(timer));
    return true;
  }
  if(message?.type==='library'){
    if(JSON.stringify(message).length>150*1024){sendResponse({ok:false,error:'Saved-word request too large.'});return;}
    if(message.operation==='open'){
      void chrome.tabs.create({url:chrome.runtime.getURL('library.html')}).then(()=>sendResponse({ok:true}),
        error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Could not open the Saved page.'}));
      return true;
    }
    void migrated.then(()=>libraryRequest(library,message as LibraryRequest)).then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Saved words unavailable. Reload the extension.'}));
    return true;
  }
  if(message?.type==='chapter-translation-settings'){
    if(!['profile','create-series','delete-series','save-term','delete-term'].includes(message.operation)||
      !message.payload||typeof message.payload!=='object'||Array.isArray(message.payload)||JSON.stringify(message.payload).length>1800){
      sendResponse({ok:false,error:'Invalid translation settings operation'});return;
    }
    void translationRequest(message.operation as TranslationOperation,message.payload).then(async data=>{
      sendResponse({ok:true,data});
      if(['delete-series','save-term','delete-term'].includes(message.operation)){
        const tabs=await chrome.tabs.query({});
        await Promise.allSettled(tabs.filter(tab=>tab.id!==undefined&&tab.id!==sender.tab!.id).map(tab=>chrome.tabs.sendMessage(tab.id!,{
          type:'chapter-glossary-changed',scope:message.payload.scope,target:message.payload.target_language,
          deleted:message.operation==='delete-series'}, {frameId:0})));
      }
    },error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Local translation settings failed'}));
    return true;
  }
  if(message?.type==='chapter-cache'){
    if(!['read','settings','clear'].includes(message.operation) || (message.operation==='settings' && typeof message.enabled!=='boolean')){
      sendResponse({ok:false,error:'Invalid cache operation'});return;
    }
    cacheRequest(message.operation,message.enabled).then(data=>sendResponse({ok:true,data}),
      error=>sendResponse({ok:false,error:error instanceof Error?error.message:'Local cache operation failed'}));
    return true;
  }
  if(message?.type==='chapter-permissions') {
    const origins=message.origins;
    if(!Array.isArray(origins) || origins.length>50 || !origins.every((x:unknown)=>typeof x==='string' && /^https?:\/\/[^/*?#]+\/\*$/.test(x))) {
      sendResponse({ok:false,error:'Invalid image host list'});return;
    }
    void (async()=>{
      if(await chrome.permissions.contains({origins})){sendResponse({ok:true});return;}
      const query=new URLSearchParams({origins:JSON.stringify(origins),tab:String(sender.tab!.id),version:String(message.version),retry:String(message.retry)});
      await chrome.windows.create({url:chrome.runtime.getURL(`image-access.html?${query}`),type:'popup',width:520,height:520});
      sendResponse({ok:false,pending:true});
    })().catch(error=>sendResponse({ok:false,error:String(error)}));
    return true;
  }
  if(message?.type === "chapter-health" || message?.type === "chapter-prepare" || message?.type === "chapter-capture") {
    const work=message.type==="chapter-prepare" ? prepareTransport().then(()=>pageBackend(message.kind)) : message.type==="chapter-capture" ? pageCapture(message,sender.tab) :
      localFetch("/health",{timeout:5000}).then(async response=>{
        if(!response.ok || (await response.json()).status!=="ok")throw new Error("YomiScan backend resources are unavailable. Check the server terminal.");
        const configuration=response.headers.get('X-YomiScan-Configuration');
        if(configuration && /^[a-f0-9]{64}$/.test(configuration))return {configuration_id:configuration};
        try {return {configuration_id:(await cacheRequest('read')).configuration_id};}
        catch {return {};}// Legacy backends remain usable; their session generation is never reused across Start.
      });
    work.then(data=>sendResponse({ok:true,...(data as object??{})}),error=>sendResponse({ok:false,error:message.type==="chapter-health" &&
      (error instanceof TypeError || error?.name==="TimeoutError") ?
      "YomiScan local backend is not running or did not respond. Start yomiscan-server with the port set in Setup & readiness.":error instanceof Error?error.message:"Local page request failed"}));
    return true;
  }
  if (message?.type === "cancel") {
    const job = pending.get(sender.tab.id);
    if (job && job.id === message.id) job.controller.abort();
    sendResponse({ok: true});
    return;
  }
  if (message?.type !== "capture") return;
  capture(message, sender.tab).then(
    data => sendResponse({ok: true, data}),
    error => sendResponse({ok: false, error: error instanceof Error ? error.message : "Capture failed. Please try again."}),
  );
  return true;
});

chrome.tabs.onRemoved.addListener(tabId => { pending.get(tabId)?.controller.abort(); pending.delete(tabId); });
