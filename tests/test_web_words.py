from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import WebStore
from app.main import create_app

PASSWORD = "correct horse battery"
NOW = datetime(2026, 10, 21, 12, 0)


@pytest.fixture
def env(tmp_path, dict_path):
    db = tmp_path / "web.db"
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False)
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    b = store.create_user("ben", auth.hash_password(PASSWORD)).id
    return app, store, a, b


def client_for(app, name):
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    c.get("/login")
    r = c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": name, "password": PASSWORD})
    assert r.status_code == 303
    return c


def test_list_shows_article_translation_and_score(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    store.record_attempt(a, wid, "form", "article", "p", "das", "correct", now=NOW)
    html = client_for(app, "anna").get("/").text
    assert "das Haus" in html and f'data-word-id="{wid}"' in html and f'href="/words/{wid}?' in html
    assert "1 Wörter" in html


def test_empty_list_has_explicit_state(env):
    app, *_ = env
    assert "Noch keine Wörter" in client_for(app, "anna").get("/").text


def test_bulk_buttons_disabled_until_selection_and_presets_preselect(env):
    app, store, a, _ = env
    for i, lemma in enumerate(["Haus", "Hund", "Katze"]):
        store.add_word(a, lemma, "noun", now=NOW.replace(hour=i))
    c = client_for(app, "anna")
    plain = c.get("/").text
    assert 'data-status="disabled"' in plain and 'data-selected="true"' not in plain
    preset = c.get("/?preset=latest").text
    assert preset.count('data-selected="true"') == 3


def test_sort_and_limit(env):
    app, store, a, _ = env
    for lemma in ["Katze", "Hund", "Haus"]:
        store.add_word(a, lemma, "noun", now=NOW)
    c = client_for(app, "anna")
    html = c.get("/?sort=word&dir=asc").text
    assert html.index("das Haus") < html.index("der Hund") < html.index("die Katze")
    assert c.get("/?sort=bogus&dir=nope&limit=-5").status_code == 200
    assert c.get("/?limit=999999").status_code == 200


def test_detail_has_declension_and_is_private(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    html = client_for(app, "anna").get(f"/words/{wid}").text
    assert "Deklination" in html and "die Häuser" in html and "Dat." in html
    assert client_for(app, "ben").get(f"/words/{wid}").status_code == 404


def test_own_translation_saved_escaped_and_owner_only(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    c = client_for(app, "anna")
    token = c.cookies.get("wort_csrf")
    r = c.post(f"/words/{wid}/translation", data={"csrf": token, "text": "<b>будинок</b>"})
    assert r.status_code == 303
    page = c.get("/").text
    assert "&lt;b&gt;будинок&lt;/b&gt;" in page and "<b>будинок" not in page
    b = client_for(app, "ben")
    assert b.post(f"/words/{wid}/translation", data={"csrf": b.cookies.get("wort_csrf"), "text": "x"}).status_code == 404
    assert c.post(f"/words/{wid}/translation", data={"csrf": token, "text": "x" * 201}).status_code == 400
    assert c.post(f"/words/{wid}/translation", data={"csrf": "forged", "text": "x"}).status_code == 403


def test_delete_only_own_word(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    b = client_for(app, "ben")
    assert b.post(f"/words/{wid}/delete", data={"csrf": b.cookies.get("wort_csrf")}).status_code == 404
    c = client_for(app, "anna")
    assert c.post(f"/words/{wid}/delete", data={"csrf": c.cookies.get("wort_csrf")}).status_code == 303
    assert store.words(a) == []


def test_import_page_adds_words_for_the_logged_in_user(env):
    import json
    from wort.transfer import FORMAT_VERSION
    app, store, a, b = env
    c = client_for(app, "anna")
    raw = json.dumps({"format_version": FORMAT_VERSION, "exported_at": "2026-10-14T10:00:00",
                      "words": [{"lemma": "Hund", "pos": "noun", "added_at": "2026-10-01T10:00:00"}],
                      "queries": []}).encode()
    r = c.post("/import", data={"csrf": c.cookies.get("wort_csrf")}, files={"file": ("e.json", raw)})
    assert r.status_code == 303 and r.headers["location"] == "/"  # words imported: land on the word list
    assert [w.lemma for w in store.words(a)] == ["Hund"] and store.words(b) == []


def history_env(env, queries=("Haus", "Hund", "Zzzzzz")):
    app, store, a, b = env
    from datetime import timedelta
    store.add_history(a, [(q, q != "Zzzzzz", NOW - timedelta(days=i)) for i, q in enumerate(queries)])
    return app, store, a, b


def test_history_offers_learn_and_it_feeds_the_word_list(env):
    app, store, a, _ = history_env(env)
    c = client_for(app, "anna")
    page = c.get("/history").text
    assert page.count('action="/words/learn"') == 2 and "Lernen" in page  # Haus and Hund (found); not Zzzzzz
    assert "nicht gefunden" in page
    r = c.post("/words/learn", data={"csrf": c.cookies.get("wort_csrf"), "query": "Haus"})
    assert r.status_code == 303 and r.headers["location"] == "/history"
    assert [(w.lemma, w.added_from) for w in store.words(a)] == [("Haus", "lookup")]
    assert "in deinen Wörtern" in c.get("/history").text
    assert "in Wörtern" in c.get("/history").text  # the row now says so instead of offering Lernen
    assert "das Haus" in c.get("/").text  # and it shows up in Wörter, ready for Üben


def test_learning_twice_or_an_unknown_word_changes_nothing_and_says_so(env):
    app, store, a, _ = history_env(env)
    c = client_for(app, "anna")
    tok = lambda: c.cookies.get("wort_csrf")  # noqa: E731
    c.post("/words/learn", data={"csrf": tok(), "query": "Haus"})
    c.post("/words/learn", data={"csrf": tok(), "query": "Haus"})
    assert len(store.words(a)) == 1 and "schon in deinen Wörtern" in c.get("/history").text
    c.post("/words/learn", data={"csrf": tok(), "query": "Zzzzzz"})
    assert len(store.words(a)) == 1 and "nicht im Wörterbuch" in c.get("/history").text
    assert c.post("/words/learn", data={"csrf": "forged", "query": "Haus"}).status_code == 403
    assert c.post("/words/learn", data={"csrf": tok(), "query": "\u200b<b>\x1b"}).status_code == 303
    assert len(store.words(a)) == 1


def test_learn_is_per_user(env):
    app, store, a, b = history_env(env)
    cb = client_for(app, "ben")
    cb.post("/words/learn", data={"csrf": cb.cookies.get("wort_csrf"), "query": "Haus"})
    assert store.words(a) == [] and len(store.words(b)) == 1


def test_import_of_history_only_lands_on_the_history_page_with_a_hint(env):
    import json
    from wort.transfer import FORMAT_VERSION
    app, store, a, _ = env
    c = client_for(app, "anna")
    raw = json.dumps({"format_version": FORMAT_VERSION, "exported_at": "2026-10-14T10:00:00", "words": [],
                      "queries": [{"query": "Haus", "found": True, "queried_at": "2026-10-01T10:00:00"}]}).encode()
    r = c.post("/import", data={"csrf": c.cookies.get("wort_csrf")}, files={"file": ("e.json", raw)})
    assert r.headers["location"] == "/history"
    assert "Lernen" in c.get("/history").text


def test_empty_word_list_points_to_the_history(env):
    app, *_ = env
    page = client_for(app, "anna").get("/").text
    assert "Aus Verlauf hinzufügen" in page and 'href="/history"' in page


def test_list_uses_article_color_and_score_chip(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    store.record_attempt(a, wid, "form", "article", "p", "das", "correct", now=NOW)
    html = client_for(app, "anna").get("/").text
    assert 'data-article="das"' in html
    from app.scoring import level
    from app import words
    chip = words.SCORE_TAG[level(store.words(a)[0].score)]
    assert f'class="ds-tag" data-type="{chip}" data-subtype="passive">' in html
    assert "ds-page-head" in html and "1 Wörter · 1 diese Woche" in html


def test_score_tag_types_follow_the_level():
    from app import words
    from app.scoring import level
    assert {level(s): words.SCORE_TAG[level(s)] for s in (None, 0, 5, 9)} == {
        "new": "neutral", "weak": "danger", "medium": "warning", "strong": "success"}


def test_detail_examples_and_mistakes_are_disclosures(env):
    app, store, a, _ = env
    store.add_word(a, "Haus", "noun", now=NOW)
    wid = store.words(a)[0].id
    html = client_for(app, "anna").get(f"/words/{wid}").text
    # only what the word has: its examples; no "Deine Fehler" without a mistake, no search history without a search
    assert html.count('<details class="ds-disclosure"') == 1 and "Beispiele" in html
    assert "Deine Fehler" not in html and "Suchverlauf" not in html
    store.record_attempt(a, wid, "form", "article", "p", "der", "wrong", now=NOW)
    html = client_for(app, "anna").get(f"/words/{wid}").text
    assert html.count('<details class="ds-disclosure"') == 2 and "Deine Fehler" in html


def test_list_and_detail_show_ukrainian_before_english(tmp_path, dict_path):
    from wort.dictionary.ukrainian import import_entries
    uk = tmp_path / "dictionary-uk.db"
    import_entries([{"word": "Haus", "pos": "noun", "lang_code": "de",
                     "senses": [{"translations": [{"lang_code": "uk", "word": "дім", "sense_index": "1"}]}]}], uk)
    db = tmp_path / "web.db"
    app = create_app(db_path=db, dict_path=dict_path, uk_path=uk, secure_cookies=False)
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(a, "Haus", "noun", now=NOW)
    c = client_for(app, "anna")
    assert "дім · house" in c.get("/").text
    assert "дім · house" in c.get(f"/words/{store.words(a)[0].id}").text


def test_history_learn_button_submits_its_own_rows_query(env):
    """The button in the page (not a hand-made POST): submit type, wired to the form for its own row."""
    import re
    app, store, a, _ = history_env(env)
    c = client_for(app, "anna")
    page = c.get("/history").text
    rows = re.findall(r'<div class="ds-table-row"[^>]*>\s*<div class="ds-table-cell"[^>]*>\s*'
                      r'<span class="ds-table-cell__text">([^<]*)</span>[\s\S]*?</div>\s*</div>', page)
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*form="(learn-\d+)"[^>]*>Lernen</button>', page)
    assert len(buttons) == 2 and 'type="button" data-priority="secondary" data-status="active" data-underline="dotted">Lernen' not in page
    form_id = buttons[-1]
    query = re.search(rf'<form id="{form_id}"[\s\S]*?name="query" value="([^"]*)"', page).group(1)
    row_of_button = page[:page.index(f'form="{form_id}"')].rsplit('<div class="ds-table-row"', 1)[1]
    assert f'<span class="ds-table-cell__text">{query}</span>' in row_of_button  # the form belongs to this row
    c.post("/words/learn", data={"csrf": c.cookies.get("wort_csrf"), "query": query})
    assert [w.lemma for w in store.words(a)] == [query]
    assert rows


def test_lookup_shows_forms_and_adds_only_on_click(env):
    app, store, a, _ = env
    c = client_for(app, "anna")
    page = c.get("/?s=1&q=Haus").text
    assert "Deklination Haus" not in page and "Deklination das Haus" in page  # forms table of the entry
    assert "dem Haus" in page and "Zu Wörtern hinzufügen" in page
    assert store.words(a) == []  # looking up adds nothing
    assert [h.query for h in store.history(a)] == ["Haus"]  # but the lookup is in the history
    r = c.post("/words/add", data={"csrf": c.cookies.get("wort_csrf"), "lemma": "Haus", "pos": "noun", "q": "Haus"})
    assert r.status_code == 303 and r.headers["location"] == "/?q=Haus"
    assert [(w.lemma, w.added_from) for w in store.words(a)] == [("Haus", "lookup")]
    again = c.get(r.headers["location"]).text
    assert "in deinen Wörtern" in again and len(store.history(a)) == 1  # the return is not a new lookup
    assert "wort-card" not in again  # the hero is the title and the field only


def test_lookup_verb_conjugation_sentence_and_unknown(env):
    app, store, a, _ = env
    c = client_for(app, "anna")
    verb = c.get("/?s=1&q=gehen").text
    assert "Konjugation gehen" in verb and "bin gegangen" in verb
    sentence = c.get("/?s=1&q=Haus gehen").text
    assert "Ein Ergebnis pro Wort" in sentence and "Deklination das Haus" in sentence and "Konjugation gehen" in sentence
    assert "Nichts gefunden" in c.get("/?s=1&q=qqqqqqqq").text


def test_lookup_input_is_escaped_and_add_checks_the_dictionary(env):
    app, store, a, _ = env
    c = client_for(app, "anna")
    page = c.get("/?s=1&q=<script>alert(1)</script>").text
    assert "<script>alert(1)" not in page
    tok = c.cookies.get("wort_csrf")
    assert c.post("/words/add", data={"csrf": "forged", "lemma": "Haus", "pos": "noun"}).status_code == 403
    assert c.post("/words/add", data={"csrf": tok, "lemma": "<b>", "pos": "noun"}).status_code == 400
    r = c.post("/words/add", data={"csrf": tok, "lemma": "Erfunden", "pos": "noun", "q": "x"})
    assert r.status_code == 303 and store.words(a) == []


def test_open_word_splits_the_table_block_and_keeps_its_sort(env):
    app, store, a, _ = env
    for i, lemma in enumerate(["Haus", "Hund", "gehen"]):
        store.add_word(a, lemma, "noun" if lemma != "gehen" else "verb", now=NOW.replace(hour=i))
    c = client_for(app, "anna")
    plain = c.get("/?sort=word&dir=asc").text
    assert '<span class="ds-table-cell__text">Erstellt</span>' in plain and 'data-open="true"' not in plain
    wid = next(w.id for w in store.words(a) if w.lemma == "Haus")
    assert f'href="/words/{wid}?sort=word&amp;dir=asc&amp;limit=20#detail"' in plain  # the row opens it in place
    page = c.get(f"/words/{wid}?sort=word&dir=asc").text
    assert 'data-open="true"' in page and 'id="detail"' in page and "Deklination" in page
    assert page.count('data-word-id="') == 3  # the whole table stays beside the word
    assert '<span class="ds-table-cell__text">Erstellt</span>' in page  # rendered always, hidden by CSS while open
    assert 'id="wort-side"' in plain and 'id="detail"' not in plain  # the side column exists empty when closed
    assert 'href="/?sort=word&amp;dir=asc&amp;limit=20#wort-table"' in page  # "Schließen" keeps the sort
    assert c.get("/words/99999").status_code == 404


def test_detail_shows_the_forms_table_of_a_verb(env):
    app, store, a, _ = env
    store.add_word(a, "gehen", "verb", now=NOW)
    html = client_for(app, "anna").get(f"/words/{store.words(a)[0].id}").text
    assert "Konjugation" in html and "bin gegangen" in html and "Deklination" not in html


def test_button_labels_have_english_and_ukrainian_for_tooltips(env):
    import json
    import re
    app, *_ = env
    html = client_for(app, "anna").get("/").text
    data = json.loads(re.search(r'<script type="application/json" id="wort-glossary">(.*?)</script>', html, re.S).group(1))
    assert data["labels"]["Sätze bilden"] == ["make sentences", "складати речення"]
    assert "</script" not in re.search(r'id="wort-glossary">(.*?)</script>', html, re.S).group(1)


def test_gloss_gives_lemma_and_translation_for_any_german_word(env):
    app, *_ = env
    c = client_for(app, "anna")
    r = c.get("/api/gloss", params={"w": "Häuser"})  # an inflected form finds its lemma
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert data["label"] == "das Haus" and data["pos"] == "Nomen" and "house" in data["en"]
    assert c.get("/api/gloss", params={"w": "ging"}).json()["label"] == "gehen"


@pytest.mark.parametrize("w", ["", "zwei Wörter", "<b>Haus</b>", "{{7*7}}", "Haus;", "a" * 61])
def test_gloss_rejects_anything_but_one_word(env, w):
    app, *_ = env
    assert client_for(app, "anna").get("/api/gloss", params={"w": w}).status_code == 400


def test_gloss_unknown_word_is_404_and_needs_login(env):
    app, *_ = env
    assert client_for(app, "anna").get("/api/gloss", params={"w": "Quatschwort"}).status_code == 404
    anon = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    r = anon.get("/api/gloss", params={"w": "Haus"})
    assert r.status_code == 303 and r.headers["location"] == "/login"
