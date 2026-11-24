// Stage 2 spike: RT-DETR-v2 comic text detector in JavaScript (Node validation and browser).
// Reproduces RTDetrImageProcessorPil (RGB, PIL bilinear 640x640, /255) and
// post_process_object_detection with focal-loss scoring, then yomiscan.detection.rtdetr.decode_regions.
import {resizeBilinear} from "./ocr.mjs";

const SIZE = 640, CLASSES = 3, QUERIES = 300;

export function detectorPixels(rgba, width, height) {
  const plane = SIZE * SIZE, out = new Float32Array(3 * plane), channel = new Uint8Array(width * height);
  for (let c = 0; c < 3; c++) {
    for (let i = 0, p = c; i < channel.length; i++, p += 4) channel[i] = rgba[p];
    const resized = resizeBilinear(channel, width, height, SIZE, SIZE);
    for (let i = 0; i < plane; i++) out[c * plane + i] = resized[i] * 0.00392156862745098;
  }
  return out;
}

export function decodeDetections(logits, boxes, width, height, {bubbleThreshold = .5, freeThreshold = .5} = {}) {
  const scored = [];
  for (let i = 0; i < QUERIES * CLASSES; i++) scored.push({i, s: 1 / (1 + Math.exp(-logits[i]))});
  scored.sort((a, b) => b.s - a.s || a.i - b.i);
  const minimum = Math.min(bubbleThreshold, freeThreshold), regions = [];
  for (const {i, s} of scored.slice(0, QUERIES)) {
    if (!(s > minimum)) continue; // transformers keeps score > threshold
    const label = i % CLASSES, q = Math.floor(i / CLASSES);
    if (label !== 1 && label !== 2) continue;
    if (s <= (label === 1 ? bubbleThreshold : freeThreshold)) continue;
    const [cx, cy, w, h] = [boxes[q * 4], boxes[q * 4 + 1], boxes[q * 4 + 2], boxes[q * 4 + 3]];
    // transformers computes corners in float32 and scales by (width, height); emulate with fround.
    const f = Math.fround;
    const x1 = f(f(f(cx) - f(f(0.5) * f(w))) * width), y1 = f(f(f(cy) - f(f(0.5) * f(h))) * height);
    const x2 = f(f(f(cx) + f(f(0.5) * f(w))) * width), y2 = f(f(f(cy) + f(f(0.5) * f(h))) * height);
    const left = Math.max(0, Math.min(width, Math.floor(x1))), top = Math.max(0, Math.min(height, Math.floor(y1)));
    const right = Math.max(0, Math.min(width, Math.ceil(x2))), bottom = Math.max(0, Math.min(height, Math.ceil(y2)));
    if (right - left <= 0 || bottom - top <= 0) continue;
    regions.push({bbox: {left, top, right, bottom}, score: s, class: label === 1 ? "text_bubble" : "text_free"});
  }
  regions.sort((a, b) => a.bbox.top - b.bbox.top || b.bbox.right - a.bbox.right || a.bbox.bottom - b.bbox.bottom || a.bbox.left - b.bbox.left || b.score - a.score);
  return regions;
}

export async function detect(ort, session, rgba, width, height, options) {
  const t0 = performance.now();
  const pixels = detectorPixels(rgba, width, height);
  const t1 = performance.now();
  const out = await session.run({pixel_values: new ort.Tensor("float32", pixels, [1, 3, SIZE, SIZE])});
  const t2 = performance.now();
  const regions = decodeDetections(out.logits.data, out.pred_boxes.data, width, height, options);
  return {regions, timings: {preprocess: t1 - t0, model: t2 - t1, postprocess: performance.now() - t2}};
}
