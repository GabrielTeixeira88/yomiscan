// Advanced → Browser engine (Stage 5a): the engine choice, the device path, the pinned components
// this device needs with their sizes and storage, and install/remove on an explicit click.
import type {EngineStatus} from '../engine/engine';
import {DEFAULT_ENGINE_SOURCE, ENGINE_SOURCE_KEY, engineChoice, setEngineChoice} from '../engine-mode';
import type {CompanionStatus} from '../companion';

const mib = (bytes: number) => (bytes / 2 ** 20).toFixed(0);

export function engineSummary(status: EngineStatus): string {
  const total = status.required.reduce((n, c) => n + c.bytes, 0), missing = status.required.filter(c => !c.installed);
  const device = status.backend === 'webgpu' ? 'GPU (WebGPU)' : `CPU (WASM, ${status.threads} thread${status.threads === 1 ? '' : 's'})`;
  const lines = [`Device path: ${device}${status.isolated ? '' : ' · not cross-origin isolated: CPU runs single-threaded'}`,
    ...status.required.map(c => `${c.id} (${c.variant}) · ${mib(c.bytes)} MiB · ${c.installed ? 'installed' : 'not installed'} · ${c.license}`),
    missing.length ? `Download needed: ${mib(missing.reduce((n, c) => n + c.bytes, 0))} of ${mib(total)} MiB, stored by Chrome for this extension.` :
      `All ${mib(total)} MiB installed${status.loaded ? ' and loaded' : ''}.`];
  if (status.storage) lines.push(`Chrome storage for YomiScan: ${mib(status.storage.usage)} MiB used, ${mib(Math.max(0, status.storage.quota - status.storage.usage))} MiB available` +
    (status.persisted ? ' · protected from automatic clearing' : ''));
  const install = status.install;
  if (install.state === 'running' && install.progress)
    lines.push(`Installing ${install.progress.component}: ${mib(install.progress.loaded)} / ${mib(install.progress.total)} MiB`);
  else if (install.state === 'failed') lines.push(`Installation failed: ${install.error ?? 'unknown error'}`);
  return lines.join('\n');
}

/** The local engine companion (Stage 5b): installed, ready, or what it still needs. */
export function companionSummary(status: CompanionStatus, extensionId?: string): string {
  if (!status.installed) return 'Local engine: not installed.' +
    (extensionId ? ` To use it, install YomiScan Engine; its installer asks for this extension's ID: ${extensionId}` : '');
  const name = `Local engine${status.version ? ` ${status.version}` : ''}`;
  if (status.error) return `${name}: installed, but it did not answer (${status.error}).`;
  if (!status.ready) return `${name}: installed; missing ${status.missing.join(', ')}. Run yomiscan-engine.exe --prepare, then check again.`;
  return `${name}: installed with its models. Automatic uses it first.`;
}

export class EngineControls {
  readonly element = document.createElement('details');
  private output = document.createElement('p');
  private source = document.createElement('input');
  private timer = 0;
  private radios: HTMLInputElement[] = [];
  constructor() {
    const summary = document.createElement('summary');summary.textContent = 'Browser engine';
    const help = document.createElement('small');
    help.textContent = 'Runs text detection, OCR, word analysis (JMdict, grammar notes) and OPUS-MT translation inside Chrome, without the Python backend. Each model file is checked against a SHA-256 pinned in the extension.';
    const label = document.createElement('label');label.textContent = 'Model source (change only for development) ';
    Object.assign(this.source, {type: 'url', value: DEFAULT_ENGINE_SOURCE});this.source.setAttribute('aria-label', 'Browser engine model source URL');
    label.append(this.source);
    const button = (text: string, operation: string) => {const b = document.createElement('button');b.textContent = text;b.onclick = () => {void this.request(operation);};return b;};
    this.output.setAttribute('role', 'status');this.output.style.whiteSpace = 'pre-wrap';
    // Which engine serves Select Text, Edit text, Read Chapter and Translate Chapter.
    const choice = document.createElement('fieldset'), legend = document.createElement('legend');
    legend.textContent = 'Engine for Study and reading';choice.append(legend);
    for (const [value, text] of [['auto', 'Automatic: the local engine when installed, then the browser engine, then a running local backend'],
      ['local', 'Local engine (or the Python backend when it is not installed)'], ['browser', 'Browser engine']] as const) {
      const row = document.createElement('label'), input = document.createElement('input');
      input.type = 'radio';input.name = 'yomiscan-engine';input.value = value;input.dataset.purpose = 'engine-' + value;
      input.addEventListener('change', () => {if (input.checked) void setEngineChoice(value);});
      this.radios.push(input);row.style.display = 'block';row.append(input, document.createTextNode(' ' + text));choice.append(row);
    }
    const note = document.createElement('small');
    note.textContent = 'Browser engine: English only; translation settings and glossaries apply to the local backend. Translate Chapter shows English as text over each bubble.';
    choice.append(note);
    this.element.append(summary, help, choice, label, button('Install Models', 'install'), button('Cancel', 'cancel'),
      button('Remove Models', 'remove'), button('Check', 'status'), this.output);
    this.element.addEventListener('toggle', () => {
      if (this.element.open) {
        void engineChoice().then(choice => this.radios.forEach(r => {r.checked = r.value === choice;}));
        void chrome.storage.local.get(ENGINE_SOURCE_KEY).then(v => {if (typeof v[ENGINE_SOURCE_KEY] === 'string') this.source.value = v[ENGINE_SOURCE_KEY];});
        void this.request('status');
      } else clearTimeout(this.timer);
    });
  }
  private async request(operation: string): Promise<void> {
    clearTimeout(this.timer);
    if (operation === 'install') {
      try {new URL(this.source.value);} catch {this.output.textContent = 'Enter the model source as a full http(s) URL.';return;}
      // Only a development override is stored; the default follows the published host across updates.
      if (this.source.value === DEFAULT_ENGINE_SOURCE) await chrome.storage.local.remove(ENGINE_SOURCE_KEY);
      else await chrome.storage.local.set({[ENGINE_SOURCE_KEY]: this.source.value});
    }
    if (operation === 'remove' && !confirm('Remove the browser engine models from this browser? They can be installed again later.')) return;
    const [reply, companion] = await Promise.all([
      chrome.runtime.sendMessage({type: 'engine', operation, base: this.source.value}).catch(() => null),
      operation === 'status' ? chrome.runtime.sendMessage({type: 'companion-status'}).catch(() => null) : Promise.resolve(null)]);
    const companionLine = companion?.ok ? `${companionSummary(companion.data as CompanionStatus, chrome.runtime.id)}\n` : '';
    if (!reply?.ok) {this.output.textContent = companionLine + (reply?.error ?? 'Browser engine unavailable. Reload the extension.');return;}
    const status = reply.data as EngineStatus;
    this.output.textContent = companionLine + engineSummary(status);
    // Poll while installing; the panel only reads status, the download runs in the engine.
    if (status.install.state === 'running' && this.element.open) this.timer = window.setTimeout(() => {void this.request('status');}, 700);
  }
}
