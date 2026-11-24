// Browser port of yomiscan.detection.base.BoundingBox, yomiscan.page_layout and the "bands"
// page order. Kept line-for-line equivalent so browser and backend produce the same blocks.

export interface Box {left: number; top: number; right: number; bottom: number}
export type Orientation = 'vertical' | 'horizontal' | 'unknown';
export interface Region {id: number; bbox: Box; confidence: number | null; orientation: Orientation;
  /** "block" for detector predictions (RT-DETR), "line" for line detectors. */
  granularity: 'block' | 'line'; class: string | null}
export interface RegionGroup {regions: Region[]; bbox: Box}

export const width = (b: Box) => b.right - b.left;
export const height = (b: Box) => b.bottom - b.top;

/** BoundingBox.clipped */
export function clipped(b: Box, imageWidth: number, imageHeight: number, padding = 0): Box {
  return {left: Math.max(0, b.left - padding), top: Math.max(0, b.top - padding),
    right: Math.min(imageWidth, b.right + padding), bottom: Math.min(imageHeight, b.bottom + padding)};
}

export function unionBox(regions: readonly Region[]): Box {
  return {left: Math.min(...regions.map(r => r.bbox.left)), top: Math.min(...regions.map(r => r.bbox.top)),
    right: Math.max(...regions.map(r => r.bbox.right)), bottom: Math.max(...regions.map(r => r.bbox.bottom))};
}

/** Python tuple ordering for sort keys. */
function compare(a: readonly number[], b: readonly number[]): number {
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] - b[i];
  return 0;
}

export function nearbyLines(a: Region, b: Region): boolean {
  // Block-level predictions must never be merged just because two bubbles are near.
  if (a.granularity !== 'line' || b.granularity !== 'line') return false;
  if (a.orientation !== b.orientation || a.orientation === 'unknown') return false;
  const x = a.bbox, y = b.bbox;
  if (a.orientation === 'vertical') {
    const overlap = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
    const gap = Math.max(x.left, y.left) - Math.min(x.right, y.right);
    return overlap >= .8 * Math.max(height(x), height(y)) && gap >= 0 && gap <= .6 * Math.min(width(x), width(y)) &&
      Math.max(width(x), width(y)) <= 1.5 * Math.min(width(x), width(y));
  }
  const overlap = Math.min(x.right, y.right) - Math.max(x.left, y.left);
  const gap = Math.max(x.top, y.top) - Math.min(x.bottom, y.bottom);
  return overlap >= .8 * Math.max(width(x), width(y)) && gap >= 0 && gap <= .6 * Math.min(height(x), height(y)) &&
    Math.max(height(x), height(y)) <= 1.5 * Math.min(height(x), height(y));
}

/** Same-class block predictions fully containing a second prediction share one OCR crop. */
export function containedDuplicate(a: Region, b: Region): boolean {
  if (a.granularity !== 'block' || b.granularity !== 'block') return false;
  if (!a.class || a.class !== b.class) return false;
  // Python's sorted(..., reverse=True) is stable: equal areas keep (a, b) order.
  const [outer, inner] = width(b.bbox) * height(b.bbox) > width(a.bbox) * height(a.bbox) ? [b, a] : [a, b];
  const x = outer.bbox, y = inner.bbox;
  return x.left <= y.left && x.top <= y.top && x.right >= y.right && x.bottom >= y.bottom &&
    (outer.confidence ?? 0) >= (inner.confidence ?? 0);
}

export function groupRegions(regions: readonly Region[]): RegionGroup[] {
  const groups: Region[][] = [];
  const sorted = [...regions].sort((a, b) => compare([a.bbox.top, -a.bbox.right, a.id], [b.bbox.top, -b.bbox.right, b.id]));
  for (const region of sorted) {
    // Complete-link rule avoids chains bridging distant bubbles.
    const target = groups.find(g => g.every(r => nearbyLines(region, r) || containedDuplicate(region, r)));
    if (target) target.push(region); else groups.push([region]);
  }
  return groups.map(g => ({regions: g, bbox: unionBox(g)}));
}

/** Top-to-bottom bands, right-to-left within each anchored band. */
export function readingOrder(groups: readonly RegionGroup[]): RegionGroup[] {
  const pending = [...groups].sort((a, b) => compare([a.bbox.top, -a.bbox.right, a.regions[0].id], [b.bbox.top, -b.bbox.right, b.regions[0].id]));
  const ordered: RegionGroup[] = [];
  while (pending.length) {
    const anchor = pending.shift()!;
    const tolerance = Math.max(8, Math.min(40, height(anchor.bbox) * .25));
    const band = [anchor];
    while (pending.length && pending[0].bbox.top <= anchor.bbox.top + tolerance) band.push(pending.shift()!);
    ordered.push(...band.sort((a, b) => compare([-a.bbox.right, a.bbox.top, a.regions[0].id], [-b.bbox.right, b.bbox.top, b.regions[0].id])));
  }
  return ordered;
}

export interface DetectedBlock {id: number; regionIds: number[]; bbox: Box; orientation: Orientation; readingOrder: number; confidence: number | null}

/** PageAnalysisService._detect followed by the default "bands" page order. */
export function blocksFromRegions(raw: readonly Region[], imageWidth: number, imageHeight: number, minimumSide = 3):
  {blocks: DetectedBlock[]; filtered: Map<number, string>} {
  const valid: Region[] = [], filtered = new Map<number, string>();
  for (const region of raw) {
    const box = clipped(region.bbox, imageWidth, imageHeight);
    if (Math.min(width(box), height(box)) < minimumSide) filtered.set(region.id, 'Region too small or outside image');
    else valid.push({...region, bbox: box});
  }
  const blocks = readingOrder(groupRegions(valid)).map((group, index): DetectedBlock => {
    const confidences = group.regions.map(r => r.confidence).filter((c): c is number => c !== null);
    const orientations = new Set(group.regions.map(r => r.orientation));
    return {id: index + 1, regionIds: group.regions.map(r => r.id), bbox: group.bbox,
      orientation: orientations.size === 1 ? [...orientations][0] : 'unknown', readingOrder: index + 1,
      confidence: confidences.length ? Math.min(...confidences) : null};
  });
  // panel_order "bands": the same band ordering over block boxes, keyed by block ID.
  const ordered = readingOrder(blocks.map(b => ({regions: [{id: b.id, bbox: b.bbox, confidence: null, orientation: 'unknown',
    granularity: 'block', class: null}], bbox: b.bbox})));
  const position = new Map(ordered.map((g, i) => [g.regions[0].id, i + 1]));
  return {blocks: blocks.map(b => ({...b, readingOrder: position.get(b.id)!})).sort((a, b) => a.readingOrder - b.readingOrder), filtered};
}

/** yomiscan.japanese.contains_japanese: a Japanese script character after NFKC. */
export function containsJapanese(text: string): boolean {
  for (const ch of text.normalize('NFKC')) {
    const c = ch.codePointAt(0)!;
    if ((c >= 0x3041 && c <= 0x3096) || (c >= 0x30a1 && c <= 0x30fa) || (c >= 0x3400 && c <= 0x4dbf) ||
      (c >= 0x4e00 && c <= 0x9fff) || (c >= 0xf900 && c <= 0xfaff) || (c >= 0x20000 && c <= 0x323af)) return true;
  }
  return false;
}
