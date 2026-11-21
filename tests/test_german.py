import json  # noqa: F401

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
