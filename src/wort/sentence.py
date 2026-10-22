"""Whole-sentence translation, German ↔ English, fully offline (Argos Translate).

Optional: `uv sync --group mt`, fetch the model files once with `scripts/fetch_data.py` (a separate
script, not part of the CLI), then `wort install-translation FILE...`. The CLI never downloads anything.
The direction follows the words: mostly German words → de→en, otherwise en→de.
"""

from __future__ import annotations

from pathlib import Path

from wort.dictionary.lookup import PUNCTUATION, Dictionary

DIRECTIONS = (("de", "en"), ("en", "de"))
MAX_CHARS = 500  # user text is data: length-capped before it reaches the model

MISSING_PACKAGE = "Sentence translation needs the 'mt' group: uv sync --group mt"
MISSING_MODEL = "Sentence translation model {src}→{dst} not installed: fetch the model files with scripts/fetch_data.py, then run `wort install-translation FILE...`"


class TranslationUnavailable(RuntimeError):
    """The package or the model is missing; the message says which and how to fix it."""


def _argos():
    try:
        from argostranslate import package, translate
    except ImportError as exc:
        raise TranslationUnavailable(MISSING_PACKAGE) from exc
    return package, translate


def detect(dictionary: Dictionary, text: str) -> tuple[str, str]:
    """(source, target) language codes: English only when more words are English-only than German."""
    german = english = 0
    for word in (w.strip(PUNCTUATION) for w in text.split()):
        if not word:
            continue
        de, en = dictionary.lookup(word, limit=1)
        if de:
            german += 1
        elif en:
            english += 1
    return ("en", "de") if english > german else ("de", "en")


def translate(text: str, source: str = "de", target: str = "en") -> str:
    """Translate one sentence. Raises TranslationUnavailable or ValueError (too long); never guesses."""
    text = " ".join(text.split())
    if len(text) > MAX_CHARS:
        raise ValueError(f"Sentence too long for translation ({len(text)} > {MAX_CHARS} characters).")
    _, argos = _argos()
    languages = {lang.code: lang for lang in argos.get_installed_languages()}
    if source not in languages or target not in languages or not languages[source].get_translation(languages[target]):
        raise TranslationUnavailable(MISSING_MODEL.format(src=source, dst=target))
    result = argos.translate(text, source, target).strip()
    if not result:
        raise RuntimeError("Translation model returned nothing.")
    return result


def describe(dictionary: Dictionary, text: str) -> str:
    """One line for the UI: the translation, or why there is none (fail loud, never silent)."""
    source, target = detect(dictionary, text)
    try:
        return f"Translation ({source}→{target}): {translate(text, source, target)}"
    except (TranslationUnavailable, ValueError, RuntimeError) as exc:
        return f"No sentence translation: {exc}"


def install(files: list[Path]) -> int:
    """Install Argos model files (.argosmodel) that were fetched separately. Returns how many were installed."""
    package, _ = _argos()
    if not files:
        raise RuntimeError("Give the .argosmodel files, e.g. the de→en and en→de models from scripts/fetch_data.py.")
    for path in files:
        if not path.is_file() or path.suffix != ".argosmodel":
            raise RuntimeError(f"Not an .argosmodel file: {path}")
        package.install_from_path(path)
    return len(files)
