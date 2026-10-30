"""Texte, the UI stage with mock data (app/texts.py): the pages, the popups, the one boundary a form crosses."""

import re
from datetime import date
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import auth, texts
from app import words as word_list
from app.db import WebStore
from app.main import create_app
from app.texts import Card, Note, SavedText, Word

pytestmark = pytest.mark.english_ui
PASSWORD = "correct horse battery"


@pytest.fixture
def env(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": "anna", "password": PASSWORD})
    return c, store, uid


@pytest.fixture
def client(env):
    return env[0]


@pytest.fixture
def small(monkeypatch):
    """One text built from words of the test dictionary (Haus, gehen) and one that is not in it (Zorp)."""
    card = Card("x", "y")
    text = SavedText(1, "Testtext", date(2026, 10, 21), 99,
                     [["Das ", Word("Haus", "noted", card, 0, "Haus", "noun"), " ist ", Word("schön", "none", card, None, "schön", "adj"),
                       ". Wir ", Word("gehen", "none", card, 1, "gehen", "verb"), " zum ", Word("Zorp", "none", card, 2, "Zorp", "noun"), "."],
                      ["Das Haus ist alt und die Katze schläft. Der Hund bellt."]],
                     [Note("das", "Haus", "будинок · house", "", "Haus", "noun"), Note("", "gehen", "іти · to go", "", "gehen", "verb"),
                      Note("der", "Zorp", "?", "", "Zorp", "noun")])
    monkeypatch.setattr(texts, "TEXTS", [text])
    return text


def tokens(html: str) -> dict[str, list[tuple[str, str]]]:
    """The words a reader can click on a page: {word as written: [(ref, state), ...]}."""
    found: dict[str, list[tuple[str, str]]] = {}
    for m in re.finditer(r'<span class="ds-word-token" data-state="(\w+)" tabindex="0"[^>]*?data-ref="(\d+-\d+)"[^>]*>([^<]+)</span>', html):
        found.setdefault(m.group(3), []).append((m.group(2), m.group(1)))
    return found


def test_every_page_needs_a_session(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    for path in ("/texte", "/texte/1", "/texte/neu", "/texte/1/bearbeiten"):
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login", path
    c.get("/login")
    for path in ("/texte/neu", "/texte/neu/speichern"):
        r = c.post(path, data={"csrf": c.cookies.get("wort_csrf"), "title": "x", "text": "x"})
        assert r.status_code == 303 and r.headers["location"] == "/login", path


def test_the_empty_page_lists_the_saved_texts_and_offers_the_upload(client):
    html = client.get("/texte").text
    assert "No text selected" in html and "Upload photo" in html and "Paste text" in html
    for text in texts.TEXTS:
        assert f'href="/texte/{text.id}"' in html and text.title in html
    assert "October 21, 2026 · 4 notes" in html  # the date and the note count follow the interface language
    assert 'class="ds-split wort-texts"' in html and 'id="wort-notes"' not in html
    # the upload popup is on every page, closed; its file input has no name: no photo is sent in this stage
    assert 'id="wort-texts-upload"' in html and 'hidden' in html.split('id="wort-texts-upload"')[1].split(">")[0]
    assert re.search(r'<input class="ds-dropzone__input" type="file" id="wort-upload-file" name=""', html)
    assert "data-autoopen" not in html and 'id="wort-texts-check"' not in html


def test_a_text_shows_its_words_with_cards_and_its_notes(client):
    html = client.get("/texte/1").text
    words = tokens(html)
    assert 'data-state="noted"' in html and len(words) >= 40
    # every word of the text can be clicked, not only the ones the text's author marked up; a click names its place
    for word in ("Sehr", "geehrte", "Damen", "und", "Herren", "fehlenden", "telefonisch", "Online-Portal", "Grüßen", "reichen", "ein"):
        assert word in words, word
    assert len({ref for refs in words.values() for ref, _ in refs}) == sum(len(r) for r in words.values())  # one place each
    assert "подавати (документи)" in html and "Click: add to word list" in html  # the hover card of "reichen" (the author's own)
    assert html.count('class="ds-note-item"') == 4 and "4 total" in html
    assert 'data-article="die"' in html and 'data-add-note="3"' in html and "data-add-all" in html
    # nothing is in the (empty) word list, so no word is marked as known and no note carries the "in list" tag
    assert '<span class="ds-word-token" data-state="known" tabindex="0"' not in html and ">in list<" not in html
    assert 'id="wort-selection-menu"' in html and 'id="wort-selection-translation"' in html and "Translating …" in html
    assert 'class="ds-context-menu__note" role="note"' in html and 'name="csrf"' in html and 'data-text-id="1"' in html
    assert "October 21, 2026 · recognized 98 %" in html
    assert "Edit text" in html and 'href="/texte/1/bearbeiten"' in html
    assert ">Herren</span></span>,</p>" in html and 'role="button" data-ref="0-8"' in html  # the comma stays right behind the last word
    # a word token is followed directly by the full stop: no line break of the component shows as a space
    assert not re.search(r"</span>\s+[.,]", html) and "</span>. <span" in html
    assert client.get("/texte/99").status_code == 404 and client.get("/texte/99/bearbeiten").status_code == 404


def test_the_url_can_ask_for_a_popup_and_closing_it_goes_back(client):
    html = client.get("/texte/neu").text
    assert 'data-popup-open="wort-texts-upload" data-autoopen data-close-href="/texte"' in html
    assert 'href="/texte">' in html.split('id="wort-texts-upload"')[1]  # "Cancel" is a link here
    html = client.get("/texte/2/bearbeiten").text
    assert 'data-popup-open="wort-texts-check" data-autoopen data-close-href="/texte/2"' in html
    assert "Edit text — Mietvertrag, § 3" in html and "ds-stepper" not in html.split('id="wort-texts-check"')[1]
    assert "Der Mieter verpflichtet sich" in html  # the open text, in the field to correct
    assert 'data-backdrop="static"' in html  # a stray click must not lose the corrections


def test_recognising_shows_the_canned_result_and_treats_the_title_as_data(client):
    csrf = client.cookies.get("wort_csrf")
    assert client.post("/texte/neu", data={"csrf": "forged", "title": "x"}).status_code == 403
    html = client.post("/texte/neu", data={"csrf": csrf, "title": "<b>Brief</b> {{ 7 * 7 }}"}).text
    assert "<b>Brief" not in html  # escaped ...
    assert "Check text — &lt;b&gt;Brief&lt;/b&gt; {{ 7 * 7 }}" in html  # ... and never evaluated as a template
    assert 'data-popup-open="wort-texts-check" data-autoopen data-close-href="/texte"' in html
    assert "2 uncertain spots" in html and "Unterlaqen" in html and "Line 4 · 61 % sure" in html
    assert 'data-state="accepted"' in html and "Recognized · 98 %" in html
    assert 'data-kind="uncertain"' in html and 'data-kind="accepted"' in html  # marks on the photo
    assert "ds-stepper" in html.split('id="wort-texts-check"')[1] and 'form="wort-check-form"' in html
    untitled = client.post("/texte/neu", data={"csrf": csrf, "title": "  "}).text
    assert "Check text — Untitled" in untitled


def test_saving_is_a_demo_and_stores_nothing(client):
    csrf = client.cookies.get("wort_csrf")
    assert client.post("/texte/neu/speichern", data={"csrf": "forged", "text": "x"}).status_code == 403
    r = client.post("/texte/neu/speichern", data={"csrf": csrf, "text": "Ein Text."})
    assert r.status_code == 303 and r.headers["location"] == "/texte/1"
    assert "Demo data" in r.headers["set-cookie"] or "Demo%20data" in r.headers["set-cookie"]
    too_long = client.post("/texte/neu/speichern", data={"csrf": csrf, "text": "a" * (texts.MAX_TEXT + 1)})
    assert too_long.status_code == 400


def test_the_texts_are_in_german_with_the_german_interface(client):
    csrf = client.cookies.get("wort_csrf")
    client.post("/settings/lang", data={"csrf": csrf, "lang": "de", "next": "/texte"})
    html = client.get("/texte").text
    assert "Kein Text ausgewählt" in html and "Foto hochladen" in html and "Text einfügen" in html
    assert "21. Oktober 2026 · 4 Notizen" in html
    html = client.get("/texte/1").text
    assert "21. Oktober 2026 · erkannt 98 %" in html and "Klick: zur Wortliste" in html and "4 gesamt" in html
    assert "Zur Liste" in html and "Alle zur Wortliste" in html and "Zur Wortliste hinzufügen" in html


def _post(c, path, **fields):
    return c.post(path, data={"csrf": c.cookies.get("wort_csrf"), **fields})


def test_a_click_on_any_word_adds_its_lemma_and_the_page_then_shows_it_as_known(env, small):
    c, store, uid = env
    words = tokens(c.get("/texte/1").text)
    (curated, _), (plain, _) = words["Haus"]  # the author's own mark-up, and a word of the plain text: both are clickable
    assert "Haus" not in [w.lemma for w in store.words(uid)]
    r = _post(c, "/texte/1/wort", ref=plain)
    data = r.json()
    assert r.status_code == 200 and data["status"] == "added" and data["message"] == "“das Haus” is now in your words."
    word = store.words(uid)[0]
    assert (word.lemma, word.pos, word.added_from) == ("Haus", "noun", "text")
    assert set(data["refs"]) == {curated, plain} and data["notes"] == [0]  # every place of the entry, and its note
    html = c.get("/texte/1").text
    assert [state for _, state in tokens(html)["Haus"]] == ["known", "known"] and ">in list<" in html
    assert _post(c, "/texte/1/wort", ref=curated).json()["status"] == "exists"  # a second click adds nothing
    assert len(store.words(uid)) == 1


def test_an_inflected_or_capitalised_word_finds_its_lemma_and_one_that_is_unknown_is_refused(env, small, monkeypatch):
    c, store, uid = env
    words = tokens(c.get("/texte/1").text)
    zorp = words["Zorp"][0][0]  # marked up by the author, but not in the dictionary
    data = _post(c, "/texte/1/wort", ref=zorp).json()
    assert data["status"] == "missing" and data["message"] == "This word is not in the dictionary." and not store.words(uid)
    assert _post(c, "/texte/1/wort", ref=words["ist"][0][0]).json()["status"] == "missing"  # a plain word, not in the dictionary
    assert _post(c, "/texte/1/wort", ref=words["Katze"][0][0]).json()["message"] == "“die Katze” is now in your words."
    hund = _post(c, "/texte/1/auswahl", text="Hund").json()  # (a lower-case or inflected form would find the same entry)
    assert hund["message"] == "“der Hund” is now in your words."


def test_a_forged_place_or_token_is_rejected(env, small):
    c, store, uid = env
    spaces = [f"{pi}-{si}" for pi, p in enumerate(texts.expand(small.paragraphs)) for si, seg in enumerate(p) if isinstance(seg, str)]
    for bad in (spaces[0], "0-99", "9-1", "x", "-1-1", "0-1; DROP", "0-1-1", ""):  # a gap between words, no such place, not a ref
        assert _post(c, "/texte/1/wort", ref=bad).status_code == 400, bad
    assert _post(c, "/texte/1/wort", note="7").status_code == 400 and _post(c, "/texte/1/wort", note="x").status_code == 400
    assert _post(c, "/texte/9/wort", ref="0-1").status_code == 404
    assert c.post("/texte/1/wort", data={"csrf": "forged", "ref": "0-1"}).status_code == 403 and not store.words(uid)


def test_the_notes_add_one_word_or_all_of_them(env, small):
    c, store, uid = env
    assert _post(c, "/texte/1/wort", note="1").json()["message"] == "“gehen” is now in your words."
    data = _post(c, "/texte/1/wort", note="all").json()
    assert data["message"] == "1 added to your words. · 1 already in your words. · 1 not in the dictionary."
    assert sorted(w.lemma for w in store.words(uid)) == ["Haus", "gehen"] and data["notes"] == [0, 1]
    assert "3 total" in c.get("/texte/1").text and c.get("/texte/1").text.count(">in list<") == 2


def test_a_selected_phrase_is_added_as_a_phrase_and_only_if_it_is_from_the_text(env, small):
    c, store, uid = env
    data = _post(c, "/texte/1/auswahl", text="Das  Haus\nist   schön").json()  # the browser's line breaks and spaces are normalized
    assert data["status"] == "added" and data["message"] == "“Das Haus ist schön” is now in your words as a phrase."
    phrase = store.words(uid)[0]
    assert (phrase.lemma, phrase.pos, phrase.added_from, phrase.is_phrase) == ("Das Haus ist schön", "phrase", "text", True)
    assert _post(c, "/texte/1/auswahl", text="das haus ist schön").json()["status"] == "exists"  # stored as the text has it: once
    assert _post(c, "/texte/1/auswahl", text="Haus ist alt").json()["status"] == "added"  # across paragraphs is fine too
    for bad, why in (("Das Auto ist schön", "not from this text"), ("", "empty"), ("<b>x y</b>", "not from this text"),
                     ("Das " * 200, "too long")):
        assert _post(c, "/texte/1/auswahl", text=bad).status_code == 400, why
    assert "not from this text" in _post(c, "/texte/1/auswahl", text="Das Auto").json()["detail"]
    assert c.post("/texte/1/auswahl", data={"csrf": "forged", "text": "Das Haus"}).status_code == 403
    assert len(store.words(uid)) == 2


def test_a_selected_single_word_is_added_as_a_word_not_a_phrase(env, small):
    c, store, uid = env
    data = _post(c, "/texte/1/auswahl", text="schön.").json()  # the full stop that came with the selection is not part of the word
    assert data["status"] == "added" and data["message"] == "“schön” is now in your words."
    assert _post(c, "/texte/1/auswahl", text="haus").json()["message"] == "“das Haus” is now in your words."  # its own capitals
    assert [(w.lemma, w.pos) for w in store.words(uid)] == [("Haus", "noun"), ("schön", "adj")] and _post(c, "/texte/1/auswahl", text="haus").json()["notes"] == [0]
    assert _post(c, "/texte/1/auswahl", text="Zorp").json()["status"] == "missing"
    assert _post(c, "/texte/1/auswahl", text="Frau").status_code == 400  # a dictionary word, but not in this text


def test_the_selection_menu_gets_a_translation_from_the_local_translator_or_says_there_is_none(env, small, monkeypatch):
    c, store, uid = env
    asked = []
    monkeypatch.setattr(texts.mt, "translate", lambda text, target: asked.append((text, target)) or f"[{target}] {text}")
    data = _post(c, "/texte/1/uebersetzung", text="Das Haus\nist schön").json()
    assert data["kind"] == "phrase" and data["lines"] == ["[uk] Das Haus ist schön", "[en] Das Haus ist schön"]
    assert asked == [("Das Haus ist schön", "uk"), ("Das Haus ist schön", "en")]
    monkeypatch.setattr(texts.mt, "translate", lambda text, target: "en only" if target == "en" else "")  # no Ukrainian model
    assert _post(c, "/texte/1/uebersetzung", text="Das Haus").json()["lines"] == ["en only"]
    monkeypatch.setattr(texts.mt, "translate", lambda text, target: "")  # no translator installed: nothing is made up
    none = _post(c, "/texte/1/uebersetzung", text="Das Haus").json()
    assert none["lines"] == [] and none["message"] == "No translation available here."
    word = _post(c, "/texte/1/uebersetzung", text="Haus").json()  # one word: from the dictionary, no translator involved
    assert word["kind"] == "word" and word["lines"][0] == "das Haus" and len(word["lines"]) == 2
    unknown = _post(c, "/texte/1/uebersetzung", text="Zorp").json()
    assert unknown["lines"] == [] and unknown["message"] == "This word is not in the dictionary."
    for bad in ("Das Auto ist schön", "", "Das " * 200):
        assert _post(c, "/texte/1/uebersetzung", text=bad).status_code == 400
    assert c.post("/texte/1/uebersetzung", data={"csrf": "forged", "text": "Das Haus"}).status_code == 403
    assert not store.words(uid)  # a translation adds nothing


def test_phrases_show_in_the_word_list_without_a_checkbox_and_are_not_practised(env, small):
    c, store, uid = env
    _post(c, "/texte/1/auswahl", text="Das Haus ist schön")
    _post(c, "/texte/1/wort", ref=tokens(c.get("/texte/1").text)["Haus"][0][0])
    phrase = next(w for w in store.words(uid) if w.is_phrase)
    haus = next(w for w in store.words(uid) if not w.is_phrase)
    html = c.get("/").text
    row = re.search(rf'<div class="ds-table-row"[^>]*data-word-id="{phrase.id}"[^>]*>.*?</div>\s*(?=<div class="ds-table-row"|</div>)', html, re.S).group(0)
    assert "data-phrase" in row and "Das Haus ist schön" in row and 'data-type="checkbox-cell"' not in row
    assert 'data-type="checkbox-cell"' in re.search(rf'<div class="ds-table-row"[^>]*data-word-id="{haus.id}".*?</div>\s*</div>', html, re.S).group(0)
    assert c.get(f"/words/{phrase.id}").status_code == 200  # the detail opens without a dictionary entry
    assert word_list.preset_ids(store.words(uid), "latest") == {haus.id}  # the presets leave phrases out
    csrf = c.cookies.get("wort_csrf")
    only = c.post("/ueben/saetze", data={"csrf": csrf, "ids": [phrase.id]})
    assert only.status_code == 303 and only.headers["location"] == "/"
    assert "Phrases cannot be practised yet." in unquote(only.headers["set-cookie"])
    mixed = c.post("/ueben/saetze", data={"csrf": csrf, "ids": [phrase.id, haus.id]})
    assert mixed.status_code == 303 and mixed.headers["location"].startswith("/ueben/s/")
    assert "Phrases are skipped" in unquote(mixed.headers["set-cookie"])
    assert "1 words" in c.get("/ueben?neu=1").text  # the phrase is not counted as a word to practise
