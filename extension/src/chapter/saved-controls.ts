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
    this.element.append(open, this.summary);
  }

  async refresh(): Promise<void> {
    const reply = await chrome.runtime.sendMessage({type: 'library', operation: 'counts'}).catch(() => null);
    if (!reply?.ok) {this.summary.textContent = reply?.error ?? 'Saved words unavailable. Reload the extension.'; return;}
    const {words, sentences} = reply.data as {words: number; sentences: number};
    this.summary.textContent = words || sentences
      ? `${words} ${words === 1 ? 'word' : 'words'} and ${sentences} ${sentences === 1 ? 'sentence' : 'sentences'} saved.`
      : 'Nothing saved yet: use ☆ Save word or Save sentence in a study card.';
  }
}
