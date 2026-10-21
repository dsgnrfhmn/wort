"""Practice: building sessions, grading answers locally, and the Üben routes.

A session is a stored list of items; an item holds only identifiers and a seed (the exercise is
rebuilt from the dictionary each time) plus, once answered, its result. Grading is deterministic and
local. `grade_sentence` is the single place a sentence provider (see app/ai) can replace.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from wort.dictionary.lookup import Dictionary, Entry
from wort.exercises import TYPES, pick_exercise
from wort.exercises.sentence import targets

from app.checking import CheckResult, check_sentence
from app.db import User, UserWord, WebStore

KINDS = {"saetze": "Sätze bilden", "abfrage": "Abfrage"}
SKILL = {"translate": "translation", "article": "form", "forms": "form", "question": "form", "sentence": "usage"}
MAX_ITEMS = 10
MAX_ANSWER = 300
QUESTION_KINDS = {"translate", "article", "forms", "question"}


@dataclass
class Graded:
    verdict: str | None  # correct | almost | wrong; None = not gradable, no score change
    expected: str = ""
    feedback: str = ""
    corrected: str = ""
    remarks: list[dict] | None = None
    missing: list[str] | None = None
    checked: bool = True
    final: bool = True  # False: a notice only, the task stays open


def build_items(kind: str, pairs: list[tuple[UserWord, Entry]], rng: random.Random) -> list[dict]:
    """One item per task. Sätze bilden: round-robin over the words, 5-10 tasks; Abfrage: one per word."""
    if kind == "saetze":
        usable = [(w, e, targets(e)) for w, e in pairs]
        usable = [u for u in usable if u[2]]
        if not usable:
            return []
        n = min(MAX_ITEMS, max(5, len(usable)))
        pools = {w.id: rng.sample(range(len(t)), len(t)) for w, _, t in usable}
        items = []
        for i in range(n):
            w, _, t = usable[i % len(usable)]
            pool = pools[w.id]
            items.append({"word_id": w.id, "kind": "sentence", "index": pool[(i // len(usable)) % len(pool)]})
        return items
    items = []
    for w, e in pairs[:MAX_ITEMS * 2]:
        ex = pick_exercise(e, {}, rng, QUESTION_KINDS)
        # seed lets the exercise be rebuilt identically (choice order, task variant)
        seed = rng.randrange(2**32)
        items.append({"word_id": w.id, "kind": ex.kind, "seed": seed})
    return items


def rebuild(item: dict, entry: Entry):
    """(prompt, hint, choices, exercise-or-None, required) for an item."""
    if item["kind"] == "sentence":
        task, required = targets(entry)[item["index"]]
        return f"Schreibe einen Satz mit «{entry.lemma}»: {task}", "", None, None, required
    ex = TYPES[item["kind"]].make(entry, random.Random(item["seed"]))
    return ex.prompt, ex.hint, ex.choices, ex, []


def grade_sentence(sentence: str, required: list[str], checker) -> Graded:
    r: CheckResult = check_sentence(sentence, required, checker)
    remarks = [{"fragment": x.fragment, "message": x.message, "replacements": x.replacements} for x in r.remarks]
    expected = " … ".join(required)
    if r.error:
        return Graded(None, expected, r.error, checked=False, final=False)
    if r.missing:
        return Graded("wrong", expected, "Die verlangte Form fehlt: " + " ".join(r.missing), r.corrected,
                      remarks, r.missing)
    if not r.checked:
        return Graded(None, expected, "Form vorhanden, Grammatik nicht geprüft: kein Score.", sentence, [], [], False)
    if remarks:
        return Graded("almost", expected, "Form richtig, aber Hinweise zur Grammatik.", r.corrected, remarks, [])
    return Graded("correct", expected, "Richtig.", sentence, [], [])


def grade_item(item: dict, entry: Entry, answer: str, checker) -> Graded:
    answer = " ".join(answer.split())[:MAX_ANSWER]
    _, _, _, ex, required = rebuild(item, entry)
    if ex is None:
        return grade_sentence(answer, required, checker)
    if not answer:
        return Graded(None, "", "Gib eine Antwort ein.", final=False)
    res = ex.check(answer)
    return Graded(res.verdict, res.expected, res.feedback)


def register(app, ctx) -> None:
    store: WebStore = ctx.store
    current_user = ctx.current_user

    def dictionary() -> Dictionary:
        try:
            return Dictionary(ctx.dict_path)
        except FileNotFoundError:
            raise HTTPException(503, "dictionary.db not found; build it with the CLI importer") from None

    def get_session(user: User, sid: int) -> dict:
        sess = store.practice(user.id, sid)
        if sess is None:
            raise HTTPException(404, "no such session")
        return sess

    @app.get("/ueben", response_class=HTMLResponse)
    def start(request: Request, user: User = Depends(current_user)):
        return ctx.render(request, "practice_start.html", user=user, page="practice", count=len(store.words(user.id)))

    @app.post("/ueben/{kind}")
    def create(request: Request, kind: str, csrf: str = Form(...), ids: list[int] = Form(default=[]),
               preset: str = Form(""), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        if kind not in KINDS:
            raise HTTPException(404, "unknown exercise")
        if preset == "weakest":
            from app.words import order
            chosen = order(store.words(user.id), "score", False)[:5]
        else:
            if not ids or len(ids) > 200:
                raise HTTPException(400, "select between 1 and 200 words")
            chosen = store.words_by_ids(user.id, ids)  # other users' ids are dropped here
        dic = dictionary()
        pairs = [(w, e) for w in chosen if (e := dic.find_lemma(w.lemma, w.pos or None))]
        items = build_items(kind, pairs, random.Random())
        if not items:
            return RedirectResponse("/?message=" + ctx.quote("Für diese Wörter gibt es keine Übungen."), status_code=303)
        return RedirectResponse(f"/ueben/s/{store.create_practice(user.id, kind, items)}", status_code=303)

    @app.get("/ueben/s/{sid}", response_class=HTMLResponse)
    def show(request: Request, sid: int, user: User = Depends(current_user)):
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if pos >= len(items):
            return ctx.render(request, "practice_done.html", user=user, page="practice", sess=sess,
                              rows=summary(user, items), kinds=KINDS)
        item = items[pos]
        word = store.word(user.id, item["word_id"])
        entry = dictionary().find_lemma(word.lemma, word.pos or None) if word else None
        if word is None or entry is None:
            raise HTTPException(404, "word is gone")
        prompt, hint, choices, _, required = rebuild(item, entry)
        return ctx.render(
            request, "practice.html", user=user, page="practice", sess=sess, item=item, pos=pos,
            total=len(items), prompt=prompt, hint=hint, choices=choices, word=word, kinds=KINDS,
            result=item.get("result"), facts=ctx.facts(entry), answer=item.get("answer", ""),
            tags=[store.word(user.id, i["word_id"]).lemma for i in items if store.word(user.id, i["word_id"])][:12],
        )

    @app.post("/ueben/s/{sid}/answer")
    def answer(request: Request, sid: int, csrf: str = Form(...), text: str = Form(""),
               user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if pos >= len(items) or "result" in items[pos]:
            return RedirectResponse(f"/ueben/s/{sid}", status_code=303)
        item = items[pos]
        word = store.word(user.id, item["word_id"])
        entry = dictionary().find_lemma(word.lemma, word.pos or None) if word else None
        if word is None or entry is None:
            raise HTTPException(404, "word is gone")
        graded = grade_item(item, entry, text, ctx.checker)
        cleaned = " ".join(text.split())[:MAX_ANSWER]
        if graded.final:
            delta = None  # an ungraded answer (grammar not checked) changes no score
            if graded.verdict is not None:
                delta = store.record_attempt(user.id, word.id, SKILL[item["kind"]], item["kind"],
                                             rebuild(item, entry)[0], cleaned, graded.verdict)
            item["result"] = {**asdict(graded), "delta": delta}
            item["answer"] = cleaned
            item.pop("notice", None)
        else:  # nothing to grade yet: show the message, keep the task open, change nothing
            item["notice"] = graded.feedback
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}", status_code=303)

    @app.post("/ueben/s/{sid}/next")
    def advance(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if pos < len(items) and "result" in items[pos]:
            store.save_practice(user.id, sid, items, pos + 1)
        return RedirectResponse(f"/ueben/s/{sid}", status_code=303)

    def summary(user: User, items: list[dict]) -> list[dict]:
        rows = []
        for it in items:
            w = store.word(user.id, it["word_id"])
            res = it.get("result") or {}
            rows.append({"label": w.lemma if w else "?", "verdict": res.get("verdict"), "delta": res.get("delta") or 0,
                         "score": w.score if w else None})
        return rows
