"""Texte, the user's saved texts (app/texts.py): the pages, the popups, saving, and the way into the word list. The photo
pipeline (upload, recognition, translation preview) is tested in tests/test_web_ocr.py."""

import re
from datetime import datetime
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import auth, texts
from app import words as word_list
from app.db import WebStore
from app.main import create_app

pytestmark = pytest.mark.english_ui
PASSWORD = "correct horse battery"
BODY = ("Das Haus ist schön. Wir gehen zum Zorp.\n\n"
        "Das Haus ist alt und die Katze schläft. Der Hund bellt.")


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
def small(env):
    """One saved text built from words of the test dictionary (Haus, gehen, Katze, Hund) and one that is not in it (Zorp)."""
    _, store, uid = env
    return store.add_text(uid, "Testtext", BODY, 98, now=datetime(2026, 10, 21, 9, 30))


def tokens(html: str) -> dict[str, list[tuple[str, str]]]:
    """The words a reader can click on a page: {word as written: [(ref, state), ...]}."""
    found: dict[str, list[tuple[str, str]]] = {}
    for m in re.finditer(r'<span class="ds-word-token" data-state="(\w+)" tabindex="0"[^>]*?data-ref="(\d+-\d+)"[^>]*>([^<]+)</span>', html):
        found.setdefault(m.group(3), []).append((m.group(2), m.group(1)))
    return found


def _post(c, path, **fields):
    return c.post(path, data={"csrf": c.cookies.get("wort_csrf"), **fields})


def test_every_page_needs_a_session(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    for path in ("/texte", "/texte/1", "/texte/neu", "/texte/1/bearbeiten"):
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login", path
    c.get("/login")
    for path in ("/texte/neu", "/texte/neu/speichern", "/texte/1/speichern", "/texte/neu/uebersetzung", "/texte/1/wort",
                 "/texte/1/auswahl", "/texte/1/uebersetzung", "/texte/1/loeschen"):
        r = c.post(path, data={"csrf": c.cookies.get("wort_csrf"), "title": "x", "text": "x"})
        assert r.status_code == 303 and r.headers["location"] == "/login", path


def test_the_page_without_texts_offers_the_upload(client):
    html = client.get("/texte").text
    assert "No text selected" in html and "Upload photo" in html and "Paste text" in html
    assert 'class="ds-split wort-texts"' in html and 'wort-notes-title' not in html and "Testtext" not in html
    # the upload popup is on every page, closed; its file field is named, takes JPG and PNG only, and the form is multipart
    assert 'id="wort-texts-upload"' in html and 'hidden' in html.split('id="wort-texts-upload"')[1].split(">")[0]
    assert re.search(r'<input class="ds-dropzone__input" type="file" id="wort-upload-file" name="photo" accept="image/jpeg,image/png" required', html)
    assert 'enctype="multipart/form-data"' in html and "HEIC" not in html
    assert "data-autoopen" not in html and 'id="wort-texts-check"' not in html


def test_the_sidebar_lists_the_users_own_texts_newest_first_and_nobody_elses(env, small):
    c, store, uid = env
    store.add_text(uid, "Zweiter", "Ein Hund.", None, now=datetime(2026, 10, 25))
    other = store.create_user("ben", auth.hash_password(PASSWORD)).id
    store.add_text(other, "Bens Text", "Ein Haus.", 90)
    html = c.get("/texte").text
    assert html.index("Zweiter") < html.index("Testtext") and "Bens Text" not in html
    assert 'href="/texte/1"' in html and 'href="/texte/2"' in html
    assert "October 21, 2026 · 0 notes" in html and "October 25, 2026 · 0 notes" in html  # in the interface language


def test_a_text_shows_its_words_and_empty_notes(env, small):
    c, store, uid = env
    html = c.get("/texte/1").text
    words = tokens(html)
    assert len(words) >= 12
    # every word of the text can be clicked; a click names its place, and no two words share one
    for word in ("Das", "Haus", "schön", "Zorp", "Katze", "Hund", "bellt"):
        assert word in words, word
    assert len({ref for refs in words.values() for ref, _ in refs}) == sum(len(r) for r in words.values())
    assert "click a word or select text" in html and 'class="ds-note-item"' not in html and "0 total" in html
    # nothing is in the (empty) word list, so no word is marked as known
    assert '<span class="ds-word-token" data-state="known" tabindex="0"' not in html and ">in list<" not in html
    assert 'id="wort-selection-menu"' in html and 'id="wort-selection-translation"' in html and "Translating …" in html
    assert 'class="ds-context-menu__note" role="note"' in html and 'name="csrf"' in html and 'data-text-id="1"' in html
    assert "October 21, 2026 · recognized 98 %" in html
    assert "Edit text" in html and 'href="/texte/1/bearbeiten"' in html
    assert "Show original" not in html  # the photo is not kept
    assert not re.search(r"</span>\s+[.,]", html) and "</span>. <span" in html  # no line break of the component before a full stop


def test_no_button_is_marked_as_the_current_page(env, small):
    """The page variable of the open text must not be called "current": dis-system's text-button reads that name and would
    mark every button of the page (Cancel, Delete, Edit text ...) with aria-current="page"."""
    c, *_ = env
    for path in ("/texte/1", "/texte/1/bearbeiten", "/texte", "/texte/neu"):
        assert not re.search(r"<button[^>]*aria-current", c.get(path).text), path


def test_a_text_that_did_not_come_from_a_photo_has_no_recognition_percent(env):
    c, store, uid = env
    store.add_text(uid, "Eingetippt", "Ein Hund.", None, now=datetime(2026, 10, 21))
    html = c.get("/texte/1").text
    assert "October 21, 2026" in html and "recognized" not in html


def test_another_users_text_is_not_found_for_every_route(env):
    c, store, uid = env
    other = store.create_user("ben", auth.hash_password(PASSWORD)).id
    theirs = store.add_text(other, "Bens Text", "Das Haus ist alt.", 90)
    assert c.get(f"/texte/{theirs}").status_code == 404 and c.get(f"/texte/{theirs}/bearbeiten").status_code == 404
    for path, fields in ((f"/texte/{theirs}/speichern", {"text": "Gestohlen."}), (f"/texte/{theirs}/loeschen", {}),
                         (f"/texte/{theirs}/wort", {"ref": "0-0"}),
                         (f"/texte/{theirs}/auswahl", {"text": "Das Haus"}), (f"/texte/{theirs}/uebersetzung", {"text": "Das Haus"})):
        assert _post(c, path, **fields).status_code == 404, path
    assert store.text(other, theirs).body == "Das Haus ist alt." and not store.words(uid)  # and nothing of it was deleted
    assert c.get("/texte/99").status_code == 404 and c.get("/texte/99/bearbeiten").status_code == 404


def test_the_url_can_ask_for_a_popup_and_closing_it_goes_back(env, small):
    c, *_ = env
    html = c.get("/texte/neu").text
    assert 'data-popup-open="wort-texts-upload" data-autoopen data-close-href="/texte"' in html
    assert 'href="/texte">' in html.split('id="wort-texts-upload"')[1]  # "Cancel" is a link here
    html = c.get("/texte/1/bearbeiten").text
    assert 'data-popup-open="wort-texts-check" data-autoopen data-close-href="/texte/1"' in html
    assert "Edit text — Testtext" in html and "ds-stepper" not in html.split('id="wort-texts-check"')[1]
    check = html.split('id="wort-texts-check"')[1]
    assert 'action="/texte/1/speichern"' in check and 'name="title"' not in check  # the title stays
    assert "Das Haus ist schön. Wir gehen zum Zorp." in html and "Katze schläft" in html  # the saved text, in the field to correct
    assert 'data-backdrop="static"' in html  # a stray click must not lose the corrections


# --- saving ---------------------------------------------------------------------------------------------------------

def test_saving_after_a_photo_stores_the_text_under_the_title_and_opens_it(env):
    c, store, uid = env
    assert c.post("/texte/neu/speichern", data={"csrf": "forged", "text": "x"}).status_code == 403 and not store.texts(uid)
    r = _post(c, "/texte/neu/speichern", title="Brief <b>vom</b> Amt", recognized="87",
              text="Sehr geehrte Damen und Herren,\r\n\r\n\r\nbitte  reichen Sie\nSie ein.  <script>x</script>")
    assert r.status_code == 303 and r.headers["location"] == "/texte/1"
    assert "Text saved." in unquote(r.headers["set-cookie"])
    saved = store.text(uid, 1)
    assert saved.title == "Brief <b>vom</b> Amt" and saved.recognized == 87 and saved.notes == 0
    # paragraphs kept apart by one blank line, lines of a paragraph made one, everything stored as data
    assert saved.body == "Sehr geehrte Damen und Herren,\n\nbitte reichen Sie Sie ein. <script>x</script>"
    html = c.get("/texte/1").text
    assert "&lt;b&gt;vom&lt;/b&gt;" in html and "<b>vom" not in html and "<script>x" not in html  # escaped when it is shown
    assert "recognized 87 %" in html


def test_a_title_that_is_missing_becomes_untitled_and_a_bad_percent_is_not_stored(env):
    c, store, uid = env
    _post(c, "/texte/neu/speichern", title="  ", recognized="abc", text="Ein Hund.")
    _post(c, "/texte/neu/speichern", title="x", recognized="150", text="Ein Hund.")
    _post(c, "/texte/neu/speichern", title="y", recognized="", text="Ein Hund.")
    rows = sorted(store.texts(uid), key=lambda r: r.id)
    assert [(r.title, r.recognized) for r in rows] == [("Untitled", None), ("x", None), ("y", None)]


def test_a_save_that_cannot_be_done_goes_back_to_the_check_step_with_the_text_and_says_why(env, monkeypatch):
    c, store, uid = env
    empty = _post(c, "/texte/neu/speichern", title="Leer", recognized="80", text="  \n \n ")
    assert empty.status_code == 400 and "The text is empty." in empty.text and 'data-flash="error"' in empty.text
    assert 'data-popup-open="wort-texts-check" data-autoopen' in empty.text and "Check text — Leer" in empty.text
    long = _post(c, "/texte/neu/speichern", title="Lang", recognized="80", text="Haus " * (texts.MAX_TEXT // 5 + 10))
    assert long.status_code == 400 and f"at most {texts.MAX_TEXT} characters" in long.text and "Haus Haus Haus" in long.text  # kept
    monkeypatch.setattr(texts, "MAX_TEXTS", 2)
    assert _post(c, "/texte/neu/speichern", title="a", text="Ein Hund.").status_code == 303
    assert _post(c, "/texte/neu/speichern", title="b", text="Ein Hund.").status_code == 303
    full = _post(c, "/texte/neu/speichern", title="c", text="Der Hund bellt.")
    assert full.status_code == 400 and "at most 2 texts" in full.text and "Der Hund bellt." in full.text
    assert len(store.texts(uid)) == 2


def test_editing_replaces_the_text_and_keeps_the_title(env, small):
    c, store, uid = env
    assert c.post("/texte/1/speichern", data={"csrf": "forged", "text": "x"}).status_code == 403
    r = _post(c, "/texte/1/speichern", text="Das Haus ist neu.\n\nDie Katze schläft.", title="Anders")
    assert r.status_code == 303 and r.headers["location"] == "/texte/1" and "Text saved." in unquote(r.headers["set-cookie"])
    row = store.text(uid, 1)
    assert (row.title, row.body, row.recognized) == ("Testtext", "Das Haus ist neu.\n\nDie Katze schläft.", 98)
    assert "neu" in tokens(c.get("/texte/1").text) and len(store.texts(uid)) == 1  # the page reads the new text
    bad = _post(c, "/texte/1/speichern", text="   ")
    assert bad.status_code == 400 and "The text is empty." in bad.text and "Edit text — Testtext" in bad.text
    assert store.text(uid, 1).body == "Das Haus ist neu.\n\nDie Katze schläft."  # nothing was lost


def test_the_texts_are_in_german_with_the_german_interface(env, small):
    c, *_ = env
    csrf = c.cookies.get("wort_csrf")
    c.post("/settings/lang", data={"csrf": csrf, "lang": "de", "next": "/texte"})
    html = c.get("/texte").text
    assert "Foto hochladen" in html and "Text einfügen" in html and "21. Oktober 2026 · 0 Notizen" in html
    html = c.get("/texte/1").text
    assert "21. Oktober 2026 · erkannt 98 %" in html and "Klick: zur Wortliste" in html and "0 gesamt" in html
    assert "Wörter, die du aus diesem Text hinzufügst" in html and "Zur Wortliste hinzufügen" in html


# --- deleting -------------------------------------------------------------------------------------------------------

def test_an_open_text_offers_the_delete_with_a_confirmation_and_the_empty_page_does_not(env, small):
    c, *_ = env
    html = c.get("/texte/1").text
    assert 'data-popup-open="wort-text-delete"' in html and ">Delete text<" in html
    popup = html.split('id="wort-text-delete"')[1].split("</section>")[0] if 'id="wort-text-delete"' in html else ""
    assert "Delete this text?" in html and "“Testtext” and its notes are deleted" in html and "stay in your word list" in html
    assert 'action="/texte/1/loeschen"' in html and 'form="wort-text-delete-form"' in html  # the popup's "Delete" submits the form
    assert 'name="csrf"' in html.split('id="wort-text-delete-form"')[1].split("</form>")[0]
    assert popup is not None
    empty = c.get("/texte").text
    assert "wort-text-delete" not in empty and "loeschen" not in empty


def test_deleting_removes_the_text_and_its_notes_but_not_the_words(env, small):
    c, store, uid = env
    store.add_text(uid, "Zweiter", "Der Hund bellt.", None)
    _post(c, "/texte/1/wort", ref=tokens(c.get("/texte/1").text)["Haus"][0][0])
    _post(c, "/texte/1/auswahl", text="Das Haus ist schön")
    assert store.text_notes(uid, 1) == [("Haus", "noun"), ("Das Haus ist schön", "phrase")]
    assert c.post("/texte/1/loeschen", data={"csrf": "forged"}).status_code == 403 and store.text(uid, 1)
    r = _post(c, "/texte/1/loeschen")
    assert r.status_code == 303 and r.headers["location"] == "/texte"
    assert "“Testtext” was deleted." in unquote(r.headers["set-cookie"])
    assert store.text(uid, 1) is None and [x.title for x in store.texts(uid)] == ["Zweiter"]
    assert store.conn.execute("SELECT COUNT(*) FROM text_words").fetchone()[0] == 0  # its links went with it
    assert sorted(w.lemma for w in store.words(uid)) == ["Das Haus ist schön", "Haus"]  # the words are still the user's
    assert c.get("/texte/1").status_code == 404 and c.get("/texte/1/bearbeiten").status_code == 404
    page = c.get("/texte").text
    assert 'href="/texte/1"' not in page and "Zweiter" in page  # gone from the sidebar ...
    assert "“Testtext” was deleted." in page  # ... and the next page says so once
    assert _post(c, "/texte/1/loeschen").status_code == 404  # twice is a 404, not a second deletion
    assert [x.title for x in store.texts(uid)] == ["Zweiter"]


def test_the_confirmation_is_in_german_with_the_german_interface(env, small):
    c, *_ = env
    c.post("/settings/lang", data={"csrf": c.cookies.get("wort_csrf"), "lang": "de", "next": "/texte"})
    html = c.get("/texte/1").text
    assert "Text löschen" in html and "Diesen Text löschen?" in html and "„Testtext“ und seine Notizen werden gelöscht" in html
    r = _post(c, "/texte/1/loeschen")
    assert "„Testtext“ wurde gelöscht." in unquote(r.headers["set-cookie"])


# --- into the word list ---------------------------------------------------------------------------------------------

def test_a_click_on_any_word_adds_its_lemma_notes_it_and_the_page_then_shows_it_as_known(env, small):
    c, store, uid = env
    words = tokens(c.get("/texte/1").text)
    first, second = (ref for ref, _ in words["Haus"])  # the word twice in the text: both places are clickable
    assert not store.words(uid)
    r = _post(c, "/texte/1/wort", ref=second)
    data = r.json()
    assert r.status_code == 200 and data["status"] == "added" and data["message"] == "“das Haus” is now in your words."
    word = store.words(uid)[0]
    assert (word.lemma, word.pos, word.added_from) == ("Haus", "noun", "text")
    assert set(data["refs"]) == {first, second} and "notes" not in data  # every place of the entry
    html = c.get("/texte/1").text
    assert [state for _, state in tokens(html)["Haus"]] == ["known", "known"]
    assert html.count('class="ds-note-item"') == 1 and ">in list<" in html and "1 total" in html and "das Haus" in html
    assert "October 21, 2026 · 1 note" in html and "1 notes" not in html  # the sidebar counts it
    assert _post(c, "/texte/1/wort", ref=first).json()["status"] == "exists"  # a second click adds nothing
    assert len(store.words(uid)) == 1 and store.text_notes(uid, 1) == [("Haus", "noun")]


def test_a_word_the_user_already_had_is_noted_for_this_text_too(env, small):
    c, store, uid = env
    store.add_word(uid, "Katze", "noun", added_from="lookup")  # from the lookup, not from a text
    katze = tokens(c.get("/texte/1").text)["Katze"][0][0]
    assert _post(c, "/texte/1/wort", ref=katze).json()["status"] == "exists"
    assert store.text_notes(uid, 1) == [("Katze", "noun")] and "die Katze" in c.get("/texte/1").text
    assert store.words(uid)[0].added_from == "lookup"  # where it came from does not change


def test_notes_are_per_text_and_follow_the_word_list(env, small):
    c, store, uid = env
    second = store.add_text(uid, "Zweiter", "Der Hund bellt.", None)
    _post(c, "/texte/1/wort", ref=tokens(c.get("/texte/1").text)["Haus"][0][0])
    _post(c, f"/texte/{second}/wort", ref=tokens(c.get(f"/texte/{second}").text)["Hund"][0][0])
    assert store.text_notes(uid, 1) == [("Haus", "noun")] and store.text_notes(uid, second) == [("Hund", "noun")]
    page = c.get("/texte/1").text
    assert "das Haus" in page and "der Hund" not in page.split('id="wort-notes-title"')[1]  # only this text's words
    # a word taken out of the word list is no longer a note, and is not a "known" word in the text either
    store.delete_word(uid, next(w.id for w in store.words(uid) if w.lemma == "Haus"))
    page = c.get("/texte/1").text
    assert "0 total" in page and [s for _, s in tokens(page)["Haus"]] == ["none", "none"]


def test_an_inflected_or_capitalised_word_finds_its_lemma_and_one_that_is_unknown_is_refused(env, small):
    c, store, uid = env
    words = tokens(c.get("/texte/1").text)
    data = _post(c, "/texte/1/wort", ref=words["Zorp"][0][0]).json()  # not in the dictionary
    assert data["status"] == "missing" and data["message"] == "This word is not in the dictionary." and not store.words(uid)
    assert not store.text_notes(uid, 1)
    assert _post(c, "/texte/1/wort", ref=words["ist"][0][0]).json()["status"] == "missing"  # a plain word, not in the dictionary
    assert _post(c, "/texte/1/wort", ref=words["Katze"][0][0]).json()["message"] == "“die Katze” is now in your words."
    hund = _post(c, "/texte/1/auswahl", text="Hund").json()  # (a lower-case or inflected form would find the same entry)
    assert hund["message"] == "“der Hund” is now in your words."


def test_a_forged_place_or_token_is_rejected(env, small):
    c, store, uid = env
    expanded = texts.expand(texts.paragraphs_of(BODY))
    spaces = [f"{pi}-{si}" for pi, p in enumerate(expanded) for si, seg in enumerate(p) if isinstance(seg, str)]
    for bad in (spaces[0], "0-99", "9-1", "x", "-1-1", "0-1; DROP", "0-1-1", ""):  # a gap between words, no such place, not a ref
        assert _post(c, "/texte/1/wort", ref=bad).status_code == 400, bad
    assert _post(c, "/texte/1/wort", note="0").status_code == 400  # the old notes buttons are gone
    assert _post(c, "/texte/9/wort", ref="0-0").status_code == 404
    assert c.post("/texte/1/wort", data={"csrf": "forged", "ref": "0-0"}).status_code == 403 and not store.words(uid)


def test_a_selected_phrase_is_added_as_a_phrase_noted_and_only_if_it_is_from_the_text(env, small):
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
    page = c.get("/texte/1").text
    assert page.count('class="ds-note-item"') == 2 and "Das Haus ist schön" in page.split('id="wort-notes-title"')[1]  # a phrase is a note


def test_a_selected_single_word_is_added_as_a_word_not_a_phrase(env, small):
    c, store, uid = env
    data = _post(c, "/texte/1/auswahl", text="schön.").json()  # the full stop that came with the selection is not part of the word
    assert data["status"] == "added" and data["message"] == "“schön” is now in your words."
    assert _post(c, "/texte/1/auswahl", text="haus").json()["message"] == "“das Haus” is now in your words."  # its own capitals
    assert [(w.lemma, w.pos) for w in store.words(uid)] == [("Haus", "noun"), ("schön", "adj")]
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
    assert not store.words(uid) and not store.text_notes(uid, 1)  # a translation adds nothing


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
    assert "Words in your list: 1" in c.get("/ueben?neu=1").text  # the phrase is not counted as a word to practise


# --- the stored texts themselves ------------------------------------------------------------------------------------

def test_the_store_keeps_texts_per_user_and_links_only_words_of_the_owner(tmp_path):
    store = WebStore(tmp_path / "web.db")
    anna = store.create_user("anna", "x").id
    ben = store.create_user("ben", "x").id
    text = store.add_text(anna, "T", "Das Haus.", 90, now=datetime(2026, 10, 21))
    assert store.text(anna, text).body == "Das Haus." and store.text(ben, text) is None
    assert store.text_count(anna) == 1 and store.text_count(ben) == 0
    assert not store.update_text(ben, text, "x", "gestohlen") and store.text(anna, text).body == "Das Haus."
    store.add_word(anna, "Haus", "noun")
    store.add_word(ben, "Haus", "noun")
    store.link_text_word(ben, text, "Haus", "noun")  # Ben cannot note a word in Anna's text
    assert store.text_notes(anna, text) == [] and store.text(anna, text).notes == 0
    store.link_text_word(anna, text, "Haus", "noun")
    store.link_text_word(anna, text, "Haus", "noun")  # twice is once
    store.link_text_word(anna, text, "Gone", "noun")  # not in her list: not a note
    assert store.text_notes(anna, text) == [("Haus", "noun")] and store.text(anna, text).notes == 1
    assert store.update_text(anna, text, "T2", "Das Haus ist alt.")
    assert (store.text(anna, text).title, store.text(anna, text).body) == ("T2", "Das Haus ist alt.")
    assert not store.delete_text(ben, text) and store.text(anna, text)  # not Ben's to delete
    assert store.delete_text(anna, text) and store.text(anna, text) is None and not store.delete_text(anna, text)
    assert store.conn.execute("SELECT COUNT(*) FROM text_words").fetchone()[0] == 0 and store.words(anna)  # the links go, the words stay
    text = store.add_text(anna, "T3", "Das Haus.")
    store.link_text_word(anna, text, "Haus", "noun")
    store.conn.execute("DELETE FROM users WHERE id = ?", (anna,))  # a user's texts and links go with the user
    store.conn.commit()
    assert store.conn.execute("SELECT COUNT(*) FROM texts").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM text_words").fetchone()[0] == 0


def test_the_page_has_one_heading_and_its_actions_are_buttons_beside_the_text(env, small):
    c, *_ = env
    page = c.get(f"/texte/{small}").text
    assert page.count("<h1") == 1 and ">Testtext</h1>" in page  # the open text names the page
    reader = page.split('class="wort-texts__reader"')[1].split('class="wort-texts__notes"')[0]
    assert f'class="wort-btn wort-btn--secondary" href="/texte/{small}/bearbeiten">Edit text</a>' in reader
    assert 'data-popup-open="wort-text-delete"' in reader and "Delete text" in reader  # both in the text's own pane, none in its head
    assert "ds-pane__action" not in reader
    empty = c.get("/texte").text
    assert empty.count("<h1") == 1 and ">Texts</h1>" in empty


def test_a_phone_gets_the_saved_texts_as_one_row_that_opens_and_the_upload_stays_in_sight(env, small):
    c, store, uid = env
    store.add_text(uid, "Zweiter", "Ein Hund.", None, now=datetime(2026, 10, 25))
    page = c.get(f"/texte/{small}").text
    mobile = page.split('class="wort-texts-m"')[1].split('class="wort-texts__side"')[0]
    assert "Upload photo" in mobile and 'data-popup-open="wort-texts-upload"' in mobile
    assert mobile.count('class="wort-words-m__row wort-texts-m__row"') == 2 and f'href="/texte/{small}" aria-current="page"' in mobile
    assert "<details" in mobile and "<details class=\"wort-words-m\" open" not in mobile  # folded while a text is open
    start = c.get("/texte").text.split('class="wort-texts-m"')[1].split('class="wort-texts__side"')[0]
    assert '<details class="wort-words-m" open>' in start  # open while none is


def test_what_is_not_connected_yet_is_muted_and_still_says_so(env, small):
    c, *_ = env
    empty = c.get("/texte").text
    assert re.search(r'<button[^>]*data-demo[^>]*aria-disabled="true"[^>]*>Paste text</button>', empty)
    assert not re.search(r'<button[^>]*data-popup-open="wort-texts-upload"[^>]*aria-disabled', empty)  # the real upload is not muted
