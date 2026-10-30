"""Text recognition for Texte: Tesseract (German) on a photo that app/uploads.py has already decoded.

The photo goes to the `tesseract` program through its stdin and the result comes back on stdout (TSV: one row per word
with its position and confidence), so no image file is ever written; there is no network involved either. The server
runs one recognition at a time (a Pi shared with other services) and every run has a time limit that is shorter than
the web server's. The output is user-sourced text like any other (CLAUDE.md): cleaned and length-capped here, escaped
by the template.

Prepared on purpose only a little: grey, stretched contrast, scaled down to MAX_SIDE. Threshold and deskew wait for the
photo measurements of DECISIONS D3, they are not guessed.

Optional like the translator: without the program, its German data or Pillow, `available()` is false and the page says
so. The answer is cached for the process; restart after installing.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from functools import lru_cache

from app import uploads
from app.i18n import t
from wort import sanitize

LANG = "deu"
MAX_SIDE = 3000  # pixels of the longer side given to Tesseract; more only costs time
TIMEOUT = 45  # seconds; nginx waits 60
WAIT = 15  # seconds a second upload waits for the first one's recognition before it is told to try again
DOUBT_BELOW = 60  # a word with a lower confidence (percent) is an "uncertain spot"
MAX_DOUBTS = 20
MAX_TEXT = 20_000  # the same cap the text field and the save step use (app/texts.py)

log = logging.getLogger("wort.ocr")
_one_at_a_time = threading.Lock()
_HYPHENS = ("-", "­", "‐")
_KEEP_HYPHEN = {"und", "oder", "bis", "sowie", "bzw"}  # "Ein- und Ausgang": the hyphen belongs to the word before it


class OcrFailed(Exception):
    """Recognition did not work. `message` is for the user (in the interface language), `status` the HTTP status."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message, self.status = message, status


@dataclass(frozen=True)
class Doubt:
    """A word the recognition was unsure of: what it read, which line of the photo, how sure, where (percent of the photo)."""

    found: str
    line: int
    sure: int
    x: float
    y: float
    w: float
    h: float

    @property
    def region(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "kind": "uncertain", "label": self.found}


@dataclass(frozen=True)
class Recognition:
    text: str
    percent: int  # mean confidence of the words
    doubts: tuple[Doubt, ...] = ()


def _env() -> dict[str, str]:
    """What the program sees: the search path and where its data is, nothing else. One thread: it is faster per photo
    in a container with few cores and it keeps the host's other services responsive."""
    env = {"PATH": os.environ.get("PATH", ""), "OMP_THREAD_LIMIT": "1"}
    if os.environ.get("TESSDATA_PREFIX"):
        env["TESSDATA_PREFIX"] = os.environ["TESSDATA_PREFIX"]
    return env


@lru_cache(maxsize=1)
def _tesseract() -> str | None:
    exe = shutil.which("tesseract")
    if not exe:
        return None
    try:
        listed = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10, env=_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if LANG in listed.split() else None


def available() -> bool:
    """Pillow, the program and its German data are all there."""
    return uploads.available() and _tesseract() is not None


def _prepare(image) -> tuple[bytes, tuple[int, int]]:
    """The photo as the PNG Tesseract reads: grey, contrast stretched, at most MAX_SIDE on the longer side."""
    from PIL import Image, ImageOps

    grey = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    if max(grey.size) > MAX_SIDE:
        grey.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    grey.save(buffer, "PNG")
    return buffer.getvalue(), grey.size


def recognize(image) -> Recognition:
    """Read the German text of a decoded photo. Raises OcrFailed; never returns a partial result."""
    exe = _tesseract()
    if exe is None or not uploads.available():
        raise OcrFailed(t("Text recognition is not set up on this server."), 503)
    png, size = _prepare(image)
    if not _one_at_a_time.acquire(timeout=WAIT):
        raise OcrFailed(t("Text recognition is busy with another photo. Try again in a moment."), 503)
    try:
        done = subprocess.run([exe, "stdin", "stdout", "-l", LANG, "--psm", "3", "tsv"], input=png, capture_output=True,
                              timeout=TIMEOUT, env=_env())
    except subprocess.TimeoutExpired:
        raise OcrFailed(t("Text recognition took too long. Try a smaller or sharper photo."), 504) from None
    except OSError:
        raise OcrFailed(t("Text recognition failed.")) from None
    finally:
        _one_at_a_time.release()
    if done.returncode != 0:
        log.warning("tesseract exited with %s", done.returncode)
        raise OcrFailed(t("Text recognition failed."))
    return parse_tsv(done.stdout.decode("utf-8", "replace"), *size)


def join_lines(lines: list[str]) -> str:
    """The lines of one paragraph as running text: a word broken at the end of a line is put together again
    ("Verwal-" + "tung"), unless the next line goes on with "und", "oder" ... ("Ein- und Ausgang")."""
    out = ""
    for line in lines:
        if not out:
            out = line
            continue
        following = line.split(" ", 1)[0]
        if (out.endswith(_HYPHENS) and len(out) > 1 and out[-2].isalpha() and following[:1].islower()
                and following.rstrip(",.;:") not in _KEEP_HYPHEN):
            out = out[:-1] + line
        else:
            out += " " + line
    return out


def parse_tsv(tsv: str, width: int, height: int) -> Recognition:
    """Tesseract's TSV for a width x height photo as text (paragraphs separated by a blank line), its mean confidence and
    the words it was unsure of. Rows of other levels, without text or without a confidence are skipped."""
    paragraphs: dict[tuple[int, int], dict[int, list[str]]] = {}
    numbers: dict[tuple[int, int, int], int] = {}  # block, paragraph, line in reading order -> the line's number on the photo
    words: list[tuple[str, float, int, int, int, int, int]] = []  # text, confidence, line, left, top, width, height
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t", 11)
        if len(cols) < 12 or cols[0] != "5":
            continue
        try:
            block, par, line = int(cols[2]), int(cols[3]), int(cols[4])
            left, top, w, h = (int(c) for c in cols[6:10])
            sure = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if not word or sure < 0:
            continue
        number = numbers.setdefault((block, par, line), len(numbers) + 1)
        paragraphs.setdefault((block, par), {}).setdefault(line, []).append(word)
        words.append((word, sure, number, left, top, w, h))
    if not words:
        return Recognition("", 0)
    text = sanitize.text("\n\n".join(join_lines([" ".join(ws) for ws in lines.values()]) for lines in paragraphs.values()),
                         MAX_TEXT, multiline=True)

    def percent(value: int, whole: int) -> float:
        return round(min(100.0, max(0.0, 100.0 * value / whole)), 1)

    unsure = [(i, w) for i, w in enumerate(words) if w[1] < DOUBT_BELOW and sum(ch.isalnum() for ch in w[0]) >= 2]
    worst = sorted(sorted(unsure, key=lambda iw: iw[1][1])[:MAX_DOUBTS])  # the least sure, back in reading order
    doubts = tuple(Doubt(sanitize.text(w[0], 60), w[2], round(w[1]), percent(w[3], width), percent(w[4], height),
                         percent(w[5], width), percent(w[6], height)) for _, w in worst)
    return Recognition(text, round(sum(w[1] for w in words) / len(words)), doubts)
