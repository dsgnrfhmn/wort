"""Word list and word detail: the Wörter screens."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote, urlencode

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry
from wort.dictionary.ukrainian import Ukrainian

from wort import sanitize

from app.db import User, UserWord, WebStore
from app.scoring import level

PAGE = 20
MAX_LIMIT = 1000
MAX_OWN = 200
SORTS = ("added", "word", "score")
POS_LABEL = {"noun": "Nomen", "verb": "Verb", "adj": "Adjektiv", "adv": "Adverb"}
SCORE_TAG = {"new": "neutral", "weak": "danger", "medium": "warning", "strong": "success"}
GENDER_LABEL = {"m": "maskulin", "f": "feminin", "n": "neutral"}
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]


def short_gloss(glosses: list[str], limit: int = 3) -> str:
    """The first few senses without their parenthetical notes: "квартира · apartment, flat", not a definition."""
    parts: list[str] = []
    for gloss in glosses[:2]:
        for part in re.split(r"[;,]", re.sub(r"\s*\([^)]*\)", "", gloss)):
            part = part.strip()
            if part and part not in parts:
                parts.append(part)
    return ", ".join(parts[:limit])


def uk_text(uk: Ukrainian | None, entry: Entry | None, lemma: str, pos: str | None, limit: int = 2) -> str:
    """Ukrainian for the word: from the German Wiktionary, else through its English glosses, marked "≈"."""
    if uk is None:
        return ""
    if direct := uk.translations(entry.lemma if entry else lemma, pos)[:limit]:
        return ", ".join(direct)
    via = uk.via_english(entry.glosses, pos, limit) if entry else []
    return "≈ " + ", ".join(via) if via else ""


def german_date(value: datetime | None) -> str:
    return f"{value.day}. {MONTHS[value.month - 1]} {value.year}" if value else "–"


@dataclass
class WordView:
    word: UserWord
    entry: Entry | None
    label: str = ""
    pos_label: str = ""
    gloss: str = ""
    uk: str = ""
    examples: list[tuple[str, str]] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.word.id

    @property
    def article(self) -> str:
        """der / die / das for a noun with a known gender, else empty (drives the word color)."""
        e = self.entry
        if e and e.pos == "noun" and e.gender in g.ARTICLES:
            return g.ARTICLES[e.gender]["nominative"]
        return ""

    @property
    def score_type(self) -> str:
        """Tag type of the score chip, by scoring.level()."""
        return SCORE_TAG[level(self.word.score)]

    @property
    def tooltip(self) -> str:
        """English, then Ukrainian, one per line (the word buttons' tooltip)."""
        return "\n".join(p for p in (self.gloss, self.uk) if p)

    @property
    def translation(self) -> str:
        """Ukrainian · English · own, as far as known (the design's "uk · en")."""
        parts = [self.uk, self.gloss, self.word.own_translation]
        return " · ".join(p for p in parts if p) or "–"


def v_label(entry: Entry) -> str:
    if entry.pos == "noun" and entry.gender in g.ARTICLES:
        return f"{g.ARTICLES[entry.gender]['nominative']} {entry.lemma}"
    return entry.lemma


def view(word: UserWord, dictionary: Dictionary | None, uk: Ukrainian | None = None) -> WordView:
    entry = dictionary.find_lemma(word.lemma, word.pos or None) if dictionary else None
    label = word.lemma
    if entry and entry.pos == "noun" and entry.gender in g.ARTICLES:
        label = f"{g.ARTICLES[entry.gender]['nominative']} {entry.lemma}"
    pos = entry.pos if entry else word.pos
    return WordView(
        word, entry, label, POS_LABEL.get(pos, pos.capitalize() if pos else ""),
        short_gloss(entry.glosses) if entry else "",
        uk_text(uk, entry, word.lemma, pos or None),
        list(entry.examples) if entry else [],
    )


def order(words: list[UserWord], sort: str, desc: bool) -> list[UserWord]:
    if sort == "word":
        return sorted(words, key=lambda w: w.lemma.casefold(), reverse=desc)
    if sort == "score":
        scored = sorted((w for w in words if w.score is not None), key=lambda w: w.score, reverse=desc)
        return scored + [w for w in words if w.score is None]
    return sorted(words, key=lambda w: (w.added_at, w.id), reverse=desc)


def preset_ids(words: list[UserWord], preset: str) -> set[int]:
    if preset == "weakest":
        return {w.id for w in order(words, "score", False)[:10]}
    if preset == "latest":
        return {w.id for w in order(words, "added", True)[:20]}
    return set()


# One German word as it stands in a text: letters (umlauts, ß), optionally joined by a hyphen or an apostrophe.
GLOSS_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]+(?:[-'][A-Za-zÄÖÜäöüß]+)*")
MAX_GLOSS_WORD = 60


def gloss(dictionary: Dictionary, uk: Ukrainian | None, word: str) -> dict | None:
    """Tooltip data for one German word anywhere on a page (an inflected form finds its lemma), or None."""
    found = dictionary.lookup_german(word, limit=1)
    if not found:
        return None
    entry = found[0]
    return {
        "word": word,
        "label": v_label(entry),
        "pos": POS_LABEL.get(entry.pos, entry.pos),
        "en": short_gloss(entry.glosses),
        "uk": uk_text(uk, entry, entry.lemma, entry.pos),
    }


def resolve_query(dictionary: Dictionary, query: str) -> Entry | None:
    """The dictionary entry a history query stands for (a German word first, else an English one)."""
    german, english = dictionary.lookup(query, limit=3)
    return (german or english or [None])[0]


def register(app, ctx) -> None:
    store: WebStore = ctx.store
    current_user = ctx.current_user

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

    def list_context(user: User, sort: str, dir: str, limit: int, preset: str = "") -> dict:
        """Everything the Wörter page shows besides a lookup or an open word."""
        sort = sort if sort in SORTS else "added"
        dir = "asc" if dir == "asc" else "desc"
        limit = max(1, min(limit, MAX_LIMIT))
        all_words = store.words(user.id)
        words = order(all_words, sort, dir != "asc")
        dic, uk = dictionary_or_none(), ukrainian_or_none()
        week = datetime.now().timestamp() - 7 * 86400
        last = max((w.added_at for w in all_words), default=None)
        return dict(
            user=user, page="words", dic=dic, uk=uk, all_words=all_words,
            rows=[view(w, dic, uk) for w in words[:limit]], selected=preset_ids(all_words, preset),
            total=len(words), limit=limit, sort=sort, dir=dir,
            list_params=urlencode({"sort": sort, "dir": dir, "limit": limit}),
            this_week=sum(1 for w in all_words if w.added_at.timestamp() >= week),
            last_added=last.strftime("%H:%M") if last else "", german_date=german_date,
            has_dictionary=dic is not None, query="", results=[], note="", detail=None,
            recent_queries=[h.query for h in store.history(user.id)[:3]],
            weakest=[view(w, dic, uk) for w in order([w for w in all_words if w.score is not None], "score", False)[:3]],
            latest=[view(w, dic, uk) for w in order(all_words, "added", True)[:3]],
        )

    def render_page(request: Request, page: dict) -> HTMLResponse:
        for key in ("dic", "uk", "all_words"):
            page.pop(key)
        return ctx.render(request, "words.html", **page)

    @app.get("/", response_class=HTMLResponse)
    def word_list(request: Request, sort: str = "added", dir: str = "desc", limit: int = PAGE,
                  preset: str = "", q: str = "", s: str = "", user: User = Depends(current_user)):
        from app import lookup
        page = list_context(user, sort, dir, limit, preset)
        query = sanitize.text(q, lookup.MAX_QUERY)
        if query and page["dic"] is not None:
            owned = {(w.lemma.casefold(), w.pos) for w in page["all_words"]}
            page["results"], page["note"] = lookup.search(page["dic"], page["uk"], query, owned)
            if s == "1":  # typed into the search field; reloads and the return after "add" are not new lookups
                found = bool(page["results"]) and not page["note"].startswith("Nicht")
                store.add_history(user.id, [(query, found, datetime.now())])
                page["recent_queries"] = [h.query for h in store.history(user.id)[:3]]
        page["query"] = query
        return render_page(request, page)

    @app.post("/words/add")
    def add_from_lookup(request: Request, csrf: str = Form(...), lemma: str = Form(...), pos: str = Form(""),
                        q: str = Form(""), user: User = Depends(current_user)):
        """"Zu Wörtern hinzufügen" on a lookup result: only a lemma that is in the dictionary is stored."""
        from app import lookup
        ctx.verify_csrf(request, csrf)
        query = sanitize.text(q, lookup.MAX_QUERY)
        back = "/?q=" + quote(query) if query else "/"
        try:
            lemma, pos = sanitize.word(lemma, 100), sanitize.word(pos, 40) if pos.strip() else ""
        except sanitize.Unsafe:
            raise HTTPException(400, "invalid word") from None
        dic = dictionary_or_none()
        entry = dic.find_lemma(lemma, pos or None) if dic else None
        if entry is None or (pos and entry.pos != pos):
            return ctx.redirect(back, "Dieses Wort steht nicht im Wörterbuch.")
        added = store.add_word(user.id, entry.lemma, entry.pos, added_from="lookup")
        label = v_label(entry)
        return ctx.redirect(back, f"„{label}“ ist jetzt in deinen Wörtern." if added else f"„{label}“ ist schon in deinen Wörtern.")

    @app.get("/words/{word_id}", response_class=HTMLResponse)
    def word_detail(request: Request, word_id: int, sort: str = "added", dir: str = "desc", limit: int = PAGE,
                    user: User = Depends(current_user)):
        """The Wörter page with the word open beside the table (the table keeps its sort and length)."""
        from app import lexicon, lookup
        word = store.word(user.id, word_id)
        if word is None:
            raise HTTPException(404, "no such word")
        page = list_context(user, sort, dir, limit)
        v = view(word, page["dic"], page["uk"])
        entry = v.entry
        attempts = store.attempts(user.id, word.id)
        queries = [h for h in store.history(user.id) if h.query.casefold() == word.lemma.casefold()]
        page["detail"] = dict(
            v=v, table=lookup.forms_table(entry) if entry else None, facts=lexicon.summary(entry) if entry else [],
            right=sum(1 for a in attempts if a.verdict == "correct"), wrong=sum(1 for a in attempts if a.verdict == "wrong"),
            mistakes=[a for a in attempts if a.verdict == "wrong"][:20], searches=queries[0].count if queries else 0,
            examples=v.examples[:10],
        )
        return render_page(request, page)

    @app.post("/words/learn")
    def learn(request: Request, csrf: str = Form(...), query: str = Form(...), user: User = Depends(current_user)):
        """Add the word behind a history query to the learning list (what Üben uses)."""
        ctx.verify_csrf(request, csrf)
        query = sanitize.text(query, 200)
        dic = dictionary_or_none()
        if dic is None:
            return ctx.redirect("/history", "Kein Wörterbuch gefunden: importiere zuerst das Wörterbuch.")
        entry = resolve_query(dic, query) if query else None
        if entry is None:
            return ctx.redirect("/history", "Dieses Wort steht nicht im Wörterbuch.")
        added = store.add_word(user.id, entry.lemma, entry.pos, added_from="lookup")
        label = v_label(entry)
        return ctx.redirect("/history", f"„{label}“ ist jetzt in deinen Wörtern." if added else f"„{label}“ ist schon in deinen Wörtern.")

    @app.post("/words/{word_id}/translation")
    def set_translation(request: Request, word_id: int, csrf: str = Form(...), text: str = Form(""),
                        user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        text = sanitize.text(text, MAX_OWN + 1)
        if len(text) > MAX_OWN:
            raise HTTPException(400, f"translation is limited to {MAX_OWN} characters")
        if not store.set_own_translation(user.id, word_id, text):
            raise HTTPException(404, "no such word")
        return RedirectResponse(f"/words/{word_id}", status_code=303)

    @app.get("/api/gloss")
    def gloss_word(w: str = "", user: User = Depends(current_user)):
        """English and Ukrainian for one German word the pointer rests on (app.js word tooltips). JSON only, text
        values; 404 when the word is not a German dictionary word, 400 when it is not one word."""
        word = sanitize.text(w, MAX_GLOSS_WORD + 1).strip()
        if not word or len(word) > MAX_GLOSS_WORD or not GLOSS_WORD.fullmatch(word):
            raise HTTPException(400, "one German word expected")
        dic = dictionary_or_none()
        if dic is None:
            raise HTTPException(503, "dictionary.db not found")
        data = gloss(dic, ukrainian_or_none(), word)
        if data is None or not (data["en"] or data["uk"]):
            raise HTTPException(404, "not in the dictionary")
        return JSONResponse(data, headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/words/{word_id}/delete")
    def delete_word(request: Request, word_id: int, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        if not store.delete_word(user.id, word_id):
            raise HTTPException(404, "no such word")
        return RedirectResponse("/", status_code=303)
