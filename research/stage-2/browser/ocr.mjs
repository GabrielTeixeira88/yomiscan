// Stage 2 spike: manga-ocr inference in JavaScript, shared by Node (validation) and the browser.
// It reproduces the reference Python path:
//   PIL L -> RGB, PIL BILINEAR resize to 224x224 (uint8, fixed point), (x/255 - .5)/.5;
//   transformers beam search (num_beams 4, length_penalty 2, early_stopping, no_repeat_ngram 3,
//   max_length 300) or greedy decoding; tokenizer decode; manga_ocr.post_process.

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

function logSoftmaxRow(logits, offset, size, out) {
  let max = -Infinity;
  for (let i = 0; i < size; i++) if (logits[offset + i] > max) max = logits[offset + i];
  let sum = 0;
  for (let i = 0; i < size; i++) sum += Math.exp(logits[offset + i] - max);
  const lse = max + Math.log(sum);
  for (let i = 0; i < size; i++) out[i] = logits[offset + i] - lse;
}

function bannedNgramTokens(sequence, n) {
  const length = sequence.length, banned = new Set();
  if (length + 1 < n) return banned;
  const prefix = sequence.slice(length - (n - 1)).join(",");
  for (let i = 0; i + n <= length; i++) {
    if (sequence.slice(i, i + n - 1).join(",") === prefix) banned.add(sequence[i + n - 1]);
  }
  return banned;
}

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

  // transformers GenerationMixin._beam_search for batch size 1 (see module comment).
  async beam(hidden) {
    const g = this.generation, beams = g.num_beams, keep = 2 * beams, V = this.vocab, promptLength = 1;
    let running = Array.from({length: beams}, () => [g.decoder_start_token_id]);
    let runningScores = Array.from({length: beams}, (_, i) => i === 0 ? 0 : -1e9);
    let finished = Array.from({length: beams}, () => ({tokens: null, score: -1e9, done: false}));
    let heuristicUnsatisfied = true, curLength = 1;
    const row = new Float64Array(V);
    while (true) {
      const {logits, stride, last} = await this.logits(running, hidden);
      // Accumulated log probabilities over beams x vocabulary; keep the top `keep`.
      const candidates = [];
      for (let b = 0; b < beams; b++) {
        logSoftmaxRow(logits, b * stride + last, V, row);
        if (g.no_repeat_ngram_size > 0) for (const t of bannedNgramTokens(running[b], g.no_repeat_ngram_size)) row[t] = -Infinity;
        for (let t = 0; t < V; t++) {
          const score = row[t] + runningScores[b];
          if (candidates.length < keep) { candidates.push({score, b, t}); if (candidates.length === keep) candidates.sort((x, y) => y.score - x.score || x.b * V + x.t - (y.b * V + y.t)); }
          else if (score > candidates[keep - 1].score) {
            let i = keep - 1;
            while (i > 0 && score > candidates[i - 1].score) { candidates[i] = candidates[i - 1]; i--; }
            candidates[i] = {score, b, t};
          }
        }
      }
      const top = candidates.map(c => ({score: c.score, tokens: [...running[c.b], c.t]}));
      const hits = top.map(c => c.tokens.at(-1) === g.eos_token_id || curLength + 1 >= g.max_length);
      // e. next running beams: best `beams` non-finished candidates.
      const runningOrder = top.map((c, i) => ({i, s: c.score + (hits[i] ? -1e9 : 0)})).sort((x, y) => y.s - x.s || x.i - y.i).slice(0, beams);
      running = runningOrder.map(o => top[o.i].tokens);
      runningScores = runningOrder.map(o => o.s);
      // f. finished beams: only the first `beams` ranks may finish; length-normalised score.
      const full = finished.every(f => f.done) && g.early_stopping === true;
      const merged = [...finished.map(f => ({...f}))];
      top.forEach((c, i) => {
        let s = c.score / Math.pow(curLength + 1 - promptLength, g.length_penalty);
        if (full) s += -1e9;
        if (!heuristicUnsatisfied) s += -1e9;
        const justFinished = hits[i] && i < beams;
        if (!justFinished) s += -1e9;
        merged.push({tokens: c.tokens, score: s, done: justFinished});
      });
      finished = merged.map((m, i) => ({...m, i})).sort((x, y) => y.score - x.score || x.i - y.i).slice(0, beams);
      curLength += 1;
      // early-stop heuristic (early_stopping true/false use cur_len - prompt length)
      const best = runningScores[0] / Math.pow(curLength - promptLength, g.length_penalty);
      const worst = Math.min(...finished.map(f => f.score));
      heuristicUnsatisfied = heuristicUnsatisfied && finished.some(f => best > (f.done ? worst : -1e9));
      const openBeam = !(finished.every(f => f.done) && g.early_stopping === true);
      const validContinuations = !hits.every(Boolean);
      if (!(heuristicUnsatisfied && openBeam && validContinuations)) break;
    }
    return finished[0].tokens;
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
