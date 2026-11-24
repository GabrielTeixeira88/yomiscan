import type {Rect} from '../geometry';
import {displayedRegion,supportsRegionGeometry} from './region-geometry';
import type {ReadingPage} from './reading';

export type EnglishState='off'|'loading'|'on';
export interface ReadingLayerPage {key:object;id:number;image:HTMLImageElement;source:string;reading:ReadingPage;english:EnglishState;
  /** Browser engine: English is drawn as text boxes over the bubbles instead of a rendered page image. */
  textOverlay?:boolean}

/** Largest font (7–26 px) at which `box` shows its whole text without overflowing its own size.
 * Wrapped text always spans the full width, so overflow is judged on the box's client area. */
export function fitText(box:HTMLElement):number {
  const fits=()=>box.scrollHeight<=box.clientHeight+.5&&box.scrollWidth<=box.clientWidth+.5;
  let low=7,high=26;
  while(high-low>.5){
    const mid=(low+high)/2;box.style.fontSize=mid+'px';
    if(fits())low=mid;else high=mid;
  }
  box.style.fontSize=low+'px';
  return low;
}

export const READABLE_PX=11;
/** Widths to try around a detected text column. Japanese columns are often tall and narrow
 * (vertical text) while English needs width, so the box may grow sideways, centered on the bubble. */
export const fitWidths=(width:number)=>[width,width*1.5,width*2,Math.max(width*2.5,120)];

/** Smallest of `fitWidths` at which the text reaches a readable size (else the widest), and its font. */
export function fitBox(box:HTMLElement,width:number,height:number):{width:number;font:number} {
  let best={width,font:0};
  box.style.height=height+'px';
  for(const candidate of fitWidths(width)){
    box.style.width=candidate+'px';
    const font=fitText(box);
    if(font>best.font)best={width:candidate,font};
    if(font>=READABLE_PX)return {width:candidate,font};
  }
  box.style.width=best.width+'px';fitText(box);
  return best;
}

/** The displayed rectangle of a bubble, or null when the page geometry cannot be mapped safely. */
export function bubbleRect(page:ReadingLayerPage,index:number):Rect|null {
  const bubble=page.reading.bubbles[index],image=page.image;
  if(!bubble||!image.isConnected||(image.currentSrc||image.src)!==page.source||!supportsRegionGeometry(image))return null;
  return displayedRegion(bubble.box,page.reading,image.getBoundingClientRect());
}

/** Clip a fixed-position element to the parts of `rect` that the page's scroll containers show. */
function clip(image:HTMLImageElement,rect:Rect):{hidden:boolean;inset:string} {
  let left=Math.max(0,rect.x),top=Math.max(0,rect.y),right=Math.min(innerWidth,rect.x+rect.width),bottom=Math.min(innerHeight,rect.y+rect.height);
  for(let parent=image.parentElement;parent;parent=parent.parentElement){const css=getComputedStyle(parent),bounds=parent.getBoundingClientRect();
    if(/hidden|clip|scroll|auto/.test(css.overflowX)){left=Math.max(left,bounds.left);right=Math.min(right,bounds.right);}
    if(/hidden|clip|scroll|auto/.test(css.overflowY)){top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom);}}
  return {hidden:right<=left||bottom<=top,
    inset:`${Math.max(0,top-rect.y)}px ${Math.max(0,rect.x+rect.width-right)}px ${Math.max(0,rect.y+rect.height-bottom)}px ${Math.max(0,left-rect.x)}px`};
}

const STYLE=`*{box-sizing:border-box}
.bubble{position:fixed;margin:0;padding:0;border:1px dashed #2a7a4b66;border-radius:6px;background:transparent;cursor:pointer;pointer-events:auto;min-width:6px;min-height:6px}
.bubble:hover,.bubble:focus-visible{border:2px solid #2a7a4b;background:#2a7a4b14;outline:none}
.bubble.active{border:2px solid #d18b00;background:#d18b0014}
.translation{position:fixed;margin:0;padding:3px;border-radius:8px;background:#fffffff2;color:#111;font-family:'Comic Sans MS','Segoe UI',system-ui,sans-serif;
  line-height:1.15;text-align:center;display:flex;align-items:center;justify-content:center;overflow:hidden;overflow-wrap:normal;word-break:normal;pointer-events:none;box-shadow:0 0 0 1px #0001}
.translation[hidden]{display:none}
.english{position:fixed;pointer-events:auto;font:600 12px/1 system-ui;padding:6px 8px;border-radius:6px;border:1px solid #b7c5ba;background:#fffdf8e6;color:#203729;cursor:pointer;box-shadow:0 2px 8px #0003}
.english[aria-pressed=true]{background:#235d3c;color:#fff}
.english:focus-visible{outline:2px solid #fc0}`;

/** Clickable bubble outlines over every read page; never rewrites the reader's own elements. */
export class ReadingLayer {
  private host=document.createElement('div');private root=this.host.attachShadow({mode:'closed'});
  private events=new AbortController();private frame=0;
  private pages:ReadingLayerPage[]=[];
  private built=new Map<object,{reading:ReadingPage;bubbles:HTMLButtonElement[];english:HTMLButtonElement;texts:HTMLDivElement[];fitted:string[]}>();
  private active:{key:object;bubble:number}|null=null;
  private suspended=false;
  constructor(private study:(key:object,bubble:number)=>void,private toggleEnglish:(key:object)=>void){
    this.host.dataset.yomiscan='reading';
    this.host.style.cssText='all:initial!important;position:fixed!important;inset:0!important;pointer-events:none!important;z-index:2147483645!important;';
    const style=document.createElement('style');style.textContent=STYLE;this.root.append(style);
    document.documentElement.append(this.host);
    // Readers often turn pages on any click; a bubble click belongs to YomiScan only.
    for(const name of ['pointerdown','pointerup','mousedown','mouseup','click','dblclick'])
      this.host.addEventListener(name,event=>event.stopPropagation(),{signal:this.events.signal});
    const schedule=()=>this.schedule();
    window.addEventListener('scroll',schedule,{capture:true,passive:true,signal:this.events.signal});
    window.addEventListener('resize',schedule,{signal:this.events.signal});
    visualViewport?.addEventListener('resize',schedule,{signal:this.events.signal});
  }
  update(pages:ReadingLayerPage[]):void {
    this.pages=pages;
    const keys=new Set(pages.map(p=>p.key));
    const drop=(entry:{bubbles:HTMLElement[];english:HTMLElement;texts:HTMLElement[]})=>{entry.bubbles.forEach(b=>b.remove());entry.texts.forEach(t=>t.remove());entry.english.remove();};
    for(const [key,entry] of this.built)if(!keys.has(key)){drop(entry);this.built.delete(key);}
    for(const page of pages){
      let entry=this.built.get(page.key);
      if(entry&&entry.reading!==page.reading){drop(entry);this.built.delete(page.key);entry=undefined;}
      if(!entry){
        // Translation boxes first, so the transparent bubble buttons stay on top and clickable.
        const texts=page.reading.bubbles.map(bubble=>{const box=document.createElement('div');box.className='translation';box.lang='en';
          box.textContent=bubble.analysis.translation??'';box.hidden=true;this.root.append(box);return box;});
        // Larger boxes first so smaller overlapping bubbles paint on top and stay clickable.
        const order=page.reading.bubbles.map((_,i)=>i).sort((a,b)=>{const x=page.reading.bubbles[a].box,y=page.reading.bubbles[b].box;return y.width*y.height-x.width*x.height;});
        const bubbles:HTMLButtonElement[]=[];
        for(const index of order){
          const button=document.createElement('button'),bubble=page.reading.bubbles[index];
          button.className='bubble';button.dataset.bubble=String(index);
          button.setAttribute('aria-label',`Study page ${page.id} bubble ${index+1}: ${bubble.analysis.original_text.slice(0,40)}`);
          button.addEventListener('click',event=>{event.preventDefault();this.study(page.key,index);});
          bubbles[index]=button;this.root.append(button);
        }
        const english=document.createElement('button');english.className='english';
        english.addEventListener('click',event=>{event.preventDefault();this.toggleEnglish(page.key);});
        this.root.append(english);
        entry={reading:page.reading,bubbles,english,texts,fitted:texts.map(()=>'')};this.built.set(page.key,entry);
      }
      entry.english.textContent=page.english==='loading'?'English…':page.english==='on'?'Japanese':'English';
      entry.english.setAttribute('aria-pressed',String(page.english==='on'));
      entry.english.title=page.english==='on'?`Show page ${page.id}'s original Japanese`:`Show page ${page.id} in English (local renderer)`;
      entry.english.disabled=page.english==='loading';
    }
    this.highlight(this.active);this.schedule();
  }
  /** Mark the bubble whose study card is open; null clears it. */
  highlight(active:{key:object;bubble:number}|null):void {
    this.active=active;
    for(const [key,entry] of this.built)entry.bubbles.forEach((b,i)=>b.classList.toggle('active',key===active?.key&&i===active.bubble));
  }
  /** Hide at once (not on the next frame) so a viewport capture never contains or hit-tests the outlines. */
  suspend(value:boolean):void {
    this.suspended=value;this.host.style.setProperty('visibility',value?'hidden':'visible','important');if(!value)this.schedule();
  }
  schedule():void {if(!this.frame)this.frame=requestAnimationFrame(()=>{this.frame=0;this.paint();});}
  private paint():void {
    this.host.style.setProperty('visibility',this.suspended?'hidden':'visible','important');
    for(const page of this.pages){
      const entry=this.built.get(page.key);if(!entry)continue;
      const shown=page.image.isConnected&&(page.image.currentSrc||page.image.src)===page.source&&supportsRegionGeometry(page.image);
      const r=page.image.getBoundingClientRect(),onScreen=shown&&r.bottom>0&&r.top<innerHeight&&r.width>0;
      const text=page.textOverlay===true&&page.english==='on';
      entry.bubbles.forEach((button,index)=>{
        const rect=onScreen?bubbleRect(page,index):null,view=rect?clip(page.image,rect):null,shown=!!rect&&!!view&&!view.hidden;
        button.hidden=!shown;
        const box=entry.texts[index],translated=text&&shown&&!!box.textContent;
        box.hidden=!translated;
        if(!shown||!rect||!view)return;
        const place={left:rect.x+'px',top:rect.y+'px',width:rect.width+'px',height:rect.height+'px',clipPath:`inset(${view.inset})`};
        Object.assign(button.style,place);
        if(translated){
          // Refit only when the bubble's displayed size changes (scrolling keeps the size).
          const size=`${Math.round(rect.width)}x${Math.round(rect.height)}`;
          if(entry.fitted[index]!==size){box.style.height=rect.height+'px';box.dataset.width=String(fitBox(box,rect.width,rect.height).width);entry.fitted[index]=size;}
          const boxWidth=Number(box.dataset.width)||rect.width,wide={...rect,x:rect.x+rect.width/2-boxWidth/2,width:boxWidth};
          const wideView=clip(page.image,wide);
          box.hidden=wideView.hidden;
          Object.assign(box.style,{left:wide.x+'px',top:rect.y+'px',width:boxWidth+'px',height:rect.height+'px',clipPath:`inset(${wideView.inset})`});
        }
      });
      // The toggle sits at the page's top-right corner, kept inside the viewport while the page is visible.
      entry.english.hidden=!onScreen;
      if(onScreen)Object.assign(entry.english.style,{left:Math.min(innerWidth-96,Math.max(4,r.right-96))+'px',top:Math.min(innerHeight-36,Math.max(8,r.top+8))+'px'});
    }
  }
  dispose():void {this.events.abort();cancelAnimationFrame(this.frame);this.host.remove();this.built.clear();this.pages=[];}
}
