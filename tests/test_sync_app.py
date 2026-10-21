import json

import pytest
from fastapi.testclient import TestClient
from wort.transfer import FORMAT_VERSION

from app import auth
from app.db import WebStore
from app.sync_app import TOKEN_PREFIX, create_sync_app, hash_token


def doc(words=(("Haus", "noun"),), queries=()):
    return json.dumps({
        "format_version": FORMAT_VERSION, "exported_at": "2026-10-21T10:00:00",
        "words": [{"lemma": w, "pos": p, "added_at": "2026-10-01T10:00:00"} for w, p in words],
        "queries": [{"query": q, "found": True, "queried_at": "2026-10-02T10:00:00"} for q in queries],
    }).encode()


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "web.db"
    store = WebStore(db)
    a, b = store.create_user("anna", "h").id, store.create_user("ben", "h").id
    ta, tb = TOKEN_PREFIX + "a" * 40, TOKEN_PREFIX + "b" * 40
    store.create_sync_token(a, hash_token(ta), "laptop")
    store.create_sync_token(b, hash_token(tb), "laptop")
    return TestClient(create_sync_app(db)), store, (a, b), (ta, tb)


def push(c, token, body, **kw):
    return c.post("/sync", content=body, headers={"Authorization": f"Bearer {token}"} if token else {}, **kw)


def test_valid_token_imports_words_for_its_user_only(env):
    c, store, (a, b), (ta, tb) = env
    r = push(c, ta, doc(queries=["Haus"]))
    assert r.status_code == 200 and r.json() == {"queries_total": 1, "queries_new": 1, "words_total": 1, "words_new": 1}
    assert [w.lemma for w in store.words(a)] == ["Haus"] and store.words(b) == []
    assert push(c, ta, doc()).json()["words_new"] == 0  # idempotent
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("token", [None, "", "x", "wsync_" + "z" * 40, "Bearer", TOKEN_PREFIX + "a" * 500])
def test_bad_tokens_get_the_same_401(env, token):
    c, store, (a, _), _ = env
    r = push(c, token, doc())
    assert r.status_code == 401 and r.json() == {"error": "unauthorized"} and store.words(a) == []


def test_revoked_token_stops_working(env):
    c, store, (a, _), (ta, _) = env
    assert push(c, ta, doc()).status_code == 200
    assert store.revoke_sync_token(a, store.sync_tokens(a)[0]["id"])
    assert push(c, ta, doc()).status_code == 401


def test_token_checked_before_the_body_is_read(env):
    c, store, *_ = env
    r = push(c, "wsync_" + "q" * 40, b"x" * (21 * 1024 * 1024))
    assert r.status_code == 401


def test_oversized_and_malformed_bodies_are_rejected_and_write_nothing(env):
    c, store, (a, _), (ta, _) = env
    assert push(c, ta, b"x" * (21 * 1024 * 1024)).status_code == 413
    for bad in (b"not json", b"[]", json.dumps({"format_version": 99}).encode(), b'{"format_version": 2, "words": [{"lemma": 1}], "queries": []}'):
        r = push(c, ta, bad)
        assert r.status_code == 400 and "error" in r.json()
    assert store.words(a) == []


def test_word_limit_per_user(env, monkeypatch):
    c, store, (a, _), (ta, _) = env
    monkeypatch.setattr("app.importer.MAX_WORDS_PER_USER", 2)
    assert push(c, ta, doc(words=[("Haus", "noun"), ("Hund", "noun")])).status_code == 200
    r = push(c, ta, doc(words=[("Katze", "noun")]))
    assert r.status_code == 400 and "limit" in r.json()["error"]


def test_rate_limit_applies_per_user(tmp_path):
    db = tmp_path / "w.db"
    store = WebStore(db)
    a, b = store.create_user("a", "h").id, store.create_user("b", "h").id
    ta, tb = TOKEN_PREFIX + "a" * 40, TOKEN_PREFIX + "b" * 40
    store.create_sync_token(a, hash_token(ta)); store.create_sync_token(b, hash_token(tb))
    c = TestClient(create_sync_app(db, auth.LoginThrottle(limit=2, window=60)))
    assert [push(c, ta, doc()).status_code for _ in range(3)] == [200, 200, 429]
    assert push(c, tb, doc()).status_code == 200


def test_only_post_sync_exists(env):
    c, *_ = env
    for method, path in [("get", "/"), ("get", "/sync"), ("post", "/login"), ("get", "/docs"), ("get", "/openapi.json"),
                         ("post", "/import"), ("get", "/history")]:
        assert getattr(c, method)(path).status_code in (404, 405), (method, path)


def test_session_cookie_or_password_do_not_work_as_credentials(env):
    c, store, (a, _), _ = env
    assert c.post("/sync", content=doc(), headers={"Cookie": "wort_session=abc"}).status_code == 401
    assert push(c, "correct horse battery", doc()).status_code == 401
