import {CHUNK, MAX_INPUT, encodeChunk} from "./wire";

export function imageHost(source: string): string | null {
  const url = new URL(source);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
  // Match patterns grant a host across ports, not an individual URL/path.
  return `${url.protocol}//${url.hostname}/*`;
}

export async function fetchSourceImage(source: string, signal: AbortSignal,
  permitted: (origin: string) => Promise<boolean>, request: typeof fetch = fetch): Promise<Blob> {
  const host = imageHost(source);
  if (!host) throw new Error("Source is not an HTTP(S) image");
  if (!await permitted(host)) throw new Error(`Image-host permission not granted: ${new URL(source).hostname}`);
  signal.throwIfAborted();
  const response = await request(source, {credentials: "include", redirect: "error", signal});
  if (!response.ok) throw new Error(`Image source returned HTTP ${response.status}${[401,403].includes(response.status) ? ' (authentication/hotlink policy; no bypass attempted)' : ''}`);
  const mime = response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
  if (!mime || !['image/png','image/jpeg','image/webp'].includes(mime)) throw new Error(`Unsupported source content type: ${mime || 'missing'}`);
  if (Number(response.headers.get('content-length')) > MAX_INPUT) throw new Error('Source image exceeds 10 MiB');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Empty source image response');
  const parts: Uint8Array<ArrayBuffer>[] = []; let size = 0;
  try {
    while (true) {
      signal.throwIfAborted();
      const item = await reader.read(); if (item.done) break;
      size += item.value.length;
      if (size > MAX_INPUT) throw new Error('Source image exceeds 10 MiB');
      parts.push(new Uint8Array(item.value));
    }
    if (!size) throw new Error('Empty source image response');
    return new Blob(parts, {type: mime});
  } finally { await reader.cancel(); reader.releaseLock(); }
}

/** Only a nonce is accepted. The isolated content script resolves its active loaded image. */
export function installSourceFetch(): void {
  chrome.runtime.onConnect.addListener(port => {
    if (port.name !== 'yomiscan-source-image' || port.sender?.id !== chrome.runtime.id ||
        port.sender.frameId !== 0 || port.sender.tab?.id === undefined) return;
    const tabId = port.sender.tab.id, controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 25_000);
    let used = false, connected = true;
    port.onDisconnect.addListener(() => { connected = false; clearTimeout(timer); controller.abort(); });
    port.onMessage.addListener(message => {
      if (used) return; used = true;
      void (async () => {
        if (typeof message.id !== 'string') throw new Error('Invalid image acquisition ticket');
        const resolve = () => chrome.tabs.sendMessage(tabId, {type:'resolve-page-source', id:message.id}, {frameId:0});
        const source = await resolve();
        if (typeof source !== 'string') throw new Error('Source image is no longer available');
        const blob = await fetchSourceImage(source, controller.signal, origin => chrome.permissions.contains({origins:[origin]}));
        const bitmap = await createImageBitmap(blob);
        const {width,height} = bitmap; bitmap.close();
        if (width*height > 12_000_000) throw new Error('Source image exceeds 12 megapixels');
        if (await resolve() !== source) throw new Error('Source changed during image fetch');
        for (let offset=0; connected && offset<blob.size; offset+=CHUNK)
          port.postMessage({type:'chunk', data:await encodeChunk(blob.slice(offset,offset+CHUNK))});
        if (connected) port.postMessage({type:'result', width,height,mime:blob.type});
      })().catch(error => {
        console.warn('YomiScan source acquisition failed',error);
        if (connected) port.postMessage({type:'error', error:controller.signal.aborted ? 'Source image fetch timed out' :
          error instanceof Error ? error.message : 'Source image fetch failed'});
      }).finally(() => clearTimeout(timer));
    });
  });
}
