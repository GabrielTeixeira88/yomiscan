import {ChapterQueue,SkipPage,WaitForViewport,viewportPriority,type ViewMode,type PageRecord} from "./model";
import {GenericPageDiscovery,type MangaPageCandidate,type PageDiscoveryStrategy,type DiscoveryDecision} from "./discovery";
import {ChapterOverlays,type PageImageResult} from "./overlay";
import {PageImageAcquirer,AcquisitionError,canvasPixels,currentViewport,verifyTicket,type CaptureTicket,type PagePixels} from "./acquisition";
import {fetchFromExtension} from './source-client';
import {imageHost} from './source-fetch';
import {stitchPage} from './stitching';
import {validSelection,type Rect} from '../geometry';
import {renderPage,analyzePage,ConfigurationChanged} from "./transport";
import {parseReadingPage,stepBubble,type ReadingPage} from './reading';
import {ReadingLayer,bubbleRect,type ReadingLayerPage} from './reading-layer';
import {createPageReport,type PageReportContext,type ReportOptions} from './reports';
import {defaultTranslationOptions,validateProfile,type ReaderTranslationOptions} from './translation-options';
import {fontScale as validateFontScale,retainsRenderedBlocks} from './font-settings';
import {RegionInspector} from './region-inspector';
import type {Analysis} from '../api';
import {progressLabel} from './progress';
/** "translate": render every page in English. "read": analyze pages for study (Reading mode);
 * English is rendered per page on request, from the retained page pixels. */
export type SessionMode='translate'|'read';
export interface ChapterSummary { active:boolean; total:number; translated:number; failed:number; skipped:number; processing:number|null; message:string; view:ViewMode; mode?:SessionMode }
const SESSION_BUDGET=128*1024*1024,FAILURE_REPORT_BUDGET=256*1024;
type Page=PageRecord<MangaPageCandidate,PageImageResult>;
/** Retained-memory estimate of a page's analysis (UTF-16 strings dominate). */
const readingBytes=(reading:ReadingPage)=>JSON.stringify(reading).length*2;
/** Scroll whichever container scrolls this page image: a reader's scroll box, else the window. */
function scrollPageBy(image:HTMLElement,delta:number):void {
  for(let node=image.parentElement;node&&node!==document.body&&node!==document.documentElement;node=node.parentElement){
    if(/auto|scroll|overlay/.test(getComputedStyle(node).overflowY)&&node.scrollHeight>node.clientHeight+1){node.scrollBy({top:delta,behavior:'instant'});return;}
  }
  window.scrollBy({top:delta,behavior:'instant'});
}
const editable=(target:EventTarget|undefined)=>target instanceof HTMLElement&&(target.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(target.tagName));

export class ChapterTranslationSession {
  readonly queue:ChapterQueue<MangaPageCandidate,PageImageResult>;
  private overlays=new ChapterOverlays();
  private observer:MutationObserver|null=null;
  private intersection:IntersectionObserver|null=null;
  private events:AbortController|null=null;
  private versions=new WeakMap<HTMLImageElement,number>();
  private loadedSources=new WeakMap<HTMLImageElement,string>();
  private decisions:DiscoveryDecision[]=[];
  private discoveryTimer=0;
  private navigationTimer=0;
  private url=location.href;
  private lifetime=new AbortController();
  private disposed=false;
  private startVersion=0;
  private notice="Ready";
  private generation='initial';
  private configuration:string|undefined;
  capture:CaptureTicket|null=null;
  debug=false;
  allowStitch=false;
  private acquiring:AbortController|null=null;
  private sourceTicket:{id:string;candidate:MangaPageCandidate}|null=null;
  private failureReports=new Map<object,{context:PageReportContext;bytes:number}>();
  private exporting=false;
  private downloads=new Set<string>();
  private renderVersion=0;
  private rerenders=new Set<object>();
  private inspector:RegionInspector|null=null;
  private stage='';
  private reading:ReadingLayer|null=null;
  /** Reading mode: pages whose English overlay is shown, and pages waiting for their English render. */
  private englishShown=new Set<object>();
  private englishRequests=new Set<object>();
  private cursor:{key:object;bubble:number}|null=null;
  private navigation=0;
  constructor(private changed:(status:ChapterSummary)=>void,private hideControls:(hidden:boolean)=>void,
              private discovery:PageDiscoveryStrategy=new GenericPageDiscovery(),
              private translation:ReaderTranslationOptions=defaultTranslationOptions(),private fontScale=1,
              private showStudy:(data:Analysis,anchor:Rect)=>void=()=>{},readonly mode:SessionMode='translate') {
    this.queue=new ChapterQueue({process:(page,signal)=>this.process(page,signal),
      priority:page=>{const r=page.source.image.getBoundingClientRect();return viewportPriority(r.top,r.bottom,innerHeight);},
      cache:{budget:SESSION_BUDGET-FAILURE_REPORT_BUDGET,size:r=>r.bytes,protected:p=>{
        const r=p.source.image.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth;
      }},
      release:result=>{if(result.url){this.overlays.release(result.url);URL.revokeObjectURL(result.url);}},changed:()=>this.update()});
    this.navigationTimer=window.setInterval(()=>{if(location.href!==this.url)this.dispose();},1000);
    window.addEventListener("pagehide",()=>this.dispose(),{once:true,signal:this.lifetime.signal});
    if(mode==='read'){
      this.reading=new ReadingLayer((key,bubble)=>{void this.studyBubble(key,bubble,false);},key=>this.toggleEnglish(key));
      // J / K: next / previous bubble in reading order. Typing in a field never navigates.
      document.addEventListener('keydown',event=>{
        if(event.defaultPrevented||event.isComposing||event.ctrlKey||event.altKey||event.metaKey||event.repeat||editable(event.composedPath()[0]))return;
        const key=event.key.toLowerCase();if(key!=='j'&&key!=='k')return;
        event.preventDefault();void this.step(key==='j'?1:-1);
      },{signal:this.lifetime.signal});
    }
  }
  get isDisposed():boolean{return this.disposed;}
  get targetLanguage(){return this.translation.target_language;}
  memoryStats():{bytes:number;budget:number;evictions:number} {
    const cache=this.queue.cacheStats();
    return {...cache,bytes:cache.bytes+[...this.failureReports.values()].reduce((n,r)=>n+r.bytes,0),budget:SESSION_BUDGET};
  }
  private rememberFailure(page:object,context:PageReportContext):void {
    this.failureReports.delete(page);
    const encoded=JSON.stringify(context),bytes=Math.max(new TextEncoder().encode(encoded).length,encoded.length*2)+1024;
    if(bytes>FAILURE_REPORT_BUDGET)return;
    while(this.failureReports.size && (this.failureReports.size>=3 ||
      [...this.failureReports.values()].reduce((n,r)=>n+r.bytes,bytes)>FAILURE_REPORT_BUDGET))
      this.failureReports.delete(this.failureReports.keys().next().value!);
    this.failureReports.set(page,{context,bytes});
  }
  summary():ChapterSummary {
    const pages=[...this.queue.pages.values()];
    return {active:this.queue.active,total:pages.length,translated:pages.filter(p=>p.state==="translated"||p.state==="evicted").length,
      failed:pages.filter(p=>p.state==="failed").length,skipped:pages.filter(p=>p.state==="skipped").length,
      processing:pages.find(p=>p.state==="processing")?.id??null,message:this.notice+(this.stage?'\n'+this.stage:''),view:this.queue.view,mode:this.mode};
  }
  private update():void {
    if(this.disposed) return;
    this.inspector?.refresh();
    if(this.notice.startsWith('Refreshing page') && ![...this.queue.pages.values()].some(p=>p.refreshing))
      this.notice='Page refresh finished; see any retained-result warning below.';
    const pages=[...this.queue.pages.values()];
    this.overlays.update(pages,this.mode==='read'?page=>this.englishShown.has(page.key):()=>this.queue.view==='english');
    this.reading?.update(this.readingPages());
    this.changed(this.summary());
    if(this.debug) console.debug("YomiScan chapter",this.summary());
  }
  /** Read pages in document order, so J/K follows the reader's page order. */
  private readingPages():ReadingLayerPage[] {
    return this.orderedPages().flatMap(page=>{
      const reading=page.result?.reading;if(!reading)return [];
      const shown=this.englishShown.has(page.key),url=page.result?.url;
      const pending=this.englishRequests.has(page.key)||(shown&&!url&&(page.state==='queued'||page.state==='processing'));
      const english=pending?'loading':shown&&url?'on':'off';
      return [{key:page.key,id:page.id,image:page.source.image,source:page.source.source,reading,english}];
    });
  }
  private orderedPages():Page[] {
    return [...this.queue.pages.values()].filter(p=>p.source.image.isConnected).sort((a,b)=>
      a.source.image===b.source.image?0:a.source.image.compareDocumentPosition(b.source.image)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1);
  }
  /** Reading mode: show or hide one page's English overlay, rendering it on first request. */
  toggleEnglish(key:object):void {
    const page=this.queue.pages.get(key);
    if(this.disposed||this.mode!=='read'||!page?.result?.reading)return;
    if(this.englishShown.has(key)&&page.result.url){this.englishShown.delete(key);this.update();return;}
    this.englishShown.add(key);
    if(!page.result.url&&!this.englishRequests.has(key)){
      this.englishRequests.add(key);
      if(!this.queue.refresh(key)){this.englishRequests.delete(key);this.englishShown.delete(key);
        this.notice=`Page ${page.id} is busy; try English again when it finishes.`;}
      else {this.observe();this.notice=`Rendering page ${page.id} in English; the Japanese stays clickable meanwhile.`;}
    }
    this.update();
  }
  /** J / K: open the next or previous bubble's study card, scrolling it into view. */
  private async step(direction:1|-1):Promise<void> {
    const pages=this.orderedPages();
    const counts=pages.map(p=>p.result?.reading?p.result.reading.bubbles.length:
      p.state==='queued'||p.state==='processing'||p.state==='evicted'?null:0);
    const index=this.cursor?pages.findIndex(p=>p.key===this.cursor!.key):-1;
    let next:ReturnType<typeof stepBubble>;
    if(index>=0)next=stepBubble(counts,{page:index,bubble:this.cursor!.bubble},direction);
    else {
      // No card open yet: the first press opens the first bubble on screen in the nearest page.
      const nearest=this.selectedPage(),at=nearest?pages.indexOf(nearest):-1;
      const layer=nearest?this.readingPages().find(p=>p.key===nearest.key):undefined;
      if(at>=0&&layer){
        const first=layer.reading.bubbles.findIndex((_,i)=>{const r=bubbleRect(layer,i);return r!==null&&r.y+r.height>0&&r.y<innerHeight;});
        next=first>=0?{page:at,bubble:first}:stepBubble(counts.map((n,i)=>i<at?0:n),null,1);
      } else next=at>=0&&counts[at]===null?{waiting:at}:stepBubble(counts,null,direction);
    }
    if(!next){this.notice=direction===1?'Last bubble of the loaded pages.':'First bubble of the loaded pages.';this.update();return;}
    if('waiting' in next){this.notice=`Page ${pages[next.waiting].id} is still being read; J / K continues when it is ready.`;this.update();return;}
    await this.studyBubble(pages[next.page].key,next.bubble,true);
  }
  /** Open one bubble's study card from retained page analysis: no screenshot, OCR or request. */
  private async studyBubble(key:object,bubble:number,scroll:boolean):Promise<void> {
    const version=++this.navigation,find=()=>this.readingPages().find(p=>p.key===key);
    let page=find();if(!page?.reading.bubbles[bubble])return;
    let rect=bubbleRect(page,bubble);
    if(!rect){this.notice='This page layout (transformed or bordered image) cannot be mapped; use Select Text.';this.update();return;}
    if(scroll&&(rect.y<0||rect.y+rect.height>innerHeight)){
      scrollPageBy(page.image,rect.y-innerHeight*.25);
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      if(this.disposed||version!==this.navigation)return;
      page=find();rect=page?bubbleRect(page,bubble):null;if(!page||!rect)return;
    }
    this.cursor={key,bubble};this.reading?.highlight(this.cursor);
    const data=page.reading.bubbles[bubble].analysis;
    this.showStudy({...data,provenance:{...data.provenance,reading:{page:page.id,bubble:bubble+1,bubbles:page.reading.bubbles.length}}},rect);
  }
  async start(retry=false,permissionHandled=false):Promise<void> {
    const version=++this.startVersion;this.notice="Checking local backend…";this.update();
    try {
      const origins=[...new Set(this.discovery.discover(document).candidates.map(c=>imageHost(c.source)).filter((s):s is string=>s!==null))];
      if(origins.length && !permissionHandled) {
        const permission=await chrome.runtime.sendMessage({type:'chapter-permissions',origins,version,retry});
        if(permission?.pending){this.notice='Choose image-host access or capture fallbacks in the YomiScan access window.';this.update();return;}
        if(!permission?.ok)throw new Error(permission?.error??'Could not request image-host access');
      }
      const reply=await chrome.runtime.sendMessage({type:"chapter-health"});
      if(!reply?.ok) throw new Error(reply?.error||"YomiScan local backend is not running.");
      if(this.disposed || version!==this.startVersion) return;
      const profileReply=await chrome.runtime.sendMessage({type:'chapter-translation-settings',operation:'profile',
        payload:{scope:this.translation.series_id??'global',target:this.translation.target_language}});
      if(profileReply?.ok){
        const profile=validateProfile(profileReply.data);
        if(!profile.capabilities.targets.includes(this.translation.target_language)){
          if(this.translation.series_id===null&&this.translation.target_language==='en')this.translation={...this.translation,target_language:profile.default_target};
          else throw new Error('Selected engine does not support this target. Reload Translation Settings.');
        }
        this.translation={...this.translation,glossary_version:profile.glossary_version};
      }else if(this.translation.glossary_enabled||this.translation.mode!=='sentences'||this.translation.target_language!=='en')
        throw new Error(profileReply?.error??'Experimental translation settings unavailable');
      if(this.disposed || version!==this.startVersion)return;
      const configuration=typeof reply.configuration_id==='string'&&/^[a-f0-9]{64}$/.test(reply.configuration_id)?reply.configuration_id:undefined;
      const effective={...this.translation,series_id:this.translation.glossary_enabled?this.translation.series_id:null,
        glossary_version:this.translation.glossary_enabled?this.translation.glossary_version:null};
      const generation=(configuration??crypto.randomUUID())+'|'+JSON.stringify(effective);
      if(this.generation!==generation)this.queue.stop();
      this.configuration=configuration;this.generation=generation;
      this.notice=this.mode==='read'?'Reading pages: click an outlined bubble or press J to study it.':"Watching for pages";
      this.reading?.suspend(false);this.observe();this.scan();
      if(retry)this.queue.retry();else this.queue.start();
    } catch(error) {if(!this.disposed && version===this.startVersion){this.notice=error instanceof Error?error.message:"Backend unavailable";this.update();}}
  }
  resumeAfterPermission(version:number,retry:boolean):void {
    if(!this.disposed && version===this.startVersion)void this.start(retry,true);
  }
  stop():void {this.startVersion++;this.renderVersion++;this.rerenders.clear();
    for(const key of this.englishRequests)this.englishShown.delete(key);this.englishRequests.clear();this.queue.stop();this.acquiring?.abort();this.disconnect();this.notice="Stopped. The current page may finish; completed pages are retained.";this.update();}
  async setFontScale(value:number):Promise<void> {
    const scale=validateFontScale(value);
    this.stop();const version=++this.renderVersion;
    await this.queue.idle();
    if(this.disposed||version!==this.renderVersion)return;
    this.fontScale=scale;this.observe();
    // Reading mode rerenders only the pages that already have an English render.
    for(const page of this.queue.pages.values())if(this.mode==='read'?page.result?.url:page.result){
      (this.mode==='read'?this.englishRequests:this.rerenders).add(page.key);this.queue.refresh(page.key);}
    this.notice=`Font ${Math.round(scale*100)}%: rerendering processed pages; previous images remain until replacement.`;this.update();
  }
  setView(view:ViewMode):void {
    if(this.mode==='read'){
      // Original hides every English page; English switches on every read page (rendering on demand).
      if(view==='original'){this.englishShown.clear();this.update();}
      else for(const page of this.queue.pages.values())if(page.result?.reading&&!this.englishShown.has(page.key))this.toggleEnglish(page.key);
    }
    this.queue.setView(view);
  }
  pageOptions():{id:number;state:string;hasResult:boolean}[] {
    return [...this.queue.pages.values()].map(p=>({id:p.id,state:p.refreshing?'refreshing':p.state,hasResult:!!p.result}));
  }
  private selectedPage(id?:number) {
    const pages=[...this.queue.pages.values()];
    return id===undefined ? pages.sort((a,b)=>{
      const distance=(p:typeof a)=>{const r=p.source.image.getBoundingClientRect();return Math.abs((r.top+r.bottom)/2-innerHeight/2);};
      return distance(a)-distance(b);
    })[0] : pages.find(p=>p.id===id);
  }
  inspectRegions(id?:number):void {
    this.inspector?.dispose();
    const page=this.selectedPage(id),result=page?.result;
    if(!page||!result?.snapshot){this.notice=page?.state==='evicted'?'Page result was evicted. Reprocess it to inspect retained analysis.':'Process a page before inspecting regions.';this.update();return;}
    const current=()=>!this.disposed&&location.href===this.url&&this.queue.pages.get(page.key)===page&&page.result===result&&
      page.source.image.isConnected&&page.source.image.complete&&(page.source.image.currentSrc||page.source.image.src)===page.source.source&&
      page.source.image.naturalWidth===page.source.width&&page.source.image.naturalHeight===page.source.height;
    const unpin=this.queue.pin(page.key);
    this.inspector=new RegionInspector(page.source.image,result.snapshot,current,this.showStudy,()=>{unpin();this.inspector=null;});
  }
  resourceSummary():string {
    const snapshot=this.selectedPage()?.result?.snapshot;
    if(!snapshot)return 'No retained completed-page timings. Backend process RSS is not measured.';
    const cache=snapshot.cache as {memory_bytes?:number;disk_bytes?:number;stages?:{stage:string;restored:boolean;compute_ms?:number}[]}|undefined;
    return (cache?.stages??[]).map(s=>s.stage+': '+(s.restored?'cached':typeof s.compute_ms==='number'?Math.round(s.compute_ms)+' ms':'processed')).join('\n')+
      (cache?`\nBackend cache RAM ${((cache.memory_bytes??0)/1024/1024).toFixed(1)} MiB · disk cache ${((cache.disk_bytes??0)/1024/1024).toFixed(1)} MiB`:'')+
      '\nProcess RSS / peak model RAM / VRAM are not measured.';
  }
  refreshPage(id?:number):void {
    if(this.disposed || location.href!==this.url)return;
    this.scan();
    const page=this.selectedPage(id);
    if(!page || !this.queue.refresh(page.key))this.notice='Choose a successfully processed page that is not already queued or processing.';
    else {this.observe();this.notice=`Refreshing page ${page.id}; previous translation stays available.`;}
    this.update();
  }
  async exportPageReport(id:number|undefined,options:ReportOptions):Promise<void> {
    if(this.exporting || this.downloads.size){this.notice='Finish the current report download before preparing another.';this.update();return;}
    const page=this.selectedPage(id);
    if(!page){this.notice='No chapter page is available to report.';this.update();return;}
    const result=page.result;
    const current=()=>!this.disposed&&location.href===this.url&&this.queue.pages.get(page.key)===page&&
      page.result===result&&
      page.source.image.isConnected&&(page.source.image.currentSrc||page.source.image.src)===page.source.source;
    if(!current())return;
    const unpin=this.queue.pin(page.key);this.exporting=true;
    const context=result?.reportContext??this.failureReports.get(page)?.context??{
      page_id:page.id,width:page.source.width,height:page.source.height,state:page.state,timings:{}};
    this.notice=`Preparing page ${page.id} report…`;this.update();
    try {
      const rendered=options.rendered&&result?.url?await(await fetch(result.url)).blob():undefined;
      const report=await createPageReport({...context,session_cache:this.memoryStats()},result?.snapshot,options,
        {original:result?.original,rendered});
      if(!current())throw new Error('Page changed during report preparation; export cancelled.');
      const url=URL.createObjectURL(report);this.downloads.add(url);
      const link=document.createElement('a');link.dataset.yomiscan='report-download';
      link.href=url;link.download=`yomiscan-page-${page.id}-report-${Date.now()}.zip`;link.click();
      window.setTimeout(()=>{if(this.downloads.delete(url))URL.revokeObjectURL(url);},1000);
      this.notice=`Page ${page.id} report prepared; browser download requested.`;
    } catch(error) {this.notice=error instanceof Error?error.message:'Page report export failed.';}
    finally {unpin();this.exporting=false;}
    this.update();
  }
  /** Select Text: free the backend and keep outlines and overlays out of the screenshot. Starting again restores them. */
  async study():Promise<void> {this.stop();this.setView("original");this.reading?.suspend(true);this.notice="Finishing any current page before Select Text…";this.update();await this.queue.idle();}
  diagnostics():void {
    this.debug=!this.debug;
    console.table(this.decisions.map(d=>({source:d.image.currentSrc||d.image.src,width:d.image.naturalWidth,height:d.image.naturalHeight,
      accepted:d.accepted,reason:d.reason,page:this.queue.pages.get(d.image)?.id,state:this.queue.pages.get(d.image)?.state})));
    console.table([...this.queue.pages.values()].map(p=>({id:p.id,state:p.state,attempts:p.attempts,error:p.error,
      rendered:p.result?.rendered,skipped:p.result?.skipped})));
    console.table([...this.queue.pages.values()].flatMap(p=>(p.result?.reportContext?.acquisition?.attempts??
      this.failureReports.get(p)?.context.acquisition?.attempts??[]).map(a=>({page:p.id,...a}))));
    console.table([...this.queue.pages.values()].filter(p=>p.result).map(p=>({page:p.id,...p.result?.coverage})));
  }
  private observe():void {
    this.disconnect();this.events=new AbortController();
    this.observer=new MutationObserver(records=>{
      if(records.every(r=>(r.target instanceof Element?r.target:r.target.parentElement)?.closest("[data-yomiscan]")))return;
      this.scheduleScan();
    });
    // Debounced attribute filter; scan only while the user explicitly enabled chapter mode.
    this.observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["src","srcset","sizes","data-src","data-srcset","class","style","hidden"]});
    this.intersection=new IntersectionObserver(entries=>{
      for(const entry of entries)if(entry.isIntersecting)this.queue.visible(entry.target,entry.intersectionRatio>=.999);
      this.overlays.schedule();
    },{threshold:[0,1]});
    document.addEventListener("load",event=>{
      if(event.target instanceof HTMLImageElement && !event.target.closest("[data-yomiscan]")) {
        const image=event.target,signature=`${image.currentSrc||image.src}|${image.naturalWidth}x${image.naturalHeight}`;
        // Source changes already invalidate identity. Increment only for a reload of
        // the same source/dimensions; otherwise attribute+load events duplicate jobs.
        if(this.loadedSources.get(image)===signature)this.versions.set(image,(this.versions.get(image)??0)+1);
        this.loadedSources.set(image,signature);this.scheduleScan();
      }
    },{capture:true,signal:this.events.signal});
    window.addEventListener("resize",()=>this.scheduleScan(),{signal:this.events.signal});
    window.addEventListener('scroll',()=>{
      for(const p of this.queue.pages.values()){
        const r=p.source.image.getBoundingClientRect();if(r.bottom>0&&r.top<innerHeight)this.queue.visible(p.key,r.top>=0&&r.bottom<=innerHeight);
      }
    },{passive:true,signal:this.events.signal});
    document.addEventListener("visibilitychange",()=>{if(!document.hidden)this.scheduleScan();},{signal:this.events.signal});
    // SPA pushState has no native event. This lightweight URL check also clears cached URLs.
  }
  private scheduleScan():void {clearTimeout(this.discoveryTimer);this.discoveryTimer=window.setTimeout(()=>this.scan(),150);}
  private scan():void {
    if(this.disposed)return;
    const {candidates,decisions}=this.discovery.discover(document);this.decisions=decisions;
    const found=new Set(candidates.map(c=>c.image));
    for(const [key,page] of this.queue.pages) if(!found.has(page.source.image))this.queue.remove(key);
    this.intersection?.disconnect();
    for(const candidate of candidates) {
      const signature=`${candidate.source}|${candidate.width}x${candidate.height}`;
      if(!this.loadedSources.has(candidate.image))this.loadedSources.set(candidate.image,signature);
      const identity=`${this.generation}|${signature}|${this.versions.get(candidate.image)??0}`;
      this.queue.register(candidate.image,identity,candidate);this.intersection?.observe(candidate.image);
    }
    const records=new Set<object>(this.queue.pages.values());
    for(const page of this.failureReports.keys())if(!records.has(page))this.failureReports.delete(page);
    this.update();
  }
  private async process(page:PageRecord<MangaPageCandidate,PageImageResult>,signal:AbortSignal):Promise<PageImageResult> {
    const candidate=page.source,start=performance.now();
    const context:PageReportContext={page_id:page.id,job_id:`${page.id}-${page.attempts}`,width:candidate.width,height:candidate.height,
      state:'processing',extension_version:chrome.runtime.getManifest().version,timings:{}};
    let failed=false;
    const renderOnly=this.rerenders.delete(page.key),english=this.englishRequests.delete(page.key),scale=this.fontScale;
    this.stage=english?'Rendering English':'Acquiring page image';this.update();
    const progress=(status:import('./progress').JobProgress)=>{if(!signal.aborted&&!this.disposed&&this.queue.pages.get(page.key)===page){this.stage=progressLabel(status);this.update();}};
    try {
      const previous=page.result;
      if(this.mode==='read'){
        if(english&&previous?.reading&&previous.original)return await this.renderEnglish(previous,previous.reading,previous.original,signal,context,scale,progress);
        return await this.readPage(candidate,signal,context,page.refreshing===true,progress);
      }
      const result=await this.processImage(candidate,signal,context,page.refreshing===true,renderOnly,scale,progress);
      if(renderOnly&&previous&&!retainsRenderedBlocks(previous,result)){
        if(result.url)URL.revokeObjectURL(result.url);
        this.notice='Font change could not preserve all previously rendered bubbles. Previous translation retained; try a smaller font or reset.';
        throw new Error(this.notice);
      }
      return result;
    }
    catch(error){
      failed=true;if(english)this.englishShown.delete(page.key);
      if(error instanceof ConfigurationChanged){this.dispose();this.changed({...this.summary(),message:error.message});}
      context.state=signal.aborted||error instanceof SkipPage?'skipped':'failed';context.error_code=signal.aborted?'cancelled':
      error instanceof AcquisitionError?'acquisition_failed':'page_processing_failed';throw error;}
    finally {this.stage='';context.timings.total_ms=performance.now()-start;
      if(failed && !this.disposed && this.queue.pages.get(page.key)===page)this.rememberFailure(page,context);
      else this.failureReports.delete(page);}
  }
  private async processImage(candidate:MangaPageCandidate,signal:AbortSignal,context:PageReportContext,refresh:boolean,renderOnly=false,scale=1,
    progress?:(status:import('./progress').JobProgress)=>void):Promise<PageImageResult> {
    const pixels=await this.acquirePixels(candidate,signal,context);
    return this.renderPixels(pixels,signal,context,{refresh,renderOnly,scale,progress});
  }
  /** Reading mode: analyze the page for study (no rendering) and keep its pixels for English on request. */
  private async readPage(candidate:MangaPageCandidate,signal:AbortSignal,context:PageReportContext,refresh:boolean,
    progress:(status:import('./progress').JobProgress)=>void):Promise<PageImageResult> {
    const pixels=await this.acquirePixels(candidate,signal,context);
    const start=performance.now();
    this.stage='Reading page locally';this.update();
    const data=await analyzePage(pixels.blob,signal,{refresh,configuration:this.configuration,translation:this.translation,progress}).finally(()=>{
      context.timings.backend_roundtrip_ms=performance.now()-start;
    });signal.throwIfAborted();
    const reading=parseReadingPage(data,{width:pixels.width,height:pixels.height});
    context.state='translated';
    return {bytes:pixels.blob.size+readingBytes(reading)+new TextEncoder().encode(JSON.stringify(context)).length+1024,
      rendered:0,skipped:0,reading,original:pixels.blob,reportContext:context};
  }
  /** Reading mode: render a read page in English from its retained pixels (no new acquisition).
   * The backend reuses the cached detection, OCR and translation of the earlier analysis. */
  private async renderEnglish(previous:PageImageResult,reading:ReadingPage,original:Blob,signal:AbortSignal,context:PageReportContext,
    scale:number,progress:(status:import('./progress').JobProgress)=>void):Promise<PageImageResult> {
    const pixels={blob:original,width:reading.width,height:reading.height};
    context.acquisition=previous.reportContext?.acquisition;context.width=pixels.width;context.height=pixels.height;
    const rendered=await this.renderPixels(pixels,signal,context,{refresh:false,renderOnly:false,scale,progress});
    return {...rendered,reading,bytes:rendered.bytes+readingBytes(reading)};
  }
  private async acquirePixels(candidate:MangaPageCandidate,signal:AbortSignal,context:PageReportContext):Promise<PagePixels> {
    const acquisitionStart=performance.now();
    const style=getComputedStyle(candidate.image);
    if(style.transform!=='none' || [style.paddingLeft,style.paddingRight,style.paddingTop,style.paddingBottom,
      style.borderLeftWidth,style.borderRightWidth,style.borderTopWidth,style.borderBottomWidth].some(v=>parseFloat(v)>0))
      throw new SkipPage('Transformed, padded or bordered image geometry is unsupported');
    this.acquiring=new AbortController();
    const acquisitionSignal=AbortSignal.any([signal,this.acquiring.signal]);
    const acquirer=new PageImageAcquirer({
      direct:async(c,s)=>{
        this.sourceTicket={id:crypto.randomUUID(),candidate:c};
        try{return await fetchFromExtension(this.sourceTicket.id,s);}finally{this.sourceTicket=null;}
      },
      canvas:canvasPixels,
      viewport:(c,s)=>this.captureWithUI(()=>this.screenshot(c,s)),
      stitch:(c,s)=>{
        if(!this.allowStitch)throw new SkipPage('Scroll capture is disabled; enable “Allow scroll capture” and Retry');
        return this.captureWithUI(()=>stitchPage(c,s,(rect,innerSignal)=>this.screenshot(c,innerSignal,rect)));
      },
    });
    let pixels:PagePixels;
    try {
      const acquired=await acquirer.acquire(candidate,acquisitionSignal);pixels=acquired;
      context.acquisition={method:acquired.method,attempts:acquired.attempts};
      context.width=pixels.width;context.height=pixels.height;
    } catch(error) {
      if(error instanceof AcquisitionError){
        context.acquisition={attempts:error.attempts};}
      throw error;
    } finally {this.acquiring=null;context.timings.acquisition_ms=performance.now()-acquisitionStart;}
    signal.throwIfAborted();
    if(!candidate.image.isConnected || (candidate.image.currentSrc||candidate.image.src)!==candidate.source)
      throw new SkipPage('Image source changed during acquisition');
    if(Math.abs(pixels.width/pixels.height-candidate.width/candidate.height)>.02)throw new SkipPage('Source pixels do not match displayed image proportions');
    return pixels;
  }
  private async renderPixels(pixels:{blob:Blob;width:number;height:number},signal:AbortSignal,context:PageReportContext,
    {refresh,renderOnly,scale,progress}:{refresh:boolean;renderOnly:boolean;scale:number;progress?:(status:import('./progress').JobProgress)=>void}):Promise<PageImageResult> {
    const renderStart=performance.now();
    this.stage='Processing locally';this.update();
    const result=await renderPage(pixels.blob,signal,{refresh,renderOnly,fontScale:scale,configuration:this.configuration,translation:this.translation,progress}).finally(()=>{
      context.timings.backend_roundtrip_ms=performance.now()-renderStart;
    });signal.throwIfAborted();
    this.stage='Finalizing output';this.update();
    context.input_sha256=result.input_sha256;
    if(result.snapshot && (result.snapshot.image.input_sha256!==context.input_sha256 ||
      result.snapshot.image.width!==pixels.width||result.snapshot.image.height!==pixels.height))
      throw new Error('Diagnostic page identity mismatch; result rejected.');
    // Original pixels, PNG and snapshot have one result owner and one budget entry.
    const retainedBytes=result.blob.size+pixels.blob.size+new TextEncoder().encode(JSON.stringify(result.snapshot??null)).length+
      new TextEncoder().encode(JSON.stringify(context)).length+1024;
    const url=URL.createObjectURL(result.blob),probe=new Image();probe.src=url;
    try {
      await probe.decode();signal.throwIfAborted();
      if(probe.naturalWidth!==pixels.width || probe.naturalHeight!==pixels.height)throw new Error("Backend returned different page dimensions");
    } catch(error) {
      URL.revokeObjectURL(url);
      throw new SkipPage("Rendered image could not be displayed. Reader content policy or invalid response; original preserved.",{cause:error});
    } finally {probe.removeAttribute("src");}
    context.state='translated';
    return {url,bytes:retainedBytes,rendered:result.rendered,skipped:result.skipped,coverage:result.coverage,
      snapshot:result.snapshot,reportContext:context,original:pixels.blob};
  }
  private async captureWithUI(work:()=>Promise<PagePixels>):Promise<PagePixels> {
    this.overlays.suspended=true;this.overlays.schedule();this.hideControls(true);this.reading?.suspend(true);
    try {return await work();}
    finally {this.overlays.suspended=false;this.overlays.schedule();this.hideControls(false);this.reading?.suspend(false);}
  }
  private async screenshot(candidate:MangaPageCandidate,signal:AbortSignal,segment?:Rect):Promise<PagePixels> {
    signal.throwIfAborted();
    const r=candidate.image.getBoundingClientRect(),vp=currentViewport();
    const rect=segment??{x:r.x,y:r.y,width:r.width,height:r.height};
    if(document.hidden || vp.scale!==1 || !validSelection(rect,vp) ||
       Math.abs(r.width/r.height-candidate.width/candidate.height)>.02)
      throw new WaitForViewport('Viewport capture cannot contain this image/segment; active tab and unclipped geometry required');
    this.capture={id:crypto.randomUUID(),source:candidate,viewport:vp,rect,imageRect:{x:r.x,y:r.y,width:r.width,height:r.height}};
    try {
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      // Reject obvious occlusion by sticky headers/dialogs/other reader UI.
      signal.throwIfAborted();
      for(const x of [.01,.25,.5,.75,.99])for(const y of [.01,.25,.5,.75,.99])if(document.elementFromPoint(rect.x+rect.width*x,rect.y+rect.height*y)!==candidate.image)
        throw new SkipPage("Page is obscured by other content. Dismiss it and retry.");
      const reply=await chrome.runtime.sendMessage({type:"chapter-capture",id:this.capture.id,rect:this.capture.rect,viewport:vp});
      signal.throwIfAborted();
      if(!reply?.ok)throw new SkipPage(reply?.error||"Visible page capture failed");
      if(!verifyTicket(this.capture))throw new SkipPage("Page moved during capture; retry");
      const bytes=Uint8Array.from(atob(reply.data),c=>c.charCodeAt(0));
      return {blob:new Blob([bytes],{type:"image/png"}),width:reply.width,height:reply.height,capture:reply.capture};
    } finally {this.capture=null;}
  }
  resolveSource(id:string):string|null {
    const ticket=this.sourceTicket,c=ticket?.candidate;
    return ticket?.id===id && c?.image.isConnected && c.image.complete && c.image.naturalWidth>0 &&
      (c.image.currentSrc||c.image.src)===c.source ? c.source:null;
  }
  verifyCapture(id:string):boolean{return this.capture?.id===id && verifyTicket(this.capture);}
  private disconnect():void {this.observer?.disconnect();this.intersection?.disconnect();this.events?.abort();clearTimeout(this.discoveryTimer);}
  dispose():void {
    this.inspector?.dispose();
    if(this.disposed)return;this.disposed=true;this.startVersion++;this.disconnect();clearInterval(this.navigationTimer);this.lifetime.abort();this.queue.dispose();this.overlays.dispose();
    this.reading?.dispose();this.reading=null;this.cursor=null;
    this.failureReports.clear();
    for(const url of this.downloads)URL.revokeObjectURL(url);this.downloads.clear();
    this.changed({active:false,total:0,translated:0,failed:0,skipped:0,processing:null,view:"original",mode:this.mode,
      message:"Session cleared. Choose Read Chapter or Translate Chapter for this reader."});
  }
}
