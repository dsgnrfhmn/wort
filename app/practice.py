"""Practice: building sessions, grading answers locally, and the Üben routes.

A session is a stored list of items; an item holds only identifiers and a seed (the exercise is
rebuilt from the dictionary each time) plus, once answered, its result. Grading is deterministic and
local unless an AI call site is on (app/ai); every AI site falls back to the local behaviour and an
invalid or failed AI reply never changes a score.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from wort.dictionary.lookup import Dictionary, Entry
from wort.exercises import TYPES, pick_exercise
from wort.exercises.sentence import targets

from wort import sanitize

from app.ai.schemas import AnswerGrade, SentenceCheck, TaskSet
from app.ai.service import AiService, AiUnavailable
from app.checking import CheckResult, check_sentence
from wort.text import normalize
from app.db import User, UserWord, WebStore

KINDS = {"saetze": "Sätze bilden", "abfrage": "Abfrage", "regel": "Regel üben"}
CREATABLE = ("saetze", "abfrage")  # "regel" sessions only come from "Diese Regel üben"
SKILL = {"translate": "translation", "article": "form", "forms": "form", "question": "form", "sentence": "usage",
         "bedeutung": "translation", "erklaere": "translation"}
AI_ANSWER_KINDS = ("bedeutung", "erklaere")
MAX_OBJECTION = 300
RULE_TASKS = 5
GRADE = {"richtig": "correct", "teilweise": "almost", "falsch": "wrong"}
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
    rule: str = ""  # name of the rule behind the mistake (AI replies only)
    natural: str = ""  # a more natural wording (AI replies only)
    word_results: list[dict] | None = None  # per target form: word, ok, note (AI replies only)


def build_items(kind: str, pairs: list[tuple[UserWord, Entry]], rng: random.Random,
                ai_answers: bool = False) -> list[dict]:
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
        if ai_answers and e.glosses and rng.random() < 0.5:  # free answers need the AI to grade them
            items.append({"word_id": w.id, "kind": rng.choice(AI_ANSWER_KINDS)})
            continue
        ex = pick_exercise(e, {}, rng, QUESTION_KINDS)
        # seed lets the exercise be rebuilt identically (choice order, task variant)
        seed = rng.randrange(2**32)
        items.append({"word_id": w.id, "kind": ex.kind, "seed": seed})
    return items


def apply_ai_tasks(items: list[dict], lemmas: dict[int, str], tasks: TaskSet) -> None:
    """Give sentence items the AI's task wording (and translations) per word, in order. Local forms stay."""
    by_word: dict[str, list] = {}
    for t in tasks.tasks:
        by_word.setdefault(t.word.casefold(), []).append(t)
    for item in items:
        queue = by_word.get(lemmas.get(item["word_id"], "").casefold())
        if item["kind"] == "sentence" and queue:
            t = queue.pop(0)
            item.update({"ai_prompt": t.prompt, "tr_uk": t.translation_uk, "tr_en": t.translation_en})


def rebuild(item: dict, entry: Entry):
    """(prompt, hint, choices, exercise-or-None, required) for an item."""
    if item["kind"] == "sentence":
        if item.get("free"):  # "Regel üben": the AI's task, graded as a whole sentence, no fixed form
            return item["ai_prompt"], "", None, None, []
        task, required = targets(entry)[item["index"]]
        base = f"Schreibe einen Satz mit «{entry.lemma}»: {task}"
        return (f"{item['ai_prompt']} ({task})" if item.get("ai_prompt") else base), "", None, None, required
    if item["kind"] == "bedeutung":
        return f"Was bedeutet «{entry.lemma}»?", "", None, None, []
    if item["kind"] == "erklaere":
        return f"Erkläre auf Deutsch: «{entry.lemma}»", "", None, None, []
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


def graded_from_ai(check: SentenceCheck, required: list[str], sentence: str) -> Graded:
    """Map the validated AI reply to a verdict for this task's word."""
    remarks = [{"fragment": e.wrong, "message": e.kind, "replacements": [e.right]} for e in check.errors]
    forms = {normalize(w) for w in required}
    target_bad = any(not r.ok for r in check.word_results if normalize(r.word) in forms)
    if target_bad:
        verdict, note = "wrong", "Die Zielform ist nicht richtig verwendet."
    elif remarks:
        verdict, note = "almost", "Zielform richtig, aber der Satz hat Fehler."
    else:
        verdict, note = "correct", "Richtig."
    return Graded(verdict, " … ".join(required), note, check.corrected or sentence, remarks, [], rule=check.rule,
                  natural=check.natural, word_results=[r.model_dump() for r in check.word_results])


def grade_free_answer(item: dict, entry: Entry, answer: str, prompt: str, ai: AiService | None, user_id: int,
                      notes: list[str] | None) -> Graded:
    """Abfrage "Was bedeutet …?" / "Erkläre auf Deutsch": the AI grades it; bedeutung has a local fallback."""
    expected = "; ".join(entry.glosses[:3])
    if not answer:
        return Graded(None, "", "Gib eine Antwort ein.", final=False)
    if ai is not None and ai.uses("answer"):
        try:  # only the question, the answer and the dictionary glosses leave the server
            g: AnswerGrade = ai.grade_answer(user_id, prompt, answer, expected)
            return Graded(GRADE[g.verdict], expected, g.comment)
        except AiUnavailable as e:
            if notes is not None:
                notes.append(e.reason)
    if item["kind"] == "bedeutung":
        from wort.exercises.translate import _de_to_en  # same comparison the CLI uses
        res = _de_to_en(entry).check(answer)
        return Graded(res.verdict, res.expected, res.feedback)
    return Graded(None, expected, "Diese Aufgabe braucht die KI und wurde nicht bewertet.")  # no score


def grade_item(item: dict, entry: Entry, answer: str, checker, ai: AiService | None = None,
               user_id: int = 0, notes: list[str] | None = None) -> Graded:
    answer = sanitize.text(answer, MAX_ANSWER)
    prompt, _, _, ex, required = rebuild(item, entry)
    if item["kind"] in AI_ANSWER_KINDS:
        return grade_free_answer(item, entry, answer, prompt, ai, user_id, notes)
    if ex is None:
        if ai is None or not ai.uses("check"):
            return grade_sentence(answer, required, checker)
        # Deterministic checks first (length, required form): they decide without an API call.
        local = grade_sentence(answer, required, lambda s: [])
        if local.verdict == "wrong" or not local.final:
            return local
        try:  # only the sentence, the target forms and the task leave the server
            check = ai.check_sentence(user_id, answer, required, prompt)
        except AiUnavailable as e:
            if notes is not None:
                notes.append(e.reason)
            return grade_sentence(answer, required, checker)  # fall back to the local check
        return graded_from_ai(check, required, answer)
    if not answer:
        return Graded(None, "", "Gib eine Antwort ein.", final=False)
    res = ex.check(answer)
    return Graded(res.verdict, res.expected, res.feedback)


def register(app, ctx) -> None:
    store: WebStore = ctx.store
    current_user = ctx.current_user
    ai: AiService = ctx.ai

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
        if kind not in CREATABLE:
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
        items = build_items(kind, pairs, random.Random(), ai_answers=ai.uses("answer"))
        if items and kind == "saetze" and ai.uses("tasks"):
            try:  # one call per session: task wording for these words (only the lemmas are sent)
                apply_ai_tasks(items, {w.id: w.lemma for w, _ in pairs},
                               ai.generate_tasks(user.id, [w.lemma for w, _ in pairs], len(items)))
            except AiUnavailable:
                pass  # the local task wording stays
        if not items:
            return ctx.redirect("/", "Für diese Wörter gibt es keine Übungen.")
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
            result=item.get("result"), facts=ctx.facts(entry), ai_on=ai.available, ai_left=ai.remaining(user.id),
            ai_check=ai.uses("check") and item["kind"] == "sentence",
            can_explain=ai.uses("explain") and item["kind"] == "sentence",
            can_recheck=ai.uses("recheck") and item["kind"] == "sentence" and not item.get("rechecked"),
            can_rule=ai.uses("rule") and item["kind"] == "sentence" and bool((item.get("result") or {}).get("rule")),
            translations=[t for t in (item.get("tr_uk"), item.get("tr_en")) if t],
            explanation=item.get("explanation"), ai_note=item.get("ai_note", ""), answer=item.get("answer", ""),
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
        notes: list[str] = []
        graded = grade_item(item, entry, text, ctx.checker, ai, user.id, notes)
        cleaned = sanitize.text(text, MAX_ANSWER)
        if graded.final:
            delta = attempt_id = None  # an ungraded answer (grammar not checked) changes no score
            if graded.verdict is not None:
                attempt_id, delta = store.record_attempt_full(user.id, word.id, SKILL[item["kind"]], item["kind"],
                                                              rebuild(item, entry)[0], cleaned, graded.verdict)
            item["result"] = {**asdict(graded), "delta": delta, "attempt_id": attempt_id}
            item["answer"] = cleaned
            item["ai_note"] = notes[0] if notes else ""
            item.pop("notice", None)
        else:  # nothing to grade yet: show the message, keep the task open, change nothing
            item["notice"] = graded.feedback
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}", status_code=303)

    @app.post("/ueben/s/{sid}/explain")
    def explain(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        item = items[pos] if pos < len(items) else None
        res = item.get("result") if item else None
        if not res or res.get("verdict") in (None, "correct") or item["kind"] != "sentence" or "explanation" in item:
            return RedirectResponse(f"/ueben/s/{sid}", status_code=303)
        check = SentenceCheck(
            errors=[{"wrong": r["fragment"], "right": (r["replacements"] or [""])[0], "kind": r["message"][:60]}
                    for r in (res.get("remarks") or [])][:20],
            word_results=[], rule=res.get("feedback", "")[:300], natural="", corrected=res.get("corrected", "")[:300],
        )
        try:  # on demand only, one call per click
            out = ai.explain(user.id, item.get("answer", ""), check)
            item["explanation"] = out.model_dump()
        except AiUnavailable as e:
            item["ai_note"] = e.reason
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}", status_code=303)

    @app.post("/ueben/s/{sid}/recheck")
    def recheck(request: Request, sid: int, csrf: str = Form(...), objection: str = Form(""),
                user: User = Depends(current_user)):
        """"Doch richtig?": one re-evaluation per answer; the verdict still comes from the validated reply."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        item = items[pos] if pos < len(items) else None
        res = item.get("result") if item else None
        objection = sanitize.text(objection, MAX_OBJECTION)
        if (not res or item["kind"] != "sentence" or item.get("rechecked") or res.get("verdict") not in ("wrong", "almost")
                or not objection):
            return RedirectResponse(f"/ueben/s/{sid}", status_code=303)
        word = store.word(user.id, item["word_id"])
        entry = dictionary().find_lemma(word.lemma, word.pos or None) if word else None
        if word is None or entry is None:
            raise HTTPException(404, "word is gone")
        prompt, _, _, _, required = rebuild(item, entry)
        try:
            check = ai.recheck(user.id, item.get("answer", ""), required, prompt, objection)
        except AiUnavailable as e:
            item["ai_note"] = e.reason  # not counted as the one recheck: nothing was re-evaluated
            store.save_practice(user.id, sid, items, pos)
            return RedirectResponse(f"/ueben/s/{sid}", status_code=303)
        item["rechecked"] = True
        graded = graded_from_ai(check, required, item.get("answer", ""))
        if graded.verdict != res["verdict"] and res.get("attempt_id"):
            delta = store.revise_attempt(user.id, res["attempt_id"], graded.verdict)
            if delta is not None:
                item["result"] = {**asdict(graded), "delta": delta, "attempt_id": res["attempt_id"]}
                item["ai_note"] = "Die Bewertung wurde nach deinem Einwand geändert."
            else:
                item["ai_note"] = "Die Bewertung kann nicht mehr geändert werden."
        else:
            item["ai_note"] = "Die KI bleibt bei der Bewertung."
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}", status_code=303)

    @app.post("/ueben/s/{sid}/regel")
    def practise_rule(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        """"Diese Regel üben": a new session of tasks for the rule behind the last mistake."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        item = items[pos] if pos < len(items) else None
        rule = ((item.get("result") or {}).get("rule") or "")[:300] if item else ""
        if not rule or item["kind"] != "sentence":
            return RedirectResponse(f"/ueben/s/{sid}", status_code=303)
        try:  # only the rule's name is sent
            tasks = ai.more_for_rule(user.id, rule, RULE_TASKS)
        except AiUnavailable as e:
            item["ai_note"] = e.reason
            store.save_practice(user.id, sid, items, pos)
            return RedirectResponse(f"/ueben/s/{sid}", status_code=303)
        new = [{"word_id": item["word_id"], "kind": "sentence", "index": 0, "free": True, "ai_prompt": t.prompt,
                "tr_uk": t.translation_uk, "tr_en": t.translation_en} for t in tasks.tasks[:RULE_TASKS]]
        return RedirectResponse(f"/ueben/s/{store.create_practice(user.id, 'regel', new)}", status_code=303)

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
