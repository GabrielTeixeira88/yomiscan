// Setup for the browser engine (Stage 5a preview): shows the device path, the pinned
// components this device needs and their sizes, and installs them only on an explicit click.
import type {EngineStatus} from '../engine/engine';

export const ENGINE_SOURCE_KEY = 'engineArtifactSource';
export const DEFAULT_ENGINE_SOURCE = 'http://127.0.0.1:47620/';
const mib = (bytes: number) => (bytes / 2 ** 20).toFixed(0);

export function engineSummary(status: EngineStatus): string {
  const total = status.required.reduce((n, c) => n + c.bytes, 0), missing = status.required.filter(c => !c.installed);
  const device = status.backend === 'webgpu' ? 'GPU (WebGPU)' : `CPU (WASM, ${status.threads} thread${status.threads === 1 ? '' : 's'})`;
  const lines = [`Device path: ${device}${status.isolated ? '' : ' · not cross-origin isolated: CPU runs single-threaded'}`,
    ...status.required.map(c => `${c.id} (${c.variant}) · ${mib(c.bytes)} MiB · ${c.installed ? 'installed' : 'not installed'} · ${c.license}`),
    missing.length ? `Download needed: ${mib(missing.reduce((n, c) => n + c.bytes, 0))} of ${mib(total)} MiB, stored by Chrome for this extension.` :
      `All ${mib(total)} MiB installed${status.loaded ? ' and loaded' : ''}.`];
  const install = status.install;
  if (install.state === 'running' && install.progress)
    lines.push(`Installing ${install.progress.component}: ${mib(install.progress.loaded)} / ${mib(install.progress.total)} MiB`);
  else if (install.state === 'failed') lines.push(`Installation failed: ${install.error ?? 'unknown error'}`);
  return lines.join('\n');
}

export class EngineControls {
  readonly element = document.createElement('details');
  private output = document.createElement('p');
  private source = document.createElement('input');
  private timer = 0;
  constructor() {
    const summary = document.createElement('summary');summary.textContent = 'Browser engine (preview)';
    const help = document.createElement('small');
    help.textContent = 'Runs text detection, OCR, word analysis (JMdict, grammar notes) and OPUS-MT translation inside Chrome, without the Python backend. Study and Read Chapter switch to it in a later preview. Each file is checked against a SHA-256 pinned in the extension.';
    const label = document.createElement('label');label.textContent = 'Model source ';
    Object.assign(this.source, {type: 'url', value: DEFAULT_ENGINE_SOURCE});this.source.setAttribute('aria-label', 'Browser engine model source URL');
    label.append(this.source);
    const button = (text: string, operation: string) => {const b = document.createElement('button');b.textContent = text;b.onclick = () => {void this.request(operation);};return b;};
    this.output.setAttribute('role', 'status');this.output.style.whiteSpace = 'pre-wrap';
    this.element.append(summary, help, label, button('Install Models', 'install'), button('Cancel', 'cancel'),
      button('Remove Models', 'remove'), button('Check', 'status'), this.output);
    this.element.addEventListener('toggle', () => {
      if (this.element.open) {
        void chrome.storage.local.get(ENGINE_SOURCE_KEY).then(v => {if (typeof v[ENGINE_SOURCE_KEY] === 'string') this.source.value = v[ENGINE_SOURCE_KEY];});
        void this.request('status');
      } else clearTimeout(this.timer);
    });
  }
  private async request(operation: string): Promise<void> {
    clearTimeout(this.timer);
    if (operation === 'install') {
      try {new URL(this.source.value);} catch {this.output.textContent = 'Enter the model source as a full http(s) URL.';return;}
      await chrome.storage.local.set({[ENGINE_SOURCE_KEY]: this.source.value});
    }
    if (operation === 'remove' && !confirm('Remove the browser engine models from this browser? They can be installed again later.')) return;
    const reply = await chrome.runtime.sendMessage({type: 'engine', operation, base: this.source.value}).catch(() => null);
    if (!reply?.ok) {this.output.textContent = reply?.error ?? 'Browser engine unavailable. Reload the extension.';return;}
    const status = reply.data as EngineStatus;
    this.output.textContent = engineSummary(status);
    // Poll while installing; the panel only reads status, the download runs in the engine.
    if (status.install.state === 'running' && this.element.open) this.timer = window.setTimeout(() => {void this.request('status');}, 700);
  }
}
