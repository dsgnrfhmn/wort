"""Dictionary access and the short per-word grammar summary (templates, no LLM)."""

from __future__ import annotations

from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry


def find_entry(dictionary: Dictionary, lemma: str, pos: str = "") -> Entry | None:
    return dictionary.find_lemma(lemma, pos or None)


def summary(entry: Entry) -> list[str]:
    """Short grammar facts for the word, one line each."""
    lines: list[str] = []
    if entry.pos == "noun":
        if entry.gender in g.ARTICLES:
            lines.append(f"Noun, article «{g.ARTICLES[entry.gender]['nominative']}».")
        if pl := g.plural(entry):
            lines.append(f"Plural: {pl}.")
        if gen := g.noun_form(entry, "genitive", "singular"):
            lines.append(f"Genitive singular: {gen}.")
    elif entry.pos == "verb":
        parts = g.principal_parts(entry)
        if parts:
            lines.append("Principal parts: " + ", ".join(parts) + ".")
        if entry.aux:
            lines.append(f"Perfekt with «{entry.aux}».")
        if entry.separable:
            lines.append("Separable verb.")
    elif entry.pos == "adj":
        if comp := g.comparative(entry):
            sup = g.superlative(entry)
            lines.append(f"Komparativ: {comp}" + (f", Superlativ: {sup}." if sup else "."))
    return lines
