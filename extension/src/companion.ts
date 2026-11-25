// The local engine companion (Stage 5b increment 4): a packaged, Torch-free engine that Chrome
// starts through native messaging (`yomiscan-engine.exe`, host com.yomiscan.engine). The host
// answers `status` and `start`; `start` returns the loopback port and a per-launch token of an
// engine it started detached (it stops itself after 15 idle minutes). The token stays in
// chrome.storage.session (memory only, extension pages only), never in content scripts.

export const NATIVE_HOST = 'com.yomiscan.engine';
export const COMPANION_KEY = 'companionConnection';
const STATUS_KEY = 'companionStatus';
const STATUS_TTL = 30_000;
export const CLIENT_HEADERS = {'X-YomiScan-Client': 'study-extension-v1'} as const;

export interface CompanionPrepare {state: 'starting' | 'running' | 'done' | 'failed'; loaded?: number; total?: number; error?: string}
export interface CompanionStatus {installed: boolean; ready: boolean; missing: string[]; version?: string; error?: string;
  /** Bytes still to download, where they come from, and the explicit download's progress. */
  bytes?: number; source?: string; prepare?: CompanionPrepare | null}
/** `started`: this call launched the engine, so its models may still be loading. */
export interface Connection {base: string; headers: Record<string, string>; companion: boolean; started?: boolean}

export interface NativeMessaging {sendNativeMessage(host: string, message: object): Promise<unknown>}
export interface SessionStore {get(key: string): Promise<Record<string, unknown>>; set(items: Record<string, unknown>): Promise<void>;
  remove(key: string): Promise<void>}

interface Deps {native: NativeMessaging; session: SessionStore; now: () => number}
/** Chrome's APIs, or null where native messaging does not exist (content scripts, tests). */
function chromeDeps(): Deps | null {
  const api = (globalThis as {chrome?: {runtime?: Partial<NativeMessaging>; storage?: {session?: SessionStore}}}).chrome;
  if (typeof api?.runtime?.sendNativeMessage !== 'function' || !api.storage?.session) return null;
  return {native: api.runtime as NativeMessaging, session: api.storage.session, now: Date.now};
}
const NO_NATIVE_MESSAGING = 'Native messaging is not available here';

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;
/** Chrome's errors when no host is registered for this extension. */
const NOT_INSTALLED = /native messaging host not found|specified native messaging host|forbidden/i;

/** Whether the companion is installed and has its models. Cached for 30 s: each check starts the host. */
export async function companionStatus(deps: Deps | null = chromeDeps(), fresh = false): Promise<CompanionStatus> {
  if (!deps) return {installed: false, ready: false, missing: []};
  const cached = (await deps.session.get(STATUS_KEY))[STATUS_KEY];
  if (!fresh && record(cached) && typeof cached.at === 'number' && deps.now() - cached.at < STATUS_TTL)
    return cached.status as CompanionStatus;
  let status: CompanionStatus;
  try {
    const reply = await deps.native.sendNativeMessage(NATIVE_HOST, {type: 'status'});
    if (!record(reply) || reply.ok !== true || !record(reply.models)) throw new Error(record(reply) && typeof reply.error === 'string' ? reply.error : 'Invalid companion reply');
    const missing = Array.isArray(reply.models.missing) ? reply.models.missing.filter((m): m is string => typeof m === 'string') : [];
    status = {installed: true, ready: reply.models.ready === true, missing, version: typeof reply.version === 'string' ? reply.version : undefined,
      bytes: typeof reply.models.bytes === 'number' ? reply.models.bytes : undefined,
      source: typeof reply.models.source === 'string' ? reply.models.source : undefined, prepare: parsePrepare(reply.prepare)};
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    status = NOT_INSTALLED.test(message) ? {installed: false, ready: false, missing: []} :
      {installed: true, ready: false, missing: [], error: message};
  }
  await deps.session.set({[STATUS_KEY]: {at: deps.now(), status}});
  return status;
}

export function parsePrepare(value: unknown): CompanionPrepare | null {
  if (!record(value) || !['starting', 'running', 'done', 'failed'].includes(value.state as string)) return null;
  const number = (key: string) => typeof value[key] === 'number' && Number.isFinite(value[key]) ? value[key] as number : undefined;
  return {state: value.state as CompanionPrepare['state'], loaded: number('loaded'), total: number('total'),
    error: typeof value.error === 'string' ? value.error.slice(0, 300) : undefined};
}

/** Start the explicit model download (after the user's click). */
export async function companionPrepare(deps: Deps | null = chromeDeps()): Promise<CompanionPrepare | null> {
  if (!deps) throw new Error(NO_NATIVE_MESSAGING);
  const reply = await deps.native.sendNativeMessage(NATIVE_HOST, {type: 'prepare'});
  if (!record(reply) || reply.ok !== true) throw new Error(`The local engine could not start the download: ${
    record(reply) && typeof reply.error === 'string' ? reply.error : 'no reply'}`);
  return parsePrepare(reply.prepare);
}

export function parseStart(reply: unknown): {port: number; token: string} {
  if (!record(reply) || reply.ok !== true) throw new Error(`The YomiScan local engine did not start: ${
    record(reply) && typeof reply.error === 'string' ? reply.error : 'no reply'}`);
  const {port, token} = reply;
  if (!Number.isInteger(port) || (port as number) < 1024 || (port as number) > 65535 || typeof token !== 'string' || !/^[\w-]{32,128}$/.test(token))
    throw new Error('The YomiScan local engine returned an invalid address');
  return {port: port as number, token};
}

/** The running companion's address and token; `restart` asks the host again (the engine may have gone idle). */
export async function companionConnection(restart = false, deps: Deps | null = chromeDeps()): Promise<Connection> {
  if (!deps) throw new Error(NO_NATIVE_MESSAGING);
  let saved = restart ? undefined : (await deps.session.get(COMPANION_KEY))[COMPANION_KEY], started = false;
  if (!record(saved)) {
    saved = parseStart(await deps.native.sendNativeMessage(NATIVE_HOST, {type: 'start'}));
    await deps.session.set({[COMPANION_KEY]: saved});
    started = true;
  }
  const {port, token} = parseStart({ok: true, ...(saved as Record<string, unknown>)});
  return {base: `http://127.0.0.1:${port}`, headers: {...CLIENT_HEADERS, 'X-YomiScan-Token': token}, companion: true, started};
}

export async function forgetCompanion(deps: Deps | null = chromeDeps()): Promise<void> {
  await deps?.session.remove(COMPANION_KEY);
}
