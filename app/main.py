"""FastAPI app: history, favorites, sentence exercise. Run: uvicorn app.main:app --host <LAN ip>."""

from __future__ import annotations

import hmac
import os
import random
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from wort import paths, sanitize
from wort.dictionary.lookup import Dictionary
from wort.exercises import grammar_check
from wort.exercises.sentence import targets

from app import auth, ds, i18n, lexicon, practice, ui_terms, words
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
    uk_path: Path | None = None,
    uk_en_path: Path | None = None,
    de_path: Path | None = None,
    cli_db: Path | None = None,
) -> FastAPI:
    sanitize.install_log_redaction()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    db_file = db_path or paths.data_dir() / "web.db"
    app.state.db_path = db_file
    store = WebStore(db_file)
    dictionary_path = dict_path or paths.dictionary_db()
    check = checker or grammar_check.check
    templates = Jinja2Templates(env=ds.make_env())
    templates.env.globals["ui_glossary"] = ui_terms.glossary()
    templates.env.globals["_"] = i18n.t
    templates.env.globals["ui_langs"] = i18n.LANGS
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
    if not secure_cookies:
        @app.middleware("http")
        async def loopback_only(request: Request, call_next):
            """Without Secure cookies (plain-http dev) the session and password would cross the network in clear
            text, so the app then answers loopback clients only: a run on a LAN address with
            WORT_INSECURE_COOKIES=1 fails loudly instead of working insecurely."""
            if not (request.client and auth.is_loopback(request.client.host)):
                return PlainTextResponse(
                    "WORT_INSECURE_COOKIES=1 serves 127.0.0.1 / ::1 only. For the LAN use scripts/dev.sh (https).",
                    status_code=403)
            return await call_next(request)

    @app.middleware("http")
    async def interface_language(request: Request, call_next):
        """The signed-in user's interface language for this request (app/i18n.py); English without a session."""
        token = request.cookies.get(auth.SESSION_COOKIE, "")
        i18n.use((store.lang_for_session(auth.token_hash(token)) if token else None) or i18n.DEFAULT)
        return await call_next(request)

    @app.middleware("http")
    async def revalidate_assets(request: Request, call_next):
        """CSS/JS/fonts carry no version in their URL, so the browser must ask before reusing a cached copy
        (a 304 via ETag when unchanged); without this it may run a stale app.js after a change."""
        response = await call_next(request)
        if request.url.path.startswith(("/static/", "/ds/")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    for part in ("tokens", "components", "icons"):
        app.mount(f"/ds/{part}", StaticFiles(directory=ds.DS_ROOT / part), name=f"ds-{part}")
    # The self-hosted display face and the staged hero-block (dis-system local-components, not yet confirmed).
    app.mount("/ds/fonts", StaticFiles(directory=ds.DS_ROOT / "fonts"), name="ds-fonts")
    app.mount("/ds/local-components/hero-block", StaticFiles(directory=ds.DS_ROOT / "local-components" / "hero-block"),
              name="ds-hero-block")

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
        response = templates.TemplateResponse(request, name, {"csrf": token, "lang": i18n.current(), **ctx},
                                              status_code=status)
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

    @app.post("/settings/lang")
    def set_language(request: Request, csrf: str = Form(...), lang: str = Form(...), next: str = Form("/"),
                     user: User = Depends(current_user)):
        """The header's language dropdown: store the interface language in the profile, back to the same page."""
        verify_csrf(request, csrf)
        if lang not in i18n.LANGS:
            raise HTTPException(400, "unknown language")
        store.set_ui_lang(user.id, lang)
        parts = urlsplit(next)
        local = not parts.scheme and not parts.netloc and next.startswith("/") and next.isprintable() and "\\" not in next
        back = next if local and len(next) <= 500 else "/"
        return RedirectResponse(back, status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html", user=None)

    @app.post("/login")
    def login(request: Request, csrf: str = Form(...), name: str = Form(""), password: str = Form("")):
        verify_csrf(request, csrf)
        name = sanitize.text(name, auth.MAX_FIELD)
        key = name.casefold()
        if throttle.blocked(key):
            return render(request, "login.html", 429, user=None, error=i18n.t("Too many attempts. Try again in a few minutes."))
        found = store.user_by_name(name)
        if not auth.verify_password(found[1] if found else None, password) or not found:
            throttle.fail(key)
            return render(request, "login.html", 401, user=None, error=i18n.t("Wrong name or password."))
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
        uk_path=uk_path or paths.dictionary_uk_db(), uk_en_path=uk_en_path or paths.dictionary_en_uk_db(),
        de_path=de_path or paths.dictionary_de_db(),
        # Dev only (DECISIONS D00g): the CLI's own user.db on this machine, for "Gesuchte laden". Unset on the server.
        cli_db=cli_db or (Path(os.environ["WORT_CLI_DB"]) if os.environ.get("WORT_CLI_DB") else None),
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
                          message=i18n.t("Import failed: {error}", error=sanitize.text(str(e), 150)), message_status="error")
        msg = i18n.t("Imported {q_new} new of {q_total} queries, {w_new} new of {w_total} words.",
                     q_new=result.queries_new, q_total=result.queries_total, w_new=result.words_new,
                     w_total=result.words_total)
        if result.words_total == 0:
            return redirect("/history", msg + " " + i18n.t("The export holds only the history: add words here with “Learn”."))
        return redirect("/", msg)

    @app.post("/import/cli")
    def import_cli(request: Request, csrf: str = Form(...), user: User = Depends(current_user)):
        """"Gesuchte laden" (dev only, DECISIONS D00g): the CLI's user.db on this machine, opened read-only and
        copied into memory, goes through the same export → import as an uploaded file (same caps and checks)."""
        import json
        import sqlite3

        from wort.store import Store
        from wort.transfer import export_words

        verify_csrf(request, csrf)
        source = shared.cli_db
        if source is None:
            raise HTTPException(404, "WORT_CLI_DB is not set")
        if not source.is_file():
            return redirect("/", i18n.t("CLI database not found: {path}", path=sanitize.text(str(source), 150)))
        ro = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        copy = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            ro.backup(copy)  # the CLI's file is never written: Store would create its schema on open
        finally:
            ro.close()
        cli = Store.__new__(Store)
        cli.conn = copy
        cli.conn.row_factory = sqlite3.Row
        try:
            result = import_export(store, user.id, json.dumps(export_words(cli)).encode())
        except ValueError as e:
            return redirect("/", i18n.t("Loading failed: {error}", error=sanitize.text(str(e), 150)))
        finally:
            copy.close()
        return redirect("/", i18n.t("Loaded from the CLI: {q_new} new of {q_total} searches, {w_new} new of {w_total} words.",
                                    q_new=result.queries_new, q_total=result.queries_total, w_new=result.words_new,
                                    w_total=result.words_total))

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



