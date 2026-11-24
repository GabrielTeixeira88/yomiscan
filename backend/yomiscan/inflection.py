"""Learner inflection labels for verbs and adjectives (食べなかった = 食べる + negative, past).

UniDic splits an inflected word into a stem and auxiliaries and labels forms such as
連用形-促音便, which mean little to a learner. This module reads the head token's own form
and the auxiliaries (and て/で/ば) that follow it, and names each step from rule data in
resources/lexical/inflections.json. Labels attach to the head token; followers get none.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from .nlp import JapaneseToken

RULES_PATH = Path(__file__).parent / "resources" / "lexical" / "inflections.json"
RULE_FIELDS = frozenset({"surface", "base", "form", "pos", "label"})


@dataclass(frozen=True)
class InflectionRules:
    own_forms: tuple[dict[str, tuple[str, ...] | str], ...]
    followers: tuple[dict[str, tuple[str, ...] | str], ...]
    follower_pos: frozenset[str]
    follower_particles: frozenset[str]
    heads: frozenset[str]


def _rules(items: list[dict], path: Path) -> tuple[dict[str, tuple[str, ...] | str], ...]:
    rules = []
    for item in items:
        if "label" not in item or set(item) - RULE_FIELDS or len(item) < 2:
            raise ValueError(f"{path}: inflection rules need a label and at least one match field: {item}")
        rules.append({key: value if key == "label" else tuple(value) for key, value in item.items()})
    return tuple(rules)


@lru_cache(maxsize=4)
def load_rules(path: Path = RULES_PATH) -> InflectionRules:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported inflection rules schema {data.get('schema_version')!r}")
    return InflectionRules(_rules(data["own_forms"], path), _rules(data["followers"], path), frozenset(data["follower_pos"]),
                           frozenset(data["follower_particles"]), frozenset(data["heads"]))


def _pos(token: JapaneseToken) -> str | None:
    return token.part_of_speech.split(" / ")[0] if token.part_of_speech else None


def _label(rules: Sequence[dict[str, tuple[str, ...] | str]], token: JapaneseToken) -> str | None:
    bases = {value for value in (token.orthographic_base, token.lemma) if value}
    for rule in rules:
        if (("surface" not in rule or token.surface in rule["surface"])
                and ("base" not in rule or bool(bases & set(rule["base"])))
                and ("pos" not in rule or _pos(token) in rule["pos"])
                and ("form" not in rule or any((token.conjugation_form or "").startswith(f) for f in rule["form"]))):
            return str(rule["label"])
    return None


def inflection_labels(tokens: Sequence[JapaneseToken], rules: InflectionRules | None = None) -> tuple[tuple[str, ...], ...]:
    """Labels per token (aligned with `tokens`): non-empty only for verb/adjective heads."""
    rules = rules or load_rules()
    result: list[tuple[str, ...]] = [() for _ in tokens]
    consumed: set[int] = set()  # followers are part of the head's word (高く+なかっ+た)
    for index, token in enumerate(tokens):
        if _pos(token) not in rules.heads or index in consumed:
            continue
        labels = [label] if (label := _label(rules.own_forms, token)) else []
        for offset, follower in enumerate(tokens[index + 1:], index + 1):
            explicit = any("pos" in rule and _label([rule], follower) for rule in rules.followers)
            if _pos(follower) not in rules.follower_pos and follower.surface not in rules.follower_particles and not explicit:
                break
            label = _label(rules.followers, follower)
            if label is None:
                break  # an unknown auxiliary (copula だ, etc.) ends the word
            labels.append(label)
            consumed.add(offset)
            if follower.surface in rules.follower_particles:
                break  # て/で/ば close the inflected word
        result[index] = tuple(dict.fromkeys(labels))
    return tuple(result)
