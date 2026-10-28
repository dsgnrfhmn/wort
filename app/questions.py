"""Questions for "Sätze bilden": a fixed list per topic (app/questions.json), picked at random, no AI.

Each question is {"q": question, "a": a sample answer (not shown since 2026-10-28: "Beispielantwort" now has the
asked word in the asked form, app/hints.example_answer), "k": English keywords,
"general"?: true when almost any word fits}. A word is matched to questions through its English glosses: the
questions whose keywords share the most stems with them; without any shared stem, the general ones.

An item stores only a reference [topic, index]; the text is looked up when the task is shown. The file
is checked when it is loaded: a malformed file fails loud at startup instead of showing broken tasks.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

PATH = Path(__file__).parent / "questions.json"
ALL = "alle"
MAX_QUESTION = 200


def _load(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a non-empty object of topics")
    for key, topic in data.items():
        qs = topic.get("questions") if isinstance(topic, dict) else None
        if key == ALL or not isinstance(topic.get("label"), str) or not isinstance(qs, list) or not qs:
            raise ValueError(f"{path}: topic {key!r} needs a label and a non-empty question list")
        for q in qs:
            ok = isinstance(q, dict) and {"q", "a", "k"} <= set(q) <= {"q", "a", "k", "general"} and all(
                isinstance(q[k], str) and q[k].strip() and len(q[k]) <= MAX_QUESTION for k in ("q", "a"))
            ok = ok and isinstance(q["k"], list) and all(isinstance(w, str) and w for w in q["k"])
            ok = ok and isinstance(q.get("general", False), bool)
            if not ok:
                raise ValueError(f"{path}: topic {key!r} has a question that is not {{q, a, k[, general]}} with short, "
                                 "non-empty text")
    return data


TOPICS = _load(PATH)
LABELS = {ALL: "Alle Themen"} | {k: t["label"] for k, t in TOPICS.items()}


def topic_or_all(value: str | None) -> str:
    return value if value in TOPICS else ALL


_STOP = {"a", "an", "the", "of", "to", "or", "and", "in", "for", "on", "by", "with", "as", "be", "that", "which",
         "something", "someone", "one", "it", "from", "at", "is", "used", "e", "g", "etc", "oneself", "about", "up"}


def stem(word: str) -> str:
    """A crude English stem, the same for keywords and glosses: repairs / repaired / repairing -> repair."""
    w = word.lower()
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def gloss_stems(glosses: list[str]) -> set[str]:
    return {stem(w) for g in glosses[:4] for w in re.findall(r"[A-Za-z]+", g) if w.lower() not in _STOP}


def _pool(topic: str) -> list[list]:
    keys = list(TOPICS) if topic == ALL else [topic]
    return [[k, i] for k in keys for i in range(len(TOPICS[k]["questions"]))]


def matches(topic: str, glosses: list[str]) -> list[list]:
    """The questions of `topic` that fit a word with these English glosses best: the highest keyword overlap; with
    none, the general questions (all of them if the topic has none)."""
    pool, stems = _pool(topic), gloss_stems(glosses)
    scored = [(len(stems & {stem(w) for w in _entry(r)["k"]}), r) for r in pool]
    best = max((s for s, _ in scored), default=0)
    if best > 0:
        return [r for s, r in scored if s == best]
    return [r for r in pool if _entry(r).get("general")] or pool


def pick_for(topic: str, glosses: list[str], rng: random.Random, avoid: list | None = None) -> list:
    """One reference [topic, index] for a word, not in `avoid` while possible: its best matches first, then the
    topic's general questions, then any question of the topic; only when all are used, a best match again."""
    best, pool = matches(topic, glosses), _pool(topic)
    for options in (best, [r for r in pool if _entry(r).get("general")], pool):
        fresh = [r for r in options if r not in (avoid or [])]
        if fresh:
            return rng.choice(fresh)
    return rng.choice(best)


def pick(topic: str, n: int, rng: random.Random) -> list[list]:
    """n references [topic, index], without repeats until the pool is used up (no word to match)."""
    pool = _pool(topic)
    out: list[list] = []
    while len(out) < n:
        out += rng.sample(pool, min(len(pool), n - len(out)))
    return out


def _entry(ref) -> dict:
    try:
        key, index = ref
        return TOPICS[key]["questions"][index] if index >= 0 else {}
    except (TypeError, ValueError, KeyError, IndexError):
        return {}


def text(ref) -> str:
    """The question for a stored reference; "" if the reference no longer exists (file edited since)."""
    return _entry(ref).get("q", "")


def example(ref) -> str:
    """The example answer for a stored reference; "" if the reference no longer exists."""
    return _entry(ref).get("a", "")
