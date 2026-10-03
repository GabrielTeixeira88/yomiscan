export {};
const params=new URLSearchParams(location.search);
const origins:unknown=JSON.parse(params.get('origins')??'[]');
const tabId=Number(params.get('tab')),version=Number(params.get('version'));
const retry=params.get('retry')==='true';
const status=document.querySelector<HTMLParagraphElement>('#status')!;
if(!Array.isArray(origins)||!origins.length||origins.length>50||!origins.every(x=>typeof x==='string'&&/^https?:\/\/[^/*?#]+\/\*$/.test(x))||!Number.isInteger(tabId)||!Number.isInteger(version)) {
  throw new Error('Invalid image-access request');
}
for(const origin of origins){const item=document.createElement('li');item.textContent=origin;document.querySelector('#hosts')!.append(item);}
async function resume():Promise<void> {
  try {
    const tab=await chrome.tabs.get(tabId);
    await chrome.tabs.update(tabId,{active:true});await chrome.windows.update(tab.windowId,{focused:true});
    await chrome.tabs.sendMessage(tabId,{type:'chapter-access-resolved',version,retry},{frameId:0});window.close();
  } catch {status.textContent='The reader/session is no longer available. Close this window and activate YomiScan again.';}
}
document.querySelector('#grant')!.addEventListener('click',()=>{
  // Direct extension-page click supplies Chrome's required user gesture.
  void chrome.permissions.request({origins:origins as string[]}).then(granted=>{
    if(granted)return resume();status.textContent='Access was declined. You may choose capture fallbacks instead.';
  }).catch(error=>{status.textContent=error instanceof Error?error.message:'Chrome could not request image-host access';});
});
document.querySelector('#fallback')!.addEventListener('click',()=>{void resume();});
