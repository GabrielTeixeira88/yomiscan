import {sameViewport, type Viewport} from "../geometry";
import {SkipPage} from "./model";
import {MAX_INPUT} from './wire';
import type {MangaPageCandidate} from "./discovery";
export const currentViewport=():Viewport=>({width:innerWidth,height:innerHeight,scrollX,scrollY,scale:visualViewport?.scale??1});
export interface PagePixels {blob:Blob;width:number;height:number;capture?:{scaleX:number;scaleY:number;x:number;y:number;width:number;height:number}}
export type AcquisitionMethod='direct-extension-fetch'|'canvas'|'viewport-capture'|'stitched-capture';
export interface AcquisitionAttempt {method:AcquisitionMethod;success:boolean;reason?:string}
export interface AcquiredPage extends PagePixels {method:AcquisitionMethod;attempts:AcquisitionAttempt[]}
export class AcquisitionError extends SkipPage {
  constructor(readonly attempts:AcquisitionAttempt[]) {
    super(`Image acquisition failed: ${attempts.at(-1)?.reason??'No method succeeded'}.`+
      (attempts.some(a=>a.reason?.includes('permission not granted'))?' Grant image-host access using Retry.':' See acquisition diagnostics for earlier failures.'));
  }
}
export interface AcquisitionStrategies {
  direct(candidate:MangaPageCandidate,signal:AbortSignal):Promise<PagePixels>;
  canvas(candidate:MangaPageCandidate,signal:AbortSignal):Promise<PagePixels>;
  viewport(candidate:MangaPageCandidate,signal:AbortSignal):Promise<PagePixels>;
  stitch(candidate:MangaPageCandidate,signal:AbortSignal):Promise<PagePixels>;
}
export class PageImageAcquirer {
  constructor(private readonly strategies:AcquisitionStrategies) {}
  async acquire(candidate:MangaPageCandidate,signal:AbortSignal):Promise<AcquiredPage> {
    const attempts:AcquisitionAttempt[]=[];
    const methods:[AcquisitionMethod,AcquisitionStrategies[keyof AcquisitionStrategies]][]=[];
    if(/^https?:/.test(candidate.source))methods.push(['direct-extension-fetch',this.strategies.direct]);
    methods.push(['canvas',this.strategies.canvas],['viewport-capture',this.strategies.viewport],['stitched-capture',this.strategies.stitch]);
    for(const [method,run] of methods) {
      signal.throwIfAborted();
      try {
        const pixels=await run(candidate,signal);signal.throwIfAborted();
        if(pixels.blob.size>MAX_INPUT || pixels.width*pixels.height>12_000_000)throw new Error('Image exceeds backend size limits');
        attempts.push({method,success:true});return {...pixels,method,attempts};
      } catch(error) {
        signal.throwIfAborted();
        attempts.push({method,success:false,reason:error instanceof Error?error.message:'Acquisition failed'});
      }
    }
    throw new AcquisitionError(attempts);
  }
}
export interface CaptureTicket { id:string; source:MangaPageCandidate; viewport:Viewport; rect:{x:number;y:number;width:number;height:number}; imageRect?:{x:number;y:number;width:number;height:number} }
export function verifyTicket(ticket:CaptureTicket):boolean {
  const image=ticket.source.image,r=image.getBoundingClientRect();
  const expected=ticket.imageRect??ticket.rect;
  return image.isConnected && (image.currentSrc||image.src)===ticket.source.source && !document.hidden &&
    sameViewport(ticket.viewport,currentViewport()) && [r.x-expected.x,r.y-expected.y,r.width-expected.width,r.height-expected.height].every(v=>Math.abs(v)<.5);
}
export async function canvasPixels(candidate:MangaPageCandidate,signal:AbortSignal):Promise<PagePixels> {
  const image=candidate.image;
  if(!image.complete || !image.naturalWidth) throw new SkipPage("Image has not loaded. Retry after it appears.");
  if(candidate.width*candidate.height>12_000_000) throw new SkipPage("Page exceeds the backend's 12 megapixel limit");
  const style=getComputedStyle(image);
  if(style.transform!=="none" || [style.paddingLeft,style.paddingRight,style.paddingTop,style.paddingBottom,
    style.borderLeftWidth,style.borderRightWidth,style.borderTopWidth,style.borderBottomWidth].some(v=>parseFloat(v)>0))
    throw new SkipPage("Transformed, padded or bordered reader images are not supported by aligned overlays");
  const canvas=document.createElement("canvas");canvas.width=candidate.width;canvas.height=candidate.height;
  try {
    const ctx=canvas.getContext("2d");if(!ctx) throw new Error("Could not acquire page pixels");
    ctx.drawImage(image,0,0,canvas.width,canvas.height);
    const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(value=>value?resolve(value):reject(new Error("Page encoding failed")),"image/png"));
    signal.throwIfAborted();
    if((image.currentSrc||image.src)!==candidate.source) throw new SkipPage("Image source changed; waiting for the new page");
    return {blob,width:candidate.width,height:candidate.height};
  } catch(error) {
    if(error instanceof DOMException && error.name==="SecurityError") throw new Error('Canvas pixels are cross-origin restricted',{cause:error});
    throw error;
  } finally {canvas.width=canvas.height=0;}
}
