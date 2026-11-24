import {BACKEND_PORT_KEY,DEFAULT_BACKEND_PORT,backendPort,validBackendPort} from '../backend';
interface ModelStatus {id:string;kind:string;model:string;revision:string;license:string;selected:boolean;installed:boolean;loaded:boolean;
  verification:string;experimental:boolean;targets:string[];structured:boolean;glossary_hints:boolean;setup_command:string;warnings:string[];
  approximate_download_bytes:number|null;compatible:boolean;compatibility_basis:string;devices:string[];dependency_available:boolean}
export interface Readiness {schema:1;version:string;initialization:string;busy:boolean;configuration_valid:boolean;failure_code:string|null;
  selected_device:string;models:ModelStatus[];dictionary:{installed:boolean;loaded:boolean;setup_command:string};tokenizer:{installed:boolean;loaded:boolean;setup_command:string};
  storage:{processing_cache:{disk_parent:string;persistent_enabled:boolean|null};glossary:{disk_parent:string;accessibility:string}}}
export function validateReadiness(value:unknown):Readiness {
  const data=value as Readiness;
  if(!data||data.schema!==1||typeof data.version!=='string'||!['initializing','ready','failed'].includes(data.initialization)||
    typeof data.busy!=='boolean'||typeof data.configuration_valid!=='boolean'||typeof data.selected_device!=='string'||
    !(data.failure_code===null||typeof data.failure_code==='string')||!Array.isArray(data.models)||data.models.length>24||
    !data.models.every(m=>m&&typeof m.id==='string'&&typeof m.model==='string'&&typeof m.loaded==='boolean'&&
      typeof m.installed==='boolean'&&typeof m.selected==='boolean'&&typeof m.experimental==='boolean'&&
      typeof m.compatible==='boolean'&&typeof m.dependency_available==='boolean'&&typeof m.structured==='boolean'&&typeof m.glossary_hints==='boolean'&&
      ['revision','license','verification','setup_command','compatibility_basis'].every(key=>typeof (m as unknown as Record<string,unknown>)[key]==='string')&&
      [m.targets,m.warnings,m.devices].every(a=>Array.isArray(a)&&a.length<=16&&a.every(v=>typeof v==='string'))&&
      (m.approximate_download_bytes===null||typeof m.approximate_download_bytes==='number'&&Number.isFinite(m.approximate_download_bytes)&&m.approximate_download_bytes>=0))||
    ![data.dictionary,data.tokenizer].every(s=>s&&typeof s.installed==='boolean'&&typeof s.loaded==='boolean'&&typeof s.setup_command==='string')||
    !data.storage?.processing_cache||typeof data.storage.processing_cache.disk_parent!=='string'||
    !(data.storage.processing_cache.persistent_enabled===null||typeof data.storage.processing_cache.persistent_enabled==='boolean')||
    !data.storage.glossary||typeof data.storage.glossary.disk_parent!=='string'||!['open','not_open','unknown'].includes(data.storage.glossary.accessibility))
    throw new Error('Invalid/outdated readiness response. Update the backend and extension together.');
  return data;
}
export class SetupControls {
  readonly element=document.createElement('details');private output=document.createElement('div');
  private port=document.createElement('input');private portStatus=document.createElement('p');
  constructor(){
    const summary=document.createElement('summary');summary.textContent='Setup & readiness';
    const reload=document.createElement('button');reload.textContent='Check Setup';reload.onclick=()=>{void this.load();};
    const label=document.createElement('label');label.textContent='Backend port ';
    Object.assign(this.port,{type:'number',min:'1024',max:'65535',step:'1'});label.append(this.port);
    const save=document.createElement('button');save.textContent='Save Port';save.onclick=()=>{void this.savePort();};
    this.portStatus.setAttribute('role','status');
    this.element.append(summary,label,save,this.portStatus,reload,this.output);
    this.element.addEventListener('toggle',()=>{if(this.element.open){void this.showPort();void this.load();}});
  }
  private async showPort():Promise<void>{
    const port=await backendPort();this.port.value=String(port);
    this.portStatus.textContent=`Start the backend with: yomiscan-server --port ${port}`;
  }
  private async savePort():Promise<void>{
    const value=Number(this.port.value);
    if(!validBackendPort(value)){this.portStatus.textContent='Enter a whole number from 1024 to 65535.';return;}
    await chrome.storage.local.set({[BACKEND_PORT_KEY]:value});
    this.portStatus.textContent=`Saved. Start the backend with: yomiscan-server --port ${value}`+
      (value===DEFAULT_BACKEND_PORT?'':` (default ${DEFAULT_BACKEND_PORT})`)+'. Then Check Setup.';
  }
  /** Installed translators the user can switch to; the backend loads them on its model worker. */
  private appendEngineChoice(data:Readiness):void{
    const engines=data.models.filter(m=>m.kind==='translation'&&m.installed&&m.dependency_available);
    if(engines.length<2)return;
    const box=document.createElement('fieldset'),legend=document.createElement('legend'),status=document.createElement('p');
    legend.textContent='Translation engine';status.setAttribute('role','status');box.append(legend);
    for(const engine of engines){
      const row=document.createElement('p');
      row.textContent=`${engine.id}${engine.experimental?' (experimental)':''} · targets ${engine.targets.join(', ')} `;
      if(engine.selected){row.append('· in use');}
      else{
        const use=document.createElement('button');use.textContent='Use';use.setAttribute('aria-label','Use translation engine '+engine.id);
        use.onclick=()=>{use.disabled=true;status.textContent=`Loading ${engine.id}… this can take a minute.`;
          void chrome.runtime.sendMessage({type:'chapter-translation-engine',engine:engine.id}).then(reply=>{
            if(!reply?.ok){status.textContent=reply?.error??'Engine switch failed.';use.disabled=false;return;}
            status.textContent=`Now using ${engine.id}. Restart chapters to translate with it.`;void this.load();
          },()=>{status.textContent='Engine switch unavailable. Reload the extension.';use.disabled=false;});};
        row.append(use);
      }
      box.append(row);
    }
    box.append(status);this.output.append(box);
  }
  private async load():Promise<void>{
    this.output.textContent='Checking local setup…';
    try{
      const reply=await chrome.runtime.sendMessage({type:'chapter-readiness'});
      if(!reply?.ok)throw new Error(`Cannot reach readiness. Start the updated backend: yomiscan-server --port ${await backendPort()}. See README setup instructions.`);
      const data=validateReadiness(reply.data);
      const line=(text:string)=>{const p=document.createElement('p');p.textContent=text;this.output.append(p);};this.output.replaceChildren();
      line(`Backend ${data.initialization}${data.busy?' · processing':''} · version ${data.version} · configured device ${data.selected_device}`);
      if(!data.configuration_valid)line('Unsupported configuration. Check YOMISCAN_DEVICE / OCR / DETECTOR / TRANSLATION_ENGINE and restart.');
      if(data.failure_code)line('Initialization issue: '+data.failure_code+'. Follow the missing component commands below, then restart.');
      line('JMdict: '+(data.dictionary.loaded?'loaded':data.dictionary.installed?'installed, not loaded':'missing')+
        (data.dictionary.loaded?'':'\n'+data.dictionary.setup_command));
      line('Japanese tokenizer: '+(data.tokenizer.loaded?'loaded':data.tokenizer.installed?'installed, not loaded':'missing')+
        (data.tokenizer.loaded?'':'\n'+data.tokenizer.setup_command));
      this.appendEngineChoice(data);
      const optional=document.createElement('details'),title=document.createElement('summary');title.textContent='Optional model information';optional.append(title);
      for(const model of data.models){const p=document.createElement('p');p.textContent=`${model.selected?'Selected ':''}${model.id}${model.experimental?' (experimental)':''}\n`+
        `${model.loaded?'Loaded':model.installed?'Artifacts installed, not loaded':'Artifacts unavailable'} · integrity ${model.verification}\n`+
        `${model.model} @ ${model.revision}\nLicense: ${model.license}\nTargets: ${model.targets.join(', ')||'not a translator'} · structured ${model.structured?'yes':'no'} · glossary hints ${model.glossary_hints?'yes':'no'}\n`+
        `Catalog device modes: ${model.devices.join(', ')}. `+
        (!model.compatible?'Requested device unsupported. ':model.compatibility_basis==='catalog_support_only'?'Runtime compatibility has not been checked by this probe. ':'')+
        (!model.dependency_available?'Optional dependency/runtime missing. ':'')+
        (model.approximate_download_bytes?`Approx. artifact download ${(model.approximate_download_bytes/1024/1024).toFixed(0)} MiB; this is not RAM usage.\n`:'')+
        model.warnings.join('\n')+'\nSetup: '+model.setup_command;
        (model.selected?this.output:optional).append(p);}
      const cache=data.storage.processing_cache,glossary=data.storage.glossary;
      this.output.append(optional);line(`Storage: persistent processing cache ${cache.persistent_enabled===null?'state unknown':cache.persistent_enabled?'enabled':'disabled'}; disk parent ${cache.disk_parent}. `+
        `Glossary database ${glossary.accessibility}; disk parent ${glossary.disk_parent}. These observations are not database integrity checks.`);
      line('Read-only checks do not load or download models. OCR and detector changes use environment settings and a backend restart; a translation engine chosen above lasts until the backend restarts (set YOMISCAN_TRANSLATION_ENGINE to keep it). Local guide: docs/post-mvp-reader-experience-distribution.md');
    }catch(error){this.output.textContent=error instanceof Error?error.message:'Readiness unavailable';}
  }
}
