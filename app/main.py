"""FastAPI app: history, favorites, sentence exercise. Run: uvicorn app.main:app --host <LAN ip>."""

from __future__ import annotations

import hmac
import os
import random
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from wort import paths
from wort.dictionary.lookup import Dictionary
from wort.exercises import grammar_check
from wort.exercises.sentence import targets

from app import auth, ds, lexicon
from app.checking import Checker, check_sentence
from app.db import User, WebStore
from app.importer import import_export

STATIC = Path(__file__).parent / "static"
CSRF_COOKIE = "wort_csrf"


class LoginRequired(Exception):
    """Raised by the user dependency; the handler redirects to /login."""


def create_app(
    db_path: Path | None = None,
    dict_path: Path | None = None,
    checker: Checker | None = None,
    secure_cookies: bool | None = None,
    throttle: auth.LoginThrottle | None = None,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    db_file = db_path or paths.data_dir() / "web.db"
    app.state.db_path = db_file
    store = WebStore(db_file)
    dictionary_path = dict_path or paths.dictionary_db()
    check = checker or grammar_check.check
    templates = Jinja2Templates(env=ds.make_env())
    if secure_cookies is None:  # behind the TLS front; WORT_INSECURE_COOKIES=1 only for plain-http dev
        secure_cookies = os.environ.get("WORT_INSECURE_COOKIES") != "1"
    throttle = throttle or auth.LoginThrottle()

    @app.exception_handler(LoginRequired)
    def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse("/login", status_code=303)

    def current_user(request: Request) -> User:
        token = request.cookies.get(auth.SESSION_COOKIE, "")
        user = store.user_for_session(auth.token_hash(token), datetime.now()) if token else None
        if user is None:
            raise LoginRequired()
        return user
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
        response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict", secure=secure_cookies)
        return response

    def verify_csrf(request: Request, token: str) -> None:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not hmac.compare_digest(cookie, token):
            raise HTTPException(403, "invalid CSRF token")

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html", user=None)

    @app.post("/login")
    def login(request: Request, csrf: str = Form(...), name: str = Form(""), password: str = Form("")):
        verify_csrf(request, csrf)
        name = name.strip()[: auth.MAX_FIELD]
        key = name.casefold()
        if throttle.blocked(key):
            return render(request, "login.html", 429, user=None, error="Too many attempts. Try again in a few minutes.")
        found = store.user_by_name(name)
        if not auth.verify_password(found[1] if found else None, password) or not found:
            throttle.fail(key)
            return render(request, "login.html", 401, user=None, error="Wrong name or password.")
        throttle.reset(key)
        token, now = auth.new_token(), datetime.now()
        store.create_session(found[0].id, auth.token_hash(token), now, auth.session_expiry(now))
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                            samesite="strict", secure=secure_cookies)
        return response

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form(...), user: User = Depends(current_user)):
        verify_csrf(request, csrf)
        store.delete_session(auth.token_hash(request.cookies.get(auth.SESSION_COOKIE, "")))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(auth.SESSION_COOKIE)
        return response

    @app.get("/", response_class=HTMLResponse)
    def history(request: Request, message: str = "", user: User = Depends(current_user)):
        return render(request, "history.html", rows=store.history(user.id), message=message, user=user)

    @app.post("/import")
    async def import_history(request: Request, csrf: str = Form(...), file: UploadFile = File(...),
                             user: User = Depends(current_user)):
        verify_csrf(request, csrf)
        raw = await file.read(20 * 1024 * 1024 + 1)
        try:
            result = import_export(store, user.id, raw)
        except ValueError as e:
            return render(request, "history.html", 400, rows=store.history(user.id), user=user,
                          message=f"Import failed: {e}", message_status="error")
        msg = (f"Imported {result.queries_new} new of {result.queries_total} queries, "
               f"{result.words_new} new of {result.words_total} words.")
        return RedirectResponse(f"/?message={quote(msg)}", status_code=303)

    @app.post("/favorites/toggle")
    def toggle(request: Request, csrf: str = Form(...), lemma: str = Form(...), pos: str = Form(""), next: str = Form("/"),
               user: User = Depends(current_user)):
        verify_csrf(request, csrf)
        lemma, pos = lemma.strip(), pos.strip()
        if not lemma or len(lemma) > 100 or len(pos) > 100:
            raise HTTPException(400, "invalid word")
        store.toggle_favorite(user.id, lemma, pos)
        return RedirectResponse(next if next in ("/", "/favorites") else "/", status_code=303)

    @app.get("/favorites", response_class=HTMLResponse)
    def favorites(request: Request, user: User = Depends(current_user)):
        return render(request, "favorites.html", favorites=store.favorites(user.id), user=user)

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
    def exercise(request: Request, lemma: str, pos: str = "", user: User = Depends(current_user)):
        entry, index, task, _, gloss = exercise_context(lemma, pos, None)
        return render(request, "exercise.html", entry=entry, pos=pos, index=index, task=task, gloss=gloss,
                      sentence="", result=None, summary=[], user=user)

    @app.post("/exercise/{lemma}", response_class=HTMLResponse)
    def exercise_check(request: Request, lemma: str, csrf: str = Form(...), pos: str = Form(""),
                       index: int = Form(...), sentence: str = Form(""),
                       user: User = Depends(current_user)):
        verify_csrf(request, csrf)
        entry, index, task, required, gloss = exercise_context(lemma, pos, index)
        result = check_sentence(sentence, required, check)
        return render(request, "exercise.html", entry=entry, pos=pos, index=index, task=task, gloss=gloss,
                      sentence=sentence, result=result, summary=lexicon.summary(entry), user=user)

    return app



