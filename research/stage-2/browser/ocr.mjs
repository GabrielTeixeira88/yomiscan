// Stage 2 spike: manga-ocr inference in JavaScript, shared by Node (validation) and the browser.
// It reproduces the reference Python path:
//   PIL L -> RGB, PIL BILINEAR resize to 224x224 (uint8, fixed point), (x/255 - .5)/.5;
//   transformers beam search (num_beams 4, length_penalty 2, early_stopping, no_repeat_ngram 3,
//   max_length 300) or greedy decoding; tokenizer decode; manga_ocr.post_process.

import {beamSearch} from "./beam.mjs";

const SIZE = 224, PRECISION_BITS = 32 - 8 - 2;

// ---- preprocessing -------------------------------------------------------------------------

// PIL "L" conversion: L = R*299/1000 + G*587/1000 + B*114/1000, fixed point (ImagingConvert).
export function luminance(rgba, width, height) {
  const out = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < out.length; i++, p += 4) {
    out[i] = (rgba[p] * 19595 + rgba[p + 1] * 38470 + rgba[p + 2] * 7471 + 0x8000) >>> 16;
  }
  return out;
}

// PIL precompute_coeffs + normalize_coeffs_8bpc for the bilinear (triangle) filter.
function coefficients(inSize, outSize) {
  const scale = inSize / outSize, filterscale = Math.max(scale, 1), support = filterscale;
  const ksize = Math.ceil(support) * 2 + 1, bounds = new Int32Array(outSize * 2), kk = new Int32Array(outSize * ksize);
  const k = new Float64Array(ksize);
  for (let xx = 0; xx < outSize; xx++) {
    const center = (xx + 0.5) * scale;
    let xmin = Math.trunc(center - support + 0.5); if (xmin < 0) xmin = 0;
    let xmax = Math.trunc(center + support + 0.5); if (xmax > inSize) xmax = inSize;
    xmax -= xmin;
    let ww = 0;
    for (let x = 0; x < xmax; x++) {
      const t = Math.abs((x + xmin - center + 0.5) / filterscale), w = t < 1 ? 1 - t : 0;
      k[x] = w; ww += w;
    }
    for (let x = 0; x < ksize; x++) {
      const w = x < xmax && ww !== 0 ? k[x] / ww : 0;
      kk[xx * ksize + x] = Math.trunc(w < 0 ? w * (1 << PRECISION_BITS) - 0.5 : w * (1 << PRECISION_BITS) + 0.5);
    }
    bounds[xx * 2] = xmin; bounds[xx * 2 + 1] = xmax;
  }
  return {ksize, bounds, kk};
}

const clip8 = v => v >= (255 << PRECISION_BITS) ? 255 : v <= 0 ? 0 : Math.floor(v / (1 << PRECISION_BITS));

// PIL ImagingResample (horizontal pass, then vertical), single 8-bit channel.
export function resizeBilinear(source, width, height, outWidth = SIZE, outHeight = SIZE) {
  let data = source, w = width, h = height;
  if (outWidth !== w) {
    const {ksize, bounds, kk} = coefficients(w, outWidth), tmp = new Uint8Array(outWidth * h);
    for (let y = 0; y < h; y++) for (let xx = 0; xx < outWidth; xx++) {
      const xmin = bounds[xx * 2], xmax = bounds[xx * 2 + 1];
      let ss = 1 << (PRECISION_BITS - 1);
      for (let x = 0; x < xmax; x++) ss += data[y * w + x + xmin] * kk[xx * ksize + x];
      tmp[y * outWidth + xx] = clip8(ss);
    }
    data = tmp; w = outWidth;
  }
  if (outHeight !== h) {
    const {ksize, bounds, kk} = coefficients(h, outHeight), tmp = new Uint8Array(w * outHeight);
    for (let yy = 0; yy < outHeight; yy++) {
      const ymin = bounds[yy * 2], ymax = bounds[yy * 2 + 1];
      for (let x = 0; x < w; x++) {
        let ss = 1 << (PRECISION_BITS - 1);
        for (let y = 0; y < ymax; y++) ss += data[(y + ymin) * w + x] * kk[yy * ksize + y];
        tmp[yy * w + x] = clip8(ss);
      }
    }
    data = tmp; h = outHeight;
  }
  return data;
}

export function pixelValues(rgba, width, height) {
  const gray = resizeBilinear(luminance(rgba, width, height), width, height), plane = SIZE * SIZE;
  const out = new Float32Array(3 * plane);
  for (let i = 0; i < plane; i++) {
    const v = (gray[i] / 255 - 0.5) / 0.5;
    out[i] = v; out[plane + i] = v; out[2 * plane + i] = v;
  }
  return out;
}

// ---- text ----------------------------------------------------------------------------------

export function postProcess(text) {
  text = text.replace(/\s+/g, "").replaceAll("…", "...");
  text = text.replace(/[・.]{2,}/g, m => ".".repeat(m.length));
  return Array.from(text, ch => {
    const c = ch.codePointAt(0);
    return c >= 0x21 && c <= 0x7e ? String.fromCodePoint(c + 0xfee0) : ch;
  }).join("");
}

export function decodeTokens(ids, vocabulary) {
  // BertJapaneseTokenizer (character subwords) decode with skip_special_tokens; spaces are
  // removed by postProcess anyway.
  return postProcess(ids.filter(id => !(vocabulary[id].startsWith("[") && vocabulary[id].endsWith("]")))
    .map(id => vocabulary[id].replace(/^##/, "")).join(" "));
}

// ---- decoding ------------------------------------------------------------------------------

export class MangaOcr {
  constructor({ort, encoder, decoder, vocabulary, generation}) {
    Object.assign(this, {ort, encoder, decoder, vocabulary});
    this.generation = generation;
    this.vocab = vocabulary.length;
  }

  async encode(pixels) {
    const input = new this.ort.Tensor("float32", pixels, [1, 3, SIZE, SIZE]);
    const out = await this.encoder.run({pixel_values: input});
    return out.last_hidden_state;
  }

  async logits(sequences, hidden) {
    const batch = sequences.length, length = sequences[0].length;
    const ids = new BigInt64Array(batch * length);
    sequences.forEach((s, b) => s.forEach((t, i) => { ids[b * length + i] = BigInt(t); }));
    const [, positions, width] = hidden.dims, data = hidden.data;
    let states = data;
    if (batch > 1) {
      states = new Float32Array(batch * positions * width);
      for (let b = 0; b < batch; b++) states.set(data, b * positions * width);
    }
    const out = await this.decoder.run({
      input_ids: new this.ort.Tensor("int64", ids, [batch, length]),
      encoder_hidden_states: new this.ort.Tensor("float32", states, [batch, positions, width]),
    });
    const logits = out.logits.data instanceof Float32Array ? out.logits.data : Float32Array.from(out.logits.data);
    return {logits, stride: length * this.vocab, last: (length - 1) * this.vocab};
  }

  async greedy(hidden) {
    const {decoder_start_token_id: start, eos_token_id: eos, max_length: maxLength} = this.generation;
    const tokens = [start];
    while (tokens.length < maxLength) {
      const {logits, last} = await this.logits([tokens], hidden);
      let best = 0;
      for (let i = 1; i < this.vocab; i++) if (logits[last + i] > logits[last + best]) best = i;
      tokens.push(best);
      if (best === eos) break;
    }
    return tokens;
  }

  // transformers GenerationMixin._beam_search (beam.mjs); the decoder has no KV cache, so every
  // step re-reads each running beam's whole sequence.
  async beam(hidden) {
    const g = this.generation;
    const result = await beamSearch({
      next: async sequences => {
        const {logits, stride, last} = await this.logits(sequences, hidden);
        const rows = new Float32Array(sequences.length * this.vocab);
        for (let b = 0; b < sequences.length; b++) rows.set(logits.subarray(b * stride + last, b * stride + last + this.vocab), b * this.vocab);
        return rows;
      },
      vocabSize: this.vocab, numBeams: g.num_beams, startId: g.decoder_start_token_id, eosId: g.eos_token_id,
      maxLength: g.max_length, lengthPenalty: g.length_penalty, earlyStopping: g.early_stopping,
      noRepeatNgram: g.no_repeat_ngram_size ?? 0,
    });
    return result.tokens;
  }

  async recognize(rgba, width, height, {decoding = "beam"} = {}) {
    const timings = {};
    let t = performance.now();
    const pixels = pixelValues(rgba, width, height);
    timings.preprocess = performance.now() - t; t = performance.now();
    const hidden = await this.encode(pixels);
    timings.encoder = performance.now() - t; t = performance.now();
    const tokens = decoding === "greedy" ? await this.greedy(hidden) : await this.beam(hidden);
    timings.decoder = performance.now() - t;
    return {text: decodeTokens(tokens, this.vocabulary), tokens: tokens.length, timings};
  }
}
