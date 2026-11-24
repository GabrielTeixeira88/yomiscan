// Browser page vision: detection, grouping, reading order and OCR of each padded block, as
// yomiscan.page.PageAnalysisService.extract does (minimum side 3 px, padding 4 px).
import type * as Ort from 'onnxruntime-web';
import {blocksFromRegions, clipped, containsJapanese, width, height, type Box, type DetectedBlock} from './geometry';
import {detectRegions, MangaOcr, type DetectorThresholds} from './vision-models';

export interface RecognizedBlock extends DetectedBlock {
  text: string;
  status: 'success' | 'error' | 'filtered';
  error: string | null;
}
export interface PageVision {width: number; height: number; regions: number; filtered: number; blocks: RecognizedBlock[];
  timings: {detection_ms: number; ocr_ms: number}}

export const PADDING = 4;

/** Copy one rectangle of RGBA pixels (PIL Image.crop). */
export function cropRGBA(rgba: Uint8ClampedArray, imageWidth: number, box: Box): Uint8ClampedArray {
  const w = width(box), h = height(box), out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    const start = ((box.top + y) * imageWidth + box.left) * 4;
    out.set(rgba.subarray(start, start + w * 4), y * w * 4);
  }
  return out;
}

export interface VisionModels {ort: typeof Ort; detector: Ort.InferenceSession; ocr: MangaOcr; thresholds?: DetectorThresholds}

export async function detectBlocks(models: VisionModels, image: ImageData) {
  const raw = await detectRegions(models.ort, models.detector, image.data, image.width, image.height, models.thresholds);
  return {raw, ...blocksFromRegions(raw, image.width, image.height)};
}

export async function recognizePage(models: VisionModels, image: ImageData, signal?: AbortSignal): Promise<PageVision> {
  let t = performance.now();
  const {raw, blocks, filtered} = await detectBlocks(models, image);
  const detection_ms = performance.now() - t;
  t = performance.now();
  const recognized = await recognizeBlocks(models, image, blocks, signal);
  return {width: image.width, height: image.height, regions: raw.length, filtered: filtered.size, blocks: recognized,
    timings: {detection_ms, ocr_ms: performance.now() - t}};
}

/** OCR each padded block crop in order; a failure is bound to its own block (PageAnalysisService). */
export async function recognizeBlocks(models: VisionModels, image: ImageData, blocks: readonly DetectedBlock[], signal?: AbortSignal): Promise<RecognizedBlock[]> {
  const {width: w, height: h, data} = image;
  const recognized: RecognizedBlock[] = [];
  for (const block of blocks) {
    signal?.throwIfAborted();
    const box = clipped(block.bbox, w, h, PADDING);
    try {
      const text = await models.ocr.recognize(cropRGBA(data, w, box), width(box), height(box));
      recognized.push(containsJapanese(text) ? {...block, text, status: 'success', error: null} :
        {...block, text, status: 'filtered', error: 'No Japanese script in OCR output.'});
    } catch (error) {
      // A failed block is reported on that block, as in the backend; the page continues.
      console.warn('YomiScan browser OCR failed for block', block.id, error);
      recognized.push({...block, text: '', status: 'error', error: 'OCR failed for this block.'});
    }
  }
  return recognized;
}
