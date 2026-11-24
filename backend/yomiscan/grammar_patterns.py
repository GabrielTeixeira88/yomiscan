"""Grammar notes: patterns over UniDic tokens, defined as data (resources/lexical/grammar.json).

JMdict lists words, not constructions. てしまう, ている, だろう or ことができる are grammar: they
explain how the words combine. A pattern is a sequence of token steps; a step matches one
token when every given field agrees (surface exact, base = orthographic base or lemma, pos =
first UniDic level, form = conjugation-form prefix). The same file can drive a browser engine.

At one start token only the longest match is kept (てもいい over ても), and a match lying
inside another is dropped (ば inside なければならない). Partly overlapping matches at different
starts are kept, because one phrase can carry several constructions.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from .nlp import JapaneseToken

RULES_PATH = Path(__file__).parent / "resources" / "lexical" / "grammar.json"
STEP_FIELDS = frozenset({"surface", "base", "pos", "form"})


@dataclass(frozen=True)
class GrammarPattern:
    id: str
    name: str
    forms: tuple[str, ...]
    meaning: str
    alternatives: tuple[tuple[dict[str, tuple[str, ...]], ...], ...]
    after: dict[str, tuple[str, ...]] | None = None  # must match the token before the match


@dataclass(frozen=True)
class GrammarMatch:
    pattern: str  # GrammarPattern.id
    start: int
    end: int  # exclusive token index


@lru_cache(maxsize=4)
def load_patterns(path: Path = RULES_PATH) -> tuple[GrammarPattern, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported grammar rules schema {data.get('schema_version')!r}")
    patterns, seen = [], set()
    for item in data["patterns"]:
        if item["id"] in seen:
            raise ValueError(f"{path}: duplicate grammar pattern {item['id']!r}")
        seen.add(item["id"])
        alternatives = []
        for steps in item["alternatives"]:
            if not steps or any(not step or set(step) - STEP_FIELDS for step in steps):
                raise ValueError(f"{path}: pattern {item['id']!r} has an empty or unknown step field")
            alternatives.append(tuple({key: tuple(values) for key, values in step.items()} for step in steps))
        after = item.get("after")
        if after is not None and (not after or set(after) - STEP_FIELDS):
            raise ValueError(f"{path}: pattern {item['id']!r} has an empty or unknown 'after' field")
        patterns.append(GrammarPattern(item["id"], item["name"], tuple(item["forms"]), item["meaning"], tuple(alternatives),
                                       {key: tuple(values) for key, values in after.items()} if after else None))
    return tuple(patterns)


def step_matches(step: dict[str, tuple[str, ...]], token: JapaneseToken) -> bool:
    pos = token.part_of_speech.split(" / ")[0] if token.part_of_speech else None
    bases = {value for value in (token.orthographic_base, token.lemma) if value}
    return (("surface" not in step or token.surface in step["surface"])
            and ("base" not in step or bool(bases & set(step["base"])))
            and ("pos" not in step or pos in step["pos"])
            and ("form" not in step or any((token.conjugation_form or "").startswith(form) for form in step["form"])))


def find_grammar(tokens: Sequence[JapaneseToken], patterns: Sequence[GrammarPattern] | None = None) -> tuple[GrammarMatch, ...]:
    patterns = patterns if patterns is not None else load_patterns()
    best: dict[int, GrammarMatch] = {}
    for start in range(len(tokens)):
        for pattern in patterns:
            if pattern.after is not None and (start == 0 or not step_matches(pattern.after, tokens[start - 1])):
                continue
            for steps in pattern.alternatives:
                end = start + len(steps)
                if end <= len(tokens) and all(step_matches(step, token) for step, token in zip(steps, tokens[start:end])):
                    current = best.get(start)
                    if current is None or end > current.end:  # longest at a start; earlier patterns win ties
                        best[start] = GrammarMatch(pattern.id, start, end)
    matches = [best[start] for start in sorted(best)]
    # A match inside another (ば inside なければならない) is part of that construction.
    return tuple(m for m in matches if not any(o is not m and o.start <= m.start and m.end <= o.end for o in matches))


def pattern_by_id(identifier: str) -> GrammarPattern:
    return next(pattern for pattern in load_patterns() if pattern.id == identifier)
