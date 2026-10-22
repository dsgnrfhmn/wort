"""The one network endpoint the CLI may reach: POST /sync, write-only.

A separate ASGI app on its own port with exactly one route, so the CLI's token can never open a page,
read data or log in. The token belongs to one user and is checked before the body is read; the body is
the CLI's export JSON and is handled as untrusted input by `import_export` (size, schema, length caps).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from wort import paths, sanitize

from app import auth
from app.db import WebStore
from app.importer import MAX_BYTES, import_export

TOKEN_PREFIX = "wsync_"
MAX_TOKEN = 200


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bearer(header: str | None) -> str:
    scheme, _, value = (header or "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def create_sync_app(db_path: Path | None = None, throttle: auth.LoginThrottle | None = None) -> FastAPI:
    sanitize.install_log_redaction()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    store = WebStore(db_path or paths.data_dir() / "web.db")
    limiter = throttle or auth.LoginThrottle(limit=20, window=600)  # accepted requests per user per 10 min

    def reply(status: int, body: dict) -> JSONResponse:
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @app.post("/sync")
    async def sync(request: Request):
        token = _bearer(request.headers.get("authorization"))
        user = store.user_for_sync_token(hash_token(token)) if token.startswith(TOKEN_PREFIX) and len(token) <= MAX_TOKEN else None
        if user is None:  # before reading the body; the same answer for every kind of bad token
            return reply(401, {"error": "unauthorized"})
        key = f"user:{user.id}"
        if limiter.blocked(key):
            return reply(429, {"error": "too many syncs, try again later"})
        limiter.fail(key)  # counts every accepted request
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            return reply(413, {"error": "file too large"})
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_BYTES:
                return reply(413, {"error": "file too large"})
        try:
            result = import_export(store, user.id, raw)
        except ValueError as e:
            return reply(400, {"error": sanitize.text(str(e), 200)})
        return reply(200, {"queries_total": result.queries_total, "queries_new": result.queries_new,
                           "words_total": result.words_total, "words_new": result.words_new})

    return app
