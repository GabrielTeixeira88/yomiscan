/**
 * The local backend address. Only loopback with a user-chosen port is ever used.
 *
 * The default is not 8765, which is AnkiConnect's default port; many Japanese
 * learners run Anki and YomiScan together. Change it in Setup & readiness and
 * start the backend with the same `--port`.
 */
export const DEFAULT_BACKEND_PORT = 47615;
export const BACKEND_PORT_KEY = "backendPort";

interface PortStorage { get(key: string): Promise<Record<string, unknown>> }

export function validBackendPort(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 1024 && (value as number) <= 65535;
}

export function backendOrigin(port: number): string {
  if (!validBackendPort(port)) throw new Error("Backend port must be an integer from 1024 to 65535");
  return `http://127.0.0.1:${port}`;
}

/** Accept only an origin produced by backendOrigin (e.g., received over an extension port). */
export function parseBackendOrigin(value: unknown): string {
  const match = typeof value === "string" ? /^http:\/\/127\.0\.0\.1:(\d{4,5})$/.exec(value) : null;
  if (!match || !validBackendPort(Number(match[1]))) throw new Error("Invalid local backend address");
  return value as string;
}

function defaultStorage(): PortStorage | undefined {
  return (globalThis as {chrome?: {storage?: {local?: PortStorage}}}).chrome?.storage?.local;
}

export async function backendPort(storage: PortStorage | undefined = defaultStorage()): Promise<number> {
  if (!storage) return DEFAULT_BACKEND_PORT;
  const stored = (await storage.get(BACKEND_PORT_KEY))[BACKEND_PORT_KEY];
  return validBackendPort(stored) ? stored : DEFAULT_BACKEND_PORT;
}

export async function backendBase(storage?: PortStorage): Promise<string> {
  return backendOrigin(await backendPort(storage));
}
