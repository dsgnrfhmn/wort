"""Pick grammatical forms out of an Entry's tagged form list."""

from __future__ import annotations

from collections.abc import Iterable

from lernen.dictionary.lookup import Entry

ARTICLES = {
    "m": {"nominative": "der", "genitive": "des", "dative": "dem", "accusative": "den"},
    "f": {"nominative": "die", "genitive": "der", "dative": "der", "accusative": "die"},
    "n": {"nominative": "das", "genitive": "des", "dative": "dem", "accusative": "das"},
    "pl": {"nominative": "die", "genitive": "der", "dative": "den", "accusative": "die"},
}
CASES = ("nominative", "genitive", "dative", "accusative")
CASE_LABELS = {"nominative": "Nom", "genitive": "Gen", "dative": "Dat", "accusative": "Akk"}
GENDER_ARTICLE = {"m": "der", "f": "die", "n": "das"}

PERSONS = {
    "ich": ("first-person", "singular"),
    "du": ("second-person", "singular"),
    "er": ("third-person", "singular"),
    "wir": ("first-person", "plural"),
    "ihr": ("second-person", "plural"),
    "sie": ("third-person", "plural"),
}

_NOT_INDICATIVE = {
    "subjunctive", "subjunctive-i", "subjunctive-ii", "subordinate-clause", "imperative",
    "participle", "perfect", "pluperfect", "future", "future-i", "future-ii", "infinitive",
    "zu", "dependent",
}
_ADJ_DECLENSION = {"strong", "weak", "mixed", "masculine", "feminine", "neuter", "plural", "singular",
                   "nominative", "genitive", "dative", "accusative", "predicative"}


def find_form(entry: Entry, required: Iterable[str], excluded: Iterable[str] = ()) -> str | None:
    """Form whose tags include all `required` and none of `excluded`; fewest tags wins."""
    required, excluded = set(required), set(excluded)
    best: tuple[int, str] | None = None
    for form, tags in entry.forms:
        tagset = set(tags)
        if required <= tagset and not (excluded & tagset):
            if best is None or len(tagset) < best[0]:
                best = (len(tagset), form)
    return best[1] if best else None


# --- verbs -------------------------------------------------------------------

def present(entry: Entry, person: str) -> str | None:
    return find_form(entry, {"present", *PERSONS[person]}, _NOT_INDICATIVE)


def preterite(entry: Entry, person: str) -> str | None:
    form = find_form(entry, {"past", *PERSONS[person]}, _NOT_INDICATIVE)
    return form or find_form(entry, {"preterite", *PERSONS[person]}, _NOT_INDICATIVE)


def participle2(entry: Entry) -> str | None:
    return find_form(entry, {"participle", "past"}, {"zu"})


def imperative(entry: Entry, number: str) -> str | None:
    return find_form(entry, {"imperative", number})


def principal_parts(entry: Entry) -> list[str]:
    """er-Präsens · er-Präteritum · hat/ist Partizip II (like verbformen's header)."""
    parts = []
    if form := present(entry, "er"):
        parts.append(form)
    if form := preterite(entry, "er") or find_form(entry, {"past"}, _NOT_INDICATIVE):
        parts.append(form)
    if form := participle2(entry):
        aux = (entry.aux or "haben").split(" / ")[0]
        parts.append(f"{'ist' if aux == 'sein' else 'hat'} {form}")
    return parts


def perfect_aux(entry: Entry, person: str) -> str:
    aux = (entry.aux or "haben").split(" / ")[0]
    table = {
        "haben": {"ich": "habe", "du": "hast", "er": "hat", "wir": "haben", "ihr": "habt", "sie": "haben"},
        "sein": {"ich": "bin", "du": "bist", "er": "ist", "wir": "sind", "ihr": "seid", "sie": "sind"},
    }
    return table.get(aux, table["haben"])[person]


WERDEN = {"ich": "werde", "du": "wirst", "er": "wird", "wir": "werden", "ihr": "werdet", "sie": "werden"}


def perfect(entry: Entry, person: str) -> str | None:
    """Perfekt in main-clause order: 'bin gegangen' (separable verbs: 'hat angefangen')."""
    if form := participle2(entry):
        return f"{perfect_aux(entry, person)} {form}"
    return None


def future1(entry: Entry, person: str) -> str:
    """Futur I: 'werde gehen' (infinitive = lemma)."""
    return f"{WERDEN[person]} {entry.lemma}"


# --- nouns -------------------------------------------------------------------

def noun_form(entry: Entry, case: str, number: str) -> str | None:
    form = find_form(entry, {case, number}, {"diminutive", "indefinite"})
    if form is None and case == "nominative" and number == "singular":
        return entry.lemma
    if form is None and case == "nominative" and number == "plural":
        return find_form(entry, {"plural"}, {"diminutive", "indefinite", *CASES[1:]})
    if form is None and case == "genitive" and number == "singular":
        return find_form(entry, {"genitive"}, {"diminutive", "plural", "indefinite"})
    return form


def plural(entry: Entry) -> str | None:
    return noun_form(entry, "nominative", "plural")


def with_article(entry: Entry, form: str, case: str, number: str) -> str:
    key = "pl" if number == "plural" else entry.gender
    if key not in ARTICLES:
        return form
    return f"{ARTICLES[key][case]} {form}"


# --- adjectives --------------------------------------------------------------

def comparative(entry: Entry) -> str | None:
    return find_form(entry, {"comparative"}, _ADJ_DECLENSION)


def superlative(entry: Entry) -> str | None:
    return find_form(entry, {"superlative"}, _ADJ_DECLENSION)


# --- display helpers ---------------------------------------------------------

def stem_of(entry: Entry) -> str:
    """The part of the lemma that inflected forms usually share (for highlighting endings)."""
    lemma = entry.lemma
    if entry.pos == "verb":
        if entry.separable and (third := present(entry, "er")) and " " in third:
            particle = third.split()[-1]
            if lemma.startswith(particle):
                lemma = lemma[len(particle):]
        for ending in ("en", "ern", "eln", "n"):
            if lemma.endswith(ending) and len(lemma) > len(ending) + 1:
                return lemma[: -len(ending)] if ending in ("en", "n") else lemma[:-1]
    return lemma


def split_ending(form: str, stem: str) -> tuple[str, str]:
    """('beabsichtig', 'te') — common prefix with stem, then the rest."""
    i = 0
    while i < min(len(form), len(stem)) and form[i] == stem[i]:
        i += 1
    if i < 2:
        return "", form
    return form[:i], form[i:]
