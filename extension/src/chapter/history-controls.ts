import type {Analysis} from '../api';
import type {HistoryState} from '../history';

export class HistoryControls {
  readonly element=document.createElement('details');
  private enabled=document.createElement('input');private list=document.createElement('select');private status=document.createElement('p');
  private state:HistoryState|null=null;
  constructor(open:(analysis:Analysis)=>void){
    const summary=document.createElement('summary');summary.textContent='Study history';
    const label=document.createElement('label');this.enabled.type='checkbox';this.enabled.dataset.purpose='study-history';
    label.append(this.enabled,document.createTextNode(' Enable local history (off by default)'));
    this.list.setAttribute('aria-label','Saved study entry');
    const help=document.createElement('small');help.textContent='Only Save to History writes an entry. Up to 100 entries / 2 MiB; oldest entries are removed at the limit. Disabling retains entries; Clear History erases them. No pages or source URLs are saved.';
    const button=(text:string,fn:()=>void)=>{const b=document.createElement('button');b.textContent=text;b.onclick=fn;return b;};
    this.element.append(summary,label,this.list,button('Open Study Entry',()=>{
      const entry=this.state?.entries.find(e=>e.id===this.list.value);if(entry)open(entry.analysis);
    }),button('Delete Study Entry',()=>{void this.request('delete',{id:this.list.value});}),
      button('Clear History',()=>{void this.request('clear');}),button('Export History',()=>{void this.export();}),
      button('Reload History',()=>{void this.request('state');}),this.status,help);
    this.enabled.disabled=true;
    this.enabled.onchange=()=>{void this.request('enabled',{enabled:this.enabled.checked});};
    this.element.addEventListener('toggle',()=>{if(this.element.open)void this.request('state');});
  }
  private async request(operation:string,payload:Record<string,unknown>={}):Promise<HistoryState|null>{
    this.enabled.disabled=true;
    try{
      const reply=await chrome.runtime.sendMessage({type:'study-history',operation,payload});
      if(!reply?.ok)throw new Error(reply?.error??'Local history unavailable');
      this.state=reply.data as HistoryState;this.enabled.checked=this.state.enabled;
      this.list.replaceChildren(...this.state.entries.map(e=>new Option(new Date(e.created_at).toLocaleString()+' · '+(e.analysis.target_language??'en')+' · '+e.analysis.original_text.slice(0,30),e.id)));
      this.status.textContent=this.state.entries.length+' saved entries. '+(this.state.enabled?'Saving enabled; use the popup Save action.':'New writes disabled; existing entries retained.');
      return this.state;
    }catch(error){this.status.textContent=error instanceof Error?error.message:'History unavailable';return null;}
    finally{this.enabled.disabled=false;}
  }
  private async export():Promise<void>{
    const state=await this.request('export');if(!state)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='yomiscan-study-history-'+Date.now()+'.json';link.click();
    window.setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
}
