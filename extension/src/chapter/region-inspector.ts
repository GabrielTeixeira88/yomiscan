import {parseAnalysis,type Analysis} from '../api';
import type {Rect} from '../geometry';
import type {PageSnapshot} from './reports';
import {displayedRegion,supportsRegionGeometry} from './region-geometry';

type RecordData=Record<string,unknown>;
const object=(v:unknown):RecordData=>v&&typeof v==='object'&&!Array.isArray(v)?v as RecordData:{};
export interface InspectableRegion {id:string;box:Rect;reason:string;confidence:number|null;detectionConfidence:number|null;text:string;translation:string;study:Analysis|null}
const confidence=(value:unknown):number|null=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1?value:null;
const reasons:Record<string,string>={rendered:'Translated text rendered',ocr_failed:'OCR failed or returned no text',
  ocr_filtered:'OCR did not contain accepted Japanese',translation_or_analysis_failed:'Translation or lexical analysis failed',
  likely_sfx:'Likely sound effect deliberately preserved',geometry_conflict:'Overlapping or close regions preserved',
  mask_failed:'Mask generation failed',inseparable_mask:'Text could not be separated safely from artwork',
  unsafe_background:'Background could not be masked safely',no_layout_region:'No safe text layout region',
  overflow:'Translation did not fit safely',inpainting_failed:'Inpainting failed; original preserved',
  typesetting_failed:'Font or layout failed; original preserved',invalid_geometry_or_unsupported:'Unsupported rendering geometry'};

export function inspectionRegions(snapshot:PageSnapshot):InspectableRegion[] {
  const regions:InspectableRegion[]=[];
  for(const block of snapshot.blocks.slice(0,256)){
    const b=object(block.bbox),render=object(block.render),ocr=object(block.ocr),text=object(block.text);
    let study:Analysis|null=null;
    try{if(text.study){const candidate=parseAnalysis(text.study);
      if(candidate.original_text===text.original&&candidate.translation===text.translation)study=candidate;}}
    catch{ /* Unavailable analysis never triggers new OCR. */ }
    regions.push({id:'B'+block.id,box:{x:Number(b.left),y:Number(b.top),width:Number(b.right)-Number(b.left),height:Number(b.bottom)-Number(b.top)},
      reason:reasons[String(render.reason_code)]??'No detailed processing reason available',
      confidence:confidence(ocr.confidence),detectionConfidence:confidence(block.detection_confidence),
      text:typeof text.original==='string'?text.original:'',translation:typeof text.translation==='string'?text.translation:'',study});
  }
  for(const region of snapshot.regions.slice(0,256-regions.length))if(Array.isArray(region.block_ids)&&region.block_ids.length===0&&Array.isArray(region.bbox)){
    const [left,top,right,bottom]=region.bbox as number[];
    regions.push({id:'R'+region.id,box:{x:left,y:top,width:right-left,height:bottom-top},reason:region.filtered?'Filtered before OCR':'Detected; no analyzed block available',
      confidence:null,detectionConfidence:confidence(region.confidence),text:'',translation:'',study:null});
  }
  return regions;
}

/** One explicitly activated page/result lease; no listener intercepts page clicks. */
export class RegionInspector {
  private host=document.createElement('div');private root=this.host.attachShadow({mode:'closed'});
  private events=new AbortController();private frame=0;private closed=false;
  private regions:InspectableRegion[];private buttons:HTMLButtonElement[]=[];
  private message=document.createElement('p');private text=document.createElement('p');
  private selected:InspectableRegion|null=null;private showText=document.createElement('input');
  private previousFocus=document.activeElement instanceof HTMLElement?document.activeElement:null;
  constructor(private image:HTMLImageElement,private snapshot:PageSnapshot,private current:()=>boolean,
    private study:(analysis:Analysis,anchor:Rect)=>void,private ended:()=>void){
    this.regions=inspectionRegions(snapshot);this.host.dataset.yomiscan='inspector';
    this.host.style.cssText='all:initial!important;position:fixed!important;inset:0!important;pointer-events:none!important;z-index:2147483645!important;';
    const style=document.createElement('style');style.textContent='*{box-sizing:border-box}button,select,input{font:inherit} .region{position:fixed;border:2px dashed #197344;background:#ffffff12;pointer-events:auto;min-width:4px;min-height:4px}.region:focus-visible{outline:3px solid #fc0}.inspect-panel{position:fixed;left:12px;top:12px;width:260px;max-height:70vh;overflow:auto;background:#fffdf8;color:#203729;box-shadow:0 3px 15px #0005;padding:12px;border-radius:8px;font:14px/1.4 system-ui;pointer-events:auto}p{white-space:pre-wrap;overflow-wrap:anywhere}';
    this.root.append(style);
    const panel=document.createElement('section');panel.className='inspect-panel';panel.setAttribute('aria-label','Region inspection');
    const close=document.createElement('button');close.textContent='Close Inspection';close.onclick=()=>this.dispose();
    const selector=document.createElement('select');selector.setAttribute('aria-label','Detected region');
    for(const region of this.regions)selector.add(new Option(region.id+' · '+region.reason,region.id));
    selector.onchange=()=>this.select(this.regions.find(r=>r.id===selector.value)!);
    const label=document.createElement('label');this.showText.type='checkbox';label.append(this.showText,document.createTextNode(' Show Japanese and translation'));
    this.showText.onchange=()=>this.updateText();
    const studyButton=document.createElement('button');studyButton.textContent='Study Bubble';studyButton.onclick=()=>{
      if(!this.current()){this.dispose();return;}
      if(!this.selected?.study){this.message.textContent+='\nWord analysis unavailable. Reprocess this page to study it; no OCR was rerun.';return;}
      const rect=this.geometry(this.selected);if(!rect){this.message.textContent='Unsupported page geometry; inspect after restoring normal layout.';return;}
      const data=this.selected.study;this.dispose();this.study(data,rect);
    };
    panel.append(close,selector,this.message,label,this.text,studyButton);panel.style.zIndex='2';this.root.append(panel);
    // Smaller overlapping regions receive later DOM paint order; all remain in the keyboard list.
    for(const region of [...this.regions].sort((a,b)=>b.box.width*b.box.height-a.box.width*a.box.height)){
      const button=document.createElement('button');button.className='region';button.title=region.id;button.setAttribute('aria-label','Inspect '+region.id);
      button.onclick=event=>{event.stopPropagation();selector.value=region.id;this.select(region);};
      button.dataset.region=region.id;this.buttons.push(button);this.root.append(button);
    }
    document.documentElement.append(this.host);
    const schedule=()=>{if(!this.frame)this.frame=requestAnimationFrame(()=>{this.frame=0;this.refresh();});};
    window.addEventListener('scroll',schedule,{capture:true,passive:true,signal:this.events.signal});
    window.addEventListener('resize',schedule,{signal:this.events.signal});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();this.dispose();}},{capture:true,signal:this.events.signal});
    if(this.regions[0])this.select(this.regions[0]);else this.message.textContent='No retained regions available; the snapshot may have reached its size limit.';
    this.refresh();close.focus({preventScroll:true});
  }
  private geometry(region:InspectableRegion):Rect|null {
    return supportsRegionGeometry(this.image)?displayedRegion(region.box,this.snapshot.image,this.image.getBoundingClientRect()):null;
  }
  private select(region:InspectableRegion):void {
    if(!this.current()){this.dispose();return;}
    this.selected=region;this.message.textContent=region.id+' · '+region.reason+
      (region.detectionConfidence===null?'\nDetector confidence unavailable.':'\nDetector confidence '+region.detectionConfidence.toFixed(3)+' (uncalibrated).')+
      (region.confidence===null?'\nOCR confidence unavailable.':'\nOCR confidence '+region.confidence.toFixed(3)+' (uncalibrated).');this.updateText();
  }
  private updateText():void {this.text.textContent=this.showText.checked&&this.selected?
    this.selected.text+'\n'+this.selected.translation:'';}
  refresh():void {
    if(this.closed)return;
    if(!this.current()){this.dispose();return;}
    for(const button of this.buttons){const region=this.regions.find(r=>r.id===button.dataset.region)!,rect=this.geometry(region);
      button.hidden=!rect;if(rect){
        let left=Math.max(0,rect.x),top=Math.max(0,rect.y),right=Math.min(innerWidth,rect.x+rect.width),bottom=Math.min(innerHeight,rect.y+rect.height);
        for(let parent=this.image.parentElement;parent;parent=parent.parentElement){const css=getComputedStyle(parent),bounds=parent.getBoundingClientRect();
          if(/hidden|clip|scroll|auto/.test(css.overflowX)){left=Math.max(left,bounds.left);right=Math.min(right,bounds.right);}
          if(/hidden|clip|scroll|auto/.test(css.overflowY)){top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom);}}
        button.hidden=right<=left||bottom<=top;
        Object.assign(button.style,{left:rect.x+'px',top:rect.y+'px',width:rect.width+'px',height:rect.height+'px',
          clipPath:`inset(${Math.max(0,top-rect.y)}px ${Math.max(0,rect.x+rect.width-right)}px ${Math.max(0,rect.y+rect.height-bottom)}px ${Math.max(0,left-rect.x)}px)`});}}
    if(!supportsRegionGeometry(this.image))this.message.textContent='Transformed or bordered page geometry is unsupported; restore its normal layout.';
  }
  dispose():void {if(this.closed)return;this.closed=true;this.events.abort();cancelAnimationFrame(this.frame);this.host.remove();this.ended();this.previousFocus?.focus({preventScroll:true});}
}
