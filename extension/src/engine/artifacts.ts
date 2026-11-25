// Browser-engine model artifacts: a manifest pinned in the extension source (path, size and
// SHA-256 per file), downloaded only on an explicit user request, verified, and kept in Cache
// Storage under a content address. A host can move files but can never swap them.

export type ComponentKind = 'detector' | 'ocr' | 'dictionary' | 'tokenizer' | 'translation';
export interface ArtifactFile {path: string; bytes: number; sha256: string}
export interface ArtifactComponent {id: string; kind: ComponentKind; variant: string; license: string; source: string; files: ArtifactFile[]}
export interface ArtifactManifest {schema: 1; bundle: string; components: ArtifactComponent[]}

const KINDS = ['detector', 'ocr', 'dictionary', 'tokenizer', 'translation'];
const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const text = (v: unknown, pattern: RegExp) => typeof v === 'string' && pattern.test(v);

export function parseManifest(value: unknown): ArtifactManifest {
  if (!record(value) || value.schema !== 1 || !text(value.bundle, /^[\w.-]{1,64}$/) || !Array.isArray(value.components))
    throw new Error('Invalid browser-engine artifact manifest');
  const ids = new Set<string>();
  for (const c of value.components) {
    if (!record(c) || !text(c.id, /^[a-z0-9-]{1,40}$/) || !KINDS.includes(String(c.kind)) || !text(c.variant, /^[\w.-]{1,40}$/) ||
      !text(c.license, /^.{1,80}$/) || !text(c.source, /^.{1,200}$/) || !Array.isArray(c.files) || !c.files.length || ids.has(String(c.id)))
      throw new Error('Invalid browser-engine artifact component');
    ids.add(String(c.id));
    for (const f of c.files) if (!record(f) || !text(f.path, /^[a-z0-9][\w.-]*(\/[\w.-]+)*$/i) || String(f.path).includes('..') ||
      !Number.isSafeInteger(f.bytes) || Number(f.bytes) <= 0 || !text(f.sha256, /^[a-f0-9]{64}$/))
      throw new Error(`Invalid artifact file in ${String(c.id)}`);
  }
  return value as unknown as ArtifactManifest;
}

export const componentBytes = (c: ArtifactComponent) => c.files.reduce((n, f) => n + f.bytes, 0);

/** The fixed Cache Storage key of one file: its content hash, never its download URL. */
export const artifactKey = (file: ArtifactFile) => `https://artifacts.yomiscan.invalid/sha256/${file.sha256}`;

export async function sha256Hex(data: ArrayBuffer | Uint8Array<ArrayBuffer>): Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', data))].map(b => b.toString(16).padStart(2, '0')).join('');
}

export interface ArtifactStorage {match(key: string): Promise<Response | undefined>; put(key: string, response: Response): Promise<void>; delete(key: string): Promise<boolean>}
export interface InstallProgress {component: string; file: string; loaded: number; total: number}

export class ArtifactStore {
  // The default calls the global fetch: called as this.request(...), a bare `fetch` property
  // would run with `this` = the store and the browser rejects it ("Illegal invocation").
  constructor(private storage: () => Promise<ArtifactStorage>, private request: typeof fetch = (input, init) => fetch(input, init)) {}

  async installed(component: ArtifactComponent): Promise<boolean> {
    const storage = await this.storage();
    for (const file of component.files) if (!await storage.match(artifactKey(file))) return false;
    return true;
  }

  /** Download each missing file from `base`, verify its size and SHA-256, then store it. */
  async install(component: ArtifactComponent, base: string, progress: (p: InstallProgress) => void = () => {}, signal?: AbortSignal): Promise<void> {
    const url = new URL(base);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
      throw new Error('Artifact source must be a plain http(s) folder URL');
    const storage = await this.storage(), total = componentBytes(component);
    let done = 0;
    for (const file of component.files) {
      if (await storage.match(artifactKey(file))) {done += file.bytes; progress({component: component.id, file: file.path, loaded: done, total}); continue;}
      const response = await this.request(new URL(file.path, url.href.endsWith('/') ? url : url.href + '/'), {signal, credentials: 'omit', redirect: 'follow', cache: 'no-store'});
      if (!response.ok || !response.body) throw new Error(`Download failed for ${file.path} (HTTP ${response.status})`);
      const reader = response.body.getReader(), buffer = new Uint8Array(file.bytes);
      let size = 0;
      try {
        while (true) {
          const item = await reader.read(); if (item.done) break;
          if (size + item.value.length > file.bytes) throw new Error(`${file.path} is larger than its pinned size`);
          buffer.set(item.value, size); size += item.value.length;
          progress({component: component.id, file: file.path, loaded: done + size, total});
        }
      } finally {reader.releaseLock();}
      if (size !== file.bytes) throw new Error(`${file.path} is incomplete (${size} of ${file.bytes} bytes)`);
      if (await sha256Hex(buffer) !== file.sha256) throw new Error(`${file.path} does not match its pinned SHA-256; not installed`);
      try {
        await storage.put(artifactKey(file), new Response(buffer, {headers: {'Content-Type': 'application/octet-stream', 'Content-Length': String(size)}}));
      } catch (error) {
        if (error instanceof DOMException && error.name === 'QuotaExceededError')
          throw new Error(`Chrome ran out of storage while saving ${file.path}. Free some disk space, then download again; finished files are kept.`, {cause: error});
        throw error;
      }
      done += file.bytes;
    }
  }

  /** Read an installed file. The size is rechecked; the hash was checked at install. */
  async read(file: ArtifactFile): Promise<Uint8Array<ArrayBuffer>> {
    const response = await (await this.storage()).match(artifactKey(file));
    if (!response) throw new Error(`Model file ${file.path} is not installed`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength !== file.bytes) throw new Error(`Stored ${file.path} is damaged; remove and reinstall the component`);
    return bytes;
  }

  async remove(component: ArtifactComponent): Promise<void> {
    const storage = await this.storage();
    for (const file of component.files) await storage.delete(artifactKey(file));
  }
}

export const cacheStorage = (): Promise<ArtifactStorage> => caches.open('yomiscan-artifacts-v1');
