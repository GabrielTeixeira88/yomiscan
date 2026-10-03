export interface ImageFacts {
  width: number; height: number; displayedWidth: number; displayedHeight: number;
  visible: boolean; excluded: boolean; source: string;
}
export function candidateReason(f: ImageFacts): string | null {
  if (f.excluded) return "Navigation, advertising, recommendations or site decoration";
  if (!f.visible) return "Hidden image";
  if (!f.source) return "No loaded current source";
  if (f.width < 400 || f.height < 500 || f.displayedWidth < 240 || f.displayedHeight < 300) return "Too small for a full manga page";
  const aspect = f.width/f.height;
  if (aspect < .15 || aspect > 2.2) return "Unsupported page aspect ratio";
  return null;
}
export interface MangaPageCandidate { image: HTMLImageElement; source: string; width: number; height: number }
export interface DiscoveryDecision { image: HTMLImageElement; reason: string; accepted: boolean }
export interface DiscoveryResult { candidates: MangaPageCandidate[]; decisions: DiscoveryDecision[] }
export interface PageDiscoveryStrategy { discover(document: Document): DiscoveryResult }
const excludedWords = /(?:^|[\s_-])(ad|ads|advert|advertisement|banner|logo|avatar|thumbnail|recommendations?|related|comments?|navigation)(?:$|[\s_-])/i;
function excluded(image: HTMLImageElement): boolean {
  if (image.closest("header,footer,nav,aside,[role=banner],[role=navigation],[data-yomiscan]")) return true;
  let node: Element | null = image;
  for (let i=0; node && i<5; i++, node=node.parentElement) {
    if (excludedWords.test(`${node.id} ${node.getAttribute("class") ?? ""} ${node.getAttribute("role") ?? ""}`)) return true;
  }
  return excludedWords.test(image.alt);
}
export class GenericPageDiscovery implements PageDiscoveryStrategy {
  discover(document: Document): DiscoveryResult {
    const decisions: DiscoveryDecision[] = [], eligible: MangaPageCandidate[] = [];
    for (const image of document.images) {
      const rect = image.getBoundingClientRect(), style = getComputedStyle(image);
      const source = image.currentSrc || image.src;
      const reason = candidateReason({width: image.naturalWidth, height: image.naturalHeight,
        displayedWidth: rect.width, displayedHeight: rect.height, source,
        visible: image.complete && image.isConnected && rect.width > 0 && style.visibility === "visible" && style.display !== "none" && Number(style.opacity) > 0,
        excluded: excluded(image)});
      if (reason) decisions.push({image, reason, accepted: false});
      else eligible.push({image, source, width: image.naturalWidth, height: image.naturalHeight});
    }
    // Pick the dominant vertically aligned reader column; do not translate unrelated grids.
    const groups: MangaPageCandidate[][] = [];
    for (const candidate of eligible) {
      const r = candidate.image.getBoundingClientRect();
      const group = groups.find(g => {
        const a = g[0].image.getBoundingClientRect();
        return Math.abs((a.left+a.right)-(r.left+r.right))/2 < Math.max(45, a.width*.12)
          && Math.abs(a.width-r.width) < a.width*.3
          && g.every(c => { const b = c.image.getBoundingClientRect(); return Math.min(b.bottom,r.bottom)-Math.max(b.top,r.top) <= 10; });
      });
      if (group) group.push(candidate); else groups.push([candidate]);
    }
    groups.sort((a,b) => b.length-a.length ||
      b.reduce((s,c)=>s+c.width*c.height,0)-a.reduce((s,c)=>s+c.width*c.height,0));
    const candidates = groups[0] ?? [];
    for (const candidate of eligible) decisions.push({image: candidate.image, accepted: candidates.includes(candidate),
      reason: candidates.includes(candidate) ? "Large image in dominant reader column" : "Outside dominant reader column"});
    return {candidates, decisions};
  }
}
