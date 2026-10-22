"""Word list and word detail: the Wörter screens."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from wort.dictionary import grammar as g
from wort.dictionary.lookup import Dictionary, Entry

from wort import sanitize

from app.db import User, UserWord, WebStore

PAGE = 20
MAX_LIMIT = 1000
MAX_OWN = 200
SORTS = ("added", "word", "score")
POS_LABEL = {"noun": "Nomen", "verb": "Verb", "adj": "Adjektiv", "adv": "Adverb"}
GENDER_LABEL = {"m": "maskulin", "f": "feminin", "n": "neutral"}
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]


def german_date(value: datetime | None) -> str:
    return f"{value.day}. {MONTHS[value.month - 1]} {value.year}" if value else "–"


@dataclass
class WordView:
    word: UserWord
    entry: Entry | None
    label: str = ""
    pos_label: str = ""
    gloss: str = ""
    examples: list[tuple[str, str]] = field(default_factory=list)

    @property
    def id(self) -> int:
        return self.word.id

    @property
    def translation(self) -> str:
        parts = [self.gloss, self.word.own_translation]
        return " · ".join(p for p in parts if p) or "–"


def v_label(entry: Entry) -> str:
    if entry.pos == "noun" and entry.gender in g.ARTICLES:
        return f"{g.ARTICLES[entry.gender]['nominative']} {entry.lemma}"
    return entry.lemma


def view(word: UserWord, dictionary: Dictionary | None) -> WordView:
    entry = dictionary.find_lemma(word.lemma, word.pos or None) if dictionary else None
    label = word.lemma
    if entry and entry.pos == "noun" and entry.gender in g.ARTICLES:
        label = f"{g.ARTICLES[entry.gender]['nominative']} {entry.lemma}"
    pos = entry.pos if entry else word.pos
    return WordView(
        word, entry, label, POS_LABEL.get(pos, pos.capitalize() if pos else ""),
        ", ".join(entry.glosses[:2]) if entry else "", list(entry.examples) if entry else [],
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

    @app.get("/", response_class=HTMLResponse)
    def word_list(request: Request, sort: str = "added", dir: str = "desc", limit: int = PAGE,
                  preset: str = "", user: User = Depends(current_user)):
        sort = sort if sort in SORTS else "added"
        limit = max(1, min(limit, MAX_LIMIT))
        all_words = store.words(user.id)
        selected = preset_ids(all_words, preset)
        words = order(all_words, sort, dir != "asc")
        shown = words[:limit]
        dic = dictionary_or_none()
        week = datetime.now().timestamp() - 7 * 86400
        return ctx.render(
            request, "words.html", user=user, page="words",
            rows=[view(w, dic) for w in shown], selected=selected, total=len(words), limit=limit,
            sort=sort, dir=dir, this_week=sum(1 for w in all_words if w.added_at.timestamp() >= week),
        )

    @app.get("/words/{word_id}", response_class=HTMLResponse)
    def word_detail(request: Request, word_id: int, user: User = Depends(current_user)):
        word = store.word(user.id, word_id)
        if word is None:
            raise HTTPException(404, "no such word")
        dic = dictionary_or_none()
        v = view(word, dic)
        entry = v.entry
        declension = []
        if entry and entry.pos == "noun":
            for case, label in (("nominative", "Nom."), ("accusative", "Akk."), ("dative", "Dat."),
                                ("genitive", "Gen.")):
                row = [label]
                for number in ("singular", "plural"):
                    form = g.noun_form(entry, case, number)
                    row.append(g.with_article(entry, form, case, number) if form else "–")
                declension.append(row)
        from app import lexicon
        facts = lexicon.summary(entry) if entry else []
        attempts = store.attempts(user.id, word.id)
        mistakes = [a for a in attempts if a.verdict == "wrong"][:20]
        queries = [h for h in store.history(user.id) if h.query.casefold() == word.lemma.casefold()]
        recent = order(store.words(user.id), "added", True)[:200]
        return ctx.render(
            request, "word.html", user=user, page="words", v=v, declension=declension, facts=facts,
            right=sum(1 for a in attempts if a.verdict == "correct"), wrong=sum(1 for a in attempts if a.verdict == "wrong"),
            mistakes=mistakes, searches=queries[0].count if queries else 0,
            sidebar=[view(w, dic) for w in recent], german_date=german_date, examples=v.examples[:10],
        )

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

    @app.post("/words/{word_id}/delete")
    def delete_word(request: Request, word_id: int, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        if not store.delete_word(user.id, word_id):
            raise HTTPException(404, "no such word")
        return RedirectResponse("/", status_code=303)
