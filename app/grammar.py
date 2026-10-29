"""Grammar (Üben › Grammatik): B1/B2 topics with an explanation and exercises, graded locally (no AI).

app/grammar.json holds the topics: title, level, summary, sections (title, text, uk, optional table) and exercises
of four types, each with `why` / `uk` (the rule behind it):
- luecke: fill the gap; `answers` are accepted words (umlauts may be typed as ae/oe/ue/ss).
- mc: pick one of `choices` (by number or word); `answers` holds the right one.
- umbau: rewrite a sentence; `answers` are accepted sentences (case and punctuation do not count).
- eigen: an own sentence; `rules` check the structure (below), LanguageTool the rest; `example` is shown as a hint.

Rules: any = groups of words of which the sentence must contain one per group (as words); all = groups of phrases
that must all appear; verb_last_after = after one of these words (with after_comma: only after a comma) the clause
ends with a verb; infinitive_last_after = after one of these words the clause ends with an infinitive.
The file is checked when it is loaded: a malformed file fails loud at startup.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from wort import sanitize
from wort.dictionary.lookup import Dictionary
from wort.text import normalize

from app.i18n import t

PATH = Path(__file__).parent / "grammar.json"
TYPES = {"luecke": "Lückentext: Ergänze die Lücke.", "mc": "Wähle die richtige Form.",
         "umbau": "Schreibe den Satz um.", "eigen": "Schreibe einen eigenen Satz."}
RULES = {"any", "all", "verb_last_after", "infinitive_last_after", "after_comma"}
MAX_ANSWER = 300


def _load(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a non-empty object of topics")
    for key, t in data.items():
        if not re.fullmatch(r"[a-z0-9_]{1,40}", key):
            raise ValueError(f"{path}: topic id {key!r} must be [a-z0-9_]")
        for field in ("title", "level", "summary"):
            if not isinstance(t.get(field), str) or not t[field].strip():
                raise ValueError(f"{path}: topic {key!r} needs a {field}")
        if not isinstance(t.get("sections"), list) or not isinstance(t.get("exercises"), list) or not t["exercises"]:
            raise ValueError(f"{path}: topic {key!r} needs sections and exercises")
        for ex in t["exercises"]:
            kind = ex.get("type")
            ok = kind in TYPES and isinstance(ex.get("prompt"), str) and isinstance(ex.get("why"), str)
            if kind in ("luecke", "mc", "umbau"):
                ok = ok and isinstance(ex.get("answers"), list) and all(isinstance(a, str) and a for a in ex["answers"])
            if kind == "mc":
                ok = ok and isinstance(ex.get("choices"), list) and set(ex["answers"]) <= set(ex["choices"])
            if kind == "eigen":
                ok = ok and isinstance(ex.get("rules"), dict) and set(ex["rules"]) <= RULES and ex["rules"]
            if not ok:
                raise ValueError(f"{path}: topic {key!r} has a malformed {kind!r} exercise: {ex.get('prompt')!r}")
    return data


TOPICS = _load(PATH)


# A mistake's local kind (hints.mistake_kind) -> the Grammatik topic that practises it. Kinds without a topic (verb
# agreement, spelling, casing, …) get no link.
TOPIC_FOR_MISTAKE = {"article": "praepositionen", "adjective": "adjektive", "predicative": "adjektive"}


def topic_for(kind: str) -> str | None:
    topic = TOPIC_FOR_MISTAKE.get(kind)
    return topic if topic in TOPICS else None


def exercise(item: dict) -> dict:
    """The exercise a stored item {topic, ex} names; {} if the file changed since."""
    try:
        return TOPICS[item["topic"]]["exercises"][item["ex"]]
    except (KeyError, IndexError, TypeError):
        return {}


def build_items(topic: str, rng: random.Random) -> list[dict]:
    """A session over one topic: every exercise once, the types mixed."""
    items = [{"kind": "grammar", "topic": topic, "ex": i} for i in range(len(TOPICS[topic]["exercises"]))]
    rng.shuffle(items)
    return items


def _plain(text: str) -> str:
    """Normalized, without punctuation: what an answer is compared by."""
    return " ".join(re.sub(r"[^\w\s]", " ", normalize(text)).split())


def _words(text: str) -> list[str]:
    return _plain(text).split()


def _is_verb(dic: Dictionary | None, word: str) -> bool:
    """A verb form, as far as the dictionary knows. A word it does not know counts when it ends like a verb form
    (-e, -t, -n: rare verbs are missing from it), so "arbeiten" passes and "hier" does not; LanguageTool still
    checks the sentence."""
    entries = dic.lookup_german(word, limit=3) if dic is not None else []
    if not entries:
        return word.endswith(("e", "t", "n"))
    return any(e.pos == "verb" for e in entries)


def _clauses_after(sentence: str, triggers: list[str], after_comma: bool) -> list[list[str]]:
    """The words from each trigger word to the end of its clause (next comma or the end)."""
    wanted = {_plain(t) for t in triggers}
    out = []
    for i, part in enumerate(re.split(r"[,;:]", sentence)):
        words = _words(part)
        for j, w in enumerate(words):
            if w in wanted and (not after_comma or i > 0):
                out.append(words[j:])
                break
    return out


def check_rules(sentence: str, rules: dict, dic: Dictionary | None) -> list[str]:
    """What the sentence lacks for the exercise's structure, as short German notes; [] when it fits."""
    words, plain, problems = _words(sentence), f" {_plain(sentence)} ", []
    for group in rules.get("any", []):
        if not any(_plain(w) in words for w in group):
            problems.append("Es fehlt: " + " / ".join(group[:6]) + ("…" if len(group) > 6 else ""))
    for group in rules.get("all", []):
        if not any(f" {_plain(p)} " in plain for p in group):
            problems.append("Es fehlt: " + " / ".join(group))
    if triggers := rules.get("verb_last_after"):
        clauses = _clauses_after(sentence, triggers, bool(rules.get("after_comma")))
        if clauses and not any(len(c) > 1 and _is_verb(dic, c[-1]) for c in clauses):
            problems.append("Im Nebensatz steht das Verb am Ende.")
    if triggers := rules.get("infinitive_last_after"):
        clauses = _clauses_after(sentence, triggers, False)
        if clauses and not any(len(c) > 1 and c[-1].endswith("n") and _is_verb(dic, c[-1]) for c in clauses):
            problems.append("Der Infinitiv steht am Ende des Satzes.")
    return problems


def grade(item: dict, answer: str, checker, dic: Dictionary | None):
    """(verdict, expected, feedback, remarks, corrected, final) for one answer. verdict None: not graded (no score);
    final False: nothing to grade yet (empty answer), the task stays open."""
    from app.checking import check_sentence  # the same LanguageTool path as the sentence tasks

    ex = exercise(item)
    answer = sanitize.text(answer, MAX_ANSWER)
    if not ex:
        return None, "", t("This task no longer exists."), [], "", True
    if not answer:
        return None, "", t("Enter an answer."), [], "", False
    expected = " / ".join(ex.get("answers", [])) or ex.get("example", "")
    kind = ex["type"]
    if kind in ("luecke", "mc"):
        given = answer
        if kind == "mc" and answer.strip().isdigit() and 1 <= int(answer) <= len(ex["choices"]):
            given = ex["choices"][int(answer) - 1]
        right = _plain(given) in {_plain(a) for a in ex["answers"]}
        return ("correct" if right else "wrong"), expected, ("Richtig." if right else t("Not right, unfortunately.")), [], "", True
    if kind == "umbau" and _plain(answer) in {_plain(a) for a in ex["answers"]}:
        return "correct", expected, "Richtig.", [], "", True
    result = check_sentence(answer, [], checker)
    if result.error:
        return None, expected, result.error, [], "", False
    remarks = [{"fragment": r.fragment, "message": r.message, "replacements": r.replacements,
                **({"rule": r.rule, "category": r.category} if r.rule or r.category else {})} for r in result.remarks]
    corrected = result.corrected if remarks else answer
    if kind == "umbau":  # not one of the accepted sentences: wrong, with the grammar remarks for the why
        return "wrong", expected, "Nicht wie erwartet: siehe Erwartet und Regel.", remarks, corrected, True
    problems = check_rules(answer, ex["rules"], dic)
    if problems:
        return "wrong", ex.get("example", ""), " ".join(problems), remarks, corrected, True
    if not result.checked:
        return None, ex.get("example", ""), t("Structure right, grammar not checked: no score."), [], answer, True
    return ("almost" if remarks else "correct"), ex.get("example", ""), \
        (t("Structure right, but there are grammar notes.") if remarks else "Richtig."), remarks, corrected, True
