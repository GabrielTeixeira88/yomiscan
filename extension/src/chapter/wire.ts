// Chrome 120 messaging serializes JSON. Bound each transfer chunk; never retain a
// chapter of base64 strings. Source images and cached results remain Blobs/object URLs.
export const CHUNK = 192 * 1024;
export const MAX_INPUT = 10 * 1024 * 1024;
export const MAX_OUTPUT = 32 * 1024 * 1024;
export async function encodeChunk(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let text = "";
  for (let i=0; i<bytes.length; i+=8192) text += String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(text);
}
export function decodeChunk(value: unknown): Uint8Array<ArrayBuffer> {
  if (typeof value !== "string" || value.length > Math.ceil(CHUNK/3)*4) throw new Error("Invalid image transfer chunk");
  return Uint8Array.from(atob(value), c=>c.charCodeAt(0));
}
