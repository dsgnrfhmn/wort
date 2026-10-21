"""Whole-sentence translation, German ↔ English, fully offline (Argos Translate).

Optional: `uv sync --group mt`, then `wort install-translation` once (downloads the models, ~100 MB
each; the only network use, run by hand). Translating never touches the network.
The direction follows the words: mostly German words → de→en, otherwise en→de.
"""

from __future__ import annotations

from wort.dictionary.lookup import PUNCTUATION, Dictionary

DIRECTIONS = (("de", "en"), ("en", "de"))
MAX_CHARS = 500  # user text is data: length-capped before it reaches the model

MISSING_PACKAGE = "Sentence translation needs the 'mt' group: uv sync --group mt"
MISSING_MODEL = "Sentence translation model {src}→{dst} not installed: run `wort install-translation`"


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


def install() -> None:
    """Download and install the de→en and en→de models (needs network, run once by the user)."""
    package, _ = _argos()
    package.update_package_index()
    available = package.get_available_packages()
    for source, target in DIRECTIONS:
        wanted = next((p for p in available if p.from_code == source and p.to_code == target), None)
        if wanted is None:
            raise RuntimeError(f"No {source}→{target} model in the Argos package index.")
        package.install_from_path(wanted.download())
