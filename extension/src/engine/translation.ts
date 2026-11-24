// Browser sentence translation (Stage 5a increment 3): OPUS-MT ja-en, ONNX fp16 (Xenova export
// of Helsinki-NLP/opus-mt-ja-en), decoded exactly as the backend's MarianTranslationEngine:
// whitespace collapsed, no truncation, num_beams 4, length_penalty 1, early_stopping false,
// max 511 new tokens, pad token banned, logits renormalized, unfinished output is an error.
// Stage 2 (research/stage-2/browser/opus.mjs, beam.mjs) measured 99/100 lines identical to Python.
import type * as Ort from 'onnxruntime-web';

// ---- transformers GenerationMixin._beam_search, batch size 1 -------------------------------

export type NextLogits = (sequences: number[][], parents: number[] | null) => Promise<Float32Array>;
export interface BeamOptions {next: NextLogits; vocabSize: number; numBeams: number; startId: number; eosId: number; maxLength: number;
  lengthPenalty?: number; earlyStopping?: boolean | 'never'; noRepeatNgram?: number; bannedTokens?: readonly number[]; renormalize?: boolean}

function logSoftmaxInPlace(row: Float64Array): void {
  let max = -Infinity;
  for (let i = 0; i < row.length; i++) if (row[i] > max) max = row[i];
  if (max === -Infinity) return;
  let sum = 0;
  for (let i = 0; i < row.length; i++) sum += Math.exp(row[i] - max);
  const lse = max + Math.log(sum);
  for (let i = 0; i < row.length; i++) row[i] -= lse;
}

function bannedNgramTokens(sequence: readonly number[], n: number): Set<number> {
  const banned = new Set<number>();
  if (sequence.length + 1 < n) return banned;
  const prefix = sequence.slice(sequence.length - (n - 1)).join(',');
  for (let i = 0; i + n <= sequence.length; i++) if (sequence.slice(i, i + n - 1).join(',') === prefix) banned.add(sequence[i + n - 1]);
  return banned;
}

/** Logits per beam: log_softmax, banned tokens, no-repeat n-grams, optional renormalization, plus the running score. */
export async function beamSearch(o: BeamOptions): Promise<{tokens: number[]; score: number; done: boolean}> {
  const V = o.vocabSize, beams = o.numBeams, keep = 2 * beams, promptLength = 1;
  const lengthPenalty = o.lengthPenalty ?? 1, earlyStopping = o.earlyStopping ?? false;
  let running = Array.from({length: beams}, () => [o.startId]);
  let runningScores: number[] = Array.from({length: beams}, (_, i) => i === 0 ? 0 : -1e9);
  let finished = Array.from({length: beams}, () => ({tokens: [] as number[], score: -1e9, done: false}));
  let parents: number[] | null = null, heuristicUnsatisfied = true, curLength = 1;
  const row = new Float64Array(V);
  while (true) {
    const logits = await o.next(running, parents);
    const candidates: {score: number; b: number; t: number}[] = [];
    for (let b = 0; b < beams; b++) {
      for (let t = 0; t < V; t++) row[t] = logits[b * V + t];
      logSoftmaxInPlace(row);
      for (const t of o.bannedTokens ?? []) row[t] = -Infinity;
      if ((o.noRepeatNgram ?? 0) > 0) for (const t of bannedNgramTokens(running[b], o.noRepeatNgram!)) row[t] = -Infinity;
      if (o.renormalize) logSoftmaxInPlace(row);
      for (let t = 0; t < V; t++) {
        const score = row[t] + runningScores[b];
        if (candidates.length < keep) {
          candidates.push({score, b, t});
          if (candidates.length === keep) candidates.sort((x, y) => y.score - x.score || x.b * V + x.t - (y.b * V + y.t));
        } else if (score > candidates[keep - 1].score) {
          let i = keep - 1;
          while (i > 0 && score > candidates[i - 1].score) {candidates[i] = candidates[i - 1]; i--;}
          candidates[i] = {score, b, t};
        }
      }
    }
    const top = candidates.map(c => ({score: c.score, parent: c.b, tokens: [...running[c.b], c.t]}));
    const hits = top.map(c => c.tokens[c.tokens.length - 1] === o.eosId || curLength + 1 >= o.maxLength);
    const order = top.map((c, i) => ({i, s: c.score + (hits[i] ? -1e9 : 0)})).sort((x, y) => y.s - x.s || x.i - y.i).slice(0, beams);
    running = order.map(x => top[x.i].tokens);
    runningScores = order.map(x => x.s);
    parents = order.map(x => top[x.i].parent);
    const full = finished.every(f => f.done) && earlyStopping === true;
    const merged = finished.map(f => ({...f}));
    top.forEach((c, i) => {
      let s = c.score / Math.pow(curLength + 1 - promptLength, lengthPenalty);
      if (full) s += -1e9;
      if (!heuristicUnsatisfied) s += -1e9;
      const justFinished = hits[i] && i < beams;
      if (!justFinished) s += -1e9;
      merged.push({tokens: c.tokens, score: s, done: justFinished});
    });
    finished = merged.map((m, i) => ({...m, i})).sort((x, y) => y.score - x.score || x.i - y.i).slice(0, beams);
    curLength += 1;
    const hypothetical = earlyStopping === 'never' && lengthPenalty > 0 ? o.maxLength - promptLength : curLength - promptLength;
    const best = runningScores[0] / Math.pow(hypothetical, lengthPenalty);
    const worst = Math.min(...finished.map(f => f.score));
    heuristicUnsatisfied = heuristicUnsatisfied && finished.some(f => best > (f.done ? worst : -1e9));
    const openBeam = !(finished.every(f => f.done) && earlyStopping === true);
    if (!(heuristicUnsatisfied && openBeam && !hits.every(Boolean))) break;
  }
  return finished[0];
}

// ---- OPUS-MT --------------------------------------------------------------------------------

export interface MarianTokenizer {encode(text: string): {ids: number[]}; decode(ids: number[], options?: {skip_special_tokens?: boolean}): string}
export interface MarianConfig {vocab_size: number; decoder_attention_heads: number; d_model: number; decoder_layers: number; max_position_embeddings: number}
export interface MarianGeneration {decoder_start_token_id: number; eos_token_id: number; bad_words_ids?: number[][]}
type Tensor = Ort.Tensor;

export class OpusTranslator {
  private vocab: number; private heads: number; private headDim: number; private banned: number[];
  private maxLength: number; private pastNames: string[];
  constructor(private ort: typeof Ort, private tokenizer: MarianTokenizer, private encoder: Ort.InferenceSession,
    private decoder: Ort.InferenceSession, private config: MarianConfig, private generation: MarianGeneration, private numBeams = 4) {
    this.vocab = config.vocab_size; this.heads = config.decoder_attention_heads; this.headDim = config.d_model / config.decoder_attention_heads;
    this.banned = (generation.bad_words_ids ?? []).filter(ids => ids.length === 1).map(ids => ids[0]);
    this.maxLength = 1 + (config.max_position_embeddings - 1);  // prompt + max_new_tokens (511)
    this.pastNames = decoder.inputNames.filter(n => n.startsWith('past_key_values.'));
  }

  private tensor(type: 'int64' | 'bool' | 'float32', data: BigInt64Array | Uint8Array | Float32Array, dims: number[]): Tensor {
    return new this.ort.Tensor(type, data, dims);
  }
  private repeatBatch(tensor: Tensor, batch: number): Tensor {
    const [, ...rest] = tensor.dims, source = tensor.data as Float32Array, data = new (source.constructor as Float32ArrayConstructor)(source.length * batch);
    for (let b = 0; b < batch; b++) data.set(source, b * source.length);
    return new this.ort.Tensor(tensor.type as 'float32', data, [batch, ...rest]);
  }
  private gatherBatch(tensor: Tensor, indices: readonly number[]): Tensor {
    const [batch, ...rest] = tensor.dims, source = tensor.data as Float32Array, size = source.length / batch;
    const data = new (source.constructor as Float32ArrayConstructor)(size * indices.length);
    indices.forEach((from, i) => data.set(source.subarray(from * size, (from + 1) * size), i * size));
    return new this.ort.Tensor(tensor.type as 'float32', data, [indices.length, ...rest]);
  }

  async translate(text: string): Promise<string> {
    // Python: tokenizer(" ".join(text.split())); MarianTokenizer appends </s>; no truncation.
    const ids = this.tokenizer.encode(text.split(/\s+/).filter(Boolean).join(' ')).ids, n = ids.length;
    if (n > this.config.max_position_embeddings) throw new Error(`Input exceeds ${this.config.max_position_embeddings} model tokens. Supply a shorter region.`);
    const encoded = await this.encoder.run({input_ids: this.tensor('int64', BigInt64Array.from(ids, BigInt), [1, n]),
      attention_mask: this.tensor('int64', new BigInt64Array(n).fill(1n), [1, n])});
    const batch = this.numBeams, states = this.repeatBatch(encoded.last_hidden_state, batch);
    const mask = this.tensor('int64', new BigInt64Array(batch * n).fill(1n), [batch, n]);
    let past: Record<string, Tensor> | null = null, encoderPast: Record<string, Tensor> = {};
    // The merged decoder reuses its key/value cache; self-attention caches follow each beam's parent.
    const next: NextLogits = async (sequences, parents) => {
      const first = past === null;
      const feeds: Record<string, Tensor> = {encoder_hidden_states: states, encoder_attention_mask: mask,
        input_ids: this.tensor('int64', BigInt64Array.from(sequences.map(s => BigInt(s[s.length - 1]))), [batch, 1]),
        use_cache_branch: this.tensor('bool', new Uint8Array([first ? 0 : 1]), [1])};
      for (const name of this.pastNames) feeds[name] = first ? this.tensor('float32', new Float32Array(0), [batch, this.heads, 0, this.headDim]) :
        name.includes('.encoder.') ? encoderPast[name] : this.gatherBatch(past![name], parents!);
      const out = await this.decoder.run(feeds);
      const present: Record<string, Tensor> = {};
      for (const name of this.pastNames) {
        const value = out[name.replace('past_key_values.', 'present.')];
        if (name.includes('.encoder.')) {if (first) encoderPast[name] = value;} else present[name] = value;
      }
      past = present;
      const logits = out.logits.data;
      return logits instanceof Float32Array ? logits : Float32Array.from(logits as ArrayLike<number>);
    };
    const result = await beamSearch({next, vocabSize: this.vocab, numBeams: this.numBeams, startId: this.generation.decoder_start_token_id,
      eosId: this.generation.eos_token_id, maxLength: this.maxLength, lengthPenalty: 1, earlyStopping: false, bannedTokens: this.banned, renormalize: true});
    if (result.tokens[result.tokens.length - 1] !== this.generation.eos_token_id) throw new Error('Output reached the generation limit; use a shorter region.');
    const output = this.tokenizer.decode(result.tokens, {skip_special_tokens: true}).trim();
    if (!output) throw new Error('The model returned an empty translation.');
    return output;
  }
}
