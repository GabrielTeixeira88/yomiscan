// Which engine serves Study and Read Chapter: the Python backend ("local") or the in-browser
// engine (Stage 5a). Local stays the default until first-run setup can download the models.
export type EngineMode = 'local' | 'browser';
export const ENGINE_MODE_KEY = 'engineMode';

export const parseEngineMode = (value: unknown): EngineMode => value === 'browser' ? 'browser' : 'local';

export async function engineMode(): Promise<EngineMode> {
  return parseEngineMode((await chrome.storage.local.get(ENGINE_MODE_KEY))[ENGINE_MODE_KEY]);
}

export async function setEngineMode(mode: EngineMode): Promise<void> {
  await chrome.storage.local.set({[ENGINE_MODE_KEY]: mode});
}
