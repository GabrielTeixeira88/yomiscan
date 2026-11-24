import {ChapterTranslationSession,type ChapterSummary} from "./session";
import {coverageSummary} from './coverage';
import {TranslationSettings} from './translation-settings';
import {defaultTranslationOptions,targetLabel,type ReaderTranslationOptions} from './translation-options';
import type {Analysis} from '../api';
import type {Rect} from '../geometry';
import {HistoryControls} from './history-controls';
import {SetupControls} from './setup-controls';

export class ChapterControls {
  private host=document.createElement("div");
  private root=this.host.attachShadow({mode:"closed"});
  private session:ChapterTranslationSession|null=null;
  private status=document.createElement("p");
  private warning=document.createElement("p");
  private original:HTMLButtonElement;
  private english:HTMLButtonElement;
  private sessionURL=location.href;
  private stitchEnabled=false;
  private pageSelect=document.createElement('select');
  private exportButton:HTMLButtonElement;
  private translationOptions=defaultTranslationOptions();
  private translationSettings:TranslationSettings;
  private fontScale=1;
  constructor(selectText:()=>void,private showStudy:(data:Analysis,anchor:Rect)=>void=()=>{}) {
    this.host.dataset.yomiscan="controls";
    this.host.style.cssText="all:initial!important;position:fixed!important;top:12px!important;right:12px!important;z-index:2147483646!important;";
    const style=document.createElement("style");style.textContent=`
      :host{color-scheme:light}*{box-sizing:border-box}.chapter-panel{width:280px;max-width:calc(100vw - 24px);max-height:80vh;overflow:auto;overscroll-behavior:contain;background:#fffdf8;color:#203729;border:1px solid #b7c5ba;border-radius:12px;box-shadow:0 8px 30px #0004;padding:14px;font:14px/1.45 system-ui;text-align:left}
      header{display:flex;justify-content:space-between;align-items:center}h2{font-size:11px;text-transform:uppercase;letter-spacing:.1em;margin:14px 0 5px;color:#607669}
      button{font:inherit;cursor:pointer;border:1px solid #b7c5ba;background:#edf4ee;color:#203729;border-radius:6px;padding:7px 9px;margin:3px 3px 3px 0}button[aria-pressed=true]{background:#235d3c;color:white}button:focus-visible{outline:2px solid #287946}p{margin:8px 0;white-space:pre-wrap;overflow-wrap:anywhere}small{color:#617064}.warning{font-size:12px;color:#8a372b}summary{cursor:pointer}`;
    const panel=document.createElement("section");panel.className="chapter-panel";panel.setAttribute("aria-label","YomiScan controls");
    const header=document.createElement("header"), title=document.createElement("strong");title.textContent="YomiScan";
    const button=(label:string,action:()=>void)=>{const b=document.createElement("button");b.textContent=label;b.addEventListener("click",action);return b;};
    header.append(title,button("×",()=>{this.showHost(false);}));panel.append(header);
    const heading=(text:string)=>{const h=document.createElement("h2");h.textContent=text;panel.append(h);};
    heading("Study");panel.append(button("Select Text",selectText));
    heading("Reading");panel.append(button("Translate Chapter",()=>{void this.current().start();}),button("Stop Translation",()=>this.session?.stop()));
    const permissionHelp=document.createElement('small');permissionHelp.textContent='Translate/Retry may ask Chrome for access to this reader’s image hosts. Screenshots and analysis stay local.';
    panel.append(permissionHelp);
    const scrollLabel=document.createElement('label'),scrollOption=document.createElement('input');scrollOption.type='checkbox';
    scrollOption.addEventListener('change',()=>{this.stitchEnabled=scrollOption.checked;if(this.session)this.session.allowStitch=this.stitchEnabled;});
    scrollLabel.append(scrollOption,document.createTextNode('Allow scroll capture (moves page temporarily; Escape cancels)'));panel.append(scrollLabel);
    this.original=button("Original",()=>this.session?.setView("original"));this.english=button("English",()=>this.session?.setView("english"));
    heading("Translation View");panel.append(this.original,this.english);
    this.status.setAttribute("aria-live","polite");this.status.textContent="Ready — select a mode.";
    this.warning.className="warning";
    panel.append(this.status,this.warning,button("Retry Failed / Skipped",()=>{void this.current().start(true);}),
      button("Clear Session",()=>{this.session?.dispose();this.session=null;}));
    const pageLabel=document.createElement('label');pageLabel.textContent='Page ';
    this.pageSelect.setAttribute('aria-label','Chapter page');
    pageLabel.append(this.pageSelect);panel.append(pageLabel,
      button('Retranslate Page',()=>this.current().refreshPage(this.selectedPageId())));
    // Developer and maintenance tools stay available but fold away from the reading controls.
    const advanced=document.createElement('details'),advancedTitle=document.createElement('summary');
    advanced.className='advanced';advancedTitle.textContent='Advanced: reports, cache, setup, diagnostics';advanced.append(advancedTitle);
    const inclusions={text:false,original:false,rendered:false};
    const reportOptions=document.createElement('details'),reportTitle=document.createElement('summary');
    reportTitle.textContent='Report inclusions (metadata only by default)';reportOptions.append(reportTitle);
    for(const [key,label] of [['text','Include OCR and translation text'],['original','Include original page image'],
      ['rendered','Include translated page image']] as const) {
      const row=document.createElement('label'),box=document.createElement('input');box.type='checkbox';
      box.dataset.purpose='report-'+key;
      box.addEventListener('change',()=>{inclusions[key]=box.checked;});
      row.style.display='block';row.append(box,document.createTextNode(label));reportOptions.append(row);
    }
    const privacy=document.createElement('small');
    privacy.textContent='Reports download locally. Text/images may contain private or copyrighted content; review before sharing. Recent originals are retained in memory only.';
    reportOptions.append(privacy);
    this.exportButton=button('Export Page Report',()=>{
      this.exportButton.disabled=true;
      void this.current().exportPageReport(this.selectedPageId(),{...inclusions}).finally(()=>{this.exportButton.disabled=false;});
    });
    advanced.append(this.exportButton,reportOptions,button('Inspect Regions',()=>this.current().inspectRegions(this.selectedPageId())));
    const cacheDetails=document.createElement('details'),cacheTitle=document.createElement('summary');cacheTitle.textContent='Local processing cache';
    const cacheInfo=document.createElement('p'),cacheLabel=document.createElement('label'),persistent=document.createElement('input');
    persistent.type='checkbox';persistent.disabled=true;
    persistent.dataset.purpose='persistent-cache';
    cacheLabel.append(persistent,document.createTextNode('Save page processing on disk (pixels and text)'));
    const cacheHelp=document.createElement('small');cacheHelp.textContent='Off by default. Saved only on this computer, without page URLs. Disabling retains stored entries until cleared. Clear Session only removes browser results.';
    const cacheAction=async(operation:'read'|'settings'|'clear')=>{
      persistent.disabled=true;
      try {
        const reply=await chrome.runtime.sendMessage({type:'chapter-cache',operation,enabled:persistent.checked});
        if(!reply?.ok)throw new Error(reply?.error??'Cache controls unavailable');
        const data=reply.data;persistent.checked=data.persistent_enabled;
        const mib=(bytes:number)=>(bytes/1024/1024).toFixed(1);
        cacheInfo.textContent=`Disk ${mib(data.disk_bytes)} / ${mib(data.disk_limit)} MiB · backend RAM ${mib(data.memory_bytes)} MiB`+
          (data.error_code?' · Storage error; inspect backend logs.':'');
        persistent.disabled=false;
      }catch(error){cacheInfo.textContent=error instanceof Error?error.message:'Cache controls unavailable';}
    };
    persistent.addEventListener('change',()=>{void cacheAction('settings');});
    cacheDetails.addEventListener('toggle',()=>{if(cacheDetails.open)void cacheAction('read');});
    cacheDetails.append(cacheTitle,cacheLabel,cacheHelp,cacheInfo,button('Refresh Cache Usage',()=>{void cacheAction('read');}),
      button('Clear Persistent Cache',()=>{void cacheAction('clear');}));advanced.append(cacheDetails);
    this.translationSettings=new TranslationSettings((options,invalidate=false)=>{
      const identity=(value:ReaderTranslationOptions)=>JSON.stringify({...value,series_id:value.glossary_enabled?value.series_id:null,
        glossary_version:value.glossary_enabled?value.glossary_version:null});
      if(invalidate||identity(options)!==identity(this.translationOptions)){this.session?.dispose();this.session=null;}
      this.translationOptions=options;this.english.textContent=targetLabel(options.target_language);
    });panel.append(this.translationSettings.element);
    panel.append(new HistoryControls(data=>this.showStudy(data,{x:16,y:16,width:0,height:0})).element);
    advanced.append(new SetupControls().element);
    const resources=document.createElement('details'),resourceTitle=document.createElement('summary'),resourceText=document.createElement('p');
    resourceTitle.textContent='Processing details';resources.append(resourceTitle,resourceText);
    resources.addEventListener('toggle',()=>{if(resources.open)resourceText.textContent=this.session?.resourceSummary()??'No processed page retained.';});advanced.append(resources);
    const fontDetails=document.createElement('details'),fontTitle=document.createElement('summary');fontTitle.textContent='Translation font';
    const scale=document.createElement('select');scale.setAttribute('aria-label','Translation font size');
    for(const value of [.75,1,1.25,1.5])scale.add(new Option(`${Math.round(value*100)}%`,String(value)));scale.value='1';
    const applyFont=()=>{this.fontScale=Number(scale.value);void this.current().setFontScale(this.fontScale);};
    const fontHelp=document.createElement('small');fontHelp.textContent='Larger text may leave a block original when it cannot fit safely. Only rendering is refreshed.';
    fontDetails.append(fontTitle,scale,button('Apply Font',applyFont),button('Reset Font',()=>{scale.value='1';applyFont();}),fontHelp);panel.append(fontDetails);
    const help=document.createElement("small");help.textContent="Selected pages stay on this machine. CPU processing may take time.";panel.append(help);
    const details=document.createElement("details"),summary=document.createElement("summary");summary.textContent="Developer diagnostics";
    details.append(summary,button("Log discovery / states",()=>this.current().diagnostics()));advanced.append(details);
    panel.append(advanced);
    this.root.append(style,panel);this.showHost(false);document.documentElement.append(this.host);
    for(const name of ["pointerdown","pointerup","click","dblclick"])this.host.addEventListener(name,event=>event.stopPropagation());
    this.host.addEventListener("keydown",event=>{if(event.key==="Escape")this.showHost(false);event.stopPropagation();});
    window.addEventListener("pagehide",()=>{this.session?.dispose();this.session=null;});
  }
  private showHost(visible:boolean):void {this.host.style.setProperty("display",visible?"block":"none","important");}
  private selectedPageId():number|undefined {return this.pageSelect.value?Number(this.pageSelect.value):undefined;}
  open():void {this.showHost(true);}
  private current():ChapterTranslationSession {
    if(this.sessionURL!==location.href || this.session?.isDisposed){this.session?.dispose();this.session=null;this.sessionURL=location.href;}
    if(!this.session)this.session=new ChapterTranslationSession(status=>this.show(status),hidden=>{this.host.style.setProperty("visibility",hidden?"hidden":"visible","important");},undefined,{...this.translationOptions},this.fontScale,this.showStudy);
    this.session.allowStitch=this.stitchEnabled;
    return this.session;
  }
  private show(status:ChapterSummary):void {
    this.english.textContent=targetLabel(this.session?.targetLanguage??this.translationOptions.target_language);
    const selection=this.pageSelect.value,options=this.session?.pageOptions()??[];
    this.pageSelect.replaceChildren(new Option('Nearest viewport',''),...options.map(p=>new Option(`Page ${p.id} · ${p.state}`,String(p.id))));
    if(options.some(p=>String(p.id)===selection))this.pageSelect.value=selection;
    this.original.setAttribute("aria-pressed",String(status.view==="original"));this.english.setAttribute("aria-pressed",String(status.view==="english"));
    const pending=this.session?[...this.session.queue.pages.values()].some(p=>p.state==="queued"):false;
    this.status.textContent=`${status.translated} / ${status.total} pages translated · ${status.failed} failed · ${status.skipped} skipped\n`+
      (status.processing?`Page ${status.processing} processing…`:status.active&&!pending?"Known pages finished; watching for lazy-loaded pages.":"")+
      '\n'+status.message;
    if(this.session){const cache=this.session.memoryStats(),evicted=[...this.session.queue.pages.values()].filter(p=>p.state==='evicted').length;
      this.status.textContent+=`\nSession ${(cache.bytes/1024/1024).toFixed(1)} / ${(cache.budget/1024/1024).toFixed(0)} MiB · ${evicted} evicted (reload on view)`;}
    const errors=this.session?[...this.session.queue.pages.values()].filter(p=>p.error&&!p.cancelled).slice(0,3).map(p=>`Page ${p.id}: ${p.error}`):[];
    const results=this.session?[...this.session.queue.pages.values()].flatMap(p=>p.result?[p.result]:[]):[];
    this.warning.textContent=errors.join("\n")+'\n'+coverageSummary(results);
    if(status.message.includes("backend")||status.message.includes("server"))this.warning.textContent+="\nStart the backend (uv run yomiscan-server); its port must match Setup & readiness.";
  }
  async prepareStudy():Promise<void> {if(this.session)await this.session.study();this.showHost(false);}
  verifyCapture(id:string):boolean{return this.session?.verifyCapture(id)??false;}
  resolveSource(id:string):string|null{return this.session?.resolveSource(id)??null;}
  resumeAfterPermission(version:number,retry:boolean):void {this.session?.resumeAfterPermission(version,retry);}
  glossaryChanged(scope:string,target?:string,deleted=false):void {this.translationSettings.invalidate(scope,target,deleted);}
}
