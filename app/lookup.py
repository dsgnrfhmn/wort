"""Word lookup on the Wörter page: a word or a sentence -> dictionary entries with their forms.

Same engine as the CLI (wort.dictionary.lookup): the whole query first, German then English, and for a
sentence that is not in the dictionary as a whole, the best entry per word (typos corrected). Nothing is
added to the word list here; the page offers "Zu Wörtern hinzufügen" per entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry
from wort.dictionary.ukrainian import Ukrainian

from app.words import GENDER_LABEL, POS_LABEL, short_gloss, uk_text, v_label

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


def result(entry: Entry, uk: Ukrainian | None, owned: set[tuple[str, str]], de=None) -> Result:
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
    )


def search(dictionary: Dictionary, uk: Ukrainian | None, query: str,
           owned: set[tuple[str, str]], de=None) -> tuple[list[Result], str]:
    """(results, note). The note says when a sentence was split into words and which typos were fixed."""
    german, english = dictionary.lookup(query, limit=MAX_RESULTS)
    entries, note = (german + english)[:MAX_RESULTS], ""
    if not entries and " " in query.strip():
        entries, fixes = dictionary.lookup_words(query, MAX_SENTENCE_WORDS)
        if entries:
            note = "Ein Ergebnis pro Wort" + "".join(f" · {a} → {b}" for a, b in fixes)
    if not entries and (suggested := dictionary.suggest(query.strip(), limit=3)):
        entries, note = suggested, "Nicht gefunden. Meintest du:"
    return [result(e, uk, owned, de) for e in entries], note
