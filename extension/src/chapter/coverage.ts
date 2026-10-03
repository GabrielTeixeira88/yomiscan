export type PageCoverage = Record<string, number>;
const keys = ['total_text_blocks','filtered_before_grouping', ...['bubble','narration','artwork_text','sfx','unknown'].flatMap(c=>['detected','rendered','preserved'].map(s=>`${c}_${s}`))];
/** Optional additive metadata; older backends remain supported. */
export function parseCoverage(value: unknown): PageCoverage | undefined {
  if(value===undefined || value===null)return undefined;
  if(typeof value!=='object' || Array.isArray(value))throw new Error('Invalid coverage metadata');
  const result:PageCoverage={};
  for(const key of keys)if(key in value){const n=(value as Record<string,unknown>)[key];
    if(typeof n!=='number'||!Number.isSafeInteger(n)||n<0)throw new Error('Invalid coverage count');result[key]=n;}
  return result;
}
export function coverageSummary(results: {skipped:number;coverage?:PageCoverage}[]):string {
  const partial=results.filter(r=>r.skipped>0);if(!partial.length)return '';
  let speech=0,sfx=0,unknown=0;
  for(const r of partial){const c=r.coverage;
    const dialogue=(c?.bubble_preserved??0)+(c?.narration_preserved??0)+(c?.artwork_text_preserved??0);
    const sounds=c?.sfx_preserved??0;
    speech+=dialogue;sfx+=sounds;unknown+=Math.max(c?.unknown_preserved??0,r.skipped-dialogue-sounds);}
  return `${partial.length} rendered pages contain preserved regions: ${speech} dialogue/artwork (see diagnostics), ${sfx} likely SFX, ${unknown} unknown.`;
}
