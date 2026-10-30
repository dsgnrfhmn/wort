"""Practice: building sessions, grading answers locally, and the Üben routes.

A session is a stored list of items; an item holds only identifiers and a seed (the exercise is
rebuilt from the dictionary each time) plus, once answered, its result. Grading is deterministic and
local unless an AI call site is on (app/ai); every AI site falls back to the local behaviour and an
invalid or failed AI reply never changes a score.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import asdict, dataclass

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from wort.dictionary.grammar import ARTICLES
from wort.dictionary.lookup import Dictionary, Entry
from wort.exercises import TYPES, pick_exercise
from wort.exercises.sentence import targets

from wort import sanitize

from app.ai.schemas import AnswerGrade, SentenceCheck, TaskSet
from app import grammar, hints, mt, questions
from app.i18n import t
from app.ai.service import AiService, AiUnavailable
from wort.dictionary.ukrainian import Ukrainian
from app.checking import CheckResult, check_sentence, lemma_forms
from wort.text import normalize
from app.db import User, UserWord, WebStore
from app.words import GENDER_LABEL, POS_LABEL, german_date, short_gloss, uk_text, v_label

# English source names; templates show them through _() (app/i18n.py).
KINDS = {"saetze": "Build sentences", "abfrage": "Quiz", "regel": "Practise the rule", "grammatik": "Grammar"}
TABS = ("saetze", "abfrage", "grammatik")  # the start page's tabs; grammar sessions start from a topic
CREATABLE = ("saetze", "abfrage")  # "regel" sessions only come from "Diese Regel üben"
# The Üben tabs and the session kinds behind each: one open session per kind; a "regel" session belongs to Sätze bilden.
MODES = {"saetze": ("saetze", "regel"), "abfrage": ("abfrage",), "grammatik": ("grammatik",)}
WORD_KINDS = ("saetze", "abfrage", "regel")  # sessions with words: the latest one's words are the current batch
SKILL = {"translate": "translation", "article": "form", "forms": "form", "question": "form", "sentence": "usage",
         "bedeutung": "translation", "erklaere": "translation"}
AI_ANSWER_KINDS = ("bedeutung", "erklaere")
# Abfrage's modes: the local drills mixed (plus free answers when the AI grades them), or one kind for every word.
# "erklaere" can only be graded by the AI; "bedeutung" falls back to the dictionary's glosses.
ABFRAGE_MODES = {"gemischt": "Mixed", "bedeutung": "What does … mean?", "erklaere": "Explain in German"}
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
    tip: str = ""  # the sentence lacks the asked form: a hint, not a mistake
    word_ok: bool | None = None  # sentence tasks: the word itself is used (in the asked or another form)
    grammar: str = ""  # sentence tasks: ok | errors | unchecked, judged apart from the word


def build_items(kind: str, pairs: list[tuple[UserWord, Entry]], rng: random.Random,
                ai_answers: bool = False, topic: str = questions.ALL, mode: str = "gemischt") -> list[dict]:
    """One item per task. Sätze bilden: round-robin over the words, 5-10 tasks, each with a question from
    `topic` that fits its word (questions.pick_for); Abfrage: one per word, of the kinds `mode` names."""
    if kind == "saetze":
        usable = [(w, e, targets(e)) for w, e in pairs]
        usable = [u for u in usable if u[2]]
        if not usable:
            return []
        n = min(MAX_ITEMS, max(5, len(usable)))
        pools = {w.id: rng.sample(range(len(t)), len(t)) for w, _, t in usable}
        items, used = [], []
        for i in range(n):
            w, e, t = usable[i % len(usable)]
            pool = pools[w.id]
            ref = questions.pick_for(topic, e.glosses, rng, avoid=used)  # a question that fits this word
            used.append(ref)
            items.append({"word_id": w.id, "kind": "sentence", "index": pool[(i // len(usable)) % len(pool)],
                          "question": ref, "topic": topic})
        return items
    if mode in AI_ANSWER_KINDS:  # one kind for every word that has glosses to compare with
        return [{"word_id": w.id, "kind": mode} for w, e in pairs[:MAX_ITEMS * 2] if e.glosses]
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


def abfrage_mode(items: list[dict]) -> str:
    """The mode a session was started in, read from its items (sessions store no mode of their own)."""
    kinds = {i["kind"] for i in items}
    return next(iter(kinds)) if len(kinds) == 1 and kinds <= set(AI_ANSWER_KINDS) else "gemischt"


def question_text(item: dict) -> str:
    """The topic question shown above a sentence task; none when the AI wrote the task wording."""
    if item["kind"] != "sentence" or item.get("free") or item.get("ai_prompt"):
        return ""
    return questions.text(item.get("question"))


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


def correction_segments(answer: str, remarks: list[dict] | None,
                        table: Callable[[str], list[str]] | None = None,
                        link: Callable[[int], str] | None = None, current: int | None = None) -> list[dict] | None:
    """Split the learner's sentence into plain / remove / add runs from the checker's remarks.

    link(n) gives a correction (the add run of remark n, 1-based in `remarks`) a link to its explanation;
    `current` marks the one whose explanation is open.

    Each remark's fragment must occur exactly once in the answer and the fragments must not overlap;
    otherwise None (the caller shows the corrected sentence as plain text, never partial marks).
    """
    spans = []
    for n, r in enumerate(remarks or [], 1):
        frag = (r.get("fragment") or "").strip()
        if not frag or answer.count(frag) != 1:
            return None
        start = answer.index(frag)
        spans.append((start, start + len(frag), r, n))
    if not spans:
        return None
    spans.sort(key=lambda t: t[0])
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        return None
    out, at = [], 0
    for start, end, r, n in spans:
        if start > at:
            out.append({"text": answer[at:start]})
        reps = [x for x in (r.get("replacements") or []) if x]
        # The tooltip on the correction: why (the checker's message), the right form, and the corrected word's
        # forms as a small table when the dictionary knows it.
        rows = table(reps[0]) if table and reps else []
        right = [t("Correct: {text}", text=reps[0])] + ([t("Also possible: {text}", text=" / ".join(reps[1:3]))]
                                                         if len(reps) > 1 else []) if reps else []
        uk = hints.rule_uk(r.get("rule") or "", r.get("category") or "")
        why = (r.get("message") or "") + (f" ({uk})" if uk else "")
        tip = "\n".join([x for x in (why,) if x] + right + ([""] + rows if rows else []))
        out.append({"text": answer[start:end], "kind": "remove"})
        if reps:
            out.append({"text": " "})
            out.append({"text": reps[0], "kind": "add", "tooltip": tip,
                        **({"href": link(n)} if link else {}), **({"current": True} if n == current else {})})
        at = end
    if at < len(answer):
        out.append({"text": answer[at:]})
    return out


def grade_sentence(sentence: str, required: list[str], checker, forms: set[str] | frozenset[str] = frozenset(),
                   task: str = "") -> Graded:
    """The word and the grammar are judged apart. Word in the asked form, or in another form of the same lemma
    (then with a tip): the score follows the grammar. Word missing: only a tip, no score. Grammar not checked:
    no score either way."""
    r: CheckResult = check_sentence(sentence, required, checker, forms)
    remarks = [{"fragment": x.fragment, "message": x.message, "replacements": x.replacements,
                **({"rule": x.rule, "category": x.category} if x.rule or x.category else {})} for x in r.remarks]
    expected = " … ".join(required)
    if r.error:
        return Graded(None, expected, r.error, checked=False, final=False)
    grammar = "unchecked" if not r.checked else ("errors" if remarks else "ok")
    by_grammar = None if not r.checked else ("almost" if remarks else "correct")
    if r.missing and not r.used:
        tip = t("Use: {words}", words=" ".join(r.missing))
        return Graded(None, expected, tip, r.corrected, remarks, r.missing, checked=r.checked, tip=tip,
                      word_ok=False, grammar=grammar)
    asked = f" ({task})" if task else ""
    tip = t("«{want}»{asked} instead of «{used}».", want=" ".join(required), asked=asked, used=" ".join(r.used)) \
        if r.missing else ""
    return Graded(by_grammar, expected, t("Word used correctly."), r.corrected if remarks else sentence, remarks,
                  r.missing, checked=r.checked, tip=tip, word_ok=True, grammar=grammar)


def graded_from_ai(check: SentenceCheck, required: list[str], sentence: str) -> Graded:
    """Map the validated AI reply to a verdict for this task's word."""
    remarks = [{"fragment": e.wrong, "message": e.kind, "replacements": [e.right]} for e in check.errors]
    forms = {normalize(w) for w in required}
    target_bad = any(not r.ok for r in check.word_results if normalize(r.word) in forms)
    if target_bad:
        verdict, note = "wrong", t("The target form is not used correctly.")
    elif remarks:
        verdict, note = "almost", t("Target form right, but the sentence has mistakes.")
    else:
        verdict, note = "correct", "Richtig."
    return Graded(verdict, " … ".join(required), note, check.corrected or sentence, remarks, [], rule=check.rule,
                  natural=check.natural, word_results=[r.model_dump() for r in check.word_results])


def grade_free_answer(item: dict, entry: Entry, answer: str, prompt: str, ai: AiService | None, user_id: int,
                      notes: list[str] | None) -> Graded:
    """Abfrage "Was bedeutet …?" / "Erkläre auf Deutsch": the AI grades it; bedeutung has a local fallback."""
    expected = "; ".join(entry.glosses[:3])
    if not answer:
        return Graded(None, "", t("Enter an answer."), final=False)
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
    return Graded(None, expected, t("This task needs the AI and was not graded."))  # no score


def attempt_details(item: dict, entry: Entry, graded: Graded, answer: str) -> dict[str, str]:
    """What the word detail needs to show a mistake later: the asked form, the right answer, the corrected
    sentence (only when it differs) and the rule (the AI's, else the checker's first remark)."""
    task = targets(entry)[item["index"]][0] if item["kind"] == "sentence" and not item.get("free") else ""
    rule = graded.rule or next((r.get("message") or "" for r in graded.remarks or [] if r.get("message")), "")
    corrected = graded.corrected if graded.corrected and graded.corrected != answer else ""
    return {"task": task, "expected": graded.expected, "corrected": corrected, "rule": rule}


def grade_item(item: dict, entry: Entry, answer: str, checker, ai: AiService | None = None,
               user_id: int = 0, notes: list[str] | None = None) -> Graded:
    answer = sanitize.text(answer, MAX_ANSWER)
    prompt, _, _, ex, required = rebuild(item, entry)
    if item["kind"] in AI_ANSWER_KINDS:
        return grade_free_answer(item, entry, answer, prompt, ai, user_id, notes)
    if ex is None:
        forms = lemma_forms(entry)
        task = "" if item.get("free") else targets(entry)[item["index"]][0]
        if ai is None or not ai.uses("check"):
            return grade_sentence(answer, required, checker, forms, task)
        # Deterministic checks first (length, required form): they decide without an API call.
        local = grade_sentence(answer, required, lambda s: [], forms, task)
        if local.tip:  # the AI verdict is about the target form; grammar of such a sentence is checked locally
            return grade_sentence(answer, required, checker, forms, task)
        if not local.final:
            return local
        try:  # only the sentence, the target forms and the task leave the server
            check = ai.check_sentence(user_id, answer, required, prompt)
        except AiUnavailable as e:
            if notes is not None:
                notes.append(e.reason)
            return grade_sentence(answer, required, checker, forms, task)  # fall back to the local check
        return graded_from_ai(check, required, answer)
    if not answer:
        return Graded(None, "", t("Enter an answer."), final=False)
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

    def translator():
        """entry -> "Ukrainian · English" for the tooltips (empty parts left out); English only without the
        Ukrainian dictionary."""
        try:
            uk = Ukrainian(ctx.uk_path, ctx.uk_en_path)
        except FileNotFoundError:
            uk = None
        def parts(e: Entry) -> tuple[str, str]:  # (Ukrainian, English)
            return uk_text(uk, e, e.lemma, e.pos), short_gloss(e.glosses, 2)

        def translate(e: Entry) -> str:
            return " · ".join(p for p in parts(e) if p)
        translate.parts = parts  # the two apart, for the example tooltip
        return translate

    def get_session(user: User, sid: int) -> dict:
        sess = store.practice(user.id, sid)
        if sess is None:
            raise HTTPException(404, "no such session")
        return sess

    def weakest_words(user: User) -> list[UserWord]:
        """The five words with the lowest score (words not practised yet follow the scored ones)."""
        from app.words import order
        return order([w for w in store.words(user.id) if not w.is_phrase], "score", False)[:5]

    @app.get("/ueben", response_class=HTMLResponse)
    def start(request: Request, modus: str = "", thema: str = questions.ALL, neu: str = "",
              user: User = Depends(current_user)):
        """Üben: back to the open session (of tab `modus`, else the newest open one); `neu`, or nothing open, shows
        the start page, which offers the current batch of words (the latest word session's) again."""
        if not neu:
            last = store.latest_practice(user.id, MODES.get(modus, ()), open_only=True)
            if last:
                return RedirectResponse(f"/ueben/s/{last['id']}#jetzt", status_code=303)
        modus = modus if modus in TABS else "saetze"
        progress = store.grammar_progress(user.id)
        return ctx.render(request, "practice_start.html", user=user, page="practice", modus=modus, kinds=KINDS,
                          tabs=TABS, count=sum(1 for w in store.words(user.id) if not w.is_phrase), thema=questions.topic_or_all(thema),
                          themen=questions.LABELS, batch=batch_of(user, store.latest_practice(user.id, WORD_KINDS)),
                          resume=store.latest_practice(user.id, MODES[modus], open_only=True),
                          ueben_tabs=mode_tabs(user, modus), weakest=[w.lemma for w in weakest_words(user)],
                          topics=[{"id": k, **t, "progress": progress.get(k)} for k, t in grammar.TOPICS.items()])

    @app.get("/grammatik/{topic}", response_class=HTMLResponse)
    def grammar_topic(request: Request, topic: str, user: User = Depends(current_user)):
        """A grammar topic: its explanation and the way into its exercises."""
        if topic not in grammar.TOPICS:
            raise HTTPException(404, "no such topic")
        return ctx.render(request, "grammar_topic.html", user=user, page="practice", topic_id=topic,
                          ueben_tabs=mode_tabs(user, "grammatik"),
                          topic=grammar.TOPICS[topic], progress=store.grammar_progress(user.id).get(topic))

    @app.post("/ueben/grammatik/{topic}")
    def grammar_start(request: Request, topic: str, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        if topic not in grammar.TOPICS:
            raise HTTPException(404, "no such topic")
        items = grammar.build_items(topic, random.Random())
        close_open(user, MODES["grammatik"])
        return RedirectResponse(f"/ueben/s/{store.create_practice(user.id, 'grammatik', items)}", status_code=303)

    def mode_tabs(user: User, active: str) -> list[dict]:
        """The Üben tabs on every Üben page: each resumes its open session (its progress as the count) or opens its
        start page."""
        out = []
        for key in TABS:
            sess = store.latest_practice(user.id, MODES[key], open_only=True)
            out.append({"label": t(KINDS[key]), "href": f"/ueben?modus={key}", "active": key == active,
                        "count": f"{sess['pos'] + 1} / {len(sess['items'])}" if sess else None})
        return out

    def mode_of(kind: str) -> str:
        return next((m for m, kinds in MODES.items() if kind in kinds), "saetze")

    def close_open(user: User, kinds: tuple[str, ...]) -> None:
        """A new session replaces the open one of its kinds: the old one is closed (its position set to the end, so
        it counts as finished; answered tasks keep their results)."""
        for sess in store.open_practices(user.id, kinds):
            store.save_practice(user.id, sess["id"], sess["items"], len(sess["items"]))

    def batch_of(user: User, sess: dict | None) -> dict | None:
        """The words of a session as the current batch: ids (still in the word list) and their lemmas."""
        if not sess:
            return None
        ids = list(dict.fromkeys(i["word_id"] for i in sess["items"] if "word_id" in i))
        words = store.words_by_ids(user.id, ids)
        return {"ids": [w.id for w in words], "lemmas": [w.lemma for w in words],
                "kind": sess["kind"] if sess["kind"] in CREATABLE else "saetze"} if words else None

    @app.post("/ueben/{kind}")
    def create(request: Request, kind: str, csrf: str = Form(...), ids: list[int] = Form(default=[]),
               preset: str = Form(""), thema: str = Form(questions.ALL), art: str = Form("gemischt"),
               user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        if kind not in CREATABLE:
            raise HTTPException(404, "unknown exercise")
        if art not in ABFRAGE_MODES:
            raise HTTPException(400, "unknown mode")
        if art == "erklaere" and not ai.uses("answer"):  # the page offers it disabled; a forged post lands here
            return ctx.redirect("/ueben?neu=1&modus=abfrage", t("“Explain in German” needs the AI; it is off."))
        if preset == "weakest":
            chosen = weakest_words(user)
        else:
            if not ids or len(ids) > 200:
                raise HTTPException(400, "select between 1 and 200 words")
            chosen = store.words_by_ids(user.id, ids)  # other users' ids are dropped here
        phrases = [w for w in chosen if w.is_phrase]  # added from a text: there is no exercise for them yet
        chosen = [w for w in chosen if not w.is_phrase]
        if phrases and not chosen:
            return ctx.redirect("/", t("Phrases cannot be practised yet."))
        dic = dictionary()
        pairs = [(w, e) for w in chosen if (e := dic.find_lemma(w.lemma, w.pos or None))]
        items = build_items(kind, pairs, random.Random(), ai_answers=ai.uses("answer"),
                            topic=questions.topic_or_all(thema), mode=art if kind == "abfrage" else "gemischt")
        if items and kind == "saetze" and ai.uses("tasks"):
            try:  # one call per session: task wording for these words (only the lemmas are sent)
                apply_ai_tasks(items, {w.id: w.lemma for w, _ in pairs},
                               ai.generate_tasks(user.id, [w.lemma for w, _ in pairs], len(items)))
            except AiUnavailable:
                pass  # the local task wording stays
        if not items:
            return ctx.redirect("/", t("There are no exercises for these words."))
        close_open(user, MODES[kind])
        url = f"/ueben/s/{store.create_practice(user.id, kind, items)}"
        if phrases:
            return ctx.redirect(url, t("Phrases are skipped: there is no exercise for them yet."))
        return RedirectResponse(url, status_code=303)

    @app.get("/ueben/s/{sid}", response_class=HTMLResponse)
    def show(request: Request, sid: int, fehler: str = "", nochmal: str = "", a: int = -1, w: int = 0,
             user: User = Depends(current_user)):
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if pos >= len(items):
            return ctx.render(request, "practice_done.html", user=user, page="practice", sess=sess,
                              rows=summary(user, items), kinds=KINDS, batch=batch_of(user, sess),
                              ueben_tabs=mode_tabs(user, mode_of(sess["kind"])))
        dic = dictionary()
        item = items[pos]
        tr = translator()
        try:  # ?fehler=<task>-<mistake>: that correction is marked as open (the pane checks the rest)
            fi, fn = (int(x) for x in fehler.split("-", 1))
            opened = {fi: fn}
        except ValueError:
            opened = {}
        current = turn(user, dic, tr, pos, item, opened)
        if current is None:
            raise HTTPException(404, "word is gone")
        if sess["kind"] == "abfrage":
            return abfrage_page(request, user, sess, current)
        # One task at a time; tabs on top switch between the answered tasks and the current one (?a=<index>; a
        # "Fehler erklären" link opens its own task). The next task opens only with "Nächste Aufgabe" (/next).
        # The sidebar: this session's words; ?w=<word id> keeps the tabs to that word's tasks.
        words = session_words(user, dic, items, pos)
        reachable = {x["id"]: x["reachable"] for x in words}
        if not reachable.get(w):
            w = 0
        view = a if a >= 0 else (next(iter(opened)) if opened else (reachable[w][0] if w else pos))
        if not 0 <= view <= pos:
            view = pos
        if w and view not in reachable[w]:
            w = 0
        shown = current if view == pos else turn(user, dic, tr, view, items[view], opened)
        if shown is None:
            raise HTTPException(404, "word is gone")
        tabs = [{"index": i, "attempts": 1 + len(items[i].get("retries") or []) if "result" in items[i] else 0,
                 "v": step_verdict(items[i])}
                for i in (reachable[w] if w else range(pos + 1))]
        # ?nochmal=1: the composer answers the shown, already answered sentence task again (a retry).
        retry = bool(nochmal) and can_retry(items[view])
        target = shown if retry or (view == pos and "result" not in item) else None
        return ctx.render(
            request, "practice.html", user=user, page="practice", sess=sess, item=item, pos=pos,
            total=len(items), shown=shown, view=view, tabs=tabs, words=words, w=w, target=target, kinds=KINDS,
            retry=retry, ueben_tabs=mode_tabs(user, mode_of(sess["kind"])),
            can_retry=can_retry(items[view]),
            erklaert=explained(user, sess, fehler, dic, tr),
            ai_on=ai.available, ai_left=ai.remaining(user.id),
            ai_check=ai.uses("check") and item["kind"] == "sentence",
            can_explain=ai.uses("explain") and item["kind"] == "sentence",
            can_recheck=ai.uses("recheck") and item["kind"] == "sentence" and not item.get("rechecked"),
            can_rule=ai.uses("rule") and item["kind"] == "sentence" and bool((item.get("result") or {}).get("rule")),
            tags=([grammar.TOPICS[items[0]["topic"]]["title"]] if item["kind"] == "grammar" and items[0].get("topic")
                  in grammar.TOPICS else
                  [w.lemma for i in items if "word_id" in i and (w := store.word(user.id, i["word_id"]))][:12]),
        )

    def abfrage_page(request: Request, user: User, sess: dict, current: dict):
        """Abfrage (design Üben 6): one word at a time on the left, this round's results on the right."""
        items, pos = sess["items"], sess["pos"]
        word = store.word(user.id, items[pos]["word_id"])
        entry = dictionary().find_lemma(word.lemma, word.pos or None)
        rows = summary(user, items[:pos + 1] if "result" in items[pos] else items[:pos])
        count = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("correct", "almost", "wrong")}
        res = items[pos].get("result") or {}
        tr_uk, tr_en = translator().parts(entry)
        return ctx.render(
            request, "practice_abfrage.html", user=user, page="practice", sess=sess, t=current, pos=pos,
            total=len(items), kinds=KINDS, batch=batch_of(user, sess), rows=rows, count=count,
            ueben_tabs=mode_tabs(user, "abfrage"),
            left=sum(1 for i in items if "result" not in i) - (0 if "result" in items[pos] else 1),
            mode=abfrage_mode(items), modes=ABFRAGE_MODES, erklaere_ok=ai.uses("answer"),
            pos_label=POS_LABEL.get(entry.pos, entry.pos.capitalize())
            + (f" · {GENDER_LABEL[entry.gender]}" if entry.pos == "noun" and entry.gender in GENDER_LABEL else ""),
            # Not `article`: text-button reads a context variable of that name and would colour every button on the page.
            word_article=ARTICLES[entry.gender]["nominative"] if entry.pos == "noun" and entry.gender in ARTICLES else "",
            lemma=entry.lemma, translations=" · ".join(x for x in (tr_uk, tr_en) if x),
            example=entry.examples[0][0] if entry.examples else "",
            can_downgrade=res.get("verdict") in ("correct", "almost") and bool(res.get("attempt_id"))
            and not items[pos].get("downgraded"),
        )

    @app.post("/ueben/s/{sid}/skip")
    def skip(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        """Abfrage "Überspringen": the current word is left out of this round, no score change."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if sess["kind"] == "abfrage" and pos < len(items) and "result" not in items[pos]:
            items[pos]["result"] = asdict(Graded(None, feedback="Übersprungen.")) | {"delta": None, "skipped": True}
            store.save_practice(user.id, sid, items, pos + 1)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    @app.post("/ueben/s/{sid}/doch-falsch")
    def downgrade(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        """Abfrage "Doch falsch": the learner marks an answer the check accepted as wrong (once, only downwards,
        only while it is the word's latest answer: store.revise_attempt)."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        item = items[pos] if pos < len(items) else None
        res = (item or {}).get("result") or {}
        if (sess["kind"] == "abfrage" and res.get("verdict") in ("correct", "almost") and res.get("attempt_id")
                and not item.get("downgraded")):
            delta = store.revise_attempt(user.id, res["attempt_id"], "wrong")
            if delta is not None:
                res.update(verdict="wrong", delta=delta, feedback=t("Marked wrong by you."))
                item["downgraded"] = True
                store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    def turn(user: User, dic: Dictionary, translate, index: int, item: dict, opened: dict | None = None) -> dict | None:
        """One task of the chat: its prompt and, once answered, the answer with its feedback. None: word gone.
        `opened` {task index: mistake number} marks the correction whose explanation is open."""
        opened = opened or {}
        if item["kind"] == "grammar":
            return grammar_turn(dic, translate, index, item, opened)
        word = store.word(user.id, item["word_id"])
        entry = dic.find_lemma(word.lemma, word.pos or None) if word else None
        if word is None or entry is None:
            return None
        prompt, hint, choices, _, required = rebuild(item, entry)
        result = item.get("result")
        sentence_task = item["kind"] == "sentence" and not item.get("free")
        return {
            "index": index, "kind": item["kind"], "prompt": prompt, "question": question_text(item), "hint": hint,
            "choices": choices, "notice": item.get("notice", ""), "result": result, "answer": item.get("answer", ""),
            "word_label": v_label(entry), "facts": ctx.facts(entry) if result else [],
            "segments": correction_segments(item.get("answer", ""), (result or {}).get("remarks"),
                                            lambda word: hints.correction_table(dic, word, translate),
                                            lambda n: f"?fehler={index}-{n}#jetzt", opened.get(index)),
            "task_hint": hints.task_hint(entry, targets(entry)[item["index"]][0], required) if sentence_task else "",
            "example": hints.example_tooltip(entry, targets(entry)[item["index"]][0], required, mt.translate,
                                             *translate.parts(entry))
                       if sentence_task else "",
            "explanation": item.get("explanation"), "ai_note": item.get("ai_note", ""),
            "translations": [t for t in (item.get("tr_uk"), item.get("tr_en")) if t],
            "details": details(item, result, ctx.facts(entry) if result else [], index),
            "mistakes": mistakes((result or {}).get("remarks"), dic, translate),
            "input": "textarea" if item["kind"] in ("sentence", "erklaere") else "text",
            "retries": [retry_turn(dic, translate, index, item, n, r, v_label(entry))
                        for n, r in enumerate(item.get("retries") or [], 2)],
        }

    def session_words(user: User, dic: Dictionary, items: list[dict], pos: int) -> list[dict]:
        """The session's words in task order: label, its tasks up to the current one (`reachable`) and how many of
        its tasks are answered. Empty for a grammar session (no words)."""
        out: dict[int, dict] = {}
        for i, it in enumerate(items):
            if "word_id" not in it:
                continue
            x = out.get(it["word_id"])
            if x is None:
                word = store.word(user.id, it["word_id"])
                entry = dic.find_lemma(word.lemma, word.pos or None) if word else None
                if entry is None:
                    continue
                x = out[it["word_id"]] = {"id": it["word_id"], "label": v_label(entry), "reachable": [], "answered": 0,
                                          "total": 0}
            x["total"] += 1
            x["answered"] += "result" in it
            if i <= pos:
                x["reachable"].append(i)
        return list(out.values())

    def can_retry(item: dict) -> bool:
        """"Nochmal antworten": any answered sentence task, as often as the learner likes (no cap, garv 2026-10-29;
        an AI check still counts against the daily AI cap)."""
        return item["kind"] == "sentence" and "result" in item

    def retry_turn(dic: Dictionary, translate, index: int, item: dict, attempt: int, r: dict, word_label: str) -> dict:
        """Attempt `attempt` (2, 3, …) of task `index`, shaped like a turn for the reply macro. No links to the
        explanation pane (it explains the first attempt), no word facts or translations (shown with the first)."""
        own = {"answer": r["answer"], "ai_note": r.get("ai_note", "")}
        return {
            "index": index, "attempt": attempt, "result": r["result"], "answer": r["answer"], "word_label": word_label,
            "segments": correction_segments(r["answer"], r["result"].get("remarks"),
                                            lambda word: hints.correction_table(dic, word, translate)),
            "details": [(label, text, "") for label, text, _ in details(own, r["result"], [], index)],
            "mistakes": mistakes(r["result"].get("remarks"), dic, translate),
            "explanation": None,
        }

    def mistakes(remarks: list[dict] | None, dic: Dictionary, translate) -> list[dict]:
        """"Explain more": each mistake in full, from the local explanation (hints.explain: what was wrong, the
        right form, the rule table with the right cell marked, Merke, Ukrainian) and its Grammatik topic."""
        out = []
        for n, r in enumerate(remarks or [], 1):
            view = hints.explain(r, dic, translate)
            topic = grammar.topic_for(view.get("kind", ""))
            uk = hints.rule_uk(r.get("rule") or "", r.get("category") or "")
            out.append({**view, "n": n, "uk_rule": uk,
                        "topic": {"id": topic, "title": grammar.TOPICS[topic]["title"]} if topic else None})
        return out

    def grammar_turn(dic: Dictionary, translate, index: int, item: dict, opened: dict) -> dict:
        """A grammar exercise as a chat turn: the exercise as the question, its type as the instruction."""
        ex = grammar.exercise(item)
        result = item.get("result")
        topic = grammar.TOPICS.get(item.get("topic"), {})
        extra = [(t("Rule"), ex.get("why", "")), (t("In Ukrainian"), ex.get("uk", ""))] if result and ex else []
        return {
            "index": index, "kind": "grammar", "prompt": grammar.TYPES.get(ex.get("type"), ""),
            "question": ex.get("prompt", t("This task no longer exists.")), "hint": "",
            "choices": ex.get("choices"), "notice": item.get("notice", ""), "result": result,
            "answer": item.get("answer", ""), "word_label": topic.get("title", ""), "facts": [],
            "segments": correction_segments(item.get("answer", ""), (result or {}).get("remarks"),
                                            lambda word: hints.correction_table(dic, word, translate),
                                            lambda n: f"?fehler={index}-{n}#jetzt", opened.get(index)),
            "task_hint": "", "example": ("Beispiel: " + ex["example"]) if ex.get("example") else "",
            "explanation": None, "ai_note": "", "translations": [],
            "details": details(item, result, [], index) + [(label, text, "") for label, text in extra if text],
            "input": "textarea" if ex.get("type") in ("umbau", "eigen") else "text",
        }

    def explained(user: User, sess: dict, ref: str, dic: Dictionary, translate) -> dict | None:
        """The "Fehler erklärt" pane for ?fehler=<task>-<mistake> (both from the page's own links): the mistake
        in its sentence, the local explanation (hints.explain) and the same rule's mistakes from earlier
        sessions. None for anything that does not name an answered task's mistake."""
        try:
            index, n = (int(x) for x in ref.split("-", 1))
        except ValueError:
            return None
        items = sess["items"]
        if not (0 <= index < len(items)) or "result" not in items[index]:
            return None
        item = items[index]
        remarks = item["result"].get("remarks") or []
        if not 1 <= n <= len(remarks):
            return None
        remark = remarks[n - 1]
        table = lambda w: hints.correction_table(dic, w, translate)
        view = hints.explain(remark, dic, translate)
        similar = []
        for past in store.practice_history(user.id):
            for i, it in enumerate(past["items"]):
                if (past["id"], i) == (sess["id"], index) or not it.get("answer"):
                    continue
                for r in (it.get("result") or {}).get("remarks") or []:
                    same = r.get("rule") and r.get("rule") == remark.get("rule")
                    if same and len(similar) < 3:
                        similar.append({"segments": correction_segments(it["answer"], [r], table),
                                        "text": it["answer"], "date": german_date(past["created_at"])})
        topic = grammar.topic_for(view.get("kind", ""))
        return {**view, "index": index, "n": n, "total": len(remarks),
                "topic": {"id": topic, "title": grammar.TOPICS[topic]["title"]} if topic else None,
                "segments": correction_segments(item.get("answer", ""), [remark], table),
                "ai": item.get("explanation"), "similar": similar}

    def details(item: dict, result: dict | None, facts: list[str], item_index: int = 0) -> list[tuple[str, str, str]]:
        """The feedback's labelled rows under the table: (label, text, href); a label is left empty when it repeats,
        a mistake's label links to its explanation."""
        if not result:
            return []
        rows = []  # the corrected sentence is the answer bubble's green line
        if result.get("verdict") == "wrong" and result.get("expected"):
            rows.append((t("Expected"), result["expected"]))
        # The mistakes themselves are explained one by one in their own sections ("Explain more", mistakes()).
        if result.get("natural") and result["natural"] != result.get("corrected"):
            rows.append((t("More natural"), result["natural"]))
        if result.get("verdict") != "correct":
            rows += [(t("About the word") if i == 0 else "", f) for i, f in enumerate(facts)]
        if item.get("ai_note"):
            rows.append((t("Hint"), item["ai_note"]))
        if ex := item.get("explanation"):
            rows += [(t("Explanation"), f"{ex.get('rule', '')}: {ex.get('explanation', '')}".strip(": ")),
                     (t("Remember"), ex.get("merke", "")), (t("In Ukrainian"), ex.get("explanation_uk", ""))]
        tr = [t for t in (item.get("tr_uk"), item.get("tr_en")) if t]
        if tr:
            rows.append(("Übersetzung", " · ".join(tr)))
        return [(row[0], row[1], row[2] if len(row) > 2 else "") for row in rows if row[1]]

    @app.post("/ueben/s/{sid}/answer")
    def answer(request: Request, sid: int, csrf: str = Form(...), text: str = Form(""), at: int = Form(-1),
               user: User = Depends(current_user)):
        """Answer the current task, or (`at` = the next index, the chat's pinned input) move on and answer that one.
        A stale `at` (a second tab, a resent form) changes nothing."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if pos < len(items) and "result" in items[pos] and at == pos + 1 < len(items):
            pos += 1
        if pos >= len(items) or "result" in items[pos] or at not in (-1, pos):
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        item = items[pos]
        if item["kind"] == "grammar":
            return answer_grammar(user, sid, items, pos, item, text)
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
                                                              rebuild(item, entry)[0], cleaned, graded.verdict,
                                                              details=attempt_details(item, entry, graded, cleaned))
            item["result"] = {**asdict(graded), "delta": delta, "attempt_id": attempt_id}
            item["answer"] = cleaned
            item["ai_note"] = notes[0] if notes else ""
            item.pop("notice", None)
        else:  # nothing to grade yet: show the message, keep the task open, change nothing
            item["notice"] = graded.feedback
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    def answer_grammar(user: User, sid: int, items: list[dict], pos: int, item: dict, text: str):
        """Grade a grammar exercise locally; a graded one counts for its topic's progress (no word score)."""
        try:
            dic = Dictionary(ctx.dict_path)
        except FileNotFoundError:
            dic = None
        verdict, expected, feedback, remarks, corrected, final = grammar.grade(item, text, ctx.checker, dic)
        if final:
            if verdict is not None:
                store.record_grammar(user.id, item["topic"], item["ex"], verdict)
            item["result"] = asdict(Graded(verdict, expected, feedback, corrected, remarks)) | {"delta": None}
            item["answer"] = sanitize.text(text, MAX_ANSWER)
            item.pop("notice", None)
        else:
            item["notice"] = feedback
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    @app.post("/ueben/s/{sid}/explain")
    def explain(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        item = items[pos] if pos < len(items) else None
        res = item.get("result") if item else None
        if not res or res.get("verdict") in (None, "correct") or item["kind"] != "sentence" or "explanation" in item:
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
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
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

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
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
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
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        item["rechecked"] = True
        graded = graded_from_ai(check, required, item.get("answer", ""))
        if graded.verdict != res["verdict"] and res.get("attempt_id"):
            delta = store.revise_attempt(user.id, res["attempt_id"], graded.verdict)
            if delta is not None:
                item["result"] = {**asdict(graded), "delta": delta, "attempt_id": res["attempt_id"]}
                item["ai_note"] = t("The assessment was changed after your objection.")
            else:
                item["ai_note"] = t("The assessment can no longer be changed.")
        else:
            item["ai_note"] = t("The AI keeps its assessment.")
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    @app.post("/ueben/s/{sid}/regel")
    def practise_rule(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        """"Diese Regel üben": a new session of tasks for the rule behind the last mistake."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        item = items[pos] if pos < len(items) else None
        rule = ((item.get("result") or {}).get("rule") or "")[:300] if item else ""
        if not rule or item["kind"] != "sentence":
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        try:  # only the rule's name is sent
            tasks = ai.more_for_rule(user.id, rule, RULE_TASKS)
        except AiUnavailable as e:
            item["ai_note"] = e.reason
            store.save_practice(user.id, sid, items, pos)
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        new = [{"word_id": item["word_id"], "kind": "sentence", "index": 0, "free": True, "ai_prompt": t.prompt,
                "tr_uk": t.translation_uk, "tr_en": t.translation_en} for t in tasks.tasks[:RULE_TASKS]]
        close_open(user, ("regel",))  # the Sätze session it came from stays open
        return RedirectResponse(f"/ueben/s/{store.create_practice(user.id, 'regel', new)}", status_code=303)

    @app.post("/ueben/s/{sid}/frage")
    def other_question(request: Request, sid: int, csrf: str = Form(...), at: int = Form(...),
                       user: User = Depends(current_user)):
        """"Andere Frage": another question for an open sentence task (the current one or, in the chat, the next),
        again one that fits the word, from the session's topic; the task itself stays."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if not (0 <= at < len(items) and at in (pos, pos + 1)):
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        item = items[at]
        if item["kind"] != "sentence" or "result" in item or not question_text(item):
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        word = store.word(user.id, item["word_id"])
        entry = dictionary().find_lemma(word.lemma, word.pos or None) if word else None
        if entry is None:
            raise HTTPException(404, "word is gone")
        avoid = [i.get("question") for i in items if i.get("question")]
        item["question"] = questions.pick_for(questions.topic_or_all(item.get("topic")), entry.glosses,
                                              random.Random(), avoid=avoid)
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    @app.post("/ueben/s/{sid}/again")
    def answer_again(request: Request, sid: int, csrf: str = Form(...), text: str = Form(""), at: int = Form(...),
                     w: int = Form(0), user: User = Depends(current_user)):
        """Answer an answered sentence task (`at`: the current one or an earlier one) once more: graded and corrected
        like the first answer, kept as the next attempt under it. Only the first answer counts: a retry records no
        attempt and changes no score."""
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if not (0 <= at <= pos < len(items)) or not can_retry(items[at]):
            return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)
        item = items[at]
        word = store.word(user.id, item["word_id"])
        entry = dictionary().find_lemma(word.lemma, word.pos or None) if word else None
        if entry is None:
            raise HTTPException(404, "word is gone")
        notes: list[str] = []
        graded = grade_item(item, entry, text, ctx.checker, ai, user.id, notes)
        if not graded.final:  # nothing to grade (e.g. empty): stay in the retry composer, change nothing
            return RedirectResponse(f"/ueben/s/{sid}?a={at}{f'&w={w}' if w else ''}&nochmal=1#jetzt", status_code=303)
        item.setdefault("retries", []).append({
            "answer": sanitize.text(text, MAX_ANSWER),
            "result": {**asdict(graded), "delta": None, "attempt_id": None},
            "ai_note": notes[0] if notes else "",
        })
        store.save_practice(user.id, sid, items, pos)
        return RedirectResponse(f"/ueben/s/{sid}?a={at}{f'&w={w}' if w else ''}#jetzt", status_code=303)

    @app.post("/ueben/s/{sid}/next")
    def advance(request: Request, sid: int, csrf: str = Form(...), user: User = Depends(current_user)):
        ctx.verify_csrf(request, csrf)
        sess = get_session(user, sid)
        items, pos = sess["items"], sess["pos"]
        if pos < len(items) and "result" in items[pos]:
            store.save_practice(user.id, sid, items, pos + 1)
        return RedirectResponse(f"/ueben/s/{sid}#jetzt", status_code=303)

    def step_verdict(item: dict) -> str:
        """How a task went, for its step in the session header: correct | almost | wrong | tip | skipped | none."""
        res = item.get("result")
        if not res:
            return "none"
        if res.get("skipped"):
            return "skipped"
        if res.get("verdict") in ("correct", "almost", "wrong"):
            return res["verdict"]
        return "tip" if res.get("tip") else "none"

    def summary(user: User, items: list[dict]) -> list[dict]:
        rows = []
        for it in items:
            res = it.get("result") or {}
            if it["kind"] == "grammar":  # the exercise instead of a word; grammar has no word score
                rows.append({"label": grammar.exercise(it).get("prompt", "?"), "verdict": res.get("verdict"),
                             "delta": 0, "score": None})
                continue
            w = store.word(user.id, it["word_id"])
            verdict = ("skipped" if res.get("skipped") else
                       "tip" if res.get("tip") and res.get("verdict") is None else res.get("verdict"))
            rows.append({"label": w.lemma if w else "?", "verdict": verdict,
                         "delta": res.get("delta") or 0,
                         "score": w.score if w else None})
        return rows
