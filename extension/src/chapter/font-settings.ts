export const FONT_MIN=.75,FONT_MAX=1.5;
export function fontScale(value:unknown):number {
  if(typeof value!=='number'||!Number.isFinite(value)||value<FONT_MIN||value>FONT_MAX)throw new Error('Font scale must be between 75% and 150%.');
  return value;
}
import type {PageSnapshot} from './reports';

/** A font refresh may improve coverage, but cannot remove already readable dialogue. */
export function retainsRenderedBlocks(previous:{rendered:number;snapshot?:PageSnapshot},next:{rendered:number;snapshot?:PageSnapshot}):boolean {
  if(next.rendered<previous.rendered)return false;
  if(previous.rendered===0)return true;
  if(!previous.snapshot||!next.snapshot||previous.snapshot.unavailable||next.snapshot.unavailable)return false;
  const rendered=(snapshot:PageSnapshot)=>snapshot.blocks.filter(b=>b.render&&typeof b.render==='object'&&
    (b.render as Record<string,unknown>).status==='rendered').map(b=>b.id);
  const after=new Set(rendered(next.snapshot));
  return rendered(previous.snapshot).every(id=>after.has(id));
}
