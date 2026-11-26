// The Saved page (library.html): every saved word and sentence, search, CSV export, backup and
// restore. It opens the same IndexedDB database as the service worker (library-idb.ts).
import {furigana, hiragana} from './furigana';
import {Library, knownForm, knownText, sentencesAnki, sentencesCsv, wordsAnki, wordsCsv, type KnownWord, type SavedWord,
  type SentenceSummary} from './library';
import {IndexedDbStore} from './library-idb';
import {element, StudyPopup, styles} from './popup';

const PAGE = 200;
const library = new Library(new IndexedDbStore());
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const list = $('list'), status = $('status'), search = $<HTMLInputElement>('search'), more = $<HTMLButtonElement>('more');
const tabs = {words: $<HTMLButtonElement>('tab-words'), sentences: $<HTMLButtonElement>('tab-sentences'), known: $<HTMLButtonElement>('tab-known')};
let tab: keyof typeof tabs = 'words', shown = PAGE;
let words: SavedWord[] = [], sentences: SentenceSummary[] = [], known: KnownWord[] = [];
let knownSet = new Set<string>();

function say(message: string, error = false): void {
  status.textContent = message;
  status.classList.toggle('error', error);
}

const fold = (text: string) => hiragana(text.normalize('NFKC').toLowerCase());
const matches = (query: string, ...fields: (string | null)[]) => !query || fields.some(field => field && fold(field).includes(query));

function ruby(parent: HTMLElement, text: string, reading: string | null): void {
  for (const segment of furigana(text, reading)) {
    if (!segment.reading) {parent.append(segment.text); continue;}
    const node = document.createElement('ruby'), rt = document.createElement('rt');
    rt.textContent = segment.reading;
    node.append(segment.text, rt);
    parent.append(node);
  }
}

/** The sentence with the saved word's surface marked (first occurrence). */
function sentence(text: string, surface: string): HTMLElement {
  const line = element('p', undefined, 'sentence');
  line.lang = 'ja';
  const at = surface ? text.indexOf(surface) : -1;
  if (at < 0) line.textContent = text;
  else line.append(text.slice(0, at), element('mark', surface), text.slice(at + surface.length));
  return line;
}

const added = (iso: string) => `Added ${new Date(iso).toLocaleDateString()}`;

function wordItem(word: SavedWord): HTMLElement {
  const item = element('article', undefined, 'item');
  const head = element('div', undefined, 'head'), expression = element('span', undefined, 'expression');
  expression.lang = 'ja';
  ruby(expression, word.expression, word.reading);
  head.append(expression);
  if (word.reading && word.reading !== word.expression) {
    const reading = element('span', word.reading, 'reading'); reading.lang = 'ja'; head.append(reading);
  }
  if (word.parts_of_speech.length) head.append(element('span', word.parts_of_speech.join(', '), 'pos'));
  const meanings = element('ol');
  for (const line of word.meanings) meanings.append(element('li', line));
  if (!word.meanings.length) meanings.append(element('li', 'No dictionary meaning was found for this word.'));
  item.append(head, meanings, sentence(word.sentence, word.surface));
  if (word.sentence_translation) item.append(element('p', word.sentence_translation, 'translation'));
  const meta = element('div', undefined, 'meta'), remove = element('button', 'Delete');
  remove.setAttribute('aria-label', `Delete ${word.expression}`);
  remove.addEventListener('click', () => {
    void library.deleteWord(word.key).then(() => {
      words = words.filter(w => w.key !== word.key);
      say(`Deleted ${word.expression}.`); render();
    }, error => say(error.message, true));
  });
  meta.append(element('span', added(word.created_at)), element('span', undefined, 'spacer'));
  const form = knownForm(word.expression);
  if (form) meta.append(knownToggle(form));
  meta.append(remove);
  item.append(meta);
  return item;
}

/** Marks a word known or not known; the study card then folds it and leaves out its furigana. */
function knownToggle(form: string): HTMLButtonElement {
  const isKnown = knownSet.has(form);
  const button = element('button', isKnown ? '✓ Known' : 'Mark known');
  button.setAttribute('aria-pressed', String(isKnown));
  button.setAttribute('aria-label', isKnown ? `${form} is known; click to undo` : `Mark ${form} as known`);
  button.addEventListener('click', () => {
    button.disabled = true;
    void library.setKnown(form, !isKnown).then(async () => {
      known = await library.knownWords(); knownSet = new Set(known.map(k => k.form));
      say(isKnown ? `${form} is no longer marked known.` : `Marked ${form} as known.`); render();
    }, error => {say(error.message, true); button.disabled = false;});
  });
  return button;
}

function knownItem(word: KnownWord): HTMLElement {
  const item = element('article', undefined, 'item known');
  const form = element('span', word.form, 'expression'); form.lang = 'ja';
  const remove = element('button', 'Not known');
  remove.setAttribute('aria-label', `Remove ${word.form} from your known words`);
  remove.addEventListener('click', () => {
    void library.setKnown(word.form, false).then(() => {
      known = known.filter(k => k.form !== word.form); knownSet.delete(word.form);
      say(`${word.form} is no longer marked known.`); render();
    }, error => say(error.message, true));
  });
  item.append(form, element('span', added(word.created_at), 'added'), element('span', undefined, 'spacer'), remove);
  return item;
}

function sentenceItem(saved: SentenceSummary): HTMLElement {
  const item = element('article', undefined, 'item');
  const line = element('p', saved.original_text, 'sentence'); line.lang = 'ja';
  item.append(line);
  if (saved.translation) item.append(element('p', saved.translation, 'translation'));
  const meta = element('div', undefined, 'meta'), open = element('button', 'Open'), remove = element('button', 'Delete');
  open.setAttribute('aria-label', 'Open this sentence in a study card');
  open.addEventListener('click', () => {void openSentence(saved.id, open);});
  remove.setAttribute('aria-label', 'Delete this sentence');
  remove.addEventListener('click', () => {
    void library.deleteSentence(saved.id).then(() => {
      sentences = sentences.filter(s => s.id !== saved.id);
      say('Deleted the sentence.'); render();
    }, error => say(error.message, true));
  });
  meta.append(element('span', added(saved.created_at)), element('span', undefined, 'spacer'), open, remove);
  item.append(meta);
  return item;
}

let card: {host: HTMLElement; popup: StudyPopup} | null = null;
function closeCard(): void {card?.popup.dispose(); card?.host.remove(); card = null;}

/** The saved analysis in the same study card the reader uses. */
async function openSentence(id: string, from: HTMLElement): Promise<void> {
  const saved = await library.sentence(id);
  if (!saved) {say('This sentence is no longer saved.', true); return;}
  closeCard();
  const host = element('div'), root = host.attachShadow({mode: 'open'});
  host.style.cssText = 'position:fixed;z-index:10;display:block';
  root.append(element('style', styles));
  document.body.append(host);
  const rect = from.getBoundingClientRect();
  const popup = new StudyPopup(host, root, {x: rect.x, y: rect.y, width: rect.width, height: rect.height}, closeCard);
  card = {host, popup};
  popup.show(saved.analysis);
}

function render(): void {
  const query = fold(search.value.trim());
  const items: (SavedWord | SentenceSummary | KnownWord)[] = tab === 'words'
    ? words.filter(w => matches(query, w.expression, w.reading, w.surface, w.sentence, w.sentence_translation, ...w.meanings))
    : tab === 'sentences' ? sentences.filter(s => matches(query, s.original_text, s.translation))
    : known.filter(k => matches(query, k.form));
  const count = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
  $('counts').textContent = `${count(words.length, 'word', 'words')} · ${count(sentences.length, 'sentence', 'sentences')} · `
    + `${count(known.length, 'known word', 'known words')}`;
  for (const [name, button] of Object.entries(tabs)) button.setAttribute('aria-selected', String(name === tab));
  // The toolbar follows the tab: a known-word list is plain text, imported and exported one word per line.
  $('export').textContent = tab === 'known' ? 'Export list' : 'Export CSV';
  $('anki').hidden = tab === 'known';
  $('import-known').hidden = tab !== 'known';
  list.setAttribute('aria-labelledby', tabs[tab].id);
  list.replaceChildren();
  if (!items.length) {
    list.append(element('p', query ? 'Nothing matches this search.' : tab === 'words'
      ? 'No saved words yet. In a study card, click ☆ Save word next to a word.'
      : tab === 'sentences' ? 'No saved sentences yet. In a study card, click Save sentence.'
      : 'No known words yet. In a study card, click Mark known next to a word, or use Import list: a text or CSV file '
        + 'with one word per line (the first column is used; lines starting with # are skipped).', 'empty'));
  }
  for (const item of items.slice(0, shown))
    list.append(tab === 'words' ? wordItem(item as SavedWord) : tab === 'sentences' ? sentenceItem(item as SentenceSummary)
      : knownItem(item as KnownWord));
  more.hidden = items.length <= shown;
  more.textContent = `Show more (${items.length - shown} left)`;
}

async function load(): Promise<void> {
  const moved = await library.migrateHistory({get: key => chrome.storage.local.get(key), remove: key => chrome.storage.local.remove(key)});
  if (moved?.moved) say(`Your ${moved.moved} Study history ${moved.moved === 1 ? 'entry is' : 'entries are'} now saved sentences.`);
  [words, sentences, known] = await Promise.all([library.words(), library.sentences(), library.knownWords()]);
  knownSet = new Set(known.map(k => k.form));
  render();
}

function download(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], {type}));
  const link = element('a'); link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const stamp = () => new Date().toISOString().slice(0, 10);

for (const [name, button] of Object.entries(tabs)) button.addEventListener('click', () => {tab = name as typeof tab; shown = PAGE; render();});
search.addEventListener('input', () => {shown = PAGE; render();});
more.addEventListener('click', () => {shown += PAGE; render();});
$('export').addEventListener('click', () => {
  if (tab === 'known') {
    download(`yomiscan-known-${stamp()}.txt`, knownText(known), 'text/plain;charset=utf-8');
    say(`Exported ${known.length} known words, one per line.`);
    return;
  }
  if (tab === 'words') download(`yomiscan-words-${stamp()}.csv`, wordsCsv(words), 'text/csv;charset=utf-8');
  else download(`yomiscan-sentences-${stamp()}.csv`, sentencesCsv(sentences), 'text/csv;charset=utf-8');
  say(`Exported ${tab === 'words' ? words.length + ' words' : sentences.length + ' sentences'} as CSV.`);
});
$('anki').addEventListener('click', () => {
  if (tab === 'words') download(`yomiscan-anki-words-${stamp()}.csv`, wordsAnki(words), 'text/csv;charset=utf-8');
  else download(`yomiscan-anki-sentences-${stamp()}.csv`, sentencesAnki(sentences), 'text/csv;charset=utf-8');
  say(`Exported ${tab === 'words' ? words.length + ' words' : sentences.length + ' sentences'} for Anki. In Anki, choose ` +
    'File > Import, pick this file, then choose a note type and deck; columns go to fields with the same name.');
});
$('backup').addEventListener('click', () => {
  void library.backup().then(data => {
    download(`yomiscan-backup-${stamp()}.json`, JSON.stringify(data, null, 1), 'application/json');
    say(`Backed up ${data.words.length} words, ${data.sentences.length} sentences and ${data.known.length} known words.`);
  }, error => say(error.message, true));
});
$<HTMLInputElement>('restore').addEventListener('change', event => {
  const input = event.target as HTMLInputElement, file = input.files?.[0];
  input.value = '';
  if (!file) return;
  void file.text().then(text => {
    let data: unknown;
    try {data = JSON.parse(text);} catch {throw new Error('This file is not a YomiScan backup (it is not JSON).');}
    return library.restore(data);
  }).then(async added => {
    say(`Restored ${added.words} words, ${added.sentences} sentences and ${added.known} known words (items you already had were kept).`);
    await load();
  }, error => say(error.message, true));
});
$<HTMLInputElement>('import-known-file').addEventListener('change', event => {
  const input = event.target as HTMLInputElement, file = input.files?.[0];
  input.value = '';
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {say('This list is over 8 MB; split it into smaller files.', true); return;}
  void file.text().then(text => library.importKnown(text)).then(async result => {
    const n = (count: number, one: string, many: string) => `${count.toLocaleString()} ${count === 1 ? one : many}`;
    say(`Imported ${n(result.added, 'known word', 'known words')}` + (result.already ? `; ${n(result.already, 'was', 'were')} already known` : '')
      + (result.skipped ? `; skipped ${n(result.skipped, 'line that is', 'lines that are')} not a Japanese word` : '') + '.');
    await load();
  }, error => say(error.message, true));
});
$('clear').addEventListener('click', () => {
  if (!confirm(`Delete all ${words.length} saved words, ${sentences.length} saved sentences and ${known.length} known words? `
    + 'This cannot be undone. Use Back up all first to keep a copy.')) return;
  void library.clear().then(async () => {say('Deleted everything saved.'); await load();}, error => say(error.message, true));
});
document.addEventListener('keydown', event => {if (event.key === 'Escape') closeCard();});
// Words saved in a reader tab appear when you come back to this page.
document.addEventListener('visibilitychange', () => {if (!document.hidden) void load().catch(error => say(error.message, true));});

void load().catch(error => say(error.message, true));
