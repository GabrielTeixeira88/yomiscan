// Stage 2 spike: transformers GenerationMixin._beam_search (batch size 1) in JavaScript.
// Shared by manga-ocr (no KV cache) and OPUS-MT (KV cache reordered by parent beam).
//
// next(sequences, parents) must return the last-position logits for every running beam as one
// Float32Array of numBeams * vocabSize. `parents[i]` is the index (in the previous call's
// `sequences`) that running beam i continues; it is null on the first call.
//
// Logits processing per beam, in transformers' order: log_softmax, then banned tokens
// (NoBadWords), then no-repeat n-grams, then (renormalize) LogitNormalization; then the beam's
// running score is added.

function logSoftmaxInPlace(row) {
  let max = -Infinity;
  for (let i = 0; i < row.length; i++) if (row[i] > max) max = row[i];
  if (max === -Infinity) return;
  let sum = 0;
  for (let i = 0; i < row.length; i++) sum += Math.exp(row[i] - max);
  const lse = max + Math.log(sum);
  for (let i = 0; i < row.length; i++) row[i] -= lse;
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

export async function beamSearch({next, vocabSize: V, numBeams: beams, startId, eosId, maxLength,
                                  lengthPenalty = 1, earlyStopping = false, noRepeatNgram = 0,
                                  bannedTokens = [], renormalize = false}) {
  const keep = 2 * beams, promptLength = 1;
  let running = Array.from({length: beams}, () => [startId]);
  let runningScores = Array.from({length: beams}, (_, i) => i === 0 ? 0 : -1e9);
  let finished = Array.from({length: beams}, () => ({tokens: null, score: -1e9, done: false}));
  let parents = null, heuristicUnsatisfied = true, curLength = 1;
  const row = new Float64Array(V);
  while (true) {
    const logits = await next(running, parents);
    const candidates = [];
    for (let b = 0; b < beams; b++) {
      for (let t = 0; t < V; t++) row[t] = logits[b * V + t];
      logSoftmaxInPlace(row);
      for (const t of bannedTokens) row[t] = -Infinity;
      if (noRepeatNgram > 0) for (const t of bannedNgramTokens(running[b], noRepeatNgram)) row[t] = -Infinity;
      if (renormalize) logSoftmaxInPlace(row);
      for (let t = 0; t < V; t++) {
        const score = row[t] + runningScores[b];
        if (candidates.length < keep) {
          candidates.push({score, b, t});
          if (candidates.length === keep) candidates.sort((x, y) => y.score - x.score || x.b * V + x.t - (y.b * V + y.t));
        } else if (score > candidates[keep - 1].score) {
          let i = keep - 1;
          while (i > 0 && score > candidates[i - 1].score) { candidates[i] = candidates[i - 1]; i--; }
          candidates[i] = {score, b, t};
        }
      }
    }
    const top = candidates.map(c => ({score: c.score, parent: c.b, tokens: [...running[c.b], c.t]}));
    const hits = top.map(c => c.tokens.at(-1) === eosId || curLength + 1 >= maxLength);
    // Next running beams: the best `beams` candidates that did not finish.
    const order = top.map((c, i) => ({i, s: c.score + (hits[i] ? -1e9 : 0)})).sort((x, y) => y.s - x.s || x.i - y.i).slice(0, beams);
    running = order.map(o => top[o.i].tokens);
    runningScores = order.map(o => o.s);
    parents = order.map(o => top[o.i].parent);
    // Finished beams: only the first `beams` ranks may finish; length-normalised score.
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
    const hypothetical = earlyStopping === "never" && lengthPenalty > 0 ? maxLength - promptLength : curLength - promptLength;
    const best = runningScores[0] / Math.pow(hypothetical, lengthPenalty);
    const worst = Math.min(...finished.map(f => f.score));
    heuristicUnsatisfied = heuristicUnsatisfied && finished.some(f => best > (f.done ? worst : -1e9));
    const openBeam = !(finished.every(f => f.done) && earlyStopping === true);
    if (!(heuristicUnsatisfied && openBeam && !hits.every(Boolean))) break;
  }
  return finished[0];
}
