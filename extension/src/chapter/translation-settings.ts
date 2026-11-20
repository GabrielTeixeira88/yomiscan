import {defaultTranslationOptions,targetLabel,validateProfile,type ReaderTranslationOptions,type TranslationProfile} from './translation-options';
import type {TranslationOperation} from './translation-client';

/** Explicit series identity and a small editor; no URL-derived manga library. */
export class TranslationSettings {
  readonly element=document.createElement('details');
  private fields=document.createElement('fieldset');
  private status=document.createElement('p');
  private target=document.createElement('select');
  private scope=document.createElement('select');
  private enabled=document.createElement('input');
  private mode=document.createElement('select');
  private order=document.createElement('input');
  private context=document.createElement('select');
  private seriesName=document.createElement('input');
  private term=document.createElement('select');
  private source=document.createElement('input');
  private preferred=document.createElement('input');
  private removeSeries:HTMLButtonElement;
  private profile:TranslationProfile|null=null;
  private options=defaultTranslationOptions();
  private loadVersion=0;
  constructor(private apply:(options:ReaderTranslationOptions,invalidate?:boolean)=>void) {
    const summary=document.createElement('summary');summary.textContent='Translation & terminology';this.element.append(summary,this.fields,this.status);
    this.fields.style.cssText='border:0;margin:0;padding:0;min-width:0';
    const row=(label:string,control:HTMLElement)=>{const line=document.createElement('label');line.style.display='block';line.append(document.createTextNode(label+' '),control);this.fields.append(line);};
    const button=(label:string,action:()=>void)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.addEventListener('click',action);this.fields.append(b);return b;};
    for(const target of ['en','pt-BR','es'] as const)this.target.add(new Option(targetLabel(target),target));
    this.target.setAttribute('aria-label','Sentence target language');row('Sentence target',this.target);
    this.scope.setAttribute('aria-label','Active series glossary');row('Active series',this.scope);
    this.enabled.type='checkbox';this.enabled.dataset.purpose='glossary-enabled';row('Use terminology hints',this.enabled);
    this.mode.setAttribute('aria-label','Translation contract');
    for(const [value,label] of [['sentences','Independent sentences (default)'],['structured-line','Structured line (experimental)'],
      ['structured-page','Structured page (experimental)'],['structured-panel','Structured panels (experimental)']])this.mode.add(new Option(label,value));
    row('Contract',this.mode);
    this.order.type='checkbox';this.order.dataset.purpose='panel-order';row('Panel order (experimental)',this.order);
    this.context.setAttribute('aria-label','Bounded dialogue context');
    for(const value of ['none','neighbor','panel','page'])this.context.add(new Option(value==='none'?'No dialogue context':value+' (experimental)',value));
    row('Context',this.context);
    this.seriesName.placeholder='User-confirmed series name';this.seriesName.maxLength=100;row('New series',this.seriesName);
    button('Create Series',()=>{void this.mutate('create-series',{label:this.seriesName.value});});
    this.removeSeries=button('Delete Series Glossary',()=>{void this.mutate('delete-series',{scope:this.scope.value});});
    this.term.setAttribute('aria-label','Terminology entry');row('Entry',this.term);
    this.source.placeholder='Exact Japanese term';this.source.maxLength=120;row('Japanese',this.source);
    this.preferred.placeholder='Preferred target-language term';this.preferred.maxLength=200;row('Preferred text',this.preferred);
    button('New Entry',()=>{this.term.value='';this.source.value=this.preferred.value='';});
    button('Save Entry',()=>{void this.mutate('save-term',{scope:this.scope.value,target_language:this.target.value,
      source:this.source.value,preferred:this.preferred.value,...(this.term.value?{entry_id:this.term.value}:{})});});
    button('Delete Entry',()=>{if(this.term.value)void this.mutate('delete-term',{scope:this.scope.value,target_language:this.target.value,entry_id:this.term.value});});
    button('Reload Translation Settings',()=>{void this.load();});
    this.term.addEventListener('change',()=>{const entry=this.profile?.entries.find(e=>e.id===this.term.value);this.source.value=entry?.source??'';this.preferred.value=entry?.preferred??'';});
    for(const control of [this.enabled,this.mode,this.order,this.context])control.addEventListener('change',()=>this.changed());
    this.scope.addEventListener('change',()=>{void this.load();});
    this.target.addEventListener('change',()=>{void this.load();});
    this.element.addEventListener('toggle',()=>{if(this.element.open)void this.load();});
    this.fields.disabled=true;
  }
  get current():ReaderTranslationOptions{return {...this.options};}
  private async request(operation:TranslationOperation,payload:Record<string,unknown>):Promise<unknown> {
    const reply=await chrome.runtime.sendMessage({type:'chapter-translation-settings',operation,payload});
    if(!reply?.ok)throw new Error(reply?.error??'Translation settings unavailable');
    return reply.data;
  }
  private changed():void {
    if(!this.profile)return;
    const structured=this.mode.value!=='sentences';
    if(!structured)this.context.value='none';
    this.context.disabled=!structured||!this.profile.capabilities.bounded_context;
    this.options={target_language:this.target.value as ReaderTranslationOptions['target_language'],series_id:this.scope.value,
      glossary_enabled:this.enabled.checked,glossary_version:this.profile.glossary_version,
      mode:this.mode.value as ReaderTranslationOptions['mode'],ordering:this.order.checked?'panels':'bands',
      context:this.context.value as ReaderTranslationOptions['context']};
    this.status.textContent=(this.profile.capabilities.glossary_hints?'Matched terminology is sent as hints; enforcement is not guaranteed.':
      'This engine does not use glossary hints. Its ordinary translation is unchanged.')+
      '\nDictionary definitions remain English. '+(this.target.value==='pt-BR'?'Brazilian usage is unverified; the model targets generic Portuguese.':'')+
      (structured?' Structured output may still mistranslate or invent meaning.':'');
    this.apply(this.current);
  }
  async load(scope=this.scope.value||'global',target=this.target.value):Promise<void> {
    const version=++this.loadVersion;
    this.fields.disabled=true;
    try{
      const profile=validateProfile(await this.request('profile',{scope,...(this.profile&&target?{target}:{})}));
      if(version!==this.loadVersion)return;
      this.profile=profile;
      this.scope.replaceChildren(...profile.series.map(s=>new Option(s.label,s.id)));this.scope.value=profile.scope;
      for(const option of this.target.options)option.disabled=!profile.capabilities.targets.includes(option.value as ReaderTranslationOptions['target_language']);
      this.target.value=profile.capabilities.targets.includes(target as ReaderTranslationOptions['target_language'])?target:profile.default_target;
      if(this.target.value!==profile.target_language){this.fields.disabled=false;await this.load(scope,this.target.value);return;}
      for(const option of this.mode.options)option.disabled=option.value!=='sentences'&&!profile.capabilities.structured;
      if(!profile.capabilities.structured)this.mode.value='sentences';
      this.term.replaceChildren(new Option('New entry',''),...profile.entries.map(e=>new Option(e.source+' → '+e.preferred,e.id)));
      this.source.value=this.preferred.value='';this.removeSeries.disabled=scope==='global';
      this.fields.disabled=false;this.changed();
    }catch(error){if(version!==this.loadVersion)return;
      this.status.textContent=error instanceof Error?error.message:'Translation settings unavailable';
      if(this.profile){this.scope.value=this.profile.scope;this.target.value=this.profile.target_language;this.fields.disabled=false;}}
  }
  private async mutate(operation:TranslationOperation,payload:Record<string,unknown>):Promise<void> {
    this.fields.disabled=true;
    try{
      const result=await this.request(operation,payload) as {id?:string};
      // The write already succeeded. Retire affected output even when the
      // following profile read is busy/offline; this tab does not receive its broadcast.
      if(operation!=='create-series')this.invalidate(String(payload.scope),
        typeof payload.target_language==='string'?payload.target_language:undefined,operation==='delete-series',false);
      const scope=operation==='create-series'?result.id:operation==='delete-series'?'global':this.scope.value;
      await this.load(scope||'global',this.target.value);
    }catch(error){this.status.textContent=error instanceof Error?error.message:'Glossary change failed';this.fields.disabled=false;}
  }
  invalidate(scope:string,target?:string,deleted=false,reload=true):void {
    if(deleted&&scope===this.options.series_id){
      this.options={...this.options,series_id:'global',glossary_version:null};this.apply(this.current,true);
      if(reload&&this.element.open)void this.load('global',this.target.value);return;
    }
    if(this.options.glossary_enabled&&(scope==='global'||scope===this.options.series_id)&&(!target||target===this.options.target_language)){
      // A session may have refreshed its version internally while this editor
      // remained stale/null. Mutation events must retire output independently
      // of option equality, including successive edits after a failed reload.
      this.options={...this.options,glossary_version:null};this.apply(this.current,true);
    }
    if(reload&&this.element.open)void this.load(this.scope.value,this.target.value);
  }
}
