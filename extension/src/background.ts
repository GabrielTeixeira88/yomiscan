import { analyzeCrop } from "./api";
import { screenshotRect, validSelection, type Rect, type Viewport } from "./geometry";

interface CaptureRequest { type: "capture"; id: string; rect: Rect; viewport: Viewport }
const pending = new Map<number, {id: string; controller: AbortController}>();

chrome.action.onClicked.addListener(async tab => {
  if (tab.id === undefined) return;
  try {
    await chrome.action.setBadgeText({tabId: tab.id, text: ""});
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["content.js"]});
    await chrome.tabs.sendMessage(tab.id, {type: "activate"}, {frameId: 0});
    await chrome.action.setTitle({tabId: tab.id, title: "YomiScan: select a Japanese text region"});
  } catch {
    await chrome.action.setBadgeText({tabId: tab.id, text: "!"});
    await chrome.action.setTitle({tabId: tab.id, title: "YomiScan cannot select here. Open a normal webpage; Chrome internal pages and the Web Store are restricted."});
  }
});

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
    await verify();
    const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, {format: "png"});
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
