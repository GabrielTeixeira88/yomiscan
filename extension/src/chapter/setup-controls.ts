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
  constructor(){
    const summary=document.createElement('summary');summary.textContent='Setup & readiness';
    const reload=document.createElement('button');reload.textContent='Check Setup';reload.onclick=()=>{void this.load();};
    this.element.append(summary,reload,this.output);
    this.element.addEventListener('toggle',()=>{if(this.element.open)void this.load();});
  }
  private async load():Promise<void>{
    this.output.textContent='Checking local setup…';
    try{
      const reply=await chrome.runtime.sendMessage({type:'chapter-readiness'});
      if(!reply?.ok)throw new Error('Cannot reach readiness. Start the updated backend: yomiscan-server. See README setup instructions.');
      const data=validateReadiness(reply.data);
      const line=(text:string)=>{const p=document.createElement('p');p.textContent=text;this.output.append(p);};this.output.replaceChildren();
      line(`Backend ${data.initialization}${data.busy?' · processing':''} · version ${data.version} · configured device ${data.selected_device}`);
      if(!data.configuration_valid)line('Unsupported configuration. Check YOMISCAN_DEVICE / OCR / DETECTOR / TRANSLATION_ENGINE and restart.');
      if(data.failure_code)line('Initialization issue: '+data.failure_code+'. Follow the missing component commands below, then restart.');
      line('JMdict: '+(data.dictionary.loaded?'loaded':data.dictionary.installed?'installed, not loaded':'missing')+
        (data.dictionary.loaded?'':'\n'+data.dictionary.setup_command));
      line('Japanese tokenizer: '+(data.tokenizer.loaded?'loaded':data.tokenizer.installed?'installed, not loaded':'missing')+
        (data.tokenizer.loaded?'':'\n'+data.tokenizer.setup_command));
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
      line('Read-only checks do not load or download models. Model changes use environment settings and a backend restart. Local guide: docs/post-mvp-reader-experience-distribution.md');
    }catch(error){this.output.textContent=error instanceof Error?error.message:'Readiness unavailable';}
  }
}
