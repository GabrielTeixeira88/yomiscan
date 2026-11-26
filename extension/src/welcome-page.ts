// The welcome page (welcome.html), opened once on install: shows the shortcut as configured and
// opens the shortcut settings, the Saved page and About & licenses.
const shortcut = document.getElementById('shortcut')!;
void chrome.commands.getAll().then(commands => {
  const key = commands.find(command => command.name === 'select-text')?.shortcut;
  shortcut.textContent = key || 'not set';
});
const openTab = (url: string) => () => {void chrome.tabs.create({url});};
document.getElementById('shortcuts')!.addEventListener('click', openTab('chrome://extensions/shortcuts'));
document.getElementById('saved')!.addEventListener('click', openTab(chrome.runtime.getURL('library.html')));
document.getElementById('about')!.addEventListener('click', openTab(chrome.runtime.getURL('about.html')));
