// First-run setup (Stage 5a): when no engine can serve Study or reading, the panel offers the
// browser models with their size and source, and downloads them only after an explicit click.
import type {EngineStatus} from '../engine/engine';
import type {EngineChoice, ResolvedEngine} from '../engine-mode';

export interface EngineState {choice: EngineChoice; mode: ResolvedEngine; status: EngineStatus | null; evicted: boolean; source: string}

const mb = (bytes: number) => Math.round(bytes / 1e6).toLocaleString('en-US');
const device = (status: EngineStatus) => status.backend === 'webgpu' ? 'your GPU' : 'your CPU';

/** "huggingface.co/owner/name" for the published host, otherwise the source's host. */
export function sourceLabel(source: string): string {
  const url = new URL(source), hf = url.hostname === 'huggingface.co' && url.pathname.match(/^\/([^/]+\/[^/]+)\/resolve\//);
  return hf ? `huggingface.co/${hf[1]}` : url.host;
}

export function setupLines(state: EngineState): {title: string; body: string; size: string; source: string} {
  const status = state.status!;
  return {
    title: state.evicted ? 'Download the reading models again' : 'Download the reading models',
    body: (state.evicted ? 'The reading models are no longer stored. Chrome can remove extension data when the disk is nearly full. ' : '') +
      'YomiScan finds, reads, looks up and translates Japanese with models that run inside Chrome: no Python, no server, no account. ' +
      'Download them once:',
    size: `${mb(status.missingBytes)} MB for this computer (runs on ${device(status)})`,
    source: `From ${sourceLabel(state.source)}. Each file is checked against a fingerprint built into YomiScan, then kept by Chrome ` +
      'for this extension only. Nothing you read is uploaded. Remove the models any time under Advanced → Browser engine.',
  };
}

export function progressLine(status: EngineStatus): string {
  const install = status.install;
  if (install.state === 'failed') return `Download stopped: ${install.error ?? 'unknown error'}`;
  if (install.state !== 'running') return '';
  if (!install.progress) return 'Starting the download…';
  const component = {detector: 'text detector', ocr: 'OCR', tokenizer: 'word splitter', dictionary: 'dictionary', translation: 'translator'}[
    status.required.find(c => c.id === install.progress!.component)?.kind ?? ''] ?? install.progress.component;
  const installed = status.required.filter(c => c.installed).reduce((n, c) => n + c.bytes, 0);
  const total = status.required.reduce((n, c) => n + c.bytes, 0);
  return `Downloading the ${component}: ${mb(installed + install.progress.loaded)} of ${mb(total)} MB`;
}

export class EngineSetup {
  readonly element = document.createElement('section');
  private title = document.createElement('strong');
  private body = document.createElement('p');
  private size = document.createElement('p');
  private source = document.createElement('small');
  private bar = document.createElement('progress');
  private progress = document.createElement('p');
  private download = document.createElement('button');
  private cancel = document.createElement('button');
  private later = document.createElement('button');
  private dismissed = false;
  private timer = 0;

  constructor(private ready: () => void) {
    this.element.className = 'setup';this.element.setAttribute('aria-label', 'Download the reading models');this.element.hidden = true;
    this.size.className = 'size';this.progress.setAttribute('role', 'status');this.bar.hidden = true;
    const licenses = document.createElement('small');
    licenses.textContent = 'Includes JMdict (EDRDG, CC BY-SA 4.0), UniDic (BSD), OPUS-MT, manga-ocr and a comic text detector (Apache-2.0).';
    const backend = document.createElement('small');
    backend.textContent = 'Already use the Python backend? Start it (uv run yomiscan-server) and YomiScan uses it until the models are downloaded.';
    this.download.dataset.purpose = 'engine-download';this.cancel.textContent = 'Cancel';this.later.textContent = 'Not now';this.cancel.hidden = true;
    this.download.addEventListener('click', () => {void this.request('install');});
    this.cancel.addEventListener('click', () => {void this.request('cancel');});
    this.later.addEventListener('click', () => {this.dismissed = true;this.hide();});
    this.element.append(this.title, this.body, this.size, this.download, this.cancel, this.later, this.bar, this.progress, this.source, licenses, backend);
  }

  /** Which engine serves the next request; shows this card when the answer is "setup". */
  async check(force = false): Promise<ResolvedEngine> {
    const reply = await chrome.runtime.sendMessage({type: 'engine-resolve'}).catch(() => null);
    if (!reply?.ok) throw new Error(reply?.error ?? 'YomiScan could not check its engines. Reload the extension.');
    const state = reply.data as EngineState;
    if (force) this.dismissed = false;
    if (state.mode === 'setup' && state.status && !this.dismissed) this.show(state);
    else if (state.status?.install.state !== 'running') this.hide();
    return state.mode;
  }

  private show(state: EngineState): void {
    const lines = setupLines(state);
    this.title.textContent = lines.title;this.body.textContent = lines.body;this.size.textContent = lines.size;this.source.textContent = lines.source;
    this.download.textContent = `Download (${mb(state.status!.missingBytes)} MB)`;
    this.element.hidden = false;this.render(state.status!);
    if (state.status!.install.state === 'running') this.timer = window.setTimeout(() => {void this.request('status');}, 700);
  }

  private hide(): void {clearTimeout(this.timer);this.element.hidden = true;}

  private render(status: EngineStatus): void {
    const running = status.install.state === 'running';
    this.download.hidden = running;this.cancel.hidden = !running;this.later.hidden = running;
    if (status.install.state === 'failed') this.download.textContent = 'Try again (finished files are kept)';
    this.bar.hidden = !running;
    const total = status.required.reduce((n, c) => n + c.bytes, 0);
    const installed = status.required.filter(c => c.installed).reduce((n, c) => n + c.bytes, 0);
    this.bar.max = total;this.bar.value = Math.min(total, installed + (status.install.progress?.loaded ?? 0));
    this.progress.textContent = progressLine(status);
  }

  private async request(operation: 'install' | 'cancel' | 'status'): Promise<void> {
    clearTimeout(this.timer);
    const reply = await chrome.runtime.sendMessage({type: 'engine', operation}).catch(() => null);
    if (!reply?.ok) {this.progress.textContent = reply?.error ?? 'Browser engine unavailable. Reload the extension.';return;}
    const status = reply.data as EngineStatus;
    if (status.required.every(c => c.installed) && status.install.state !== 'running') {
      this.hide();this.ready();return;
    }
    this.element.hidden = false;this.render(status);
    if (status.install.state === 'running') this.timer = window.setTimeout(() => {void this.request('status');}, 700);
  }
}
