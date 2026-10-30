import gzip
import json

import pytest

from wort.dictionary.ukrainian import Ukrainian, import_file, parse


def raw(word, pos, translations, lang="de", in_sense=True):
    trs = [{"lang_code": code, "word": w, "sense_index": i} for code, w, i in translations]
    entry = {"word": word, "pos": pos, "lang_code": lang}
    if in_sense:
        entry["senses"] = [{"translations": trs}]
    else:
        entry["translations"] = trs
    return entry


ROWS = [
    raw("Wohnung", "noun", [("en", "flat", "1"), ("uk", "житло", "2"), ("uk", "квартира", "1")]),
    raw("Bank", "noun", [("uk", "лава", "1")]),
    raw("Bank", "noun", [("uk", "банк", "1"), ("uk", "лава", "2")], in_sense=False),  # homograph: merged
    raw("tief", "adj", [("uk", "глибокий", "1")]),
    raw("tief", "adv", [("uk", "глибоко", "1")]),
    raw("Wohnung", "noun", [("uk", "чужа", "1")], lang="nl"),  # not German
    raw("Haus", "noun", [("ru", "дом", "1")]),  # no Ukrainian
    raw("<b>x", "noun", [("uk", "x", "1")]),  # unsafe lemma
]


@pytest.fixture
def uk(tmp_path):
    src = tmp_path / "dump.jsonl.gz"
    with gzip.open(src, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS) + "\nnot json\n")
    db = tmp_path / "dictionary-uk.db"
    assert import_file(src, db) == 4  # Wohnung, Bank, tief adj + adv
    return Ukrainian(db)


def test_sense_order_and_other_languages_dropped(uk):
    assert uk.translations("Wohnung") == ["квартира", "житло"]
    assert uk.translations("wohnung") == ["квартира", "житло"]  # normalized like the main dictionary
    assert uk.translations("Haus") == []


def test_homographs_merge_without_duplicates(uk):
    assert uk.translations("Bank", "noun") == ["лава", "банк"]


def test_part_of_speech_preferred_with_fallback(uk):
    assert uk.translations("tief", "adv") == ["глибоко"]
    assert uk.translations("tief", "adj") == ["глибокий"]
    assert uk.translations("tief", "verb") in (["глибоко"], ["глибокий"])


def test_unsafe_entries_skipped():
    assert parse(raw("<b>x", "noun", [("uk", "x", "1")])) is None
    assert parse(raw("Ort", "noun", [("uk", "<script>", "1")])) is None


def test_missing_file_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        Ukrainian(tmp_path / "nope.db")


def en(word, pos, pairs, lang="en"):
    return {"word": word, "pos": pos, "lang_code": lang,
            "senses": [{"translations": [{"lang_code": "uk", "word": w, "sense": s} for w, s in pairs]}]}


@pytest.fixture
def via(tmp_path, uk):
    from wort.dictionary.ukrainian import import_english
    src = tmp_path / "en.jsonl"
    src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        en("application", "noun", [("застосува́ння", "act of applying or putting to use"),
                                   ("заява", "formal request, e.g. for a job or a permit")]),
        en("request", "noun", [("прохання", "act of asking"), ("запит", "formal request")]),
        en("deep", "adj", [("глибокий", "extending far down")]),
        en("deep", "noun", [("глибина", "the deep part")]),
        en("application", "noun", [("x", "y")], lang="fr"),
    ]), encoding="utf-8")
    db = tmp_path / "dictionary-en-uk.db"
    assert import_english(src, db) == 4  # application, request, deep adj + noun (not the French row)
    return Ukrainian(tmp_path / "dictionary-uk.db", db)


def test_via_english_prefers_the_sense_that_matches_the_glosses(via):
    # Antrag: "application, request, motion, petition" -> the formal-request sense of "application" (its sense
    # shares "request" with the glosses), not "use"; "request" has no sense sharing a word, so its first one
    assert via.via_english(["application, request, motion, petition"], "noun") == ["заява", "прохання"]


def test_via_english_strips_stress_and_respects_part_of_speech(via):
    assert via.via_english(["use, application"], "noun") == ["застосування"]  # shares "use"; no U+0301 left
    assert via.via_english(["deep (having a long distance to the bottom)"], "adj") == ["глибокий"]


def test_via_english_is_empty_without_the_file(uk):
    assert uk.via_english(["application"], "noun") == []
