"""Texte: reading texts, UI stage with mock texts.

Design: the "Texte 1-5" boards of the wort/design canvas (2026-10-30). The saved texts, the recognition result and the
notes below are fixed examples: no text is read from or written to the database and no photo is read (the upload form
sends a title only, the dropzone's file input has no name). The real pipeline (local OCR, stored texts; PLAN Step 6,
post-MVP) replaces this data layer; the routes and templates stay.

What is real is the way into the word list (maintainer decisions 2026-10-30): every word of a text is a word the reader
can click, which adds its dictionary lemma; selecting text opens a menu with its translation and "Add to word list",
which adds a single word as a word and anything longer as a phrase, both into the user's Wörter with added_from
"text". The server decides what is added: a clicked word is found by its place in the text, a selection must occur in
the open text, and no lemma ever comes from the browser. The translation of a phrase is local (Argos, app/mt.py, only
where the optional "mt" install and its models exist; German to English only so far); a single word is glossed from
the dictionary.

The texts themselves are German in both interface languages; the dates and the labels around them follow the
interface language (app/i18n.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app import i18n, mt
from app.db import PHRASE, User
from app.i18n import t
from app.words import GLOSS_WORD, POS_LABEL, short_gloss, uk_text, v_label
from wort import sanitize
from wort.dictionary.lookup import Dictionary, Entry
from wort.dictionary.ukrainian import Ukrainian

MAX_TITLE = 80
MAX_TEXT = 20_000  # characters of a pasted or recognized text we are willing to look at
MAX_PHRASE = 300  # characters of a phrase or sentence added to the word list
PUNCTUATION = ".,;:!?\"'()[]{}„“”‚‘’»«–—…"  # around a single selected word
REF = re.compile(r"^(\d{1,3})-(\d{1,3})$")  # "paragraph-segment": where a word stands in a text


@dataclass(frozen=True)
class Card:
    """What a word's hover card says: lemma and part of speech, translation, English, a grammar note."""

    kicker: str
    title: str
    gloss: str = ""
    note: str = ""


@dataclass(frozen=True)
class Word:
    """A word of the text the reader can look up. state: none | noted (in the notes); "known" (in the word list) is
    never stored here, it comes from the user's word list. lemma and pos: the dictionary entry a click adds."""

    text: str
    state: str = "none"
    card: Card | None = None
    note: int | None = None  # index into the text's notes
    lemma: str = ""
    pos: str = ""


@dataclass(frozen=True)
class Note:
    article: str  # der | die | das | "" (not a noun)
    word: str  # as it stands in the text
    translation: str
    form: str
    lemma: str  # the dictionary entry "Add to list" adds
    pos: str

    @property
    def label(self) -> str:
        return f"{self.article} {self.word}" if self.article else self.word


@dataclass(frozen=True)
class SavedText:
    id: int
    title: str
    day: date
    recognized: int  # percent
    paragraphs: list[list[str | Word]]
    notes: list[Note] = field(default_factory=list)

    @property
    def plain(self) -> str:
        return "\n\n".join("".join(s if isinstance(s, str) else s.text for s in p) for p in self.paragraphs)


_EINREICHEN = Card("einreichen · Verb, trennbar", "подавати (документи)", "to submit, hand in",
                   "hier: Imperativ, Sie-Form — „reichen Sie … ein“")


def _w(text: str, lemma: str, pos: str, card: Card, state: str = "none", note: int | None = None) -> Word:
    return Word(text, state, card, note, lemma, pos)


TEXTS: list[SavedText] = [
    SavedText(
        1, "Brief vom Jobcenter", date(2026, 10, 21), 98,
        [
            ["Sehr geehrte Damen und Herren,"],
            ["bitte ", _w("reichen", "einreichen", "verb", _EINREICHEN), " Sie die fehlenden ",
             _w("Unterlagen", "Unterlage", "noun", Card("die Unterlagen · Nomen", "документи", "documents", "nur Plural · hier Akkusativ"), "noted", 0),
             " bis zum 15. November ", _w("ein", "einreichen", "verb", _EINREICHEN),
             ". Dazu gehören eine aktuelle ",
             _w("Mietbescheinigung", "Mietbescheinigung", "noun",
                Card("die Mietbescheinigung · Nomen", "довідка про оренду", "rent certificate", "Miete + Bescheinigung"), "noted", 1),
             " und ein ",
             _w("Nachweis", "Nachweis", "noun",
                Card("der Nachweis · Nomen", "підтвердження", "proof", "Plural: die Nachweise · hier Akkusativ"), "noted", 2),
             " über Ihre Weiterbildung."],
            ["Ohne diese Unterlagen können wir Ihren ",
             _w("Antrag", "Antrag", "noun", Card("der Antrag · Nomen", "заява", "application", "hier Akkusativ Singular")),
             " leider nicht ",
             _w("bearbeiten", "bearbeiten", "verb",
                Card("bearbeiten · Verb", "опрацювати, розглянути", "to process, to handle", "bearbeitete · hat bearbeitet"), "noted", 3),
             ". Bei Fragen erreichen Sie uns telefonisch oder über das Online-Portal."],
            ["Mit freundlichen Grüßen"],
        ],
        [
            Note("die", "Unterlagen", "документи · documents", "nur Plural · hier Akk. Pl.", "Unterlage", "noun"),
            Note("die", "Mietbescheinigung", "довідка про оренду", "Miete + Bescheinigung", "Mietbescheinigung", "noun"),
            Note("der", "Nachweis", "підтвердження · proof", "Pl. die Nachweise · hier Akk.", "Nachweis", "noun"),
            Note("", "bearbeiten", "опрацювати, розглянути", "bearbeitete · hat bearbeitet", "bearbeiten", "verb"),
        ],
    ),
    SavedText(
        2, "Mietvertrag, § 3", date(2026, 10, 18), 95,
        [
            ["§ 3 Miete"],
            ["Der ", _w("Mieter", "Mieter", "noun", Card("der Mieter · Nomen", "орендар", "tenant", "hier Nominativ Singular"), "noted", 0),
             " verpflichtet sich, die ", _w("Miete", "Miete", "noun", Card("die Miete · Nomen", "оренда, орендна плата", "rent", "")),
             " monatlich im Voraus, spätestens bis zum dritten ",
             _w("Werktag", "Werktag", "noun", Card("der Werktag · Nomen", "робочий день", "working day", "Werk + Tag"), "noted", 1),
             ", zu ", _w("entrichten", "entrichten", "verb", Card("entrichten · Verb", "сплачувати", "to pay", "formell; Zu-Infinitiv"), "noted", 2),
             "."],
        ],
        [
            Note("der", "Mieter", "орендар · tenant", "hier Nom. Sg.", "Mieter", "noun"),
            Note("der", "Werktag", "робочий день · working day", "Werk + Tag", "Werktag", "noun"),
            Note("", "entrichten", "сплачувати · to pay", "zu entrichten", "entrichten", "verb"),
        ],
    ),
    SavedText(
        3, "Kursplan Umschulung", date(2026, 10, 12), 91,
        [
            ["Die ", _w("Umschulung", "Umschulung", "noun", Card("die Umschulung · Nomen", "перекваліфікація", "retraining", ""), "noted", 0),
             " beginnt am 4. November und dauert zwölf Monate."],
            ["Die ", _w("Teilnahme", "Teilnahme", "noun", Card("die Teilnahme · Nomen", "участь", "participation", ""), "noted", 1),
             " ist verpflichtend; ",
             _w("Fehlzeiten", "Fehlzeit", "noun", Card("die Fehlzeit · Nomen", "пропуски", "absences", "meist Plural"), "noted", 2),
             " müssen Sie schriftlich entschuldigen."],
        ],
        [
            Note("die", "Umschulung", "перекваліфікація · retraining", "hier Nom. Sg.", "Umschulung", "noun"),
            Note("die", "Teilnahme", "участь · participation", "hier Nom. Sg.", "Teilnahme", "noun"),
            Note("die", "Fehlzeiten", "пропуски · absences", "meist Plural", "Fehlzeit", "noun"),
        ],
    ),
    SavedText(
        4, "Zeitungsartikel", date(2026, 10, 9), 87,
        [
            ["Die Stadt will im kommenden Jahr mehr Geld in den ",
             _w("Nahverkehr", "Nahverkehr", "noun", Card("der Nahverkehr · Nomen", "місцеве сполучення", "local transport", ""), "noted", 0),
             " ", _w("investieren", "investieren", "verb", Card("investieren · Verb", "інвестувати", "to invest", "investierte · hat investiert"), "noted", 1),
             ". ", _w("Kritiker", "Kritiker", "noun", Card("der Kritiker · Nomen", "критик", "critic", "hier Nominativ Plural"), "noted", 2),
             " ", _w("bezweifeln", "bezweifeln", "verb", Card("bezweifeln · Verb", "сумніватися", "to doubt", "bezweifelte · hat bezweifelt"), "noted", 3),
             ", dass die Mittel ausreichen."],
        ],
        [
            Note("der", "Nahverkehr", "місцеве сполучення · local transport", "", "Nahverkehr", "noun"),
            Note("", "investieren", "інвестувати · to invest", "investierte · hat investiert", "investieren", "verb"),
            Note("der", "Kritiker", "критик · critic", "hier Nom. Pl.", "Kritiker", "noun"),
            Note("", "bezweifeln", "сумніватися · to doubt", "bezweifelte · hat bezweifelt", "bezweifeln", "verb"),
        ],
    ),
]

# What "Foto hochladen" would recognise: the text (with two slips the check step points at) and where the photo is unsure.
RECOGNIZED_TEXT = (
    "Sehr geehrte Damen und Herren,\n\n"
    "bitte reichen Sie die fehlenden Unterlaqen bis zum 15. November ein. Dazu gehören eine aktuelle Mietbescheinigung "
    "und ein Nachweis über Ihre Weiterbildung.\n\n"
    "Ohne diese Unterlagen können wir Ihren Antrag leider nicht bearbeiten. Bei Fragen erreichen Sie uns telefonisch "
    "oder über das Online-Portal.\n\n"
    "Mit freundlichen Grüßen"
)
RECOGNIZED_PERCENT = 98
DOUBTS = [
    {"found": "Unterlaqen", "proposal": "Unterlagen", "line": 4, "sure": 61, "state": "open"},
    {"found": "Mietbescheiniqung", "proposal": "Mietbescheinigung", "line": 6, "sure": None, "state": "accepted"},
]
# Percent of the photo (the placeholder page of dis-system's image-regions): where the recognition was unsure (line 4)
# and where a correction was accepted (line 6).
REGIONS = [
    {"x": 48, "y": 11.2, "w": 24, "h": 3.2, "kind": "uncertain", "label": "Unterlaqen"},
    {"x": 27, "y": 15.7, "w": 31, "h": 3.2, "kind": "accepted", "label": "Mietbescheinigung"},
]

_MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"],
}


def long_date(day: date) -> str:
    """'21. Oktober 2026' in German, 'October 21, 2026' in English."""
    lang = i18n.current()
    month = _MONTHS[lang][day.month - 1]
    return f"{day.day}. {month} {day.year}" if lang == "de" else f"{month} {day.day}, {day.year}"


def notes_label(n: int) -> str:
    return t("1 note") if n == 1 else t("{n} notes", n=n)


def side_items(current_id: int | None) -> list[dict]:
    """The saved texts for dis-system's sidebar-list: title, date and note count, the open one active."""
    return [{"name": x.title, "caption": f"{long_date(x.day)} · {notes_label(len(x.notes))}", "href": f"/texte/{x.id}",
             "active": x.id == current_id, "save": False} for x in TEXTS]


def expand(paragraphs: list[list[str | Word]]) -> list[list[str | Word]]:
    """The text as the reader sees it: every word of a plain string becomes a Word of its own (no lemma: it is resolved
    from the dictionary), the words the text's author marked up stay as they are. A "paragraph-segment" ref (the place
    a click names) counts in this expanded list."""
    out = []
    for paragraph in paragraphs:
        items: list[str | Word] = []
        for seg in paragraph:
            if isinstance(seg, Word):
                items.append(seg)
                continue
            at = 0
            for m in GLOSS_WORD.finditer(seg):
                if m.start() > at:
                    items.append(seg[at:m.start()])
                items.append(Word(m.group(0)))
                at = m.end()
            if at < len(seg):
                items.append(seg[at:])
        out.append(items)
    return out


class Reader:
    """What the dictionary and the user's word list say about the words of a text: one per request, with caches."""

    def __init__(self, dic: Dictionary | None, uk: Ukrainian | None, have: set[tuple[str, str]]):
        self.dic, self.uk, self.have = dic, uk, have
        self._entries: dict[tuple[str, str, str], Entry | None] = {}

    def entry(self, word: Word) -> Entry | None:
        """The dictionary entry of a word: the one its author named, else the best match for the word as written
        (an inflected form finds its lemma)."""
        if self.dic is None:
            return None
        key = (word.lemma, word.pos, "" if word.lemma else word.text.casefold())
        if key not in self._entries:
            if word.lemma:
                found = self.dic.find_lemma(word.lemma, word.pos or None)
                self._entries[key] = found if found and (not word.pos or found.pos == word.pos) else None
            else:
                self._entries[key] = (self.dic.lookup_german(word.text, limit=1) or [None])[0]
        return self._entries[key]

    def known(self, entry: Entry | None) -> bool:
        return entry is not None and (entry.lemma, entry.pos) in self.have

    def card(self, word: Word, entry: Entry | None) -> dict | None:
        """The hover card: the author's own, else the dictionary's lemma, part of speech and glosses; none without either."""
        if word.card:
            return {"kicker": word.card.kicker, "title": word.card.title, "gloss": word.card.gloss, "note": word.card.note}
        if entry is None:
            return None
        en = short_gloss(entry.glosses)
        uk = uk_text(self.uk, entry, entry.lemma, entry.pos)
        return {"kicker": f"{v_label(entry)} · {POS_LABEL.get(entry.pos, entry.pos)}", "title": uk or en or v_label(entry),
                "gloss": en if uk else "", "note": ""}


def reading(found: SavedText, reader: Reader) -> tuple[list[list[dict]], set[str]]:
    """The text for the template (each word with its ref, state and card) and the refs that are in the word list."""
    paragraphs, known = [], set()
    for pi, paragraph in enumerate(expand(found.paragraphs)):
        items = []
        for si, seg in enumerate(paragraph):
            if isinstance(seg, str):
                items.append({"text": seg})
                continue
            entry = reader.entry(seg)
            ref = f"{pi}-{si}"
            if reader.known(entry):
                known.add(ref)
            items.append({"word": True, "ref": ref, "text": seg.text, "card": reader.card(seg, entry),
                          "state": "known" if ref in known else seg.state})
        paragraphs.append(items)
    return paragraphs, known


def known_notes(found: SavedText, reader: Reader) -> set[int]:
    return {i for i, n in enumerate(found.notes) if reader.known(reader.entry(Word(n.word, lemma=n.lemma, pos=n.pos)))}


def register(app, ctx) -> None:
    current_user = ctx.current_user
    store = ctx.store

    def dictionary_or_none() -> Dictionary | None:
        try:
            return Dictionary(ctx.dict_path)
        except FileNotFoundError:
            return None

    def ukrainian_or_none() -> Ukrainian | None:
        try:
            return Ukrainian(ctx.uk_path, ctx.uk_en_path)
        except FileNotFoundError:
            return None

    def reader_for(user: User) -> Reader:
        return Reader(dictionary_or_none(), ukrainian_or_none(), {(w.lemma, w.pos) for w in store.words(user.id)})

    def find(text_id: int) -> SavedText:
        found = next((x for x in TEXTS if x.id == text_id), None)
        if found is None:
            raise HTTPException(404, "no such text")
        return found

    def page(request: Request, user: User, current: SavedText | None = None, popup: str = "", status: int = 200,
             **extra) -> HTMLResponse:
        paragraphs, notes = [], set()
        if current:
            reader = reader_for(user)
            paragraphs, _ = reading(current, reader)
            notes = known_notes(current, reader)
        return ctx.render(request, "texts.html", status=status, user=user, page="texts", current=current, popup=popup,
                          texts=TEXTS, side_items=side_items(current.id if current else None), long_date=long_date,
                          notes_label=notes_label, paragraphs=paragraphs, known_notes=notes, **extra)

    @app.get("/texte", response_class=HTMLResponse)
    def texts(request: Request, user: User = Depends(current_user)):
        return page(request, user)

    @app.get("/texte/neu", response_class=HTMLResponse)
    def upload(request: Request, user: User = Depends(current_user)):
        return page(request, user, popup="upload")

    @app.post("/texte/neu", response_class=HTMLResponse)
    def recognise(request: Request, csrf: str = Form(...), title: str = Form(""), user: User = Depends(current_user)):
        """Mock: the check step with the canned recognition result, whatever photo was chosen (none is sent)."""
        ctx.verify_csrf(request, csrf)
        title = sanitize.text(title, MAX_TITLE) or t("Untitled")
        words = len(RECOGNIZED_TEXT.split())
        return page(request, user, popup="check", new_title=title, recognized_text=RECOGNIZED_TEXT, doubts=DOUBTS,
                    regions=REGIONS, recognized=RECOGNIZED_PERCENT, word_count=words)

    @app.post("/texte/neu/speichern")
    def save(request: Request, csrf: str = Form(...), text: str = Form(""), user: User = Depends(current_user)):
        """Mock: the text is looked at (size, characters) and dropped; nothing is stored."""
        ctx.verify_csrf(request, csrf)
        if len(sanitize.text(text, MAX_TEXT + 1, multiline=True)) > MAX_TEXT:
            raise HTTPException(400, f"a text is limited to {MAX_TEXT} characters")
        return ctx.redirect(f"/texte/{TEXTS[0].id}", t("Demo data: nothing was saved."))

    @app.get("/texte/{text_id:int}", response_class=HTMLResponse)
    def show(request: Request, text_id: int, user: User = Depends(current_user)):
        return page(request, user, current=find(text_id))

    @app.get("/texte/{text_id:int}/bearbeiten", response_class=HTMLResponse)
    def edit(request: Request, text_id: int, user: User = Depends(current_user)):
        """Mock: "Text bearbeiten" opens the check step over the open text, with that text and no photo marks."""
        found = find(text_id)
        return page(request, user, current=found, popup="check", new_title=found.title, recognized_text=found.plain,
                    doubts=[], regions=[], recognized=found.recognized, word_count=len(found.plain.split()), editing=True)

    # --- into the word list ---------------------------------------------------------------------------------------

    def entries_of(found: SavedText, reader: Reader, ref: str, note: str) -> list[Entry | None]:
        """The dictionary entries a click means. Found by place in the text, never by browser text."""
        if ref:
            m = REF.match(ref)
            paragraphs = expand(found.paragraphs)
            try:
                seg = paragraphs[int(m.group(1))][int(m.group(2))] if m else None
            except IndexError:
                seg = None
            if not isinstance(seg, Word):
                raise HTTPException(400, "no such word")
            return [reader.entry(seg)]
        notes = [Word(n.word, lemma=n.lemma, pos=n.pos) for n in found.notes]
        if note == "all":
            return [reader.entry(w) for w in notes]
        if note.isdigit() and int(note) < len(notes):
            return [reader.entry(notes[int(note)])]
        raise HTTPException(400, "no such word")

    def marks(found: SavedText, user: User) -> dict:
        """What is in the user's word list now, for the page to mark: words as "paragraph-segment", notes by index."""
        reader = reader_for(user)
        _, refs = reading(found, reader)
        return {"refs": sorted(refs), "notes": sorted(known_notes(found, reader))}

    def add_entries(user: User, entries: list[Entry | None]) -> tuple[str, str]:
        """Add dictionary entries to the word list as "from a text"; (status, message) for the toast."""
        added = existing = missing = 0
        label = ""
        seen: set[int] = set()  # two words of one text can be the same entry
        for entry in entries:
            if entry is None:
                missing += 1
            elif entry.id in seen:
                continue
            elif store.add_word(user.id, entry.lemma, entry.pos, added_from="text"):
                seen.add(entry.id)
                added, label = added + 1, v_label(entry)
            else:
                seen.add(entry.id)
                existing, label = existing + 1, v_label(entry)
        status = "added" if added else "exists" if existing else "missing"
        if len(entries) == 1:
            return status, {"added": t("“{word}” is now in your words.", word=label),
                            "exists": t("“{word}” is already in your words.", word=label),
                            "missing": t("This word is not in the dictionary.")}[status]
        return status, " · ".join(x for x in (t("{n} added to your words.", n=added) if added else "",
                                              t("{n} already in your words.", n=existing) if existing else "",
                                              t("{n} not in the dictionary.", n=missing) if missing else "") if x)

    @app.post("/texte/{text_id:int}/wort")
    def add_word(request: Request, text_id: int, csrf: str = Form(...), ref: str = Form(""), note: str = Form(""),
                 user: User = Depends(current_user)):
        """A click on any word of the text, or "Add to list" / "All to the word list" on the notes: into the word list."""
        ctx.verify_csrf(request, csrf)
        found = find(text_id)
        reader = reader_for(user)
        if reader.dic is None:
            return JSONResponse({"status": "missing", "message": t("No dictionary found: import the dictionary first."),
                                 "refs": [], "notes": []})
        status, message = add_entries(user, entries_of(found, reader, ref, note))
        return JSONResponse({"status": status, "message": message, **marks(found, user)})

    def selection_of(found: SavedText, text: str) -> str:
        """A selection as the text has it (its own capitals, spaces and line breaks made one space): what is stored."""
        phrase = " ".join(sanitize.text(text, MAX_PHRASE + 1).split())
        if len(phrase) > MAX_PHRASE:
            raise HTTPException(400, t("A phrase can have at most {n} characters.", n=MAX_PHRASE))
        hit = re.search(re.escape(phrase), " ".join(found.plain.split()), re.IGNORECASE) if phrase else None
        if hit is None:
            raise HTTPException(400, t("This is not from this text."))
        return hit.group(0)

    @app.post("/texte/{text_id:int}/auswahl")
    def add_selection(request: Request, text_id: int, csrf: str = Form(...), text: str = Form(""),
                      user: User = Depends(current_user)):
        """"Add to word list" in the selection menu: one word is added as a word, anything longer as a phrase."""
        ctx.verify_csrf(request, csrf)
        found = find(text_id)
        phrase = selection_of(found, text)
        if len(phrase.split()) == 1:
            reader = reader_for(user)
            bare = phrase.strip(PUNCTUATION)
            entry = reader.entry(Word(bare)) if bare else None
            status, message = add_entries(user, [entry])
            return JSONResponse({"status": status, "message": message, **marks(found, user)})
        shown = phrase if len(phrase) <= 60 else phrase[:57] + "…"
        if store.add_word(user.id, phrase, PHRASE, added_from="text"):
            return JSONResponse({"status": "added", "message": t("“{phrase}” is now in your words as a phrase.", phrase=shown),
                                 **marks(found, user)})
        return JSONResponse({"status": "exists", "message": t("“{word}” is already in your words.", word=shown),
                             **marks(found, user)})

    @app.post("/texte/{text_id:int}/uebersetzung")
    def translate(request: Request, text_id: int, csrf: str = Form(...), text: str = Form(""),
                  user: User = Depends(current_user)):
        """The selection menu's translation: a word from the dictionary, a phrase from the local translator (Argos,
        app/mt.py; none installed here means no lines, never a made-up one)."""
        ctx.verify_csrf(request, csrf)
        phrase = selection_of(find(text_id), text)
        if len(phrase.split()) == 1:
            reader = reader_for(user)
            entry = reader.entry(Word(phrase.strip(PUNCTUATION))) if phrase.strip(PUNCTUATION) else None
            card = reader.card(Word(phrase), entry)
            if entry is None or card is None:
                return JSONResponse({"kind": "word", "lines": [], "message": t("This word is not in the dictionary.")})
            return JSONResponse({"kind": "word", "lines": [card["kicker"].split(" · ")[0],
                                                            " · ".join(x for x in (card["title"], card["gloss"]) if x)],
                                 "message": ""})
        lines = [line for line in (mt.translate(phrase, "uk"), mt.translate(phrase, "en")) if line]
        return JSONResponse({"kind": "phrase", "lines": lines, "message": t("No translation available here.")})
