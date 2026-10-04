from lernen.dictionary import grammar as g
from lernen.dictionary.importer import clean_form, gloss_keys


def test_import_skips_form_of_and_other_languages(dictionary):
    assert dictionary.conn.execute("SELECT value FROM meta WHERE key='entries'").fetchone()[0] == "10"
    assert dictionary.lookup_german("Häuser")[0].lemma == "Haus"  # via form index, not the form-of entry


def test_entry_metadata(dictionary):
    haus = dictionary.find_lemma("Haus")
    assert (haus.pos, haus.gender, haus.ipa) == ("noun", "n", "/haʊ̯s/")
    gehen = dictionary.find_lemma("gehen")
    assert (gehen.aux, gehen.conj, gehen.separable) == ("sein", "strong", False)
    assert dictionary.find_lemma("anfangen").separable


def test_lookup_umlaut_and_case_insensitive(dictionary):
    assert dictionary.lookup_german("schoen")[0].lemma == "schön"
    assert dictionary.lookup_german("haus")[0].lemma == "Haus"
    assert dictionary.lookup_german("ging")[0].lemma == "gehen"


def test_lookup_english_ranks_primary_sense_first(dictionary):
    german, english = dictionary.lookup("house")
    assert german == []
    assert [e.lemma for e in english] == ["Haus", "Gebäude"]
    assert dictionary.lookup("to start")[1][0].lemma == "anfangen"


def test_gloss_keys():
    assert list(gloss_keys("to intend, to plan (something)")) == ["intend", "plan"]


def test_clean_form():
    assert clean_form("das Haus") == "Haus"
    assert clean_form("ich gehe") == "gehe"
    assert clean_form("fange an") == "fange an"


def test_verb_forms(dictionary):
    v = dictionary.find_lemma("beabsichtigen")
    assert g.present(v, "du") == "beabsichtigst"  # not the subjunctive
    assert g.preterite(v, "er") == "beabsichtigte"
    assert g.principal_parts(v) == ["beabsichtigt", "beabsichtigte", "hat beabsichtigt"]
    a = dictionary.find_lemma("anfangen")
    assert g.present(a, "er") == "fängt an"  # main clause, not subordinate "anfängt"
    assert g.principal_parts(dictionary.find_lemma("gehen"))[-1] == "ist gegangen"


def test_noun_and_adj_forms(dictionary):
    haus = dictionary.find_lemma("Haus")
    assert g.plural(haus) == "Häuser"
    assert g.noun_form(haus, "dative", "plural") == "Häusern"
    assert g.with_article(haus, "Hauses", "genitive", "singular") == "des Hauses"
    schoen = dictionary.find_lemma("schön")
    assert (g.comparative(schoen), g.superlative(schoen)) == ("schöner", "am schönsten")


def test_split_ending():
    assert g.split_ending("beabsichtigte", "beabsichtig") == ("beabsichtig", "te")
    assert g.split_ending("ging", "geh") == ("", "ging")


def _entry(word, pos, gloss="g", **extra):
    return {"word": word, "lang_code": "de", "pos": pos, "senses": [{"glosses": [gloss]}], **extra}


def _form_of(word, target, pos="noun"):
    return {"word": word, "lang_code": "de", "pos": pos,
            "senses": [{"glosses": [f"inflection of {target}"], "tags": ["form-of"], "form_of": [{"word": target}]}]}


def _build(tmp_path, raws):
    from lernen.dictionary.importer import import_entries
    from lernen.dictionary.lookup import Dictionary

    import_entries(raws, tmp_path / "d.db")
    return Dictionary(tmp_path / "d.db")


def test_form_of_entries_become_pointers_to_the_lemma(tmp_path):
    # zigtausend has no forms; the plural exists only as a "form of" entry tagged with another pos
    d = _build(tmp_path, [_entry("zigtausend", "num", "many thousand"), _form_of("zigtausende", "zigtausend")])
    assert [e.lemma for e in d.lookup_german("zigtausende")] == ["zigtausend"]
    assert d.lookup_german("Zigtausende")[0].lemma == "zigtausend"  # case-insensitive like other lookups
    assert d.conn.execute("SELECT value FROM meta WHERE key='entries'").fetchone()[0] == "1"  # not stored as an entry
    assert d.conn.execute("SELECT value FROM meta WHERE key='form_pointers'").fetchone()[0] == "1"


def test_pointer_prefers_the_same_part_of_speech(tmp_path):
    d = _build(tmp_path, [_entry("Gehen", "noun"), _entry("gehen", "verb"), _form_of("gehens", "Gehen", "noun")])
    assert [e.pos for e in d.lookup_german("gehens")] == ["noun"]


def test_pointer_without_a_lemma_adds_nothing(tmp_path):
    d = _build(tmp_path, [_entry("Haus", "noun"), _form_of("xyzen", "xyz")])
    assert d.lookup_german("xyzen") == []
    assert d.conn.execute("SELECT value FROM meta WHERE key='form_pointers'").fetchone()[0] == "0"


def test_own_forms_are_not_duplicated_by_pointers(tmp_path):
    haus = _entry("Haus", "noun", forms=[{"form": "Häuser", "tags": ["plural"]}])
    d = _build(tmp_path, [haus, _form_of("Häuser", "Haus")])
    from lernen.text import normalize

    rows = d.conn.execute("SELECT count(*) FROM form_index WHERE form_norm = ?", (normalize("Häuser"),)).fetchone()[0]
    assert rows == 1  # indexed once, from the lemma's own form list
    assert [e.lemma for e in d.lookup_german("Häuser")] == ["Haus"]


def test_other_languages_and_wrong_pos_pointers_are_ignored(tmp_path):
    foreign = {**_form_of("zigtausende", "zigtausend"), "lang_code": "en"}
    d = _build(tmp_path, [_entry("zigtausend", "num"), foreign, {**_form_of("xx", "zigtausend"), "pos": "name"}])
    assert d.lookup_german("zigtausende") == [] and d.lookup_german("xx") == []
