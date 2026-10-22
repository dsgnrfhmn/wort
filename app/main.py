"""FastAPI app: history, favorites, sentence exercise. Run: uvicorn app.main:app --host <LAN ip>."""

from __future__ import annotations

import hmac
import os
import random
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from wort import paths, sanitize
from wort.dictionary.lookup import Dictionary
from wort.exercises import grammar_check
from wort.exercises.sentence import targets

from app import auth, ds, lexicon, practice, words
from app.ai import config as ai_config
from app.ai import service as ai_service
from types import SimpleNamespace
from app.checking import Checker, check_sentence
from app.db import User, WebStore
from app.importer import import_export

STATIC = Path(__file__).parent / "static"
CSRF_COOKIE = "wort_csrf"
FLASH_COOKIE = "wort_flash"  # a server-set message for the next page: never reflected from a URL
MAX_FLASH = 200


class LoginRequired(Exception):
    """Raised by the user dependency; the handler redirects to /login."""


def create_app(
    db_path: Path | None = None,
    dict_path: Path | None = None,
    checker: Checker | None = None,
    secure_cookies: bool | None = None,
    throttle: auth.LoginThrottle | None = None,
    ai: ai_service.AiService | None = None,
) -> FastAPI:
    sanitize.install_log_redaction()
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
        flash = request.cookies.get(FLASH_COOKIE)
        if flash and not ctx.get("message"):
            ctx["message"] = sanitize.text(unquote(flash), MAX_FLASH)
        response = templates.TemplateResponse(request, name, {"csrf": token, **ctx}, status_code=status)
        response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict", secure=secure_cookies)
        if flash:
            response.delete_cookie(FLASH_COOKIE)
        return response

    def redirect(url: str, message: str = "") -> RedirectResponse:
        """303 to an in-app path, with an optional one-time message set by the server (not a query string)."""
        response = RedirectResponse(url, status_code=303)
        if message:
            response.set_cookie(FLASH_COOKIE, quote(sanitize.text(message, MAX_FLASH)), max_age=60, httponly=True,
                                samesite="strict", secure=secure_cookies)
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
        name = sanitize.text(name, auth.MAX_FIELD)
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

    shared = SimpleNamespace(
        store=store, render=render, verify_csrf=verify_csrf, current_user=current_user, dict_path=dictionary_path,
        redirect=redirect, facts=lexicon.summary, checker=check,
        ai=ai or ai_service.build(ai_config.load(), store),
    )
    @app.get("/texte", response_class=HTMLResponse)
    def texts(request: Request, user: User = Depends(current_user)):
        return render(request, "texts.html", user=user, page="texts")

    words.register(app, shared)
    practice.register(app, shared)

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request, limit: int = 100, user: User = Depends(current_user)):
        limit = max(1, min(limit, 1000))
        all_rows = store.history(user.id)
        try:
            dic = Dictionary(dictionary_path)
        except FileNotFoundError:
            dic = None
        owned = {(w.lemma.casefold(), w.pos) for w in store.words(user.id)}
        rows = []
        for r in all_rows[:limit]:
            entry = words.resolve_query(dic, r.query) if dic and r.found else None
            rows.append({"row": r, "entry": entry,
                         "learned": bool(entry) and (entry.lemma.casefold(), entry.pos) in owned})
        return render(request, "history.html", rows=rows, total=len(all_rows), limit=limit, user=user,
                      has_dictionary=dic is not None)

    @app.post("/import")
    async def import_history(request: Request, csrf: str = Form(...), file: UploadFile = File(...),
                             user: User = Depends(current_user)):
        verify_csrf(request, csrf)
        raw = await file.read(20 * 1024 * 1024 + 1)
        try:
            result = import_export(store, user.id, raw)
        except ValueError as e:
            return render(request, "history.html", 400, rows=store.history(user.id), user=user,
                          message=f"Import failed: {sanitize.text(str(e), 150)}", message_status="error")
        msg = (f"Imported {result.queries_new} new of {result.queries_total} queries, "
               f"{result.words_new} new of {result.words_total} words.")
        if result.words_total == 0:
            return redirect("/history", msg + " Der Export enthält nur den Verlauf: füge Wörter hier mit „Lernen“ hinzu.")
        return redirect("/", msg)

    @app.post("/favorites/toggle")
    def toggle(request: Request, csrf: str = Form(...), lemma: str = Form(...), pos: str = Form(""), next: str = Form("/history"),
               user: User = Depends(current_user)):
        verify_csrf(request, csrf)
        try:
            lemma = sanitize.word(lemma, 100)
            pos = sanitize.word(pos, 100) if pos.strip() else ""
        except sanitize.Unsafe:
            raise HTTPException(400, "invalid word") from None
        store.toggle_favorite(user.id, lemma, pos)
        return RedirectResponse(next if next in ("/history", "/favorites") else "/history", status_code=303)

    @app.get("/favorites", response_class=HTMLResponse)
    def favorites(request: Request, user: User = Depends(current_user)):
        return render(request, "favorites.html", favorites=store.favorites(user.id), user=user)

    def exercise_context(lemma: str, pos: str, index: int | None):
        try:
            lemma = sanitize.word(lemma, 100)
            pos = sanitize.word(pos, 100) if pos.strip() else ""
        except sanitize.Unsafe:
            raise HTTPException(400, "invalid word") from None
        entry = lexicon.find_entry(dictionary(), lemma, pos)
        if entry is None or not (opts := targets(entry)):
            raise HTTPException(404, "no dictionary entry with exercises for this word")
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
        result = check_sentence(sanitize.text(sentence, 400), required, check)
        return render(request, "exercise.html", entry=entry, pos=pos, index=index, task=task, gloss=gloss,
                      sentence=sentence, result=result, summary=lexicon.summary(entry), user=user)

    return app



