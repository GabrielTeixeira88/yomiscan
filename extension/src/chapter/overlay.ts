import type {MangaPageCandidate} from "./discovery";
import type {PageRecord, ViewMode} from "./model";
import type {PageCoverage} from './coverage';
export interface PageImageResult { url: string; bytes: number; rendered: number; skipped: number; coverage?:PageCoverage }

/** Fixed, pointer-transparent siblings: never rewrite the site's img/srcset/layout. */
export class ChapterOverlays {
  private host = document.createElement("div");
  private root = this.host.attachShadow({mode:"closed"});
  private images = new Map<number, HTMLImageElement>();
  private frame = 0;
  private pages: PageRecord<MangaPageCandidate,PageImageResult>[] = [];
  private view: ViewMode = "english";
  suspended = false;
  private events = new AbortController();
  private resize = new ResizeObserver(()=>this.schedule());
  constructor() {
    this.host.dataset.yomiscan="overlays";
    this.host.style.cssText="all:initial!important;position:fixed!important;inset:0!important;pointer-events:none!important;z-index:2147483644!important;";
    document.documentElement.append(this.host);
    window.addEventListener("scroll",()=>this.schedule(),{capture:true,passive:true,signal:this.events.signal});
    window.addEventListener("resize",()=>this.schedule(),{signal:this.events.signal});
    document.addEventListener("load",()=>this.schedule(),{capture:true,signal:this.events.signal});
    visualViewport?.addEventListener("resize",()=>this.schedule(),{signal:this.events.signal});
  }
  update(pages: PageRecord<MangaPageCandidate,PageImageResult>[],view:ViewMode):void {
    this.pages=pages; this.view=view;
    const ids=new Set(pages.filter(p=>p.result).map(p=>p.id));
    for(const [id,image] of this.images) if(!ids.has(id)){image.remove();this.images.delete(id);}
    this.resize.disconnect();
    for(const page of pages) this.resize.observe(page.source.image);
    this.schedule();
  }
  schedule():void { if(!this.frame) this.frame=requestAnimationFrame(()=>{this.frame=0;this.paint();}); }
  private paint():void {
    this.host.style.setProperty("visibility",this.suspended || this.view==="original" ? "hidden" : "visible","important");
    for(const page of this.pages) {
      if(!page.result) continue;
      let overlay=this.images.get(page.id);
      if(!overlay) {
        overlay=document.createElement("img"); overlay.alt=""; overlay.setAttribute("aria-hidden","true");
        overlay.style.cssText="position:fixed;pointer-events:none;margin:0;padding:0;border:0;display:block;max-width:none;max-height:none;";
        this.images.set(page.id,overlay);this.root.append(overlay);
      }
      const source=page.source.image, r=source.getBoundingClientRect(), style=getComputedStyle(source);
      const visible=source.isConnected && (source.currentSrc||source.src)===page.source.source && source.naturalWidth===page.source.width && source.naturalHeight===page.source.height &&
        r.width>0 && r.height>0 && style.visibility==="visible" && style.display!=="none" && Number(style.opacity)>0;
      overlay.style.display=visible?"block":"none";
      // Release decoded bitmap surfaces for offscreen pages, retain compressed Blob URL.
      if(!visible || this.view==="original" || r.bottom < -innerHeight || r.top > 2*innerHeight) {overlay.removeAttribute("src");continue;}
      if(overlay.getAttribute("src")!==page.result.url) overlay.src=page.result.url;
      let left=Math.max(0,r.left), top=Math.max(0,r.top), right=Math.min(innerWidth,r.right), bottom=Math.min(innerHeight,r.bottom);
      for(let parent=source.parentElement;parent;parent=parent.parentElement) {
        const css=getComputedStyle(parent), bounds=parent.getBoundingClientRect();
        if(/hidden|clip|scroll|auto/.test(css.overflowX)){left=Math.max(left,bounds.left);right=Math.min(right,bounds.right);}
        if(/hidden|clip|scroll|auto/.test(css.overflowY)){top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom);}
      }
      Object.assign(overlay.style,{left:`${r.left}px`,top:`${r.top}px`,width:`${r.width}px`,height:`${r.height}px`,
        objectFit:style.objectFit,objectPosition:style.objectPosition,borderRadius:style.borderRadius,opacity:style.opacity,
        clipPath:`inset(${Math.max(0,top-r.top)}px ${Math.max(0,r.right-right)}px ${Math.max(0,r.bottom-bottom)}px ${Math.max(0,left-r.left)}px)`});
    }
  }
  dispose():void {this.events.abort();this.resize.disconnect();cancelAnimationFrame(this.frame);this.host.remove();this.images.clear();this.pages=[];}
}
