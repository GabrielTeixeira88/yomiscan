export interface Point { x: number; y: number }
export interface Size { width: number; height: number }
export interface Rect extends Point, Size {}
export interface Viewport extends Size { scrollX: number; scrollY: number; scale: number }
export type ResizeEdge = "right" | "bottom" | "corner";

/** Fit the whole popup, relaxing its minimum only for a smaller viewport. */
export function constrainPopup(rect: Rect, viewport: Size): Rect {
  const maxWidth = Math.max(1, viewport.width - 16), maxHeight = Math.max(1, viewport.height - 16);
  const width = Math.max(Math.min(320, maxWidth), Math.min(rect.width, maxWidth));
  const height = Math.max(Math.min(220, maxHeight), Math.min(rect.height, maxHeight));
  return {width, height, x: Math.max(8, Math.min(rect.x, viewport.width - width - 8)),
    y: Math.max(8, Math.min(rect.y, viewport.height - height - 8))};
}

/** Resize from a fixed top-left corner; never push the opposite edge off-screen. */
export function resizePopup(rect: Rect, delta: Point, edge: ResizeEdge, viewport: Size): Rect {
  const maxWidth = Math.max(1, viewport.width - rect.x - 8);
  const maxHeight = Math.max(1, viewport.height - rect.y - 8);
  return {...rect,
    width: edge === "bottom" ? rect.width : Math.max(Math.min(320, maxWidth), Math.min(rect.width + delta.x, maxWidth)),
    height: edge === "right" ? rect.height : Math.max(Math.min(220, maxHeight), Math.min(rect.height + delta.y, maxHeight)),
  };
}

const clamp = (n: number, max: number) => Math.max(0, Math.min(n, max));

export function selectionRect(a: Point, b: Point, viewport: Size): Rect {
  const x1 = clamp(a.x, viewport.width), x2 = clamp(b.x, viewport.width);
  const y1 = clamp(a.y, viewport.height), y2 = clamp(b.y, viewport.height);
  return {x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1)};
}

export function validSelection(rect: Rect, viewport: Size): boolean {
  return [rect.x, rect.y, rect.width, rect.height, viewport.width, viewport.height].every(Number.isFinite)
    && viewport.width > 0 && viewport.height > 0 && rect.width >= 4 && rect.height >= 4
    && rect.x >= 0 && rect.y >= 0
    && rect.x + rect.width <= viewport.width && rect.y + rect.height <= viewport.height;
}

export function screenshotRect(rect: Rect, viewport: Size, screenshot: Size): Rect {
  if (!validSelection(rect, viewport) || ![screenshot.width, screenshot.height].every(n => Number.isFinite(n) && n > 0)) {
    throw new Error("Invalid capture coordinates. Select a larger region and try again.");
  }
  // Measured ratios include OS scaling and ordinary browser zoom; do not multiply DPR again.
  const sx = screenshot.width / viewport.width, sy = screenshot.height / viewport.height;
  const x = Math.floor(rect.x * sx), y = Math.floor(rect.y * sy);
  const right = Math.min(screenshot.width, Math.ceil((rect.x + rect.width) * sx));
  const bottom = Math.min(screenshot.height, Math.ceil((rect.y + rect.height) * sy));
  return {x, y, width: right - x, height: bottom - y};
}

export function popupPosition(anchor: Rect, popup: Size, viewport: Size): Point {
  const margin = 8, gap = 10;
  const x = Math.max(margin, Math.min(anchor.x, viewport.width - popup.width - margin));
  const below = anchor.y + anchor.height + gap;
  const y = below + popup.height <= viewport.height - margin ? below : anchor.y - popup.height - gap;
  return {x, y: Math.max(margin, Math.min(y, viewport.height - popup.height - margin))};
}

export function sameViewport(a: Viewport, b: Viewport): boolean {
  return a.width === b.width && a.height === b.height && a.scrollX === b.scrollX
    && a.scrollY === b.scrollY && a.scale === b.scale;
}
