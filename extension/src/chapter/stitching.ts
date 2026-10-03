import type {Rect} from '../geometry';
import type {MangaPageCandidate} from './discovery';
import type {PagePixels} from './acquisition';

export interface Segment {y:number;height:number}
/** Adjacent half-open slices; shared rounded boundaries avoid duplicate pixel rows. */
export function captureSegments(height:number,available:number):Segment[] {
  if(!Number.isFinite(height)||!Number.isFinite(available)||height<4||available<32)throw new Error('Insufficient capture area');
  const count=Math.ceil(height/available);
  if(count>40)throw new Error('Page requires more than 40 capture segments');
  return Array.from({length:count},(_,i)=>({y:height*i/count,height:height*(i+1)/count-height*i/count}));
}
export function pixelSlice(segment:Segment,scale:number):Segment {
  const y=Math.round(segment.y*scale);
  return {y,height:Math.round((segment.y+segment.height)*scale)-y};
}
export async function withRestoredScroll<T>(read:()=>{x:number;y:number},scroll:(x:number,y:number)=>void,
  work:()=>Promise<T>):Promise<T> {
  const original=read();try{return await work();}finally{scroll(original.x,original.y);}
}
const settle=()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));
function edgeInsets(left:number,right:number):{top:number;bottom:number} {
  let top=8,bottom=8;
  for(const x of [left+2,(left+right)/2,right-2])for(const y of [1,32,96,innerHeight-96,innerHeight-32,innerHeight-1]) {
    let element=document.elementFromPoint(x,y);
    while(element && !element.hasAttribute('data-yomiscan')) {
      const style=getComputedStyle(element),r=element.getBoundingClientRect();
      if(['fixed','sticky'].includes(style.position)) {
        if(r.top<=8 && r.bottom<innerHeight*.45)top=Math.max(top,r.bottom+8);
        if(r.bottom>=innerHeight-8 && r.top>innerHeight*.55)bottom=Math.max(bottom,innerHeight-r.top+8);
      }
      element=element.parentElement;
    }
  }
  return {top,bottom};
}

/** Window-scrolling, axis-aligned readers only. All exits restore the original position. */
export async function stitchPage(candidate:MangaPageCandidate,signal:AbortSignal,
  capture:(rect:Rect,signal:AbortSignal)=>Promise<PagePixels>):Promise<PagePixels> {
  signal.throwIfAborted();
  const image=candidate.image, initial=image.getBoundingClientRect();
  if(document.hidden || (visualViewport?.scale??1)!==1)throw new Error('Capture needs the active tab without pinch zoom');
  if(initial.left<0 || initial.right>innerWidth)throw new Error('Horizontally clipped images cannot be stitched');
  for(let p=image.parentElement;p && p!==document.body && p!==document.documentElement;p=p.parentElement)
    if(/auto|scroll|hidden|clip/.test(getComputedStyle(p).overflowY) && p.scrollHeight>p.clientHeight+1)
      throw new Error('Nested scrolling/clipping readers cannot be stitched');
  const pageTop=initial.top+scrollY, pageLeft=initial.left+scrollX;
  const viewportWidth=innerWidth,viewportHeight=innerHeight;
  const controller=new AbortController();
  const combined=AbortSignal.any([signal,controller.signal]);
  const interrupt=()=>controller.abort(new Error('Capture interrupted by user input'));
  for(const name of ['wheel','touchstart','pointerdown','keydown'])window.addEventListener(name,interrupt,{capture:true,signal:controller.signal});
  const canvas=document.createElement('canvas');
  try {
    return await withRestoredScroll(()=>({x:scrollX,y:scrollY}),
      (x,y)=>window.scrollTo({left:x,top:y,behavior:'instant'}),async()=>{
        window.scrollTo({left:scrollX,top:Math.max(0,pageTop-8),behavior:'instant'});await settle();
        const insets=edgeInsets(initial.left,initial.right);
        const segments=captureSegments(initial.height,innerHeight-insets.top-insets.bottom);
        let scale=0;
        for(const segment of segments) {
          combined.throwIfAborted();
          window.scrollTo({left:scrollX,top:Math.max(0,pageTop+segment.y-insets.top),behavior:'instant'});await settle();
          combined.throwIfAborted();
          const r=image.getBoundingClientRect();
          if(innerWidth!==viewportWidth || innerHeight!==viewportHeight || !image.isConnected || (image.currentSrc||image.src)!==candidate.source ||
            Math.abs(r.width-initial.width)>.5 || Math.abs(r.height-initial.height)>.5 ||
            Math.abs(r.top+scrollY-pageTop)>.5 || Math.abs(r.left+scrollX-pageLeft)>.5)
            throw new Error('Reader layout/source changed while stitching');
          const rect={x:r.left,y:r.top+segment.y,width:r.width,height:segment.height};
          const shot=await capture(rect,combined);combined.throwIfAborted();
          const bitmap=await createImageBitmap(shot.blob);
          try {
            if(!scale) {
              scale=shot.capture?.scaleY??bitmap.width/r.width;
              canvas.width=Math.round(r.width*(shot.capture?.scaleX??scale));canvas.height=Math.round(initial.height*scale);
              if(canvas.width*canvas.height>12_000_000)throw new Error('Stitched image exceeds 12 megapixels');
            }
            if(Math.abs((shot.capture?.scaleY??scale)-scale)>.001 || Math.abs(bitmap.width-canvas.width)>2)throw new Error('Screenshot scale changed while stitching');
            const destination=pixelSlice(segment,scale);
            const source=shot.capture??{x:0,y:0,width:bitmap.width,height:bitmap.height};
            canvas.getContext('2d')!.drawImage(bitmap,source.x,source.y,source.width,source.height,0,destination.y,canvas.width,destination.height);
          } finally {bitmap.close();}
        }
        combined.throwIfAborted();
        const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Stitched image encoding failed')),'image/png'));
        return {blob,width:canvas.width,height:canvas.height};
      });
  } finally {controller.abort();canvas.width=canvas.height=0;}
}
