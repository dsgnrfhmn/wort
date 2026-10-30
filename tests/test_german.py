import json

from fastapi.testclient import TestClient

from app import auth
from app.db import WebStore
from app.main import create_app
from wort.dictionary import german

RAWS = [
    {"lang_code": "de", "word": "Haus", "pos": "noun", "senses": [
        {"glosses": ["Gebäude, das Menschen zum Wohnen dient"]},
        {"glosses": ["<script>alert(1)</script>Familie, Haushalt"]},
        {"glosses": ["Gebäude, das Menschen zum Wohnen dient"]},  # duplicate sense
        {"glosses": ["Theater"]}, {"glosses": ["vierter Sinn, über dem Limit"]}]},
    {"lang_code": "de", "word": "Häuser", "pos": "noun", "senses": [
        {"glosses": ["Nominativ Plural des Substantivs Haus"], "form_of": [{"word": "Haus"}]}]},
    {"lang_code": "en", "word": "house", "pos": "noun", "senses": [{"glosses": ["Gebäude"]}]},
]


def test_import_keeps_up_to_three_german_definitions_and_skips_forms(tmp_path):
    db = tmp_path / "de.db"
    assert german.import_entries(RAWS, db) == 1
    defs = german.GermanDefinitions(db).definitions("Haus", "noun")
    assert len(defs) == 3 and defs[0] == "Gebäude, das Menschen zum Wohnen dient" and defs[2] == "Theater"
    assert german.GermanDefinitions(db).definitions("Häuser") == []


def test_lookup_shows_german_definitions_when_installed(tmp_path, dict_path):
    db = tmp_path / "de.db"
    german.import_entries(RAWS, db)
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, de_path=db)
    WebStore(tmp_path / "web.db").create_user("anna", auth.hash_password("correct horse battery"))
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": "correct horse battery"})
    html = c.get("/?q=Haus").text
    assert '<ol class="wort-definitions" lang="de" aria-label="Bedeutung"><li>Gebäude, das Menschen zum Wohnen dient</li>' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;Familie" in html and "<script>alert(1)" not in html  # data, escaped
    without = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False,
                         de_path=tmp_path / "missing.db")
    c2 = TestClient(without, follow_redirects=False, client=("127.0.0.1", 50000))
    c2.get("/login")
    c2.post("/login", data={"csrf": c2.cookies.get("wort_csrf"), "name": "anna", "password": "correct horse battery"})
    assert "wort-definitions" not in c2.get("/?q=Haus").text  # no file: no block, nothing breaks
