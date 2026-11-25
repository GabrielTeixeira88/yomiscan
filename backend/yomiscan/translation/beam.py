"""transformers' GenerationMixin beam search for one input, without Torch (Stage 5b).

A Python port of the browser engine's port (extension/src/engine/translation.ts), which follows
transformers' `_beam_search`: log-softmax, banned tokens, optional renormalization, top 2*beams
candidates with index order on ties, finished hypotheses scored with the length penalty, and the
same stopping heuristic. With `early_stopping=False` it reproduced MarianMTModel.generate on
153/153 translation-set lines.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

# step(sequences, parents) -> logits (beams, vocab) for each running sequence's next token.
# `parents[i]` is the beam whose cache sequence i continues (None on the first step).
Step = Callable[[list[list[int]], list[int] | None], np.ndarray]
NEG = -1e9


@dataclass(frozen=True)
class Hypothesis:
    tokens: list[int]
    score: float
    done: bool


def _log_softmax(rows: np.ndarray) -> np.ndarray:
    peak = rows.max(axis=1, keepdims=True)
    peak[~np.isfinite(peak)] = 0
    shifted = rows - peak
    return shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))


def beam_search(step: Step, *, vocab_size: int, num_beams: int, start_id: int, eos_id: int, max_length: int,
                length_penalty: float = 1.0, banned: Sequence[int] = (), renormalize: bool = True) -> Hypothesis:
    """Beam search with early_stopping=False; returns the best finished (or best kept) hypothesis."""
    keep, prompt = 2 * num_beams, 1
    running = [[start_id] for _ in range(num_beams)]
    running_scores = np.array([0.0] + [NEG] * (num_beams - 1))
    finished = [Hypothesis([], NEG, False) for _ in range(num_beams)]
    parents: list[int] | None = None
    heuristic, length = True, 1
    while True:
        rows = _log_softmax(np.asarray(step(running, parents), dtype=np.float64).reshape(num_beams, vocab_size))
        if banned:
            rows[:, list(banned)] = -np.inf
        if renormalize:
            rows = _log_softmax(rows)
        flat = (rows + running_scores[:, None]).reshape(-1)
        part = np.argpartition(-flat, keep)[:keep]
        order = part[np.lexsort((part, -flat[part]))]  # score descending, then index
        top = [(float(flat[i]), int(i // vocab_size), running[i // vocab_size] + [int(i % vocab_size)]) for i in order]
        hits = [tokens[-1] == eos_id or length + 1 >= max_length for _, _, tokens in top]
        kept = sorted(range(keep), key=lambda i: (-(top[i][0] + (NEG if hits[i] else 0)), i))[:num_beams]
        running = [top[i][2] for i in kept]
        running_scores = np.array([top[i][0] + (NEG if hits[i] else 0) for i in kept])
        parents = [top[i][1] for i in kept]
        merged = list(finished)
        for i, (score, _, tokens) in enumerate(top):
            just_finished = hits[i] and i < num_beams
            scored = score / (length + 1 - prompt) ** length_penalty
            if not heuristic:  # transformers adds each penalty separately
                scored += NEG
            if not just_finished:
                scored += NEG
            merged.append(Hypothesis(tokens, scored, just_finished))
        finished = [merged[i] for i in sorted(range(len(merged)), key=lambda i: (-merged[i].score, i))[:num_beams]]
        length += 1
        best = running_scores[0] / (length - prompt) ** length_penalty
        worst = min(h.score for h in finished)
        heuristic = heuristic and any(best > (worst if h.done else NEG) for h in finished)
        if not heuristic or all(hits):
            return finished[0]
