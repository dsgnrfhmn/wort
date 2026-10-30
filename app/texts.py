"""Texte: the user's saved texts, reading them, and the way from a photo to a text.

Design: the "Texte 1-5" boards of the wort/design canvas (2026-10-30). The texts are the user's own (web.db: `texts`,
`text_words`; the photo is never kept, only the text the user saves).

From a photo to a text: "Recognize text" takes the photo (app/uploads.py: checked, held in memory only), reads it locally
(app/ocr.py, Tesseract), counts it against the user's daily cap, and opens the check step with the recognised text, the
places the recognition was unsure of, and a translation preview that app.js asks for paragraph by paragraph
(`/texte/neu/uebersetzung`, app/mt.py, Argos: where the optional "mt" install and its models exist; none means no lines,
never a made-up one). "Save text" stores the text as it stands in the field; "Edit text" opens the same step over a saved text;
"Delete text" (after a confirmation) removes the text and its notes, the words it added stay in the word list.

Reading: every word of a text is a word the reader can click, which adds its dictionary lemma; selecting text opens a menu
with its translation and "Add to word list", which adds a single word as a word and anything longer as a phrase, both into
the user's Wörter with added_from "text" (maintainer decisions 2026-10-30). The server decides what is added: a clicked word
is found by its place in the text, a selection must occur in the open text, and no lemma ever comes from the browser. The
translation of a phrase is local (Argos, app/mt.py; German to English only so far); a single word is glossed from the
dictionary. The words added from a text (a click, or a selection) are linked to it (`text_words`) and make its notes: the
right-hand list shows the ones that are still in the user's word list.

The texts themselves are German in both interface languages; the dates and the labels around them follow the
interface language (app/i18n.py).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from app import i18n, mt, ocr, uploads
from app.db import MAX_TEXTS, PHRASE, StoredText, User
from app.i18n import t
from app.words import GLOSS_WORD, POS_LABEL, short_gloss, uk_text, v_label
from wort import sanitize
from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry
from wort.dictionary.ukrainian import Ukrainian

MAX_TITLE = 80
MAX_TEXT = ocr.MAX_TEXT  # characters of a pasted or recognized text we are willing to look at
MAX_PARAGRAPH = 3_000  # characters of one paragraph sent to the translation preview (app.js asks paragraph by paragraph)
OCR_DAILY_CAP = 20  # photos per user and day (WORT_OCR_DAILY_CAP); a starting value, not measured
MAX_PHRASE = 300  # characters of a phrase or sentence added to the word list
PUNCTUATION = ".,;:!?\"'()[]{}„“”‚‘’»«–—…"  # around a single selected word
REF = re.compile(r"^(\d{1,3})-(\d{1,3})$")  # "paragraph-segment": where a word stands in a text


@dataclass(frozen=True)
class Word:
    """A word of the text the reader can look up. lemma and pos (both given or both empty): the dictionary entry it
    stands for, else the best match for the text as written."""

    text: str
    lemma: str = ""
    pos: str = ""


@dataclass(frozen=True)
class Note:
    article: str  # der | die | das | "" (not a noun)
    word: str
    translation: str
    form: str
    lemma: str
    pos: str

    @property
    def label(self) -> str:
        return f"{self.article} {self.word}" if self.article else self.word


@dataclass(frozen=True)
class SavedText:
    id: int
    title: str
    day: date
    recognized: int | None  # percent; none for a text that did not come from a photo
    body: str
    notes: list[Note] = field(default_factory=list)

    @property
    def paragraphs(self) -> list[str]:
        return paragraphs_of(self.body)

    @property
    def plain(self) -> str:
        return "\n\n".join(self.paragraphs)


def paragraphs_of(body: str) -> list[str]:
    """The paragraphs of a text (blank lines between them), each on one line."""
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]


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


def side_items(rows: list[StoredText], current_id: int | None) -> list[dict]:
    """The saved texts for dis-system's sidebar-list: title, date and note count, the open one active."""
    return [{"name": x.title, "caption": f"{long_date(x.created_at.date())} · {notes_label(x.notes)}", "href": f"/texte/{x.id}",
             "active": x.id == current_id, "save": False} for x in rows]


def expand(paragraphs: list[str]) -> list[list[str | Word]]:
    """The text as the reader sees it: every word of a paragraph becomes a Word of its own (no lemma: it is resolved from
    the dictionary), the text between them stays a string. A "paragraph-segment" ref (the place a click names) counts in
    this expanded list."""
    out = []
    for paragraph in paragraphs:
        items: list[str | Word] = []
        at = 0
        for m in GLOSS_WORD.finditer(paragraph):
            if m.start() > at:
                items.append(paragraph[at:m.start()])
            items.append(Word(m.group(0)))
            at = m.end()
        if at < len(paragraph):
            items.append(paragraph[at:])
        out.append(items)
    return out


class Reader:
    """What the dictionary and the user's word list say about the words of a text: one per request, with caches."""

    def __init__(self, dic: Dictionary | None, uk: Ukrainian | None, have: set[tuple[str, str]]):
        self.dic, self.uk, self.have = dic, uk, have
        self._entries: dict[tuple[str, str, str], Entry | None] = {}

    def entry(self, word: Word) -> Entry | None:
        """The dictionary entry of a word: the one named by its lemma, else the best match for the word as written
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

    def card(self, entry: Entry | None) -> dict | None:
        """The hover card: the dictionary's lemma, part of speech and glosses; none for a word it does not have."""
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
            items.append({"word": True, "ref": ref, "text": seg.text, "card": reader.card(entry),
                          "state": "known" if ref in known else "none"})
        paragraphs.append(items)
    return paragraphs, known


def notes_of(linked: list[tuple[str, str]], reader: Reader) -> list[Note]:
    """The notes of a text: the words added from it that are still in the word list, as the dictionary describes them
    (a phrase has only its text)."""
    notes = []
    for lemma, pos in linked:
        entry = None if pos == PHRASE else reader.entry(Word(lemma, lemma=lemma, pos=pos))
        if entry is None:
            notes.append(Note("", lemma, "", "", lemma, pos))
            continue
        card = reader.card(entry)
        article = g.ARTICLES[entry.gender]["nominative"] if entry.pos == "noun" and entry.gender in g.ARTICLES else ""
        notes.append(Note(article, entry.lemma, " · ".join(x for x in (card["title"], card["gloss"]) if x), "", entry.lemma,
                          entry.pos))
    return notes


def register(app, ctx) -> None:
    current_user = ctx.current_user
    store = ctx.store
    ocr_cap = int(os.environ.get("WORT_OCR_DAILY_CAP", OCR_DAILY_CAP))
    if ocr_cap < 1:
        raise ValueError("WORT_OCR_DAILY_CAP must be at least 1")

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

    def stored(user: User, text_id: int) -> StoredText:
        """The user's own text; another user's, or none, is a 404 (the same answer for both)."""
        row = store.text(user.id, text_id)
        if row is None:
            raise HTTPException(404, "no such text")
        return row

    def saved(row: StoredText, notes: list[Note] | None = None) -> SavedText:
        return SavedText(row.id, row.title, row.created_at.date(), row.recognized, row.body, notes or [])

    def find(user: User, text_id: int) -> SavedText:
        return saved(stored(user, text_id))

    def page(request: Request, user: User, row: StoredText | None = None, popup: str = "", status: int = 200,
             **extra) -> HTMLResponse:
        extra.setdefault("upload_title", "")  # what to put back in the upload step's title field after a refusal
        current, paragraphs = None, []
        if row:
            reader = reader_for(user)
            current = saved(row, notes_of(store.text_notes(user.id, row.id), reader))
            paragraphs, _ = reading(current, reader)
        return ctx.render(request, "texts.html", status=status, user=user, page="texts", open_text=current, popup=popup,  # not "current": text-button reads that and marks every button aria-current
                          side_items=side_items(store.texts(user.id), row.id if row else None), long_date=long_date,
                          notes_label=notes_label, paragraphs=paragraphs, ocr_ready=ocr.available(), **extra)

    @app.get("/texte", response_class=HTMLResponse)
    def texts(request: Request, user: User = Depends(current_user)):
        return page(request, user)

    @app.get("/texte/neu", response_class=HTMLResponse)
    def upload(request: Request, user: User = Depends(current_user)):
        return page(request, user, popup="upload")

    @app.post("/texte/neu", response_class=HTMLResponse)
    async def recognise(request: Request, csrf: str = Form(...), title: str = Form(""), photo: UploadFile | None = File(None),
                        user: User = Depends(current_user)):
        """"Recognize text": the photo is checked (app/uploads.py), read locally (app/ocr.py) and the check step opens with
        what was read. The photo is held in memory for this request only (the server may spool a large upload to an
        unnamed temporary file of /tmp, a tmpfs in the container, which is gone when the request ends). Every way it can
        fail goes back to the upload step with a message, never a stack trace, never a part of the file."""
        ctx.verify_csrf(request, csrf)
        typed = sanitize.text(title, MAX_TITLE)
        title = typed or t("Untitled")
        day = datetime.now().date().isoformat()

        def back(message: str, status: int) -> HTMLResponse:
            return page(request, user, popup="upload", status=status, message=message, message_status="error",
                        upload_title=typed)

        try:
            if not ocr.available():
                return back(t("Text recognition is not set up on this server."), 503)
            if store.ocr_uploads_today(user.id, day) >= ocr_cap:
                return back(t("The daily limit for photos is reached ({n}). Try again tomorrow.", n=ocr_cap), 429)
            if photo is None:
                return back(t("Choose a photo first."), 400)
            try:
                raw = await photo.read(uploads.MAX_BYTES + 1)
            finally:
                await photo.close()
            image = await run_in_threadpool(uploads.read_image, raw, photo.content_type or "")
            store.ocr_count_upload(user.id, day)  # from here on the recognition costs CPU: a failed one counts too
            found = await run_in_threadpool(ocr.recognize, image)
            shown = await run_in_threadpool(uploads.thumbnail, image)
        except (uploads.UploadRejected, ocr.OcrFailed) as e:
            return back(e.message, e.status)
        if not found.text:
            return back(t("No text was found in the photo. Try a sharper photo with the text filling more of it."), 422)
        return page(request, user, popup="check", new_title=title, recognized_text=found.text, doubts=list(found.doubts),
                    regions=[d.region for d in found.doubts], recognized=found.percent, word_count=len(found.text.split()),
                    photo=shown)

    @app.post("/texte/neu/uebersetzung")
    async def preview(request: Request, csrf: str = Form(...), text: str = Form(""), user: User = Depends(current_user)):
        """The check step's translation preview, one paragraph per request (app.js sends them one after the other, so the
        first lines appear at once and no request outlasts the web server's timeout). English, and Ukrainian where the
        local translator has it; no model means no lines and a message, never a made-up translation."""
        ctx.verify_csrf(request, csrf)
        paragraph = sanitize.text(text, MAX_PARAGRAPH + 1)
        if len(paragraph) > MAX_PARAGRAPH:
            raise HTTPException(400, t("A paragraph can have at most {n} characters.", n=MAX_PARAGRAPH))
        if not paragraph:
            return JSONResponse({"lines": [], "message": ""})
        try:
            english = await run_in_threadpool(mt.paragraph, paragraph, "en")
            ukrainian = await run_in_threadpool(mt.paragraph, paragraph, "uk") if english else ""  # uk goes through English
        except mt.Busy:
            return JSONResponse({"lines": [], "message": t("The translator is busy. Try again in a moment.")}, status_code=503)
        lines = [{"lang": lang, "text": done} for lang, done in (("en", english), ("uk", ukrainian)) if done]
        return JSONResponse({"lines": lines, "message": "" if lines else t("No translation available here.")})

    # --- saving ----------------------------------------------------------------------------------------------------

    def check_again(request: Request, user: User, message: str, status: int, title: str, text: str, percent: int | None,
                    row: StoredText | None = None) -> HTMLResponse:
        """A save that cannot be done goes back to the check step with the text the user wrote, and says why."""
        text = sanitize.text(text, MAX_TEXT, multiline=True)
        return page(request, user, row, popup="check", status=status, message=message, message_status="error",
                    new_title=title, recognized_text=text, doubts=[], regions=[], recognized=percent,
                    word_count=len(text.split()), editing=row is not None)

    def percent_of(value: str) -> int | None:
        return int(value) if value.isdigit() and int(value) <= 100 else None

    def body_of(text: str) -> str:
        """The text as saved: cleaned (multi-line), paragraphs separated by one blank line; "" when there is none or too much."""
        body = "\n\n".join(paragraphs_of(sanitize.text(text, MAX_TEXT + 1, multiline=True)))
        return body if len(body) <= MAX_TEXT else ""

    @app.post("/texte/neu/speichern")
    def save(request: Request, csrf: str = Form(...), text: str = Form(""), title: str = Form(""), recognized: str = Form(""),
             user: User = Depends(current_user)):
        """"Save text" after a photo: the text of the field, under the title of the upload step."""
        ctx.verify_csrf(request, csrf)
        name = sanitize.text(title, MAX_TITLE) or t("Untitled")
        percent = percent_of(recognized)
        if len(sanitize.text(text, MAX_TEXT + 1, multiline=True)) > MAX_TEXT:
            return check_again(request, user, t("A text can have at most {n} characters.", n=MAX_TEXT), 400, name, text, percent)
        body = body_of(text)
        if not body:
            return check_again(request, user, t("The text is empty."), 400, name, text, percent)
        if store.text_count(user.id) >= MAX_TEXTS:
            return check_again(request, user, t("You can keep at most {n} texts.", n=MAX_TEXTS), 400, name, text, percent)
        return ctx.redirect(f"/texte/{store.add_text(user.id, name, body, percent)}", t("Text saved."))

    @app.get("/texte/{text_id:int}", response_class=HTMLResponse)
    def show(request: Request, text_id: int, user: User = Depends(current_user)):
        return page(request, user, stored(user, text_id))

    @app.get("/texte/{text_id:int}/bearbeiten", response_class=HTMLResponse)
    def edit(request: Request, text_id: int, user: User = Depends(current_user)):
        """"Text bearbeiten" opens the check step over a saved text, with its translation preview and no photo marks."""
        row = stored(user, text_id)
        return page(request, user, row, popup="check", new_title=row.title, recognized_text=saved(row).plain, doubts=[],
                    regions=[], recognized=row.recognized, word_count=len(row.body.split()), editing=True)

    @app.post("/texte/{text_id:int}/speichern")
    def save_edit(request: Request, text_id: int, csrf: str = Form(...), text: str = Form(""),
                  user: User = Depends(current_user)):
        """"Save text" after "Edit text": the text of the field replaces the saved one (the title stays)."""
        ctx.verify_csrf(request, csrf)
        row = stored(user, text_id)
        if len(sanitize.text(text, MAX_TEXT + 1, multiline=True)) > MAX_TEXT:
            return check_again(request, user, t("A text can have at most {n} characters.", n=MAX_TEXT), 400, row.title, text,
                               row.recognized, row)
        body = body_of(text)
        if not body:
            return check_again(request, user, t("The text is empty."), 400, row.title, text, row.recognized, row)
        store.update_text(user.id, row.id, row.title, body)
        return ctx.redirect(f"/texte/{row.id}", t("Text saved."))

    @app.post("/texte/{text_id:int}/loeschen")
    def delete(request: Request, text_id: int, csrf: str = Form(...), user: User = Depends(current_user)):
        """"Delete text" after its confirmation: the text and its notes go, the words stay in the word list."""
        ctx.verify_csrf(request, csrf)
        row = stored(user, text_id)
        store.delete_text(user.id, row.id)
        return ctx.redirect("/texte", t("“{title}” was deleted.", title=row.title))

    # --- into the word list ---------------------------------------------------------------------------------------

    def entry_at(found: SavedText, reader: Reader, ref: str) -> Entry | None:
        """The dictionary entry a click means. Found by place in the text, never by browser text."""
        m = REF.match(ref)
        paragraphs = expand(found.paragraphs)
        try:
            seg = paragraphs[int(m.group(1))][int(m.group(2))] if m else None
        except IndexError:
            seg = None
        if not isinstance(seg, Word):
            raise HTTPException(400, "no such word")
        return reader.entry(seg)

    def marks(found: SavedText, user: User) -> dict:
        """What is in the user's word list now, for the page to mark: the places of its words, as "paragraph-segment"."""
        _, refs = reading(found, reader_for(user))
        return {"refs": sorted(refs)}

    def add_entry(user: User, text_id: int, entry: Entry | None) -> tuple[str, str]:
        """Add a dictionary entry to the word list as "from a text" and note it for this text; (status, message) for the toast."""
        if entry is None:
            return "missing", t("This word is not in the dictionary.")
        added = store.add_word(user.id, entry.lemma, entry.pos, added_from="text")
        store.link_text_word(user.id, text_id, entry.lemma, entry.pos)  # a word the user already had counts as noted too
        if added:
            return "added", t("“{word}” is now in your words.", word=v_label(entry))
        return "exists", t("“{word}” is already in your words.", word=v_label(entry))

    @app.post("/texte/{text_id:int}/wort")
    def add_word(request: Request, text_id: int, csrf: str = Form(...), ref: str = Form(""),
                 user: User = Depends(current_user)):
        """A click on any word of the text: into the word list, and into this text's notes."""
        ctx.verify_csrf(request, csrf)
        found = find(user, text_id)
        reader = reader_for(user)
        if reader.dic is None:
            return JSONResponse({"status": "missing", "message": t("No dictionary found: import the dictionary first."),
                                 "refs": []})
        status, message = add_entry(user, text_id, entry_at(found, reader, ref))
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
        found = find(user, text_id)
        phrase = selection_of(found, text)
        if len(phrase.split()) == 1:
            reader = reader_for(user)
            bare = phrase.strip(PUNCTUATION)
            status, message = add_entry(user, text_id, reader.entry(Word(bare)) if bare else None)
            return JSONResponse({"status": status, "message": message, **marks(found, user)})
        shown = phrase if len(phrase) <= 60 else phrase[:57] + "…"
        added = store.add_word(user.id, phrase, PHRASE, added_from="text")
        store.link_text_word(user.id, text_id, phrase, PHRASE)
        if added:
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
        phrase = selection_of(find(user, text_id), text)
        if len(phrase.split()) == 1:
            reader = reader_for(user)
            entry = reader.entry(Word(phrase.strip(PUNCTUATION))) if phrase.strip(PUNCTUATION) else None
            card = reader.card(entry)
            if entry is None or card is None:
                return JSONResponse({"kind": "word", "lines": [], "message": t("This word is not in the dictionary.")})
            return JSONResponse({"kind": "word", "lines": [card["kicker"].split(" · ")[0],
                                                            " · ".join(x for x in (card["title"], card["gloss"]) if x)],
                                 "message": ""})
        lines = [line for line in (mt.translate(phrase, "uk"), mt.translate(phrase, "en")) if line]
        return JSONResponse({"kind": "phrase", "lines": lines, "message": t("No translation available here.")})
