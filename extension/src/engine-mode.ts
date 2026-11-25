// Which engine serves Study and reading (Stage 5a, 5b). Unless the user picks one, the choice is
// Automatic: the local engine companion when installed with its models, then the browser engine
// once its models are installed, then a running developer backend, otherwise first-run setup.
// "local" means the companion when it is ready, else the developer backend (local.ts).
import host from './engine/artifact-host.json';

export type EngineMode = 'local' | 'browser';
export type EngineChoice = 'auto' | EngineMode;
/** 'setup': nothing can serve a request until the models are downloaded (or the backend is started). */
export type ResolvedEngine = EngineMode | 'setup';
export const ENGINE_MODE_KEY = 'engineMode';
export const ENGINE_SOURCE_KEY = 'engineArtifactSource';
/** Set after a complete install. If the models later disappear, setup explains that Chrome removed them. */
export const ENGINE_INSTALLED_KEY = 'engineModelsInstalled';
/** The published model folder: an immutable Hugging Face commit (scripts/publish_browser_artifacts.py). */
export const ENGINE_HOST = host as {repository: string | null; revision: string | null; base: string};
export const DEFAULT_ENGINE_SOURCE = ENGINE_HOST.base;

export const parseEngineChoice = (value: unknown): EngineChoice => value === 'browser' || value === 'local' ? value : 'auto';

export async function engineChoice(): Promise<EngineChoice> {
  return parseEngineChoice((await chrome.storage.local.get(ENGINE_MODE_KEY))[ENGINE_MODE_KEY]);
}

export async function setEngineChoice(choice: EngineChoice): Promise<void> {
  if (choice === 'auto') await chrome.storage.local.remove(ENGINE_MODE_KEY);
  else await chrome.storage.local.set({[ENGINE_MODE_KEY]: choice});
}

/** Automatic prefers the local engine companion when it is installed with its models (Stage 5b,
 * owner decision: GPU and the pixel renderer), then installed browser models, then a running
 * developer backend. An explicit choice is kept, except that the browser engine without its models
 * needs setup. Checks run only when needed. */
export async function resolveEngine(choice: EngineChoice, browserReady: () => Promise<boolean>,
  backendRunning: () => Promise<boolean>, companionReady: () => Promise<boolean> = async () => false): Promise<ResolvedEngine> {
  if (choice === 'local') return 'local';
  if (choice === 'auto' && await companionReady()) return 'local';
  if (await browserReady()) return 'browser';
  if (choice === 'browser') return 'setup';
  return await backendRunning() ? 'local' : 'setup';
}

/** The model source: a developer override (Advanced → Browser engine) or the published host. */
export async function engineSource(): Promise<string> {
  const stored = (await chrome.storage.local.get(ENGINE_SOURCE_KEY))[ENGINE_SOURCE_KEY];
  return typeof stored === 'string' && /^https?:\/\/[^\s]+$/.test(stored) ? stored : DEFAULT_ENGINE_SOURCE;
}

export const SETUP_NEEDED = 'YomiScan needs its reading models. Click the YomiScan toolbar icon and choose Download ' +
  '(once, about 550 MB), or start the local backend.';
