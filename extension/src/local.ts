// The "local" engine's address for the service worker (Stage 5b increment 4): the companion when
// it is installed and has its models, otherwise the developer backend on the port set in Setup &
// readiness. Every backend request from the service worker goes through localFetch.
import {backendBase} from './backend';
import {CLIENT_HEADERS, companionConnection, companionStatus, forgetCompanion, type Connection} from './companion';

export async function localConnection({verify = false}: {verify?: boolean} = {}): Promise<Connection> {
  const status = await companionStatus();
  if (!status.installed || !status.ready) return {base: await backendBase(), headers: {...CLIENT_HEADERS}, companion: false};
  const connection = await companionConnection();
  if (connection.started) return initialized(connection);
  if (!verify || await answers(connection)) return connection;
  return initialized(await companionConnection(true));  // it stopped (idle or closed): launch it again
}

/** A just-launched engine answers readiness at once but loads its models first (a few seconds):
 * wait until initialization is over, so the first real request is not refused. */
async function initialized(connection: Connection, timeout = 90_000): Promise<Connection> {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try {
      const response = await fetch(connection.base + '/api/v1/readiness', {headers: connection.headers, signal: AbortSignal.timeout(5000),
        credentials: 'omit', redirect: 'error', cache: 'no-store'});
      if (response.ok && (await response.json() as {initialization?: unknown}).initialization !== 'initializing') return connection;
    } catch {
      // still starting
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('The YomiScan local engine is still loading its models. Try again in a moment.');
}

async function answers(connection: Connection): Promise<boolean> {
  try {
    const response = await fetch(connection.base + '/api/v1/readiness', {headers: connection.headers, signal: AbortSignal.timeout(1500),
      credentials: 'omit', redirect: 'error', cache: 'no-store'});
    return response.ok;
  } catch {
    return false;  // not answering is the expected sign of an engine that exited
  }
}

/** fetch() against the local engine with its headers. A companion that stopped since the last
 * request (network error) or restarted (401: a new token) is launched again and asked once more.
 * `timeout` (ms) starts when the request is sent, after any engine launch and model load. */
export async function localFetch(path: string, {timeout, ...init}: RequestInit & {timeout?: number} = {}): Promise<Response> {
  const connection = await localConnection();
  const request = (target: Connection) => {
    const limit = timeout === undefined ? init.signal : init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout);
    return fetch(target.base + path, {...init, signal: limit, headers: {...target.headers, ...(init.headers as Record<string, string> ?? {})},
      credentials: 'omit', redirect: 'error', cache: 'no-store'});
  };
  try {
    const response = await request(connection);
    if (response.status !== 401 || !connection.companion) return response;
  } catch (error) {
    if (!connection.companion || !(error instanceof TypeError)) throw error;
  }
  await forgetCompanion();
  return request(await initialized(await companionConnection(true)));
}

/** The message for an unreachable local engine. */
export async function localUnreachable(): Promise<string> {
  const connection = await localConnection();
  return connection.companion ? 'Cannot reach YomiScan. The local engine did not answer; try again.' :
    `Cannot reach YomiScan. Start the local server at ${connection.base.replace('http://', '')} and try again.`;
}
