// Browser ports of the production vision models, validated in Stage 2 (research/stage-2):
// - RT-DETR-v2 comic text detector: RTDetrImageProcessorPil + post_process_object_detection +
//   yomiscan.detection.rtdetr.decode_regions (fp32 port reproduced 225/226 PyTorch boxes).
// - manga-ocr: PIL-exact grayscale + bilinear 224x224 preprocessing, greedy decoding (the
//   backend default since fix/ocr-greedy-decoding), tokenizer decode and manga_ocr post_process.
import type * as Ort from 'onnxruntime-web';
import type {Region} from './geometry';

// ---- PIL-exact resampling --------------------------------------------------------------------

const PRECISION_BITS = 32 - 8 - 2;

/** PIL "L" conversion (ImagingConvert fixed point). */
export function luminance(rgba: Uint8ClampedArray | Uint8Array, w: number, h: number): Uint8Array {
  const out = new Uint8Array(w * h);
  for (let i = 0, p = 0; i < out.length; i++, p += 4) out[i] = (rgba[p] * 19595 + rgba[p + 1] * 38470 + rgba[p + 2] * 7471 + 0x8000) >>> 16;
  return out;
}

/** PIL precompute_coeffs + normalize_coeffs_8bpc for the bilinear (triangle) filter. */
function coefficients(inSize: number, outSize: number) {
  const scale = inSize / outSize, filterscale = Math.max(scale, 1), support = filterscale;
  const ksize = Math.ceil(support) * 2 + 1, bounds = new Int32Array(outSize * 2), kk = new Int32Array(outSize * ksize);
  const k = new Float64Array(ksize);
  for (let xx = 0; xx < outSize; xx++) {
    const center = (xx + .5) * scale;
    let xmin = Math.trunc(center - support + .5); if (xmin < 0) xmin = 0;
    let xmax = Math.trunc(center + support + .5); if (xmax > inSize) xmax = inSize;
    xmax -= xmin;
    let ww = 0;
    for (let x = 0; x < xmax; x++) {const t = Math.abs((x + xmin - center + .5) / filterscale), w = t < 1 ? 1 - t : 0; k[x] = w; ww += w;}
    for (let x = 0; x < ksize; x++) {
      const w = x < xmax && ww !== 0 ? k[x] / ww : 0;
      kk[xx * ksize + x] = Math.trunc(w < 0 ? w * (1 << PRECISION_BITS) - .5 : w * (1 << PRECISION_BITS) + .5);
    }
    bounds[xx * 2] = xmin; bounds[xx * 2 + 1] = xmax;
  }
  return {ksize, bounds, kk};
}
const clip8 = (v: number) => v >= (255 << PRECISION_BITS) ? 255 : v <= 0 ? 0 : Math.floor(v / (1 << PRECISION_BITS));

/** PIL ImagingResample (horizontal pass, then vertical) of one 8-bit channel. */
export function resizeBilinear(source: Uint8Array, w: number, h: number, outW: number, outH: number): Uint8Array {
  let data = source;
  if (outW !== w) {
    const {ksize, bounds, kk} = coefficients(w, outW), tmp = new Uint8Array(outW * h);
    for (let y = 0; y < h; y++) for (let xx = 0; xx < outW; xx++) {
      const xmin = bounds[xx * 2], xmax = bounds[xx * 2 + 1];
      let ss = 1 << (PRECISION_BITS - 1);
      for (let x = 0; x < xmax; x++) ss += data[y * w + x + xmin] * kk[xx * ksize + x];
      tmp[y * outW + xx] = clip8(ss);
    }
    data = tmp; w = outW;
  }
  if (outH !== h) {
    const {ksize, bounds, kk} = coefficients(h, outH), tmp = new Uint8Array(w * outH);
    for (let yy = 0; yy < outH; yy++) {
      const ymin = bounds[yy * 2], ymax = bounds[yy * 2 + 1];
      for (let x = 0; x < w; x++) {
        let ss = 1 << (PRECISION_BITS - 1);
        for (let y = 0; y < ymax; y++) ss += data[(y + ymin) * w + x] * kk[yy * ksize + y];
        tmp[yy * w + x] = clip8(ss);
      }
    }
    data = tmp;
  }
  return data;
}

// ---- detector --------------------------------------------------------------------------------

const DETECTOR_SIZE = 640, CLASSES = 3, QUERIES = 300;

export function detectorPixels(rgba: Uint8ClampedArray | Uint8Array, w: number, h: number): Float32Array {
  const plane = DETECTOR_SIZE * DETECTOR_SIZE, out = new Float32Array(3 * plane), channel = new Uint8Array(w * h);
  for (let c = 0; c < 3; c++) {
    for (let i = 0, p = c; i < channel.length; i++, p += 4) channel[i] = rgba[p];
    const resized = resizeBilinear(channel, w, h, DETECTOR_SIZE, DETECTOR_SIZE);
    for (let i = 0; i < plane; i++) out[c * plane + i] = resized[i] * 0.00392156862745098;
  }
  return out;
}

export interface DetectorThresholds {bubble: number; free: number}

/** Focal-loss top-300 scoring, then decode_regions: text classes only, stable spatial order. */
export function decodeDetections(logits: ArrayLike<number>, boxes: ArrayLike<number>, w: number, h: number,
  thresholds: DetectorThresholds = {bubble: .5, free: .5}): Region[] {
  const scored: {i: number; s: number}[] = [];
  for (let i = 0; i < QUERIES * CLASSES; i++) scored.push({i, s: 1 / (1 + Math.exp(-logits[i]))});
  scored.sort((a, b) => b.s - a.s || a.i - b.i);
  const minimum = Math.min(thresholds.bubble, thresholds.free);
  const candidates: {bbox: Region['bbox']; score: number; label: number}[] = [];
  const f = Math.fround;
  for (const {i, s} of scored.slice(0, QUERIES)) {
    if (!(s > minimum)) continue; // transformers keeps score > threshold
    const label = i % CLASSES, q = Math.floor(i / CLASSES);
    if (label !== 1 && label !== 2) continue;
    if (s <= (label === 1 ? thresholds.bubble : thresholds.free)) continue;
    const cx = boxes[q * 4], cy = boxes[q * 4 + 1], bw = boxes[q * 4 + 2], bh = boxes[q * 4 + 3];
    if (![cx, cy, bw, bh, s].every(Number.isFinite)) continue;
    // transformers computes corners in float32 and scales by (width, height).
    const x1 = f(f(f(cx) - f(f(.5) * f(bw))) * w), y1 = f(f(f(cy) - f(f(.5) * f(bh))) * h);
    const x2 = f(f(f(cx) + f(f(.5) * f(bw))) * w), y2 = f(f(f(cy) + f(f(.5) * f(bh))) * h);
    const bbox = {left: Math.max(0, Math.min(w, Math.floor(x1))), top: Math.max(0, Math.min(h, Math.floor(y1))),
      right: Math.max(0, Math.min(w, Math.ceil(x2))), bottom: Math.max(0, Math.min(h, Math.ceil(y2)))};
    if (bbox.right - bbox.left <= 0 || bbox.bottom - bbox.top <= 0) continue;
    candidates.push({bbox, score: s, label});
  }
  candidates.sort((a, b) => a.bbox.top - b.bbox.top || b.bbox.right - a.bbox.right || a.bbox.bottom - b.bbox.bottom ||
    a.bbox.left - b.bbox.left || b.score - a.score);
  return candidates.map((c, index) => ({id: index + 1, bbox: c.bbox, confidence: c.score, orientation: 'unknown',
    granularity: 'block', class: c.label === 1 ? 'text_bubble' : 'text_free'}));
}

export async function detectRegions(ort: typeof Ort, session: Ort.InferenceSession, rgba: Uint8ClampedArray, w: number, h: number,
  thresholds?: DetectorThresholds): Promise<Region[]> {
  const out = await session.run({pixel_values: new ort.Tensor('float32', detectorPixels(rgba, w, h), [1, 3, DETECTOR_SIZE, DETECTOR_SIZE])});
  return decodeDetections(out.logits.data as Float32Array, out.pred_boxes.data as Float32Array, w, h, thresholds);
}

// ---- OCR -------------------------------------------------------------------------------------

const OCR_SIZE = 224;

export function ocrPixels(rgba: Uint8ClampedArray | Uint8Array, w: number, h: number): Float32Array {
  const gray = resizeBilinear(luminance(rgba, w, h), w, h, OCR_SIZE, OCR_SIZE), plane = OCR_SIZE * OCR_SIZE;
  const out = new Float32Array(3 * plane);
  for (let i = 0; i < plane; i++) {const v = (gray[i] / 255 - .5) / .5; out[i] = v; out[plane + i] = v; out[2 * plane + i] = v;}
  return out;
}

/** manga_ocr.ocr.post_process */
export function postProcess(text: string): string {
  text = text.replace(/\s+/g, '').replaceAll('…', '...');
  text = text.replace(/[・.]{2,}/g, m => '.'.repeat(m.length));
  return Array.from(text, ch => {const c = ch.codePointAt(0)!; return c >= 0x21 && c <= 0x7e ? String.fromCodePoint(c + 0xfee0) : ch;}).join('');
}

/** BertJapaneseTokenizer (character subwords) decode with skip_special_tokens. */
export function decodeTokens(ids: readonly number[], vocabulary: readonly string[]): string {
  return postProcess(ids.filter(id => !(vocabulary[id].startsWith('[') && vocabulary[id].endsWith(']')))
    .map(id => vocabulary[id].replace(/^##/, '')).join(' '));
}

export interface OcrGeneration {decoder_start_token_id: number; eos_token_id: number; max_length: number}

export class MangaOcr {
  constructor(private ort: typeof Ort, private encoder: Ort.InferenceSession, private decoder: Ort.InferenceSession,
    private vocabulary: readonly string[], private generation: OcrGeneration) {}

  async recognize(rgba: Uint8ClampedArray, w: number, h: number): Promise<string> {
    const encoded = await this.encoder.run({pixel_values: new this.ort.Tensor('float32', ocrPixels(rgba, w, h), [1, 3, OCR_SIZE, OCR_SIZE])});
    const hidden = encoded.last_hidden_state, vocab = this.vocabulary.length;
    const {decoder_start_token_id: start, eos_token_id: eos, max_length: maxLength} = this.generation;
    const tokens = [start];
    // The exported decoder has no KV cache: each step reads the whole sequence (greedy, as the backend).
    while (tokens.length < maxLength) {
      const ids = BigInt64Array.from(tokens, BigInt);
      const out = await this.decoder.run({input_ids: new this.ort.Tensor('int64', ids, [1, tokens.length]), encoder_hidden_states: hidden});
      const raw = out.logits.data, logits = raw instanceof Float32Array ? raw : Float32Array.from(raw as ArrayLike<number>);
      const last = (tokens.length - 1) * vocab;
      let best = 0;
      for (let i = 1; i < vocab; i++) if (logits[last + i] > logits[last + best]) best = i;
      tokens.push(best);
      if (best === eos) break;
    }
    return decodeTokens(tokens, this.vocabulary);
  }
}
