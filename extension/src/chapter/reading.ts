// Reading mode data: the page's text blocks from /api/v1/analyze-page, each already analyzed for
// study, so clicking a bubble shows its card without another screenshot, OCR or request.
// Pure and DOM-free: parsing, validation and bubble order are unit-tested in Node.
import {parseAnalysis,type Analysis} from '../api';
import type {Rect} from '../geometry';

/** Upper bound on one page's JSON (tokens and meanings for up to 256 blocks). */
export const MAX_READING_JSON=4*1024*1024;
const MAX_BLOCKS=256;

export interface ReadingBubble {id:number;order:number;box:Rect;analysis:Analysis}
export interface ReadingPage {width:number;height:number;bubbles:ReadingBubble[];
  /** Text blocks that produced no study card (filtered, OCR failure or no Japanese). */
  unreadable:number}

type Data=Record<string,unknown>;
const record=(v:unknown):v is Data=>typeof v==='object'&&v!==null&&!Array.isArray(v);
const count=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>=0;

export function parseReadingPage(value:unknown,expected?:{width:number;height:number}):ReadingPage {
  if(!record(value)||!count(value.width)||!count(value.height)||!value.width||!value.height||!Array.isArray(value.text_blocks)||
    value.text_blocks.length>MAX_BLOCKS)throw new Error('Invalid page analysis from local server.');
  const width=value.width,height=value.height;
  if(expected&&(expected.width!==width||expected.height!==height))throw new Error('Page analysis dimensions do not match the page image.');
  const bubbles:ReadingBubble[]=[];let unreadable=0;
  for(const block of value.text_blocks){
    if(!record(block)||!count(block.id)||!count(block.reading_order)||!record(block.bbox)||typeof block.status!=='string'||
      typeof block.original_text!=='string')throw new Error('Invalid page text block from local server.');
    const {left,top,right,bottom}=block.bbox;
    if(![left,top,right,bottom].every(count)||Number(right)<=Number(left)||Number(bottom)<=Number(top)||Number(right)>width||Number(bottom)>height)
      throw new Error('Invalid page text block geometry from local server.');
    const tokens=Array.isArray(block.tokens)?block.tokens:[];
    if(block.status!=='success'||!block.original_text.trim()||!tokens.length){unreadable++;continue;}
    const analysis=parseAnalysis({original_text:block.original_text,translation:block.translation??null,
      processing:{ocr_ms:0,translation_ms:0,analysis_ms:0,total_ms:0},tokens,units:block.units,grammar:block.grammar,
      provenance:{...(record(block.provenance)?block.provenance:{}),analysis_origin:'page'}});
    bubbles.push({id:block.id,order:block.reading_order,analysis,
      box:{x:Number(left),y:Number(top),width:Number(right)-Number(left),height:Number(bottom)-Number(top)}});
  }
  bubbles.sort((a,b)=>a.order-b.order||a.id-b.id);
  return {width,height,bubbles,unreadable};
}

/** A bubble position across the chapter: pages in document order, bubbles in reading order. */
export interface BubbleRef {page:number;bubble:number}

/** The next (+1) or previous (-1) bubble, skipping pages without bubbles; null at either end.
 * `counts[i]` is the number of bubbles on page i, or null while that page is not read yet:
 * navigation stops there instead of jumping over unread text. */
export function stepBubble(counts:readonly (number|null)[],current:BubbleRef|null,direction:1|-1):BubbleRef|{waiting:number}|null {
  if(!current){
    const order=direction===1?counts.keys():[...counts.keys()].reverse();
    for(const page of order){const n=counts[page];if(n===null)return {waiting:page};if(n>0)return {page,bubble:direction===1?0:n-1};}
    return null;
  }
  const here=counts[current.page];
  if(here!==null&&here!==undefined){const bubble=current.bubble+direction;if(bubble>=0&&bubble<here)return {page:current.page,bubble};}
  for(let page=current.page+direction;page>=0&&page<counts.length;page+=direction){
    const n=counts[page];if(n===null)return {waiting:page};if(n>0)return {page,bubble:direction===1?0:n-1};
  }
  return null;
}
