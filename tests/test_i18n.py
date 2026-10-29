import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth, i18n, practice
from app.db import WebStore
from app.main import create_app

pytestmark = pytest.mark.english_ui
ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "correct horse battery"


def _texts() -> set[str]:
    """Every literal text the code passes to _() (templates) or t() (Python)."""
    found = set()
    for path in (ROOT / "app" / "templates").glob("*.html"):
        found |= set(re.findall(r"""\b_\('((?:[^'\\]|\\.)*)'""", path.read_text()))
    for path in (ROOT / "app").rglob("*.py"):
        found |= set(re.findall(r'''\b(?:i18n\.)?t\("((?:[^"\\]|\\.)*)"''', path.read_text()))
    return found | set(practice.KINDS.values()) | set(practice.ABFRAGE_MODES.values()) | {"Not found. Did you mean:"}


def test_every_interface_text_has_a_german_translation():
    texts = _texts()
    assert len(texts) > 150
    missing = sorted(x for x in texts if x not in i18n.DE)
    assert not missing, missing
    for en, de in i18n.DE.items():  # the same placeholders on both sides
        assert set(re.findall(r"{(\w+)}", en)) == set(re.findall(r"{(\w+)}", de)), en


def test_t_falls_back_to_english_and_fills_values_as_data():
    assert i18n.t("Words") == "Words"
    token = i18n._lang.set("de")
    try:
        assert i18n.t("Words") == "Wörter" and i18n.t("not in the catalog") == "not in the catalog"
        assert i18n.t("Hint: {text}", text="{x} <b>") == "Hinweis: {x} <b>"  # a value is not a format string
    finally:
        i18n._lang.reset(token)


@pytest.fixture
def client(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    assert 'lang="en"' in c.get("/login").text and ">Sign in<" in c.get("/login").text
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": PASSWORD})
    return c, store, uid


def test_the_interface_is_english_by_default_and_the_exercises_stay_german(client):
    c, store, uid = client
    html = c.get("/").text
    assert 'lang="en"' in html and ">Words<" in html and ">Practice<" in html and ">Wörter<" not in html
    assert 'id="wort-glossary"' not in html  # the EN/UK tooltips for German labels: German interface only
    assert ">English<" in html and 'data-value="de"' in html  # the language switch in the nav bar
    r = c.post("/ueben/saetze", data={"csrf": c.cookies.get("wort_csrf"), "ids": [store.words(uid)[0].id]})
    loc = r.headers["location"].split("#")[0]
    html = c.get(loc).text
    assert ">Build sentences<" in html and "Your answer" in html
    assert "Schreibe einen Satz mit «Haus»" in html  # the task itself stays German
    c.post(loc + "/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Das Haus ist sehr groß hier", "at": 0})
    html = c.get(loc).text
    assert ">Feedback<" in html and ">richtig<" in html  # verdicts stay German


def test_the_language_is_stored_in_the_profile_and_switches_the_whole_interface(client):
    c, store, uid = client
    csrf = c.cookies.get("wort_csrf")
    r = c.post("/settings/lang", data={"csrf": csrf, "lang": "de", "next": "/history?limit=5"})
    assert r.status_code == 303 and r.headers["location"] == "/history?limit=5"
    assert store.lang_for_session(auth.token_hash(c.cookies.get(auth.SESSION_COOKIE))) == "de"
    html = c.get("/").text
    assert 'lang="de"' in html and ">Wörter<" in html and ">Üben<" in html and 'id="wort-glossary"' in html
    assert ">Deutsch<" in html
    # only a local path comes back; an unknown language or a forged token changes nothing
    for bad in ("//evil.example/x", "https://evil.example/", "/\\evil", "/a\nb"):
        assert c.post("/settings/lang", data={"csrf": csrf, "lang": "en", "next": bad}).headers["location"] == "/"
    assert c.post("/settings/lang", data={"csrf": csrf, "lang": "xx", "next": "/"}).status_code == 400
    assert c.post("/settings/lang", data={"csrf": "forged", "lang": "de", "next": "/"}).status_code == 403
    assert 'lang="en"' in c.get("/").text  # the last valid choice was English


def test_switching_needs_a_session(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    c.get("/login")
    r = c.post("/settings/lang", data={"csrf": c.cookies.get("wort_csrf"), "lang": "de", "next": "/"})
    assert r.status_code == 303 and r.headers["location"] == "/login"
