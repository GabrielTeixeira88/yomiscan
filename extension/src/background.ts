import { analyzeCrop } from "./api";
import {installSourceFetch} from './chapter/source-fetch';
import {CaptureThrottle} from './chapter/capture-throttle';
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
  const timer = setTimeout(() => controller.abort(), 25_000);
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
    return await analyzeCrop(crop, controller.signal);
  } finally {
    clearTimeout(timer);
    if (pending.get(tabId)?.id === request.id) pending.delete(tabId);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || sender.tab?.id === undefined) return;
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
    const work=message.type==="chapter-prepare" ? prepareTransport() : message.type==="chapter-capture" ? pageCapture(message,sender.tab) :
      fetch("http://127.0.0.1:8765/health",{signal:AbortSignal.timeout(5000),credentials:"omit",redirect:"error",cache:"no-store"}).then(async response=>{
        if(!response.ok || (await response.json()).status!=="ok")throw new Error("YomiScan backend resources are unavailable. Check the server terminal.");
      });
    work.then(data=>sendResponse({ok:true,...(data as object??{})}),error=>sendResponse({ok:false,error:message.type==="chapter-health" &&
      (error instanceof TypeError || error?.name==="TimeoutError") ?
      "YomiScan local backend is not running or did not respond.":error instanceof Error?error.message:"Local page request failed"}));
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
