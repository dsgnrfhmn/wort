"""Looking a word or sentence up: the dictionary lookup, the logged `find`, and the plain output."""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from typing import Callable, ContextManager

from rich.text import Text

from wort import paths, sanitize, sentence
from wort.dataschema import Invalid
from wort.dictionary.grammar import GENDER_ARTICLE
from wort.dictionary.lookup import PUNCTUATION, Dictionary, Entry
from wort.history import HistoryStore
from wort.output import console, print_text
from wort.render.card import MUTED, noun_color
from wort.sentence import MIN_SENTENCE_WORDS, Translation

MAX_PHRASE_WORDS = 30  # a short phrase is looked up word by word up to this many words; each one is a picker entry

Working = Callable[[str], ContextManager[None]]  # shows a message while a slow step runs (output.working)


@dataclass
class Result:
    query: str
    kind: str  # "word" (a word or a short phrase) or "sentence" (translated as a whole)
    entries: list[Entry]  # word results; empty for a sentence
    summary: Text  # one line: `• query — translation`
    note: str = ""  # a phrase looked up word by word: "One result per word · corrected a → b"
    translation: Translation | None = None  # a sentence
    warning: str = ""  # shown after the result: what was not looked up or not saved, and why


def open_dictionary() -> Dictionary:
    try:
        return Dictionary(paths.dictionary_db())
    except FileNotFoundError:
        print_text(
            "The dictionary has not been imported yet.\n"
            "Fetch the dump once with scripts/fetch_data.py (the CLI never downloads),\n"
            "then `wort import --file kaikki.org-dictionary-German.jsonl`."
        )
        sys.exit(1)


def resolve(dictionary: Dictionary, query: str) -> tuple[list[Entry], str, str]:
    """Look a word or short phrase up without saving it: (entries, short translation, note).

    A phrase that is not in the dictionary as a whole is looked up word by word (best entry per word);
    `note` then says so and lists typo corrections. It is empty for an ordinary lookup.
    """
    german, english = dictionary.lookup(query)
    if not (german or english) and " " in query:
        entries, fixes = dictionary.lookup_words(query, MAX_PHRASE_WORDS)
        if entries:
            note = "One result per word" + "".join(f" · corrected {a} → {b}" for a, b in fixes)
            return entries, " / ".join(e.glosses[0] for e in entries if e.glosses), note
    return german + english, _translation(german, english), ""


def word_meaning(dictionary: Dictionary, text: str) -> tuple[str, str]:
    """A history row's translation and color: nouns take their article's color (as the main line of a card does), nothing
    else is colored. Only an entry of the whole text counts (not the first word of a phrase)."""
    german, english = dictionary.lookup(text)
    if german or english:
        return _translation(german, english), noun_color(german[0]) if german else ""
    return resolve(dictionary, text)[1], ""


def is_sentence(dictionary: Dictionary, query: str) -> bool:
    """Two or more words that are not in the dictionary as a whole, with at least one known word: they are translated
    as a whole, the way a sentence is (`wie so`), instead of word by word.

    (Without a known word it is more likely a typo or gibberish than something to translate.)
    """
    words = [w for w in (w.strip(PUNCTUATION) for w in query.split()) if w]
    if len(words) < MIN_SENTENCE_WORDS or any(dictionary.lookup(query)):
        return False
    return any(any(dictionary.lookup(w, limit=1)) for w in words)


def find(dictionary: Dictionary, history: HistoryStore, query: str, working: Working | None = None) -> Result:
    """Look `query` up and save it in the history as typed (a word, or a sentence that is translated).

    `working(message)` is shown while the translation runs (the first use loads the model; it can take seconds).
    """
    query = sanitize.text(query, 10_000)
    if len(query) > sentence.MAX_CHARS:
        shown = Text(f"• {query[:40]}… — too long")
        return Result(query, "word", [], shown, warning=f"Too long: at most {sentence.MAX_CHARS} characters. Nothing was looked up or saved.")
    translation = None
    note = ""
    if is_sentence(dictionary, query):
        kind, entries, found = "sentence", [], True
        with working("Translating…") if working else contextlib.nullcontext():
            translation = sentence.run(dictionary, query)
        meaning = translation.text or "no translation"
    else:
        kind = "word"
        entries, meaning, note = resolve(dictionary, query)
        found = bool(entries)
    warning = ""
    try:
        history.add(kind, query, found)
    except Invalid as exc:
        warning = f"Not saved to history: {exc}."
    except OSError as exc:  # the history files cannot be written (read-only, full disk): the lookup still works
        warning = f"Not saved to history: {exc.strerror or exc}."
    return Result(query, kind, entries, summary_line(query, meaning), note, translation, warning)


def summary_line(text: str, meaning: str) -> Text:
    """`• text — meaning`: the text in the normal foreground, the meaning in muted grey (what a result collapses into)."""
    line = Text("• ")
    line.append(text)
    line.append(f" — {meaning}", style=MUTED)
    return line


def _translation(german: list[Entry], english: list[Entry]) -> str:
    if not (german or english):
        return "nothing found"
    if german:  # a German word: show its English meaning(s), ignore weaker English-side matches
        parts = ["; ".join(e.glosses[:2]) for e in german]
    else:  # an English word: show the German equivalents
        parts = [f"{GENDER_ARTICLE[e.gender]} {e.lemma}" if e.pos == "noun" and e.gender in GENDER_ARTICLE else e.lemma for e in english]
    unique = list(dict.fromkeys(p for p in parts if p))
    return " / ".join(unique[:3])


def show(entries: list[Entry]) -> int:
    """Print the cards (or a not-found line); returns how many terminal lines that took."""
    from wort.render.card import render_card

    with console.capture() as captured:
        if not entries:
            print_text("Nothing found.")
        for entry in entries:
            console.print(render_card(entry))
    return _write(captured.get())


def show_translation(result: Result) -> int:
    """Print the sentence and its translation as one two-line block; returns how many terminal lines that took."""
    from wort.render.card import render_translation

    with console.capture() as captured:
        console.print(render_translation(result.query, result.translation))
    return _write(captured.get())


def show_result(result: Result) -> int:
    """Print what `find` found: the translation block of a sentence, the cards of a word."""
    return show_translation(result) if result.kind == "sentence" else show(result.entries)


def _write(out: str) -> int:
    sys.stdout.write(out)
    sys.stdout.flush()
    return out.count("\n")


def did_you_mean(similar: list[Entry]) -> str:
    return "Did you mean: " + ", ".join(dict.fromkeys(e.lemma for e in similar)) + "?"
