"""Small text helpers shared by lookup and answer checking."""

import unicodedata

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalize(text: str) -> str:
    """Lowercase, fold umlauts to ae/oe/ue/ss and collapse whitespace."""
    text = unicodedata.normalize("NFC", text).strip().lower().translate(_UMLAUTS)
    return " ".join(text.split())


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]
