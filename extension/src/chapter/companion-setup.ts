// First start of the local engine companion (Stage 5b increment 5): when it is installed but its
// models and dictionary are not, the panel offers them with size and source, and downloads them
// only after an explicit click. The download runs in the engine's own process, outside Chrome.
import type {CompanionStatus} from '../companion';

const mb = (bytes: number) => Math.round(bytes / 1e6).toLocaleString('en-US');

export function companionSetupLines(status: CompanionStatus): {title: string; body: string; size: string; source: string} {
  return {
    title: 'Download the local engine\'s models',
    body: 'The YomiScan local engine is installed. It reads and translates outside Chrome (using your GPU when it can) ' +
      'and needs its reading models and dictionary once:',
    size: `${mb(status.bytes ?? 0)} MB, saved in your user folder (AppData\\Local\\YomiScan)`,
    source: `From ${status.source ?? 'the pinned model host'}. Each file is checked against a fingerprint built into the ` +
      'engine. Nothing you read is uploaded.',
  };
}

export function companionProgress(status: CompanionStatus): string {
  const prepare = status.prepare;
  if (!prepare) return '';
  if (prepare.state === 'failed') return `Download stopped: ${prepare.error ?? 'unknown error'}`;
  if (prepare.state === 'starting' || prepare.total === undefined) return 'Starting the download…';
  if (prepare.state === 'done') return 'Download finished.';
  return `Downloading the local engine's models: ${mb(prepare.loaded ?? 0)} of ${mb(prepare.total)} MB`;
}

const downloading = (status: CompanionStatus) => status.prepare?.state === 'starting' || status.prepare?.state === 'running';

export class CompanionSetup {
  readonly element = document.createElement('section');
  private title = document.createElement('strong');
  private body = document.createElement('p');
  private size = document.createElement('p');
  private source = document.createElement('small');
  private bar = document.createElement('progress');
  private progress = document.createElement('p');
  private download = document.createElement('button');
  private later = document.createElement('button');
  private dismissed = false;
  private timer = 0;

  constructor(private ready: () => void) {
    this.element.className = 'setup';this.element.setAttribute('aria-label', 'Download the local engine\'s models');this.element.hidden = true;
    this.size.className = 'size';this.progress.setAttribute('role', 'status');this.bar.hidden = true;
    const licenses = document.createElement('small');
    licenses.textContent = 'Includes JMdict (EDRDG, CC BY-SA 4.0), OPUS-MT, manga-ocr and a comic text detector (Apache-2.0).';
    this.download.dataset.purpose = 'companion-download';this.later.textContent = 'Not now';
    this.download.addEventListener('click', () => {void this.start();});
    this.later.addEventListener('click', () => {this.dismissed = true;this.hide();});
    this.element.append(this.title, this.body, this.size, this.download, this.later, this.bar, this.progress, this.source, licenses);
  }

  /** Shows the card when the companion is installed without its models; true while it is shown. */
  async check(force = false): Promise<boolean> {
    const reply = await chrome.runtime.sendMessage({type: 'companion-status'}).catch(() => null);
    const status = reply?.ok ? reply.data as CompanionStatus : null;
    if (force) this.dismissed = false;
    if (!status?.installed || status.ready || (this.dismissed && !downloading(status))) {this.hide();return false;}
    this.show(status);
    return true;
  }

  private show(status: CompanionStatus): void {
    const lines = companionSetupLines(status);
    this.title.textContent = lines.title;this.body.textContent = lines.body;this.size.textContent = lines.size;this.source.textContent = lines.source;
    this.download.textContent = status.prepare?.state === 'failed' ? 'Try again (finished files are kept)' : `Download (${mb(status.bytes ?? 0)} MB)`;
    this.element.hidden = false;this.render(status);
  }

  private hide(): void {clearTimeout(this.timer);this.element.hidden = true;}

  private render(status: CompanionStatus): void {
    const running = downloading(status);
    this.download.hidden = running;this.later.hidden = running;this.bar.hidden = !running;
    this.bar.max = status.prepare?.total ?? 1;this.bar.value = Math.min(this.bar.max, status.prepare?.loaded ?? 0);
    this.progress.textContent = status.error ? `The local engine did not answer: ${status.error}` : companionProgress(status);
    clearTimeout(this.timer);
    if (running) this.timer = window.setTimeout(() => {void this.poll();}, 1000);
  }

  private async start(): Promise<void> {
    this.download.hidden = true;this.later.hidden = true;this.progress.textContent = 'Starting the download…';
    const reply = await chrome.runtime.sendMessage({type: 'companion-prepare'}).catch(() => null);
    if (!reply?.ok) {this.download.hidden = false;this.later.hidden = false;
      this.progress.textContent = reply?.error ?? 'The local engine could not start the download.';return;}
    await this.poll();
  }

  private async poll(): Promise<void> {
    const reply = await chrome.runtime.sendMessage({type: 'companion-status', fresh: true}).catch(() => null);
    if (!reply?.ok) {this.progress.textContent = reply?.error ?? 'Local engine status unavailable.';return;}
    const status = reply.data as CompanionStatus;
    if (status.ready) {this.hide();this.ready();return;}
    this.show(status);
  }
}
