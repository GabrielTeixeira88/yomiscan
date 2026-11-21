import type {Rect} from '../geometry';

/** Reject geometry we cannot map; never guess a rotated or cropped coordinate. */
export function displayedRegion(box:Rect,pixels:{width:number;height:number},display:Rect):Rect|null {
  if(![box.x,box.y,box.width,box.height,pixels.width,pixels.height,display.x,display.y,display.width,display.height].every(Number.isFinite)||
    Math.min(box.width,box.height,pixels.width,pixels.height,display.width,display.height)<=0||box.x<0||box.y<0||
    box.x+box.width>pixels.width||box.y+box.height>pixels.height||Math.abs(display.width/display.height-pixels.width/pixels.height)>.02)return null;
  return {x:display.x+box.x*display.width/pixels.width,y:display.y+box.y*display.height/pixels.height,
    width:box.width*display.width/pixels.width,height:box.height*display.height/pixels.height};
}
export function supportsRegionGeometry(image:HTMLImageElement):boolean {
  const style=getComputedStyle(image);
  if([style.paddingLeft,style.paddingRight,style.paddingTop,style.paddingBottom,style.borderLeftWidth,style.borderRightWidth,
    style.borderTopWidth,style.borderBottomWidth].some(v=>parseFloat(v)>0))return false;
  for(let node:HTMLElement|null=image;node;node=node.parentElement)if(getComputedStyle(node).transform!=='none')return false;
  return true;
}
