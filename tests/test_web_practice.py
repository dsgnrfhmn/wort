import random
import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import auth, checking, practice, questions
from app.db import WebStore
from app.main import create_app
from wort.dictionary.lookup import Dictionary
from wort.exercises.grammar_check import Issue

PASSWORD = "correct horse battery"


@pytest.fixture
def env(tmp_path, dict_path):
    db = tmp_path / "web.db"
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    b = store.create_user("ben", auth.hash_password(PASSWORD)).id
    for lemma, pos in [("Haus", "noun"), ("gehen", "verb")]:
        store.add_word(a, lemma, pos)
    return app, store, a, b


def login(app, name):
    c = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    c.get("/login")
    c.post("/login", data={"csrf": c.cookies.get("wort_csrf"), "name": name, "password": PASSWORD})
    return c


def start(c, store, uid, kind, ids=None):
    ids = ids or [w.id for w in store.words(uid)]
    r = c.post(f"/ueben/{kind}", data={"csrf": c.cookies.get("wort_csrf"), "ids": ids})
    assert r.status_code == 303, r.text
    return r.headers["location"]


def test_build_items_round_robin_and_abfrage(dict_path):
    dic = Dictionary(dict_path)
    store_words = [(type("W", (), {"id": i})(), dic.find_lemma(l)) for i, l in [(1, "Haus"), (2, "gehen")]]
    items = practice.build_items("saetze", store_words, random.Random(1))
    assert len(items) == 5 and {i["word_id"] for i in items} == {1, 2} and all(i["kind"] == "sentence" for i in items)
    ab = practice.build_items("abfrage", store_words, random.Random(1))
    assert len(ab) == 2 and all("seed" in i for i in ab)


def test_grade_sentence_cases():
    ok = practice.grade_sentence("Ich sehe die Häuser dort", ["Häuser"], lambda s: [])
    assert ok.verdict == "correct"
    missing = practice.grade_sentence("Ich sehe das Haus dort", ["Häuser"], lambda s: [])
    assert missing.verdict is None and missing.tip and missing.final and missing.missing == ["Häuser"]
    assert missing.feedback == "Verwende: Häuser"
    unchecked = practice.grade_sentence("Ich sehe die Häuser dort", ["Häuser"], lambda s: None)
    assert unchecked.verdict is None and unchecked.final is True and unchecked.checked is False
    short = practice.grade_sentence("Häuser", ["Häuser"], lambda s: [])
    assert short.verdict is None and short.final is False
    remark = practice.grade_sentence("Ich sehe die Häuser dort", ["Häuser"],
                                     lambda s: [Issue("Stil", 4, 4, ["sah"])])
    assert remark.verdict == "almost"


def test_full_abfrage_session_updates_scores(env, dict_path):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "abfrage")
    sid = int(loc.rsplit("/", 1)[1])
    page = c.get(loc).text
    assert "Wort 1" in page and "von 2" in page and "Diese Runde" in page and "Noch 1 Wort." in page
    for _ in range(2):
        sess = store.practice(a, sid)
        item = sess["items"][sess["pos"]]
        word = store.word(a, item["word_id"])
        dic = Dictionary(dict_path)
        entry = dic.find_lemma(word.lemma, word.pos or None)
        _, _, _, ex, _ = practice.rebuild(item, entry)
        right = ex.check("zzz").expected.split(";")[0].strip()
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": right})
        c.post(f"/ueben/s/{sid}/next", data={"csrf": c.cookies.get("wort_csrf")})
    done = c.get(loc).text
    assert "Ergebnis" in done
    n = store.conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (a,)).fetchone()[0]
    assert n == 2


def test_sentence_session_with_unreachable_grammar_check_gives_no_score(tmp_path, dict_path):
    db = tmp_path / "w.db"
    app = create_app(db_path=db, dict_path=dict_path, secure_cookies=False, checker=lambda s: None)
    store = WebStore(db)
    a = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(a, "Haus", "noun")
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    item = store.practice(a, sid)["items"][0]
    entry = Dictionary(dict_path).find_lemma("Haus", "noun")
    required = practice.rebuild(item, entry)[4]
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe " + " ".join(required) + " dort"})
    page = c.get(loc).text
    assert "nicht geprüft" in page and store.words(a)[0].score is None


def test_other_users_cannot_open_or_answer_a_session_or_use_foreign_word_ids(env):
    app, store, a, b = env
    ca = login(app, "anna")
    loc = start(ca, store, a, "abfrage")
    sid = int(loc.rsplit("/", 1)[1])
    cb = login(app, "ben")
    assert cb.get(loc).status_code == 404
    assert cb.post(f"/ueben/s/{sid}/answer", data={"csrf": cb.cookies.get("wort_csrf"), "text": "x"}).status_code == 404
    r = cb.post("/ueben/abfrage", data={"csrf": cb.cookies.get("wort_csrf"), "ids": [w.id for w in store.words(a)]})
    assert r.status_code == 303 and r.headers["location"] == "/"  # nothing usable, no session
    assert "keine" in cb.get("/").text  # the one-time message comes from a server-set cookie, not the URL


def test_csrf_and_input_limits(env):
    app, store, a, _ = env
    c = login(app, "anna")
    assert c.post("/ueben/saetze", data={"csrf": "forged", "ids": [1]}).status_code == 403
    assert c.post("/ueben/saetze", data={"csrf": c.cookies.get("wort_csrf")}).status_code == 400
    assert c.post("/ueben/bogus", data={"csrf": c.cookies.get("wort_csrf"), "ids": [1]}).status_code == 404
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    r = c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "x" * 5000})
    assert r.status_code == 303  # capped, not an error
    assert len(store.conn.execute("SELECT answer FROM attempts").fetchall()) <= 1


def test_correction_segments_marks_each_unique_fragment():
    segs = practice.correction_segments(
        "Ich gehe gestern in die Schule.",
        [{"fragment": "gehe", "message": "Präteritum", "replacements": ["ging"]}])
    assert [s.get("kind") for s in segs] == [None, "remove", None, "add", None]
    assert segs[3]["text"] == "ging" and segs[3]["tooltip"] == "Präteritum\nRichtig: ging"
    with_table = practice.correction_segments(
        "Ich gehe gestern in die Schule.",
        [{"fragment": "gehe", "message": "Präteritum", "replacements": ["ging", "lief"]}], lambda w: ["«gehen»:", "ich ging"])
    assert with_table[3]["tooltip"] == "Präteritum\nRichtig: ging\nAuch möglich: lief\n\n«gehen»:\nich ging"


@pytest.mark.parametrize("answer,remarks", [
    ("Ich gehe gehe.", [{"fragment": "gehe", "message": "m", "replacements": ["ging"]}]),  # twice
    ("Ich gehe.", [{"fragment": "xyz", "message": "m", "replacements": []}]),  # absent
    ("Ich gehe.", [{"fragment": "", "message": "m", "replacements": []}]),
    ("Ich gehe heim.", [{"fragment": "gehe heim", "message": "m", "replacements": []},
                        {"fragment": "heim", "message": "m", "replacements": []}]),  # overlap
    ("Ich gehe.", []), ("Ich gehe.", None)])
def test_correction_segments_falls_back_to_none(answer, remarks):
    assert practice.correction_segments(answer, remarks) is None


def test_start_page_tabs_are_links_and_modus_is_whitelisted(env):
    app, store, a, _ = env
    c = login(app, "anna")
    html = c.get("/ueben?modus=abfrage").text
    assert 'href="/ueben?modus=saetze"' in html and 'action="/ueben/abfrage"' in html
    html = c.get("/ueben?modus=evil\"><x").text
    assert 'action="/ueben/saetze"' in html and "evil" not in html


def test_start_tabs_do_not_show_the_word_count(env):
    app, store, a, _ = env
    html = login(app, "anna").get("/ueben").text
    assert "ds-header-tab__count" not in html


def test_sentence_items_get_questions_from_the_chosen_topic(dict_path):
    dic = Dictionary(dict_path)
    pairs = [(type("W", (), {"id": i})(), dic.find_lemma(l)) for i, l in [(1, "Haus"), (2, "gehen")]]
    items = practice.build_items("saetze", pairs, random.Random(1), topic="fahrrad")
    refs = [i["question"] for i in items]
    assert all(k == "fahrrad" for k, _ in refs) and len({tuple(r) for r in refs}) == len(refs)  # no repeats
    assert all(practice.question_text(i) in [q["q"] for q in questions.TOPICS["fahrrad"]["questions"]] for i in items)
    mixed = practice.build_items("saetze", pairs, random.Random(1))
    assert all(practice.question_text(i) for i in mixed)


def test_question_text_is_empty_for_ai_wording_and_stale_refs():
    item = {"kind": "sentence", "index": 0, "question": ["design", 0]}
    assert practice.question_text(item) == questions.TOPICS["design"]["questions"][0]["q"]
    assert practice.question_text(item | {"ai_prompt": "x"}) == ""
    assert practice.question_text(item | {"question": ["design", 9999]}) == ""
    assert practice.question_text(item | {"question": ["gone", 0]}) == ""
    assert practice.question_text(item | {"question": ["design", -1]}) == ""
    assert practice.question_text({"kind": "article", "seed": 1}) == ""


def test_pick_repeats_only_after_the_pool_is_used_up():
    n = len(questions.TOPICS["design"]["questions"])
    refs = questions.pick("design", n + 3, random.Random(2))
    assert len({tuple(r) for r in refs[:n]}) == n and len(refs) == n + 3


def test_malformed_questions_file_fails_loud(tmp_path):
    bad = tmp_path / "q.json"
    for data in ('{}', '{"x": {"label": "X", "questions": []}}', '{"x": {"label": "X", "questions": ["Wie?"]}}',
                 '{"x": {"label": "X", "questions": [{"q": "Wie?", "a": ""}]}}',
                 '{"alle": {"label": "A", "questions": [{"q": "Wie?", "a": "So."}]}}'):
        bad.write_text(data)
        with pytest.raises(ValueError):
            questions._load(bad)


def test_sentence_task_shows_question_bold_and_instruction_as_note(env):
    app, store, a, _ = env
    c = login(app, "anna")
    html = c.get("/ueben?modus=saetze&thema=design").text
    assert 'name="thema" value="design"' in html and 'href="/ueben?neu=1&amp;modus=saetze&amp;thema=fahrrad"' in html
    assert 'name="thema" value="alle"' in c.get("/ueben?modus=saetze&thema=evil").text
    r = c.post("/ueben/saetze", data={"csrf": c.cookies.get("wort_csrf"), "preset": "weakest", "thema": "design"})
    html = c.get(r.headers["location"]).text
    text = html.split('class="ds-message__text" lang="de">', 1)[1].split("</div>", 1)[0].strip()
    note = html.split('class="ds-message__note" lang="de">', 1)[1].split("</div>", 1)[0]
    assert text in [q["q"] for q in questions.TOPICS["design"]["questions"]]
    assert note.startswith("Schreibe einen Satz mit")
    # hints: one disclosure holds what the asked form means and an example answer, no hover tooltip
    assert 'class="wort-hints"' in html and "Gesucht: " in html and "ds-message__more" not in html
    assert ">Beispielantwort<" in html
    asked = html.split("Gesucht: ", 1)[1].split("&#10;", 1)[0].split("\n", 1)[0]
    example = html.split('<span class="wort-hints__label">Beispielantwort</span><br><span lang="de">', 1)[1].split("</span>", 1)[0]
    assert all(w in example for w in asked.split()), (asked, example)  # the example has the asked form


def test_missing_form_is_a_tip_but_the_grammar_is_still_checked():
    issue = Issue("Falscher Artikel", 9, 3, ["den"])
    g = practice.grade_sentence("Ich sehe der Garten dort", ["Häuser"], lambda s: [issue])
    assert g.tip and g.verdict is None and g.missing == ["Häuser"]
    assert g.remarks == [{"fragment": "der", "message": "Falscher Artikel", "replacements": ["den"]}]
    assert g.corrected == "Ich sehe den Garten dort"
    unchecked = practice.grade_sentence("Ich sehe der Garten dort", ["Häuser"], lambda s: None)
    assert unchecked.tip and not unchecked.checked and unchecked.grammar == "unchecked" and unchecked.verdict is None


def test_tip_answer_changes_no_score_and_shows_tipp(tmp_path, dict_path):
    issue = Issue("Falscher Artikel", 9, 3, ["den"])
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False,
                     checker=lambda s: [issue])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    before = store.words(uid)[0].score
    c = login(app, "anna")
    loc = start(c, store, uid, "saetze")
    sid = loc.rsplit("/", 1)[1]
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe der Garten dort"})
    html = c.get(loc).text
    verdict = html.split('class="wort-verdict"', 1)[1].split("</section>", 1)[0]  # the verdict is on the page, not behind "Mehr erklären"
    assert ">Tipp<" in html and "Verwende:" in verdict and "richtig" not in verdict
    assert ">Grammatik<" in html and ">falsch<" in html and "1 Fehler, siehe unten." in verdict
    assert 'data-kind="remove">der<' in html  # the wrong article is marked
    # the right sentence in green under the marked answer; each mistake explained in the hidden feedback
    assert 'data-tone="success">Ich sehe den Garten dort<' in html
    assert ">Fehler 1<" in html and "«der» → den" in html and '<p lang="de">Falscher Artikel' in html
    assert 'class="wort-review" id="fb-0-1" hidden' in html and ">Mehr erklären<" in html
    # once checked, one bubble shows: the corrected version carries the marks; the answer as written lies in the
    # same cell, invisible, behind "Original anzeigen" (app.js swaps them, data-shown), both the white outlined `answer` message
    shown = html.split('<template id="wort-pending">')[0]
    assert html.count('data-kind="remove">der<') == 1
    assert 'data-answer-view="corrected">' in shown and "Korrigiert</div>" in shown
    assert 'class="wort-reply__mine" data-shown="corrected"' in shown and 'data-answer-view="original">' in shown
    assert 'data-answer-toggle="original"' in shown and ">Original anzeigen<" in shown and ">Korrigiert anzeigen<" in shown
    assert 'data-inverted="true"' not in html
    assert store.words(uid)[0].score == before


def test_one_task_at_a_time_next_opens_the_next_and_tabs_switch_back(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    html = c.get(loc).text
    assert 'name="at" value="0"' in html and f'action="/ueben/s/{sid}/next"' not in html
    assert html.count(f'href="/ueben/s/{sid}?a=') == 1  # only the current task has a tab
    r = c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Das ist ein Satz hier", "at": 0})
    assert r.headers["location"] == f"/ueben/s/{sid}#jetzt"
    html = c.get(loc).text
    # answered: the next task is not shown yet, "Nächste Aufgabe" opens it
    assert "Aufgabe 2" not in html and f'action="/ueben/s/{sid}/next"' in html and ">Nächste Aufgabe<" in html
    assert 'name="at"' not in html.split('class="wort-composer"')[1]
    c.post(f"/ueben/s/{sid}/next", data={"csrf": csrf})
    html = c.get(loc).text
    assert store.practice(a, sid)["pos"] == 1 and 'name="at" value="1"' in html
    chat = html.split('<template id="wort-pending">')[0]  # the template holds the pending answer of the next Send
    assert html.count(f'href="/ueben/s/{sid}?a=') == 2 and chat.count("Deine Antwort</div>") == 0  # one task shown
    # the first task's tab shows it again, read-only apart from the retry, with a way back
    old = c.get(f"{loc}?a=0").text
    assert "Das ist ein Satz hier" in old and ">Zur aktuellen Aufgabe (2)<" in old and 'action="/ueben/s/%d/answer"' % sid not in old
    assert 'aria-current="step"' in old.split(">1</span>")[0].rsplit("<a", 1)[1]  # task 1 is the step shown
    # a tab beyond the current task falls back to the current one
    assert 'name="at" value="1"' in c.get(f"{loc}?a=4").text
    # a stale form (the first task again) changes nothing
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Noch ein Satz hier", "at": 0})
    assert store.practice(a, sid)["pos"] == 1 and "result" not in store.practice(a, sid)["items"][1]


def test_chat_last_task_answered_offers_the_result(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    total = len(store.practice(a, sid)["items"])
    for i in range(total):
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": f"Das ist Satz Nummer {i}", "at": i})
    html = c.get(loc).text
    assert f'action="/ueben/s/{sid}/next"' in html and 'name="at"' not in html
    c.post(f"/ueben/s/{sid}/next", data={"csrf": csrf})
    assert "Ergebnis" in c.get(loc).text and store.practice(a, sid)["pos"] == total


def test_other_form_of_the_word_is_right_with_a_tip_and_grammar_is_judged_apart(dict_path):
    entry = Dictionary(dict_path).find_lemma("gehen", "verb")
    forms = checking.lemma_forms(entry)
    assert {"gehen", "gehe", "ging", "gegangen"} <= forms and "sein" not in forms and "zu" not in forms
    ok = practice.grade_sentence("Wir gingen gestern nach Hause", ["gehen"], lambda s: [], forms, "Präsens, wir")
    assert ok.verdict == "correct" and ok.word_ok and ok.grammar == "ok"
    assert ok.tip == "«gehen» (Präsens, wir) statt «gingen»."
    bad = practice.grade_sentence("Wir gingen gestern nach Hause", ["gehen"],
                                  lambda s: [Issue("Stil", 4, 6, ["gehen"])], forms, "Präsens, wir")
    assert bad.verdict == "almost" and bad.word_ok and bad.grammar == "errors" and bad.tip
    asked = practice.grade_sentence("Wir gehen gestern nach Hause", ["gehen"], lambda s: [], forms, "Präsens, wir")
    assert asked.verdict == "correct" and not asked.tip
    other = practice.grade_sentence("Wir schlafen gestern zu Hause", ["gehen"], lambda s: [], forms)
    assert other.verdict is None and other.word_ok is False and other.tip == "Verwende: gehen"


def test_other_form_shows_richtig_magenta_tip_and_grammar_rows(tmp_path, dict_path):
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "gehen", "verb")
    c = login(app, "anna")
    loc = start(c, store, uid, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    item = store.practice(uid, sid)["items"][0]
    entry = Dictionary(dict_path).find_lemma("gehen", "verb")
    required = practice.rebuild(item, entry)[4]
    other = next(f for f in ("ging", "gegangen", "gehst") if f not in {r.casefold() for r in required})
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": f"Wir {other} gestern dorthin"})
    html = c.get(loc).text
    assert 'data-v="tip"' in html and ">Tipp<" in html and f"statt «{other}»." in html
    assert html.count(">richtig<") == 3  # the verdict, the word and the grammar
    assert 'aria-label="Bewertung"' in html and ">Form<" in html
    assert store.practice(uid, sid)["items"][0]["result"]["verdict"] == "correct"


def test_toolbar_and_lookup_side_panel_are_on_the_practice_pages_only(env):
    app, store, a, _ = env
    anon = TestClient(app, follow_redirects=False, client=("127.0.0.1", 50000))
    html = anon.get("/login").text
    assert "data-side-toggle" not in html and 'id="wort-lookup-side"' not in html
    c = login(app, "anna")
    html = c.get("/").text  # Wörter has its own lookup field (D00h)
    assert 'class="wort-toolbar"' not in html and "data-side-toggle" not in html and 'id="wort-lookup-side"' not in html
    for path in ("/ueben",):
        html = c.get(path).text
        assert 'class="wort-modebar"' in html and 'class="wort-toolbar"' not in html  # the toggle shares the mode bar's row
        assert "data-side-toggle" in html and 'aria-controls="wort-lookup-side"' in html
        assert 'id="wort-lookup-side" data-resizable' in html and 'class="wort-side__search"' in html
        assert 'class="ds-split__handle"' in html  # the panel's width can be dragged (dis-system pane)
        assert html.count('id="wort-lookup-side"') == 1


def test_task_hint_and_correction_table_come_from_the_dictionary(dict_path):
    from app import hints
    dic = Dictionary(dict_path)
    gehen = dic.find_lemma("gehen", "verb")
    tip = hints.task_hint(gehen, "Präteritum, ich", ["ging"])
    assert tip.startswith("Gesucht: ging\nPräteritum: Vergangenheit") and "Beispiel: " in tip
    assert "«gehen»:" in tip and "ich ging" in tip and "er/sie/es ging" in tip
    haus = dic.find_lemma("Haus", "noun")
    assert "Dat. dem Haus — den Häusern" in hints.task_hint(haus, "Dativ Plural", ["Häusern"])
    assert hints.correction_table(dic, "Er geht")[:2] == ["«gehen»:", "ich gehe"]
    assert hints.correction_table(dic, "Quatsch") == [] and hints.correction_table(None, "geht") == []


def test_correction_tooltip_adds_ukrainian_for_the_rule_and_the_lemma_translation(dict_path):
    from app import hints
    assert hints.rule_uk("DE_AGREEMENT2", "GRAMMAR").startswith("іменник")
    assert hints.rule_uk("SOME_NEW_RULE", "TYPOS") == "друкарська помилка" and hints.rule_uk("X", "Y") == ""
    dic = Dictionary(dict_path)
    segs = practice.correction_segments(
        "Er gehen nach Hause.",
        [{"fragment": "Er gehen", "message": "Möglicherweise fehlende Übereinstimmung.", "replacements": ["Er geht"],
          "rule": "DE_VERBAGREEMENT", "category": "GRAMMAR"}],
        lambda w: hints.correction_table(dic, w, lambda e: "йти · to go"))
    tip = next(s for s in segs if s.get("kind") == "add")["tooltip"]
    assert tip.startswith("Möglicherweise fehlende Übereinstimmung. (підмет і дієслово не узгоджені")
    assert "«gehen» (йти · to go):" in tip and "er/sie/es geht" in tip


def test_grammar_check_keeps_rule_and_category(monkeypatch):
    import io, json
    from wort.exercises import grammar_check
    payload = {"matches": [{"message": "m", "offset": 0, "length": 2, "replacements": [{"value": "x"}],
                            "rule": {"id": "DE_AGREEMENT", "category": {"id": "GRAMMAR"}}}]}
    monkeypatch.delenv("WORT_LT_DISABLE", raising=False)
    monkeypatch.setattr(grammar_check.urllib.request, "urlopen",
                        lambda *a, **k: io.BytesIO(json.dumps(payload).encode()))
    [issue] = grammar_check.check("Er gehen.")
    assert (issue.rule, issue.category) == ("DE_AGREEMENT", "GRAMMAR")


def test_only_the_latest_result_is_held_for_its_entrance(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    html = c.get(loc).text
    assert "data-result-step" not in html and "/ds/components/fade-in/component.js" in html
    for i in range(2):
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": f"Das ist Satz Nummer {i}", "at": i})
    html = c.get(loc).text
    assert all(html.count(f'data-result-step="{n}"') == 1 for n in (0, 1, 2))  # answer, verdict, then the retry row
    assert 'class="wort-actions wort-retry" data-fade-hold data-result-step="2"' in html
    assert "data-result-step" not in c.get(f"{loc}?a=0").text  # an earlier task does not arrive again


def test_ueben_returns_to_the_running_session_and_keeps_the_batch_until_a_new_one(env):
    app, store, a, _ = env
    c = login(app, "anna")
    csrf = c.cookies.get("wort_csrf")
    first = [w.id for w in store.words(a)][:1]
    loc = start(c, store, a, "saetze", ids=first)
    sid = int(loc.rsplit("/", 1)[1])
    r = c.get("/ueben")  # back from another page: the running session, not the start page
    assert r.status_code == 303 and r.headers["location"] == f"/ueben/s/{sid}#jetzt"
    html = c.get("/ueben?neu=1").text  # the start page offers the same words again
    assert "Dieselben Wörter noch einmal" in html and f'name="ids" value="{first[0]}"' in html
    total = len(store.practice(a, sid)["items"])
    for i in range(total):
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": f"Das ist Satz Nummer {i}", "at": i})
    c.post(f"/ueben/s/{sid}/next", data={"csrf": csrf})
    assert c.get("/ueben").status_code == 200  # finished: the start page, with the same batch offered
    done = c.get(loc).text
    assert "Noch eine Runde mit denselben Wörtern" in done and f'name="ids" value="{first[0]}"' in done
    other = [w.id for w in store.words(a)][1:2]
    start(c, store, a, "saetze", ids=other)  # a new batch replaces the old one
    assert f'name="ids" value="{other[0]}"' in c.get("/ueben?neu=1").text


def test_questions_are_matched_to_the_word_through_its_glosses():
    rng = random.Random(3)
    bike = questions.matches("alle", ["to repair", "to fix"])
    assert bike and all("repair" in [questions.stem(w) for w in questions._entry(r)["k"]] for r in bike)
    walk = [questions._entry(r)["q"] for r in questions.matches("alle", ["to accompany", "to escort"])]
    assert "Wen hast du zuletzt besucht?" in walk  # begleiten: visiting someone, not changing a tube
    general = questions.matches("alle", ["xyzzy"])
    assert general and all(questions._entry(r).get("general") for r in general)
    first = questions.pick_for("alle", ["to repair"], rng)
    second = questions.pick_for("alle", ["to repair"], rng, avoid=[first])
    assert second != first


def test_other_question_replaces_the_open_tasks_question_only(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    before = store.practice(a, sid)["items"][0]["question"]
    assert 'action="/ueben/s/%d/frage"' % sid in c.get(loc).text and ">Andere Frage<" in c.get(loc).text
    c.post(f"/ueben/s/{sid}/frage", data={"csrf": csrf, "at": 0})
    item = store.practice(a, sid)["items"][0]
    assert item["question"] != before and "result" not in item and item["index"] is not None
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Das ist ein Satz hier", "at": 0})
    answered = store.practice(a, sid)["items"][0]["question"]
    c.post(f"/ueben/s/{sid}/frage", data={"csrf": csrf, "at": 0})  # answered: unchanged
    assert store.practice(a, sid)["items"][0]["question"] == answered
    assert c.post(f"/ueben/s/{sid}/frage", data={"csrf": "forged", "at": 1}).status_code == 403


def test_explain_marks_the_right_article_and_verb_form(dict_path):
    from app import hints
    dic = Dictionary(dict_path)
    art = hints.explain({"fragment": "ein Hund", "message": "m", "replacements": ["einen Hund"],
                         "rule": "DE_AGREEMENT", "category": "GRAMMAR"}, dic)
    assert art["kind"] == "article" and art["table"]["title"] == "Regel: unbestimmter Artikel"
    r, c = art["table"]["hl"]
    assert art["table"]["rows"][r][0] == "Akk." and art["table"]["headers"][c] == "maskulin"
    assert art["caption"] == "Artikel · maskulin" and "Akkusativ" in art["merke"] and art["uk"]
    verb = hints.explain({"fragment": "Er gehen", "message": "m", "replacements": ["Er geht"],
                          "rule": "DE_VERBAGREEMENT", "category": "GRAMMAR"}, dic)
    r, c = verb["table"]["hl"]
    assert verb["kind"] == "verb" and verb["table"]["rows"][r] == ["er/sie/es", "geht"]
    adj = hints.explain({"fragment": "ein schöner Haus", "message": "m", "replacements": ["ein schönes Haus"],
                         "rule": "DE_AGREEMENT", "category": "GRAMMAR"}, dic)
    r, c = adj["table"]["hl"]
    assert adj["kind"] == "adjective" and adj["table"]["rows"][r][c] == "-es" and adj["table"]["headers"][c] == "neutrum"


def test_fehler_erklaert_pane_opens_from_the_feedback_and_lists_earlier_mistakes(tmp_path, dict_path):
    issue = Issue("Falscher Artikel", 9, 8, ["einen Hund"], "DE_AGREEMENT", "GRAMMAR")
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [issue])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    c = login(app, "anna")
    csrf = c.cookies.get("wort_csrf")
    for _ in range(2):  # two sessions, so the second has an earlier mistake of the same rule
        loc = start(c, store, uid, "saetze")
        sid = int(loc.rsplit("/", 1)[1])
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Ich sehe ein Hund dort", "at": 0})
    html = c.get(loc).text
    assert 'href="?fehler=0-1#jetzt"' in html and "Fehler erklärt" not in html.split("<main", 1)[1].split("</main>")[0]
    pane = c.get(f"{loc}?fehler=0-1").text
    assert 'class="wort-side wort-explain ds-split"' in pane and ">Fehler erklärt<" in pane
    assert "Regel: unbestimmter Artikel" in pane and 'data-highlight="success"' in pane
    assert ">Merke<" in pane and ">Українською<" in pane and ">Ähnliche Fehler von dir<" in pane
    assert "wort-explain" not in c.get(f"{loc}?fehler=5-9").text and "wort-explain" not in c.get(f"{loc}?fehler=x").text


def test_explain_tells_a_predicative_adjective_from_a_spelling_mistake(dict_path):
    from app import hints
    dic = Dictionary(dict_path)
    pred = hints.explain({"fragment": "schöne", "message": "Meinten Sie die Form „schön“?", "replacements": ["schön"],
                          "rule": "FLEKTIERTES_ADJEKTIV_AM_SATZENDE", "category": "TYPOS"}, dic)
    assert pred["kind"] == "predicative" and "ohne Endung" in pred["merke"] and pred["uk"].startswith("Після sein")
    typo = hints.explain({"fragment": "Hauss", "message": "Tippfehler", "replacements": ["Haus"],
                          "rule": "GERMAN_SPELLER_RULE", "category": "TYPOS"}, dic)
    assert typo["kind"] == "spelling" and typo["table"] and typo["table"]["title"].startswith("«Haus»")


def test_a_correction_links_to_its_explanation_and_is_marked_while_open(tmp_path, dict_path):
    issue = Issue("Falscher Artikel", 9, 8, ["einen Hund"], "DE_AGREEMENT", "GRAMMAR")
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [issue])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    c = login(app, "anna")
    loc = start(c, store, uid, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe ein Hund dort", "at": 0})
    html = c.get(loc).text
    assert '<a class="ds-inline-mark" href="?fehler=0-1#jetzt" data-kind="add"' in html and 'data-current' not in html
    opened = c.get(f"{loc}?fehler=0-1").text
    assert 'data-kind="add" data-tooltip=' in opened and 'data-current="true" aria-current="true">einen Hund</a>' in opened
    segs = practice.correction_segments("a b c", [{"fragment": "b", "replacements": ["x"]}], link=lambda n: f"#{n}", current=1)
    assert segs[1] == {"text": "b", "kind": "remove"} and segs[3]["href"] == "#1" and segs[3]["current"]  # only the fix


def test_example_answer_has_the_asked_form_and_person(dict_path):
    from app import hints
    dic = Dictionary(dict_path)
    gehen = dic.find_lemma("gehen", "verb")
    assert hints.example_answer(gehen, "Präteritum, du", ["gingst"]) == "Gestern gingst du …"
    assert hints.example_answer(gehen, "Perfekt, ich", ["bin", "gegangen"]) == "Ich bin gestern … gegangen."
    anf = dic.find_lemma("anfangen", "verb")
    assert hints.example_answer(anf, "Präsens, ich", ["fange", "an"]).startswith("Ich fange") and " an" in \
        hints.example_answer(anf, "Präsens, ich", ["fange", "an"])
    haus = dic.find_lemma("Haus", "noun")
    assert "Häusern" in hints.example_answer(haus, "Dativ Plural", ["Häusern"])


def test_example_tooltip_translates_the_example_or_falls_back_to_the_word(dict_path):
    from app import hints, mt
    dic = Dictionary(dict_path)
    gehen = dic.find_lemma("gehen", "verb")
    fake = {("Gestern gingst du …", "en"): "Yesterday you went …", ("Gestern gingst du …", "uk"): "Вчора ти пішов …"}
    tip = hints.example_tooltip(gehen, "Präteritum, du", ["gingst"], lambda t, lang: fake.get((t, lang), ""),
                                "йти", "to go")
    assert tip == "Gestern gingst du …\nEN: Yesterday you went …\nUK: Вчора ти пішов …"
    plain = hints.example_tooltip(gehen, "Präteritum, du", ["gingst"], lambda t, lang: "", "йти", "to go")
    assert plain == "Gestern gingst du …\nEN (Wort): gehen — to go\nUK (Wort): gehen — йти"
    mt.translate.cache_clear()
    assert isinstance(mt.translate("Ich gehe.", "uk"), str)  # no package or model: "", never an exception


def test_answer_field_is_two_lines(env):
    app, store, a, _ = env
    c = login(app, "anna")
    html = c.get(start(c, store, a, "saetze")).text
    assert '<textarea class="ds-input" data-type="textarea" data-fill="filled" data-rows rows="2"' in html


def test_gesuchte_laden_reads_the_cli_db_read_only_and_only_when_configured(tmp_path, dict_path):
    from datetime import datetime
    from wort.store import Store
    cli_path = tmp_path / "user.db"
    cli = Store(cli_path)
    cli.add_word("Haus", "noun", None, datetime(2026, 10, 1))
    cli.log_query("gehen", True, datetime(2026, 10, 2))
    cli.conn.close()
    before = cli_path.read_bytes()
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, cli_db=cli_path)
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    c = login(app, "anna")
    assert ">Gesuchte laden<" in c.get("/").text
    r = c.post("/import/cli", data={"csrf": c.cookies.get("wort_csrf")})
    assert r.status_code == 303 and [w.lemma for w in store.words(uid)] == ["Haus"]
    assert [h.query for h in store.history(uid)] == ["gehen"]
    assert cli_path.read_bytes() == before  # the CLI's file is not touched
    plain = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False)
    c2 = login(plain, "anna")
    assert ">Gesuchte laden<" not in c2.get("/").text
    assert c2.post("/import/cli", data={"csrf": c2.cookies.get("wort_csrf")}).status_code == 404



def test_abfrage_modes_one_kind_per_word_and_erklaere_needs_the_ai(env, dict_path):
    dic = Dictionary(dict_path)
    words = [(type("W", (), {"id": i})(), dic.find_lemma(l)) for i, l in [(1, "Haus"), (2, "gehen")]]
    items = practice.build_items("abfrage", words, random.Random(1), mode="bedeutung")
    assert [i["kind"] for i in items] == ["bedeutung", "bedeutung"] and practice.abfrage_mode(items) == "bedeutung"
    assert practice.abfrage_mode(practice.build_items("abfrage", words, random.Random(1))) == "gemischt"
    app, store, a, _ = env
    c = login(app, "anna")
    ids = [w.id for w in store.words(a)]
    r = c.post("/ueben/abfrage", data={"csrf": c.cookies.get("wort_csrf"), "ids": ids, "art": "bedeutung"})
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    assert {i["kind"] for i in store.practice(a, sid)["items"]} == {"bedeutung"}
    page = c.get(r.headers["location"]).text
    assert 'role="radio" aria-checked="true" tabindex="0" data-value="bedeutung"' in page
    assert 'data-value="erklaere" data-priority="secondary" data-status="disabled" data-underline="dotted" disabled' in page
    # AI off: a forged "erklaere" starts nothing; an unknown mode is refused
    before = store.conn.execute("SELECT COUNT(*) FROM practice_sessions").fetchone()[0]
    r = c.post("/ueben/abfrage", data={"csrf": c.cookies.get("wort_csrf"), "ids": ids, "art": "erklaere"})
    assert r.status_code == 303 and r.headers["location"].startswith("/ueben")
    assert c.post("/ueben/abfrage", data={"csrf": c.cookies.get("wort_csrf"), "ids": ids, "art": "x"}).status_code == 400
    assert store.conn.execute("SELECT COUNT(*) FROM practice_sessions").fetchone()[0] == before


def test_abfrage_skip_leaves_the_score_and_shows_in_the_round(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "abfrage")
    sid = int(loc.rsplit("/", 1)[1])
    first = store.word(a, store.practice(a, sid)["items"][0]["word_id"])
    c.post(f"/ueben/s/{sid}/skip", data={"csrf": c.cookies.get("wort_csrf")})
    c.post(f"/ueben/s/{sid}/skip", data={"csrf": c.cookies.get("wort_csrf")})  # the second skips the second word
    assert store.practice(a, sid)["pos"] == 2
    assert store.word(a, first.id).score is None
    assert store.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    assert "übersprungen" in c.get(loc).text  # the result page


def test_abfrage_doch_falsch_downgrades_once(env, dict_path):
    from wort.exercises.translate import _de_to_en
    app, store, a, _ = env
    c = login(app, "anna")
    ids = [w.id for w in store.words(a)]
    loc = c.post("/ueben/abfrage", data={"csrf": c.cookies.get("wort_csrf"), "ids": ids, "art": "bedeutung"}).headers["location"]
    sid = int(loc.rsplit("/", 1)[1])
    word = store.word(a, store.practice(a, sid)["items"][0]["word_id"])
    entry = Dictionary(dict_path).find_lemma(word.lemma, word.pos or None)
    right = re.split(r"[;,]", _de_to_en(entry).check("zzz").expected)[0].strip()  # one sense of the dictionary's gloss
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": right})
    res = store.practice(a, sid)["items"][0]["result"]
    assert res["verdict"] == "correct"
    page = c.get(loc).text
    assert "Doch falsch" in page and 'data-v="correct"' in page and ">richtig<" in page
    c.post(f"/ueben/s/{sid}/doch-falsch", data={"csrf": c.cookies.get("wort_csrf")})
    item = store.practice(a, sid)["items"][0]
    assert item["result"]["verdict"] == "wrong" and item["downgraded"]
    assert store.conn.execute("SELECT verdict FROM attempts").fetchone()[0] == "wrong"
    page = c.get(loc).text
    assert "Doch falsch" not in page and "0 richtig" in page and "1 falsch" in page
    c.post(f"/ueben/s/{sid}/doch-falsch", data={"csrf": c.cookies.get("wort_csrf")})  # once only: no change
    assert store.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    assert c.post(f"/ueben/s/{sid}/doch-falsch", data={"csrf": "forged"}).status_code == 403


def test_answer_again_keeps_the_first_answer_adds_an_attempt_and_changes_no_score(tmp_path, dict_path):
    issue = Issue("Falscher Artikel", 9, 3, ["den"])
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False,
                     checker=lambda s: [issue] if "der Garten" in s else [])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.create_user("ben", auth.hash_password(PASSWORD))
    store.add_word(uid, "Haus", "noun")
    c = login(app, "anna")
    loc = start(c, store, uid, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    assert ">Nochmal antworten<" not in c.get(loc).text  # nothing answered yet
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Ich sehe der Garten dort", "at": 0})
    word = store.words(uid)[0]
    score, attempts = word.score, len(store.attempts(uid, word.id))
    html = c.get(loc).text
    assert ">Nochmal antworten<" in html and 'href="?a=0&amp;nochmal=1#jetzt"' in html
    retry_page = c.get(loc + "?a=0&nochmal=1").text
    assert f'action="/ueben/s/{sid}/again"' in retry_page and "Nochmal: Aufgabe 1" in retry_page
    assert ">Nochmal antworten<" not in retry_page and "data-fade-hold" not in retry_page.split('class="wort-chat"')[1]
    # an empty retry grades nothing and keeps the retry composer
    r = c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": "", "at": 0})
    assert r.headers["location"].endswith("?a=0&nochmal=1#jetzt") and "retries" not in store.practice(uid, sid)["items"][0]
    r = c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": "Ich sehe den Garten dort", "at": 0})
    assert r.headers["location"] == f"/ueben/s/{sid}?a=0#jetzt"
    item = store.practice(uid, sid)["items"][0]
    assert item["answer"] == "Ich sehe der Garten dort" and item["result"]["grammar"] == "errors"  # first kept
    assert [x["answer"] for x in item["retries"]] == ["Ich sehe den Garten dort"]
    assert item["retries"][0]["result"]["grammar"] == "ok" and item["retries"][0]["result"]["delta"] is None
    assert store.words(uid)[0].score == score  # only the first answer counts
    assert len(store.attempts(uid, word.id)) == attempts
    html = c.get(loc).text
    assert "Aufgabe 1 · Versuch 2 · Deine Antwort" in html and 'aria-label="Aufgabe 1 · Versuch 2 · Bewertung"' in html and "ohne Score" in html
    assert html.count('data-kind="remove">der<') == 1  # the first correction is still on the page
    # the first attempt's correction comes first; the clean retry is shown as written
    assert html.index('data-kind="remove">der<') < html.index(">Ich sehe den Garten dort<")
    assert "Aufgabe 1 · Versuch 2 · Deine Antwort" in html
    # no cap: as many attempts as the learner likes; a forged token and another user change nothing
    for i in range(8):
        c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": f"Ich sehe das Haus Nummer {i}", "at": 0})
    assert len(store.practice(uid, sid)["items"][0]["retries"]) == 9
    assert ">Nochmal antworten<" in c.get(loc).text
    assert c.post(f"/ueben/s/{sid}/again", data={"csrf": "forged", "text": "x", "at": 0}).status_code == 403
    b = login(app, "ben")
    assert b.post(f"/ueben/s/{sid}/again", data={"csrf": b.cookies.get("wort_csrf"), "text": "Ich sehe das Haus", "at": 0}).status_code == 404


def test_answer_again_on_an_earlier_task_but_not_ahead_or_in_abfrage(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Das ist ein Satz hier", "at": 0})
    c.post(f"/ueben/s/{sid}/next", data={"csrf": csrf})
    c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": "Ein dritter Satz hier", "at": 0})
    c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": "Zu weit voraus hier", "at": 2})
    c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": "Noch offen hier", "at": 1})  # not answered yet
    items = store.practice(a, sid)["items"]
    assert [x["answer"] for x in items[0]["retries"]] == ["Ein dritter Satz hier"]
    assert all("retries" not in i for i in items[1:])
    html = c.get(f"{loc}?a=0").text
    assert "Versuch 2" in html and ">2×<" in html  # the tab counts the attempts
    # an Abfrage session has no retry
    loc2 = start(c, store, a, "abfrage")
    sid2 = int(loc2.rsplit("/", 1)[1])
    c.post(f"/ueben/s/{sid2}/answer", data={"csrf": csrf, "text": "x"})
    c.post(f"/ueben/s/{sid2}/again", data={"csrf": csrf, "text": "y", "at": 0})
    assert all("retries" not in i for i in store.practice(a, sid2)["items"])


def test_sidebar_lists_the_session_words_and_a_word_keeps_the_tabs_to_its_tasks(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    items = store.practice(a, sid)["items"]
    first, second = items[0]["word_id"], items[1]["word_id"]
    assert first != second  # round robin over the two words
    html = c.get(loc).text
    assert 'aria-label="Wörter dieser Übung"' in html and ">Alle Aufgaben<" in html and ">das Haus<" in html
    assert f"?w={second}" not in html  # its first task comes later: muted, no link yet
    for i in range(3):
        c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": f"Das ist Satz Nummer {i}", "at": i})
    html = c.get(f"{loc}?w={first}").text
    tabs = re.findall(r'href="/ueben/s/\d+\?a=(\d+)&amp;w=(\d+)#jetzt"', html)
    assert [int(i) for i, _ in tabs] == [i for i, it in enumerate(items[:3]) if it["word_id"] == first]
    assert {int(x) for _, x in tabs} == {first} and 'data-active="true"' in html
    # a task of another word drops the filter; an unknown word is ignored
    assert "&amp;w=" not in c.get(f"{loc}?w={first}&a=1").text
    assert "&amp;w=" not in c.get(f"{loc}?w=999").text
    # a grammar session has no word sidebar
    assert "Wörter dieser Übung" not in c.get("/ueben?neu=1&modus=grammatik").text


def test_each_tab_keeps_its_own_open_session_and_the_word_batch_survives_grammar(env):
    app, store, a, _ = env
    c = login(app, "anna")
    csrf = c.cookies.get("wort_csrf")
    saetze = int(start(c, store, a, "saetze").rsplit("/", 1)[1])
    c.post(f"/ueben/s/{saetze}/answer", data={"csrf": csrf, "text": "Das ist ein Satz hier", "at": 0})
    abfrage = int(start(c, store, a, "abfrage").rsplit("/", 1)[1])
    grammar = int(c.post("/ueben/grammatik/modalverben", data={"csrf": csrf}).headers["location"].rsplit("/", 1)[1])
    # every tab resumes its own session; the newest open one is the default
    assert c.get("/ueben?modus=saetze").headers["location"] == f"/ueben/s/{saetze}#jetzt"
    assert c.get("/ueben?modus=abfrage").headers["location"] == f"/ueben/s/{abfrage}#jetzt"
    assert c.get("/ueben?modus=grammatik").headers["location"] == f"/ueben/s/{grammar}#jetzt"
    assert c.get("/ueben").headers["location"] == f"/ueben/s/{grammar}#jetzt"
    # every Üben page shows the three tabs, an open session with its progress
    html = c.get(f"/ueben/s/{grammar}").text
    for key in ("saetze", "abfrage", "grammatik"):
        assert f'href="/ueben?modus={key}"' in html
    assert '<span class="wort-modes__count">1 / ' in html.split('href="/ueben?modus=saetze"')[1].split("</li>")[0]
    assert 'href="/ueben?modus=grammatik" aria-current="page"' in html
    # the start page (neu) offers to resume this tab's session, and still the words of the last word session
    page = c.get("/ueben?neu=1&modus=saetze").text
    assert f'href="/ueben/s/{saetze}#jetzt"' in page and ">Fortsetzen<" in page and "Dieselben Wörter noch einmal" in page
    # a new session of a tab closes that tab's old one, not the others
    start(c, store, a, "saetze")
    assert store.practice(a, saetze)["pos"] == len(store.practice(a, saetze)["items"])
    assert store.practice(a, saetze)["items"][0]["answer"] == "Das ist ein Satz hier"  # answers kept
    assert store.practice(a, abfrage)["pos"] == 0 and store.practice(a, grammar)["pos"] == 0
    # another user's open sessions never show up
    b = login(app, "ben")
    assert b.get("/ueben?modus=saetze").status_code == 200


def test_a_sentence_mistake_links_to_its_grammar_topic_without_the_ai(tmp_path, dict_path):
    from app import grammar, hints
    article = {"fragment": "der Garten", "message": "m", "replacements": ["den Garten"], "rule": "DE_AGREEMENT",
               "category": "GRAMMAR"}
    assert grammar.topic_for(hints.mistake_kind(article)) == "praepositionen"
    assert grammar.topic_for(hints.mistake_kind({"fragment": "x", "replacements": ["y"]})) is None  # AI remark
    assert grammar.topic_for("spelling") is None
    issue = Issue("Falscher Artikel", 9, 3, ["den"], "DE_AGREEMENT", "GRAMMAR")
    app = create_app(db_path=tmp_path / "web.db", dict_path=dict_path, secure_cookies=False, checker=lambda s: [issue])
    store = WebStore(tmp_path / "web.db")
    uid = store.create_user("anna", auth.hash_password(PASSWORD)).id
    store.add_word(uid, "Haus", "noun")
    c = login(app, "anna")
    loc = start(c, store, uid, "saetze")
    sid = loc.rsplit("/", 1)[1]
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Ich sehe der Garten dort"})
    html = c.get(loc).text
    assert html.count('href="/grammatik/praepositionen"') == 1  # once, in the explained mistake
    assert html.count(">Thema üben: Präpositionen und Kasus<") == 1
    pane = c.get(f"{loc}?fehler=0-1").text
    assert ">Thema üben: Präpositionen und Kasus<" in pane


def test_feedback_is_always_hidden_under_its_answer_behind_explain_more(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = int(loc.rsplit("/", 1)[1])
    csrf = c.cookies.get("wort_csrf")
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": csrf, "text": "Das ist ein Satz hier", "at": 0})
    feedback = lambda html: re.findall(r'<div class="wort-review" id="fb-0-\d+"( hidden)?>', html)
    for i in range(2):
        html = c.get(loc).text
        # the first answer has something to explain and starts hidden; a retry with nothing more has no extra block
        assert feedback(html) == [" hidden"] and html.count('aria-expanded="false">Mehr erklären<') == 1
        assert html.count('class="wort-verdict"') == i + 1  # every attempt's verdict is on the page
        c.post(f"/ueben/s/{sid}/again", data={"csrf": csrf, "text": f"Noch ein Satz Nummer {i}", "at": 0})


# --- GUI refresh (2026-10-30): the pieces that were wrong on the screen and are guarded here ----------------------

def test_quiz_page_does_not_colour_buttons_by_the_words_article_and_keeps_send_in_the_card(env):
    app, store, a, _ = env
    c = login(app, "anna")
    haus = [w.id for w in store.words(a) if w.lemma == "Haus"]  # a noun: it has an article (a verb would not)
    loc = start(c, store, a, "abfrage", ids=haus)
    html = c.get(loc).text
    # the word's article lives on its own heading; text-button reads a context variable `article` and would paint
    # every button of the page (sign out, theme, look up, send …) in the article's colour
    assert not re.findall(r"<(?:a|button)\b[^>]*data-article", html)
    assert 'class="wort-quiz__word"' in html
    card = html.split('class="wort-card"', 1)[1].split("</section>", 1)[0]
    assert 'action="/ueben/s/%s/answer"' % loc.rsplit("/", 1)[1] in card and ">Senden<" in card  # form and Send together


def test_the_verdict_is_on_the_page_before_explain_more_is_pressed(env):
    app, store, a, _ = env
    c = login(app, "anna")
    loc = start(c, store, a, "saetze")
    sid = loc.rsplit("/", 1)[1]
    c.post(f"/ueben/s/{sid}/answer", data={"csrf": c.cookies.get("wort_csrf"), "text": "Das ist ein Satz hier", "at": 0})
    html = c.get(loc).text
    verdict = html.split('class="wort-verdict"', 1)[1].split("</section>", 1)[0]
    assert 'aria-label="Bewertung"' in html and "wort-badge" in verdict  # a badge: glyph, word and colour
    # the verdict card comes before the hidden explanation, never inside it
    assert html.index('class="wort-verdict"') < html.index('class="wort-review"')
    assert 'class="wort-review"' in html and "wort-verdict" not in html.split('class="wort-review"', 1)[1].split("</section>", 1)[0]


def test_practice_pages_have_one_h1_a_skip_link_the_open_mode_marked_and_german_text_marked_as_german(env):
    app, store, a, _ = env
    c = login(app, "anna")
    pages = {"start": c.get("/ueben?neu=1&modus=saetze").text, "grammar": c.get("/ueben?neu=1&modus=grammatik").text}
    loc = start(c, store, a, "saetze")
    pages["session"] = c.get(loc).text
    pages["quiz"] = c.get(start(c, store, a, "abfrage")).text
    for name, html in pages.items():
        assert html.count("<h1") == 1, name
        assert 'class="wort-skip" href="#main"' in html and 'id="main"' in html, name
        assert html.count('aria-current="page"') >= 1 and 'role="tablist"' not in html, name  # mode bar, no fake tabs
    assert 'class="ds-message__text" lang="de"' in pages["session"]  # the task is German text in any interface language
    assert 'class="wort-modes"' in pages["start"] and html.count('<ul class="wort-modes">') == 1


def test_start_page_names_the_words_it_would_use(env):
    app, store, a, _ = env
    c = login(app, "anna")
    html = c.get("/ueben?neu=1&modus=saetze").text
    weakest = html.split('aria-labelledby="start-weakest"', 1)[1].split("</section>", 1)[0]
    assert ">Haus<" in weakest and ">gehen<" in weakest and 'name="preset" value="weakest"' in weakest
