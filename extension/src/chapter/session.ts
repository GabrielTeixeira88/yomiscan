import {ChapterQueue,SkipPage,WaitForViewport,viewportPriority,type ViewMode} from "./model";
import {GenericPageDiscovery,type MangaPageCandidate,type PageDiscoveryStrategy,type DiscoveryDecision} from "./discovery";
import {ChapterOverlays,type PageImageResult} from "./overlay";
import {PageImageAcquirer,AcquisitionError,canvasPixels,currentViewport,verifyTicket,type AcquisitionAttempt,type CaptureTicket,type PagePixels} from "./acquisition";
import {fetchFromExtension} from './source-client';
import {imageHost} from './source-fetch';
import {stitchPage} from './stitching';
import {validSelection,type Rect} from '../geometry';
import {renderPage} from "./transport";
export interface ChapterSummary { active:boolean; total:number; translated:number; failed:number; skipped:number; processing:number|null; message:string; view:ViewMode }

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
  private bytes=0;
  private disposed=false;
  private startVersion=0;
  private notice="Ready";
  capture:CaptureTicket|null=null;
  debug=false;
  allowStitch=false;
  private acquiring:AbortController|null=null;
  private sourceTicket:{id:string;candidate:MangaPageCandidate}|null=null;
  private acquisitionDiagnostics=new WeakMap<HTMLImageElement,AcquisitionAttempt[]>();
  constructor(private changed:(status:ChapterSummary)=>void,private hideControls:(hidden:boolean)=>void,
              private discovery:PageDiscoveryStrategy=new GenericPageDiscovery()) {
    this.queue=new ChapterQueue({process:(page,signal)=>this.process(page.source,signal),
      priority:page=>{const r=page.source.image.getBoundingClientRect();return viewportPriority(r.top,r.bottom,innerHeight);},
      release:result=>{URL.revokeObjectURL(result.url);this.bytes-=result.bytes;},changed:()=>this.update()});
    this.navigationTimer=window.setInterval(()=>{if(location.href!==this.url)this.dispose();},1000);
    window.addEventListener("pagehide",()=>this.dispose(),{once:true,signal:this.lifetime.signal});
  }
  get isDisposed():boolean{return this.disposed;}
  summary():ChapterSummary {
    const pages=[...this.queue.pages.values()];
    return {active:this.queue.active,total:pages.length,translated:pages.filter(p=>p.state==="translated").length,
      failed:pages.filter(p=>p.state==="failed").length,skipped:pages.filter(p=>p.state==="skipped").length,
      processing:pages.find(p=>p.state==="processing")?.id??null,message:this.notice,view:this.queue.view};
  }
  private update():void {
    if(this.disposed) return;
    this.overlays.update([...this.queue.pages.values()],this.queue.view);
    this.changed(this.summary());
    if(this.debug) console.debug("YomiScan chapter",this.summary());
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
      this.notice="Watching for pages";this.observe();this.scan();
      if(retry)this.queue.retry();else this.queue.start();
    } catch(error) {if(!this.disposed && version===this.startVersion){this.notice=error instanceof Error?error.message:"Backend unavailable";this.update();}}
  }
  resumeAfterPermission(version:number,retry:boolean):void {
    if(!this.disposed && version===this.startVersion)void this.start(retry,true);
  }
  stop():void {this.startVersion++;this.queue.stop();this.acquiring?.abort();this.disconnect();this.notice="Stopped. The current page may finish; completed pages are retained.";this.update();}
  setView(view:ViewMode):void {this.queue.setView(view);}
  async study():Promise<void> {this.stop();this.setView("original");this.notice="Finishing any current page before Select Text…";this.update();await this.queue.idle();}
  diagnostics():void {
    this.debug=!this.debug;
    console.table(this.decisions.map(d=>({source:d.image.currentSrc||d.image.src,width:d.image.naturalWidth,height:d.image.naturalHeight,
      accepted:d.accepted,reason:d.reason,page:this.queue.pages.get(d.image)?.id,state:this.queue.pages.get(d.image)?.state})));
    console.table([...this.queue.pages.values()].map(p=>({id:p.id,state:p.state,attempts:p.attempts,error:p.error,
      rendered:p.result?.rendered,skipped:p.result?.skipped})));
    console.table([...this.queue.pages.values()].flatMap(p=>(this.acquisitionDiagnostics.get(p.source.image)??[]).map(a=>({page:p.id,...a}))));
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
      for(const entry of entries)if(entry.isIntersecting && entry.intersectionRatio>=.999)this.queue.visible(entry.target);
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
      const identity=`${signature}|${this.versions.get(candidate.image)??0}`;
      this.queue.register(candidate.image,identity,candidate);this.intersection?.observe(candidate.image);
    }
    this.update();
  }
  private async process(candidate:MangaPageCandidate,signal:AbortSignal):Promise<PageImageResult> {
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
      this.acquisitionDiagnostics.set(candidate.image,acquired.attempts);
    } catch(error) {
      if(error instanceof AcquisitionError)this.acquisitionDiagnostics.set(candidate.image,error.attempts);
      throw error;
    } finally {this.acquiring=null;}
    signal.throwIfAborted();
    if(!candidate.image.isConnected || (candidate.image.currentSrc||candidate.image.src)!==candidate.source)
      throw new SkipPage('Image source changed during acquisition');
    if(Math.abs(pixels.width/pixels.height-candidate.width/candidate.height)>.02)throw new SkipPage('Source pixels do not match displayed image proportions');
    const result=await renderPage(pixels.blob,signal);signal.throwIfAborted();
    if(this.bytes+result.blob.size>128*1024*1024)throw new SkipPage("Session image cache reached 128 MiB. Clear the session before translating more pages.");
    const url=URL.createObjectURL(result.blob),probe=new Image();probe.src=url;
    try {
      await probe.decode();signal.throwIfAborted();
      if(probe.naturalWidth!==pixels.width || probe.naturalHeight!==pixels.height)throw new Error("Backend returned different page dimensions");
    } catch(error) {
      URL.revokeObjectURL(url);
      throw new SkipPage("Rendered image could not be displayed. Reader content policy or invalid response; original preserved.",{cause:error});
    } finally {probe.removeAttribute("src");}
    this.bytes+=result.blob.size;
    return {url,bytes:result.blob.size,rendered:result.rendered,skipped:result.skipped,coverage:result.coverage};
  }
  private async captureWithUI(work:()=>Promise<PagePixels>):Promise<PagePixels> {
    this.overlays.suspended=true;this.overlays.schedule();this.hideControls(true);
    try {return await work();}
    finally {this.overlays.suspended=false;this.overlays.schedule();this.hideControls(false);}
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
    if(this.disposed)return;this.disposed=true;this.startVersion++;this.disconnect();clearInterval(this.navigationTimer);this.lifetime.abort();this.queue.dispose();this.overlays.dispose();
    this.changed({active:false,total:0,translated:0,failed:0,skipped:0,processing:null,view:"original",message:"Session cleared. Activate Translate Chapter for this reader."});
  }
}
