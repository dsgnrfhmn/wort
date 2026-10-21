import json
import socket
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import auth, practice
from app.ai import config as cfg
from app.ai import schemas, service
from app.ai.anthropic_provider import explain_payload, sentence_payload
from app.ai.fake import FakeProvider
from app.ai.limits import DailyLimit, LimitReached
from app.db import WebStore
from app.main import create_app
from wort.dictionary.lookup import Dictionary

PASSWORD = "correct horse battery"


def test_disabled_by_default_and_key_required_when_enabled():
    c = cfg.load({})
    assert c.enabled is False and c.model == "claude-haiku-5-5" and c.daily_cap == 50
    with pytest.raises(ValueError):
        cfg.load({"WORT_AI_ENABLED": "1"})
    on = cfg.load({"WORT_AI_ENABLED": "1", "ANTHROPIC_API_KEY": "sk-secret"})
    assert on.enabled and "sk-secret" not in repr(on)
    with pytest.raises(ValueError):
        cfg.load({"WORT_AI_DAILY_CAP": "0"})


def test_disabled_build_never_imports_the_anthropic_provider(tmp_path):
    import sys
    sys.modules.pop("app.ai.anthropic_provider", None)
    store = WebStore(tmp_path / "w.db")
    svc = service.build(cfg.load({}), store)
    assert svc.available is False and "app.ai.anthropic_provider" not in sys.modules
    with pytest.raises(service.AiUnavailable):
        svc.check_sentence(1, "Ich sehe Häuser", ["Häuser"], "Plural")


GOOD = {"errors": [{"wrong": "ein", "right": "einen", "kind": "Artikel"}],
        "word_results": [{"word": "Antrag", "ok": False, "note": "Akkusativ"}],
        "rule": "Artikel im Akkusativ", "natural": "Ich stelle einen Antrag.", "corrected": "Ich stelle einen Antrag."}


def test_schema_accepts_good_and_fenced_json():
    assert schemas.parse(schemas.SentenceCheck, json.dumps(GOOD)).rule == "Artikel im Akkusativ"
    assert schemas.parse(schemas.SentenceCheck, "```json\n" + json.dumps(GOOD) + "\n```").errors[0].right == "einen"


@pytest.mark.parametrize("bad", [
    "not json", "[]", json.dumps({**GOOD, "extra": 1}), json.dumps({**GOOD, "rule": "x" * 301}),
    json.dumps({k: v for k, v in GOOD.items() if k != "errors"}),
    json.dumps({**GOOD, "errors": [{"wrong": "a", "right": "b", "kind": "k"}] * 21}),
])
def test_schema_rejects_malformed_and_oversized(bad):
    with pytest.raises(schemas.AiInvalid) as e:
        schemas.parse(schemas.SentenceCheck, bad)
    assert "x" * 50 not in str(e.value)  # no model text in the error


def test_request_payload_has_only_allowed_fields():
    p = sentence_payload("Ich stelle ein Antrag", ["Antrag"], "Akkusativ")
    assert set(p) == {"request", "sentence", "words", "task", "schema"}
    chk = schemas.parse(schemas.SentenceCheck, json.dumps(GOOD))
    assert set(explain_payload("S", chk)) == {"request", "sentence", "errors", "rule", "schema"}


def test_daily_limit_per_user_and_day(tmp_path):
    store = WebStore(tmp_path / "w.db")
    a, b = store.create_user("a", "h").id, store.create_user("b", "h").id
    lim = DailyLimit(store, 2)
    now = datetime(2026, 10, 21, 10)
    lim.take(a, now); lim.take(a, now)
    with pytest.raises(LimitReached):
        lim.take(a, now)
    lim.take(b, now)
    lim.take(a, datetime(2026, 10, 22, 10))  # new day


def test_service_turns_failures_and_invalid_replies_into_unavailable(tmp_path):
    store = WebStore(tmp_path / "w.db")
    uid = store.create_user("a", "h").id
    on = cfg.AiConfig(enabled=True, api_key="k", daily_cap=5)
    svc = service.build(on, store, FakeProvider(fail=True))
    with pytest.raises(service.AiUnavailable) as e:
        svc.check_sentence(uid, "Ich sehe Häuser dort", ["Häuser"], "Plural")
    assert "nicht erreichbar" in e.value.reason
    assert store.ai_calls_today(uid, datetime.now().date().isoformat()) == 1  # failed calls count


@pytest.fixture
def env(tmp_path, dict_path):
    db = tmp_path / "web.db"
    store = WebStore(db)
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    fake = FakeProvider()
    svc = service.build(cfg.AiConfig(enabled=True, api_key="k", daily_cap=2), store, fake)
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False, checker=lambda s: [], ai=svc)
    c = TestClient(app, follow_redirects=False)
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": PASSWORD})
    return c, store, uid, fake


def session(c, store, uid):
    r = c.post("/ueben/saetze", data={"csrf": c.cookies.get("wort_csrf"), "ids": [w.id for w in store.words(uid)]})
    return r.headers["location"], int(r.headers["location"].rsplit("/", 1)[1])


def required_for(store, uid, sid, dict_path):
    item = store.practice(uid, sid)["items"][store.practice(uid, sid)["pos"]]
    return practice.rebuild(item, Dictionary(dict_path).find_lemma("Haus", "noun"))[4]


def test_sentence_graded_by_provider_and_explained_on_click(env, dict_path):
    c, store, uid, fake = env
    loc, sid = session(c, store, uid)
    req = required_for(store, uid, sid, dict_path)
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"),
                                           "text": "Das FEHLER " + " ".join(req) + " dort"})
    assert [n for n, _ in fake.calls] == ["check_sentence"]
    sent = fake.calls[0][1]
    assert sent[1] == req and "Haus" not in str(sent[0])  # only sentence, forms, task
    page = c.get(loc).text
    assert "Fehler erklären" in page and "Prüfung: KI" in page
    c.post(f"/ueben/s/{sid}/explain", data={"csrf": c.cookies.get("wort_csrf")})
    assert [n for n, _ in fake.calls] == ["check_sentence", "explain"]
    assert "Merke dir das." in c.get(loc).text
    c.post(f"/ueben/s/{sid}/explain", data={"csrf": c.cookies.get("wort_csrf")})
    assert len(fake.calls) == 2  # no second call for the same explanation


def test_missing_form_is_decided_locally_without_an_api_call(env):
    c, store, uid, fake = env
    loc, sid = session(c, store, uid)
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Das ist ein Satz hier"})
    assert fake.calls == []
    assert "Die verlangte Form fehlt" in c.get(loc).text


def test_cap_reached_falls_back_to_local_check_and_says_so(env, dict_path):
    c, store, uid, fake = env
    store.ai_count_call(uid, datetime.now().date().isoformat()); store.ai_count_call(uid, datetime.now().date().isoformat())
    loc, sid = session(c, store, uid)
    req = required_for(store, uid, sid, dict_path)
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe " + " ".join(req) + " dort"})
    assert fake.calls == []
    assert "Tageslimit" in c.get(loc).text


def test_ai_off_makes_no_network_connection_during_a_session(tmp_path, dict_path, monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network access attempted")

    db = tmp_path / "w.db"
    store = WebStore(db)
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    monkeypatch.delenv("WORT_AI_ENABLED", raising=False)
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    c = TestClient(app, follow_redirects=False)  # TestClient talks to the ASGI app in-process
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": PASSWORD})
    loc, sid = session(c, store, uid)
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe die Häuser dort"})
    assert c.get(loc).status_code == 200
