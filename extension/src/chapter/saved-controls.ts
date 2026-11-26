import type {Counts} from '../library';
/** The panel's way to the Saved page (library.html), with how much is saved. */
export class SavedControls {
  readonly element = document.createElement('div');
  private summary = document.createElement('small');

  constructor() {
    const open = document.createElement('button');
    open.textContent = 'Open Saved';
    open.addEventListener('click', () => {
      void chrome.runtime.sendMessage({type: 'library', operation: 'open'}).then(reply => {
        if (!reply?.ok) this.summary.textContent = reply?.error ?? 'Could not open the Saved page. Reload the extension.';
      });
    });
    this.summary.style.display = 'block';
    // Getting started and About & licenses (version, privacy, third-party licenses).
    const pages = document.createElement('small');
    pages.style.display = 'block';
    for (const [page, label] of [['welcome', 'Getting started'], ['about', 'About & licenses']] as const) {
      const link = document.createElement('a');
      link.href = '#'; link.textContent = label; link.dataset.page = page;
      link.addEventListener('click', event => {
        event.preventDefault();
        void chrome.runtime.sendMessage({type: 'open-page', page}).then(reply => {
          if (!reply?.ok) this.summary.textContent = reply?.error ?? 'Could not open the page. Reload the extension.';
        });
      });
      pages.append(...pages.childNodes.length ? [' · ', link] : [link]);
    }
    this.element.append(open, this.summary, pages);
  }

  async refresh(): Promise<void> {
    const reply = await chrome.runtime.sendMessage({type: 'library', operation: 'counts'}).catch(() => null);
    if (!reply?.ok) {this.summary.textContent = reply?.error ?? 'Saved words unavailable. Reload the extension.'; return;}
    const {words, sentences, known} = reply.data as Counts;
    this.summary.textContent = (words || sentences
      ? `${words} ${words === 1 ? 'word' : 'words'} and ${sentences} ${sentences === 1 ? 'sentence' : 'sentences'} saved.`
      : 'Nothing saved yet: use ☆ Save word or Save sentence in a study card.')
      + (known ? ` ${known.toLocaleString()} known ${known === 1 ? 'word' : 'words'}.` : '');
  }
}
