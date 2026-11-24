// Stage 2 spike: OPUS-MT ja-en (Xenova ONNX export of Helsinki-NLP/opus-mt-ja-en) with
// transformers-exact beam search, matching the Python backend's MarianTranslationEngine:
// num_beams 4, length_penalty 1, early_stopping false, max 511 new tokens, pad token banned
// (bad_words_ids), renormalize_logits, no forced EOS. Greedy decoding is kept for comparison.
// The merged decoder reuses its key/value cache; caches are reordered by parent beam each step.
import {beamSearch} from "./beam.mjs";

export class OpusTranslator {
  constructor({ort, tokenizer, encoder, decoder, config, generation, numBeams = 4}) {
    Object.assign(this, {ort, tokenizer, encoder, decoder, numBeams});
    this.vocab = config.vocab_size;
    this.heads = config.decoder_attention_heads;
    this.headDim = config.d_model / config.decoder_attention_heads;
    this.layers = config.decoder_layers;
    this.start = generation.decoder_start_token_id;
    this.eos = generation.eos_token_id;
    this.banned = (generation.bad_words_ids ?? []).filter(ids => ids.length === 1).map(ids => ids[0]);
    this.maxLength = 1 + (config.max_position_embeddings - 1); // prompt + max_new_tokens (511)
    this.pastNames = decoder.inputNames.filter(n => n.startsWith("past_key_values."));
  }

  tensor(type, data, dims) { return new this.ort.Tensor(type, data, dims); }

  async encode(text) {
    // Python: prefix "" + " ".join(text.split()), MarianTokenizer adds </s>.
    const ids = this.tokenizer.encode(text.split(/\s+/).filter(Boolean).join(" "));
    const n = ids.length;
    const out = await this.encoder.run({
      input_ids: this.tensor("int64", BigInt64Array.from(ids, BigInt), [1, n]),
      attention_mask: this.tensor("int64", new BigInt64Array(n).fill(1n), [1, n]),
    });
    return {hidden: out.last_hidden_state, length: n};
  }

  repeatBatch(tensor, batch) {
    const [, ...rest] = tensor.dims, size = tensor.data.length;
    const data = new tensor.data.constructor(size * batch);
    for (let b = 0; b < batch; b++) data.set(tensor.data, b * size);
    return this.tensor(tensor.type, data, [batch, ...rest]);
  }

  gatherBatch(tensor, indices) {
    const [batch, ...rest] = tensor.dims, size = tensor.data.length / batch;
    const data = new tensor.data.constructor(size * indices.length);
    indices.forEach((source, i) => data.set(tensor.data.subarray(source * size, (source + 1) * size), i * size));
    return this.tensor(tensor.type, data, [indices.length, ...rest]);
  }

  // Returns a next(sequences, parents) callback for beam.mjs over a batch of `batch` beams.
  decoderStep({hidden, length}, batch) {
    const encoderStates = this.repeatBatch(hidden, batch);
    const encoderMask = this.tensor("int64", new BigInt64Array(batch * length).fill(1n), [batch, length]);
    let past = null, encoderPast = null;
    return async (sequences, parents) => {
      const feeds = {encoder_hidden_states: encoderStates, encoder_attention_mask: encoderMask};
      const first = past === null;
      feeds.input_ids = this.tensor("int64", BigInt64Array.from(sequences.map(s => BigInt(s.at(-1)))), [batch, 1]);
      feeds.use_cache_branch = this.tensor("bool", new Uint8Array([first ? 0 : 1]), [1]);
      for (const name of this.pastNames) {
        if (first) {
          feeds[name] = this.tensor("float32", new Float32Array(0), [batch, this.heads, 0, this.headDim]);
        } else if (name.includes(".encoder.")) {
          feeds[name] = encoderPast[name];
        } else {
          feeds[name] = this.gatherBatch(past[name], parents);
        }
      }
      const out = await this.decoder.run(feeds);
      past = {};
      if (first) encoderPast = {};
      for (const name of this.pastNames) {
        const present = out[name.replace("past_key_values.", "present.")];
        if (name.includes(".encoder.")) { if (first) encoderPast[name] = present; }
        else past[name] = present;
      }
      const logits = out.logits.data instanceof Float32Array ? out.logits.data : Float32Array.from(out.logits.data);
      return logits; // [batch, 1, vocab] == batch * vocab
    };
  }

  async translate(text, {decoding = "beam"} = {}) {
    const t0 = performance.now();
    const encoded = await this.encode(text);
    const t1 = performance.now();
    let tokens;
    if (decoding === "greedy") {
      const next = this.decoderStep(encoded, 1);
      tokens = [this.start];
      let parents = null;
      while (tokens.length < this.maxLength) {
        const row = await next([tokens], parents);
        for (const t of this.banned) row[t] = -Infinity;
        let best = 0;
        for (let i = 1; i < this.vocab; i++) if (row[i] > row[best]) best = i;
        tokens.push(best); parents = [0];
        if (best === this.eos) break;
      }
    } else {
      const result = await beamSearch({next: this.decoderStep(encoded, this.numBeams), vocabSize: this.vocab,
        numBeams: this.numBeams, startId: this.start, eosId: this.eos, maxLength: this.maxLength,
        lengthPenalty: 1, earlyStopping: false, bannedTokens: this.banned, renormalize: true});
      tokens = result.tokens;
    }
    if (tokens.at(-1) !== this.eos) throw new Error("Output reached the generation limit; use a shorter region.");
    const text_ = this.tokenizer.decode(tokens, {skip_special_tokens: true});
    return {text: text_, tokens: tokens.length, timings: {encoder: t1 - t0, decoder: performance.now() - t1}};
  }
}
