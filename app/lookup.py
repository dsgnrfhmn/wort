"""Word lookup on the Wörter page: a word or a sentence -> dictionary entries with their forms.

Same engine as the CLI (wort.dictionary.lookup): the whole query first, German then English, and for a
sentence that is not in the dictionary as a whole, the best entry per word (typos corrected). Nothing is
added to the word list here; the page offers "Zu Wörtern hinzufügen" per entry.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry
from wort.dictionary.ukrainian import Ukrainian

from app.words import GENDER_LABEL, POS_LABEL, short_gloss, uk_text, v_label
from app.i18n import t

MAX_QUERY = 200
MAX_RESULTS = 5  # entries for a single word
MAX_SENTENCE_WORDS = 12  # one entry per word
CASES = (("nominative", "Nom."), ("accusative", "Akk."), ("dative", "Dat."), ("genitive", "Gen."))
PERSON_LABELS = (("ich", "ich"), ("du", "du"), ("er", "er/sie/es"), ("wir", "wir"), ("ihr", "ihr"), ("sie", "sie/Sie"))


@dataclass
class FormsTable:
    title: str
    headers: list[str]
    rows: list[list[str]]


@dataclass
class Result:
    entry: Entry
    label: str
    article: str
    caption: str
    translation: str
    tooltip: str
    owned: bool
    table: FormsTable | None = None
    examples: list[tuple[str, str]] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)  # German, from dictionary-de.db when it is installed
    meta: str = ""  # "Nomen · feminin · Pl. die Entwicklungen · /ɛntˈvɪklʊŋ/"
    sample: list[dict] = field(default_factory=list)  # examples: {"segments": [{text, hl?}], "translation"}
    related: list[dict] = field(default_factory=list)  # {"label", "article", "pos", "q"}


def declension(entry: Entry) -> list[list[str]]:
    """Kasus | Singular | Plural, with articles; [] for a non-noun."""
    if entry.pos != "noun":
        return []
    rows = []
    for case, label in CASES:
        row = [label]
        for number in ("singular", "plural"):
            form = g.noun_form(entry, case, number)
            row.append(g.with_article(entry, form, case, number) if form else "–")
        rows.append(row)
    return rows


def forms_table(entry: Entry) -> FormsTable | None:
    if entry.pos == "noun":
        return FormsTable("Deklination", ["Kasus", "Singular", "Plural"], declension(entry))
    if entry.pos == "verb":
        rows = [[label, g.present(entry, p) or "–", g.preterite(entry, p) or "–", g.perfect(entry, p) or "–"]
                for p, label in PERSON_LABELS]
        return FormsTable("Konjugation", ["Person", "Präsens", "Präteritum", "Perfekt"], rows)
    if entry.pos == "adj" and (comp := g.comparative(entry)):
        return FormsTable("Steigerung", ["Positiv", "Komparativ", "Superlativ"],
                          [[entry.lemma, comp, g.superlative(entry) or "–"]])
    return None


MAX_EXAMPLES = 6


def highlight(sentence: str, forms: set[str]) -> list[dict]:
    """The sentence as runs, the ones that are a form of the word marked `hl` (plain text, never markup)."""
    from wort.text import normalize
    out: list[dict] = []
    for part in re.split(r"([\wÄÖÜäöüß]+)", sentence):
        if part:
            out.append({"text": part, "hl": True} if normalize(part) in forms else {"text": part})
    return out


def sample(entry: Entry, translate: Callable[[str], str] | None = None) -> list[dict]:
    """Up to MAX_EXAMPLES examples with the word marked; the translation is `translate`'s (Ukrainian, offline) when
    it has one, else the dataset's English."""
    from app.checking import lemma_forms
    forms = lemma_forms(entry)
    return [{"segments": highlight(de, forms), "translation": (translate(de) if translate else "") or en}
            for de, en in entry.examples[:MAX_EXAMPLES]]


def result(entry: Entry, uk: Ukrainian | None, owned: set[tuple[str, str]], de=None,
           translate: Callable[[str], str] | None = None, dictionary: Dictionary | None = None) -> Result:
    article = g.ARTICLES[entry.gender]["nominative"] if entry.pos == "noun" and entry.gender in g.ARTICLES else ""
    caption = POS_LABEL.get(entry.pos, entry.pos.capitalize())
    if article:
        caption += " · " + GENDER_LABEL[entry.gender]
    uk_words, en_words = uk_text(uk, entry, entry.lemma, entry.pos, 3), short_gloss(entry.glosses)
    return Result(
        entry, v_label(entry), article, caption,
        " · ".join(p for p in (uk_words, en_words) if p) or "–", "\n".join(p for p in (en_words, uk_words) if p),
        (entry.lemma.casefold(), entry.pos) in owned, forms_table(entry), list(entry.examples[:2]),
        de.definitions(entry.lemma, entry.pos) if de else [],
        meta=" · ".join(x for x in (caption, plural_label(entry), f"/{entry.ipa.strip('/')}/" if entry.ipa else "") if x),
        sample=sample(entry, translate),
        related=[{"label": v_label(r), "article": g.ARTICLES[r.gender]["nominative"]
                  if r.pos == "noun" and r.gender in g.ARTICLES else "",
                  "pos": "" if r.pos == "noun" else POS_LABEL.get(r.pos, r.pos.capitalize()), "q": r.lemma}
                 for r in (dictionary.related(entry) if dictionary else [])],
    )


def plural_label(entry: Entry) -> str:
    if entry.pos != "noun":
        return ""
    form = g.noun_form(entry, "nominative", "plural")
    return f"Pl. {g.with_article(entry, form, 'nominative', 'plural')}" if form else ""


SUGGESTED = "Not found. Did you mean:"  # the note for close matches only (app/words.py: not a hit)


def search(dictionary: Dictionary, uk: Ukrainian | None, query: str,
           owned: set[tuple[str, str]], de=None) -> tuple[list[Result], str]:
    """(results, note). The note says when a sentence was split into words and which typos were fixed."""
    german, english = dictionary.lookup(query, limit=MAX_RESULTS)
    entries, note = (german + english)[:MAX_RESULTS], ""
    if not entries and " " in query.strip():
        entries, fixes = dictionary.lookup_words(query, MAX_SENTENCE_WORDS)
        if entries:
            note = t("One result per word") + "".join(f" · {a} → {b}" for a, b in fixes)
    if not entries and (suggested := dictionary.suggest(query.strip(), limit=3)):
        entries, note = suggested, t(SUGGESTED)
    # The first entry is the one shown in full: its examples translated (offline, slow on a small server) and its
    # related words; the others stay short.
    from app import mt
    first = lambda text: mt.translate(text, "uk")
    return [result(e, uk, owned, de, first if i == 0 else None, dictionary if i == 0 else None)
            for i, e in enumerate(entries)], note
