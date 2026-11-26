// About & licenses (about.html): the version, the downloaded models with their licenses (from the
// pinned artifact manifest the engine uses), and the packaged third-party notices.
import manifest from './engine/artifact-manifest.json';

document.getElementById('version')!.textContent = chrome.runtime.getManifest().version;

const KIND: Record<string, string> = {detector: 'Text detector', ocr: 'OCR', dictionary: 'Dictionary (JMdict)', translation: 'Translation'};
const rows = document.getElementById('models')!;
for (const component of manifest.components) {
  const row = document.createElement('tr');
  const bytes = component.files.reduce((total, file) => total + file.bytes, 0);
  const variant = component.kind === 'ocr' ? ` (${component.variant === 'q4' ? 'graphics card' : 'processor'})` : '';
  for (const text of [KIND[component.kind] + variant, component.license, component.source, `${Math.round(bytes / 1e6)} MB`]) {
    const cell = document.createElement('td');
    cell.textContent = text;
    row.append(cell);
  }
  rows.append(row);
}

const notices = document.getElementById('notices')!;
void fetch(chrome.runtime.getURL('THIRD-PARTY-NOTICES.txt')).then(response => {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}).then(text => {notices.textContent = text;}, error => {notices.textContent = `The license file could not be read: ${error.message}`;});
