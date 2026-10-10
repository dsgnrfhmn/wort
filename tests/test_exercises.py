import random

import pytest

from wort.exercises import TYPES, build_session, pick_exercise
from wort.exercises import article, forms, question, sentence, translate
from wort.exercises.base import compare
from wort.exercises.grammar_check import Issue, server_url
from wort.dictionary.lookup import Entry


class FixedRng(random.Random):
    """Always takes the first candidate so tests are deterministic."""

    def choice(self, seq):
        return seq[0]

    def random(self):
        return 0.0


def test_compare():
    assert compare("Häuser", "Häuser")[0] == "correct"
    assert compare("haeuser", "Häuser")[0] == "correct"
    assert compare("Hauser", "Häuser")[0] == "almost"
    assert compare("Haus", "Häuser")[0] == "wrong"


def test_translate_de_to_en(dictionary):
    ex = translate._de_to_en(dictionary.find_lemma("beabsichtigen"))
    assert ex.check("to intend").ok
    assert ex.check("plan").ok
    assert ex.check("intnd").verdict == "almost"
    assert ex.check("go").verdict == "wrong"


def test_translate_en_to_de_checks_article(dictionary):
    ex = translate._en_to_de(dictionary.find_lemma("Haus"))
    assert ex.check("das Haus").ok
    assert ex.check("der Haus").verdict == "almost"
    r = ex.check("Haus")
    assert r.ok and "article" in r.feedback


def test_article(dictionary):
    ex = article.make(dictionary.find_lemma("Katze"), random.Random(0))
    assert ex.check("die").ok
    assert ex.check("2").ok  # by number
    assert not ex.check("der").ok
    assert not article.TYPE.available(dictionary.find_lemma("gehen"))


def test_forms(dictionary):
    ex = forms.make(dictionary.find_lemma("Haus"), FixedRng())
    assert ex.prompt.startswith("Plural")
    assert ex.check("Häuser").ok
    verb = dictionary.find_lemma("gehen")
    perfekt = [c for c in forms.candidates(verb) if c[0].startswith("Perfekt")][0]
    assert perfekt[2] == ["ist gegangen"]
    present = forms.make(verb, FixedRng())
    assert present.check("du gehst").ok  # pronoun is allowed


def test_question(dictionary):
    ex = question.make(dictionary.find_lemma("gehen"), FixedRng())
    assert ex.choices == ["haben", "sein"]
    assert ex.check("sein").ok and not ex.check("1").ok
    pl = question.make(dictionary.find_lemma("Haus"), random.Random(1))
    assert "Häuser" in pl.choices and len(pl.choices) == 4
    assert question.umlauted("Haus") == "Häus"


def test_sentence_checks_form_and_grammar(dictionary):
    entry = dictionary.find_lemma("gehen")
    ex = sentence.make(entry, FixedRng(), checker=lambda text: [])
    assert ex.prompt.endswith("Präsens, ich")
    assert ex.check("Ich gehe heute ins Kino.").ok
    assert ex.check("Ich ging gestern ins Kino.").verdict == "wrong"
    assert ex.check("gehe").verdict == "wrong"

    issue = Issue("Falsches Verb", 4, 4, ["gehe"])
    with_issue = sentence.make(entry, FixedRng(), checker=lambda text: [issue])
    r = with_issue.check("Ich gehe heute Kino.")
    assert r.verdict == "almost" and "Falsches Verb" in r.feedback

    offline = sentence.make(entry, FixedRng(), checker=lambda text: None)
    assert offline.check("Ich gehe heute ins Kino.").ok


def test_separable_sentence(dictionary):
    ex = sentence.make(dictionary.find_lemma("anfangen"), FixedRng(), checker=lambda t: [])
    assert ex.check("Ich fange morgen mit der Arbeit an.").ok
    assert ex.check("Ich fange morgen mit der Arbeit.").verdict == "wrong"


@pytest.mark.parametrize("pos, forms", [
    ("noun", []),
    ("verb", []),
    ("adj", []),
    ("noun", [("Information", ("genitive", "singular"))]),
    ("verb", [("regnet", ("present", "third-person", "singular", "subordinate-clause"))]),
    ("adj", [("einzigartige", ("nominative", "singular", "feminine", "weak"))]),
])
def test_sentence_unavailable_without_required_forms(pos, forms):
    entry = Entry(1, "word", pos, gender="f", glosses=["meaning"], forms=forms)
    assert not sentence.TYPE.available(entry)


@pytest.mark.parametrize("lemma", ["Information", "regnen", "einzigartig"])
def test_sentence_generation_rejects_missing_targets(sentence_dictionary, lemma):
    entry = sentence_dictionary.find_lemma(lemma)
    with pytest.raises(ValueError, match="No sentence targets"):
        sentence.make(entry, FixedRng())


def test_sentence_without_inflections_can_use_adverb_lemma():
    entry = Entry(1, "heute", "adv", glosses=["today"])
    assert sentence.TYPE.available(entry)
    ex = sentence.make(entry, FixedRng(), checker=lambda text: [])
    assert ex.check("Heute ist Montag.").ok


def test_mixed_session_uses_available_exercises(sentence_dictionary, store):
    class PreferSentenceRng(FixedRng):
        def choices(self, population, weights=None, *, cum_weights=None, k=1):
            return [next((t for t in population if t.kind == "sentence"), population[0])]

    for lemma, pos in [("Information", "noun"), ("regnen", "verb"), ("einzigartig", "adj"), ("Haus", "noun")]:
        store.add_word(lemma, pos, None)
    session = build_session(store, sentence_dictionary, rng=PreferSentenceRng())
    assert len(session) == 4
    assert [word.lemma for word, ex in session if ex.kind == "sentence"] == ["Haus"]
    assert all(ex.kind != "sentence" for word, ex in session if word.lemma != "Haus")
    assert all(s.attempts == 0 for s in store.all_stats())


def test_sentence_session_skips_unavailable_words_before_limit(sentence_dictionary, store):
    for lemma, pos in [("Information", "noun"), ("regnen", "verb"), ("einzigartig", "adj"), ("Haus", "noun")]:
        store.add_word(lemma, pos, None)
    session = build_session(store, sentence_dictionary, limit=1, kinds={"sentence"}, rng=FixedRng())
    assert [(word.lemma, ex.kind) for word, ex in session] == [("Haus", "sentence")]


def test_sentence_session_with_no_usable_forms_is_empty(sentence_dictionary, store):
    for lemma, pos in [("Information", "noun"), ("regnen", "verb"), ("einzigartig", "adj")]:
        store.add_word(lemma, pos, None)
    assert build_session(store, sentence_dictionary, kinds={"sentence"}, rng=FixedRng()) == []
    assert all(s.attempts == 0 for s in store.all_stats())


def test_languagetool_stays_local(monkeypatch):
    monkeypatch.setenv("WORT_LT_URL", "https://api.languagetool.org")
    assert server_url() is None
    monkeypatch.setenv("WORT_LT_URL", "http://127.0.0.1:8081")
    assert server_url() == "http://127.0.0.1:8081"


@pytest.mark.parametrize("lemma", ["Haus", "gehen", "anfangen", "schön", "Katze", "beabsichtigen"])
def test_every_available_type_builds(dictionary, lemma):
    entry = dictionary.find_lemma(lemma)
    for t in TYPES.values():
        if t.available(entry):
            ex = t.make(entry, random.Random(3))
            assert ex.prompt and ex.check("xyz").verdict in ("wrong", "almost", "correct")


def test_build_session(dictionary, store):
    for lemma, pos in [("Haus", "noun"), ("gehen", "verb"), ("schön", "adj")]:
        store.add_word(lemma, pos, None)
    session = build_session(store, dictionary, limit=2, rng=random.Random(0))
    assert len(session) == 2
    only_articles = build_session(store, dictionary, rng=random.Random(0), kinds={"article"})
    assert {ex.kind for _, ex in only_articles if ex.entry.pos == "noun"} == {"article"}
    assert pick_exercise(dictionary.find_lemma("Haus"), {}, random.Random(0)).kind in TYPES


def test_languagetool_client_against_local_server(monkeypatch):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs

    from wort.exercises import grammar_check

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            seen.update(path=self.path, language=body["language"][0], text=body["text"][0])
            payload = {"matches": [{"message": "Kongruenz", "offset": 4, "length": 4,
                                    "replacements": [{"value": "gehe"}, {"value": "ging"}]}]}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.delenv("WORT_LT_DISABLE")
        monkeypatch.setenv("WORT_LT_URL", f"http://127.0.0.1:{server.server_port}")
        issues = grammar_check.check("Ich gehst heute.")
        assert seen == {"path": "/v2/check", "language": "de-DE", "text": "Ich gehst heute."}
        assert issues == [grammar_check.Issue("Kongruenz", 4, 4, ["gehe", "ging"])]
    finally:
        server.shutdown()

    monkeypatch.setenv("WORT_LT_URL", "http://127.0.0.1:1")  # nothing listening
    assert grammar_check.check("Ich gehe.") is None
