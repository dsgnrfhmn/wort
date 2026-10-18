"""FastAPI app: history, favorites, sentence exercise. Run: uvicorn app.main:app --host <LAN ip>."""

from __future__ import annotations

import hmac
import random
import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from wort import paths
from wort.dictionary.lookup import Dictionary
from wort.exercises import grammar_check
from wort.exercises.sentence import targets

from app import ds, lexicon
from app.checking import Checker, check_sentence
from app.db import WebStore
from app.importer import import_export

STATIC = Path(__file__).parent / "static"
CSRF_COOKIE = "wort_csrf"


def create_app(
    db_path: Path | None = None,
    dict_path: Path | None = None,
    checker: Checker | None = None,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = WebStore(db_path or paths.data_dir() / "web.db")
    dictionary_path = dict_path or paths.dictionary_db()
    check = checker or grammar_check.check
    templates = Jinja2Templates(env=ds.make_env())
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    for part in ("tokens", "components", "icons"):
        app.mount(f"/ds/{part}", StaticFiles(directory=ds.DS_ROOT / part), name=f"ds-{part}")

    def dictionary() -> Dictionary:
        try:
            return Dictionary(dictionary_path)
        except FileNotFoundError:
            raise HTTPException(503, "dictionary.db not found; build it with the CLI importer") from None

    def render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
        token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        response = templates.TemplateResponse(request, name, {"csrf": token, **ctx}, status_code=status)
        response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict")
        return response

    def verify_csrf(request: Request, token: str) -> None:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not hmac.compare_digest(cookie, token):
            raise HTTPException(403, "invalid CSRF token")

    @app.get("/", response_class=HTMLResponse)
    def history(request: Request, message: str = ""):
        return render(request, "history.html", rows=store.history(), message=message)

    @app.post("/import")
    async def import_history(request: Request, csrf: str = Form(...), file: UploadFile = File(...)):
        verify_csrf(request, csrf)
        raw = await file.read(20 * 1024 * 1024 + 1)
        try:
            result = import_export(store, raw)
        except ValueError as e:
            return render(request, "history.html", 400, rows=store.history(), message=f"Import failed: {e}", message_status="error")
        msg = f"Imported {result.queries_new} new of {result.queries_total} queries."
        return RedirectResponse(f"/?message={quote(msg)}", status_code=303)

    @app.post("/favorites/toggle")
    def toggle(request: Request, csrf: str = Form(...), lemma: str = Form(...), pos: str = Form(""), next: str = Form("/")):
        verify_csrf(request, csrf)
        lemma, pos = lemma.strip(), pos.strip()
        if not lemma or len(lemma) > 100 or len(pos) > 100:
            raise HTTPException(400, "invalid word")
        store.toggle_favorite(lemma, pos)
        return RedirectResponse(next if next in ("/", "/favorites") else "/", status_code=303)

    @app.get("/favorites", response_class=HTMLResponse)
    def favorites(request: Request):
        return render(request, "favorites.html", favorites=store.favorites())

    def exercise_context(lemma: str, pos: str, index: int | None):
        entry = lexicon.find_entry(dictionary(), lemma, pos)
        if entry is None or not (opts := targets(entry)):
            raise HTTPException(404, f"no dictionary entry with exercises for «{lemma}»")
        if index is None:
            index = random.randrange(len(opts))
        if not 0 <= index < len(opts):
            raise HTTPException(400, "invalid task")
        task, required = opts[index]
        gloss = entry.glosses[0] if entry.glosses else ""
        return entry, index, task, required, gloss

    @app.get("/exercise/{lemma}", response_class=HTMLResponse)
    def exercise(request: Request, lemma: str, pos: str = ""):
        entry, index, task, _, gloss = exercise_context(lemma, pos, None)
        return render(request, "exercise.html", entry=entry, pos=pos, index=index, task=task, gloss=gloss,
                      sentence="", result=None, summary=[])

    @app.post("/exercise/{lemma}", response_class=HTMLResponse)
    def exercise_check(request: Request, lemma: str, csrf: str = Form(...), pos: str = Form(""),
                       index: int = Form(...), sentence: str = Form("")):
        verify_csrf(request, csrf)
        entry, index, task, required, gloss = exercise_context(lemma, pos, index)
        result = check_sentence(sentence, required, check)
        return render(request, "exercise.html", entry=entry, pos=pos, index=index, task=task, gloss=gloss,
                      sentence=sentence, result=result, summary=lexicon.summary(entry))

    return app



