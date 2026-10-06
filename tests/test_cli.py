import io
import re
import json
import shutil
import sys

import pytest

from wort import cli, paths
from wort.dictionary import grammar as g
from wort.dictionary.importer import MAX_EXAMPLES, import_file
from wort.dictionary.lookup import Dictionary
from wort.render.card import render_card
from wort.store import Store
from wort.transfer import FORMAT_VERSION, export_words, parse_export


@pytest.fixture
def home(dict_path):
    shutil.copy(dict_path, paths.dictionary_db())


def _stdin(monkeypatch, text: str, tty: bool = False) -> None:
    stream = io.StringIO(text)
    stream.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", stream)


def _queries():
    return [(q.query, q.found) for q in Store(paths.user_db()).queries()]


def test_verb_perfect_and_future(dictionary):
    gehen = dictionary.find_lemma("gehen")
    assert g.perfect(gehen, "ich") == "bin gegangen"
    assert g.perfect(gehen, "wir") == "sind gegangen"
    assert g.future1(gehen, "er") == "wird gehen"
    assert g.perfect(dictionary.find_lemma("anfangen"), "er") == "hat angefangen"


def _render(entry) -> str:
    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=False)
    console.print(render_card(entry))
    return console.export_text()


def test_card_shows_all_tenses(dictionary):
    out = _render(dictionary.find_lemma("gehen"))
    for header in ("Präsens", "Präteritum", "Perfekt", "Futur I"):
        assert header in out
    assert "ich bin gegangen" in out and "er wird gehen" in out


def test_card_lines_are_square_and_palette_is_small(dictionary):
    import re

    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="truecolor")
    console.print(render_card(dictionary.find_lemma("gehen")))
    out = console.export_text(styles=True)
    assert "┌" in out and "└" in out and "╭" not in out and "╰" not in out  # square corners
    used = set(re.findall(r"38;5;(\d+)", out))
    assert used <= {"242", "88"}  # grey text and the burgundy verb color, nothing else
    assert not re.search(r"38;2;", out)  # no truecolor foregrounds
    assert not re.search(r"\x1b\[(?:\d+;)*(?:3[0-79]|9[0-7])m", out)  # no 16-color foregrounds


def _first_content_line(dictionary, word: str) -> str:
    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="256")
    console.print(render_card(dictionary.find_lemma(word)))
    return console.export_text(styles=True).split("\n")[1]  # the card's main line


def test_main_line_takes_the_word_class_color(dictionary):
    assert "\x1b[1;38;5;88m" in _first_content_line(dictionary, "gehen")  # verb: burgundy
    assert "\x1b[1;38;5;160mKatze" in _first_content_line(dictionary, "Katze")  # die: red
    assert "\x1b[1;38;5;34mHaus" in _first_content_line(dictionary, "Haus")  # das: green
    assert "\x1b[1;38;5;54mschön" in _first_content_line(dictionary, "schön")  # adj: dark purple


def test_title_meta_stays_grey(dictionary):
    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="256")
    console.print(render_card(dictionary.find_lemma("Katze")))
    title = console.export_text(styles=True).split("\n")[0]
    assert "\x1b[1;38;5;160mKatze" in title  # lemma in the word color, bold
    assert "38;5;242m  Substantiv" in title and "\x1b[1;38;5;242m  Substantiv" not in title  # meta: grey, not bold


def test_main_line_keeps_article_colors_inside(dictionary):
    line = _first_content_line(dictionary, "Haus")  # das Haus · des Hauses · die Häuser
    assert "38;5;34mdas" in line and "38;5;242mdie" in line  # das keeps its color, plural die is grey
    assert "38;5;34mdes" in line  # other prefix words take the noun's color


def test_articles_are_colored(dictionary):
    import re

    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="256")
    console.print(render_card(dictionary.find_lemma("Haus")))  # das Haus, die Häuser, der/den/des in the table
    out = console.export_text(styles=True)
    assert re.search(r"\x1b\[(?:\d+;)*38;5;34m(?:das)", out)    # das: green
    assert re.search(r"\x1b\[(?:\d+;)*38;5;33m(?:der)", out)    # der: blue (genitive plural)
    assert not re.search(r"38;5;160m(?:die)", out)               # Haus has no singular `die`


def test_plural_die_is_grey_singular_die_is_red(dictionary):
    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="256")
    console.print(render_card(dictionary.find_lemma("Katze")))  # die Katze (sg), die Katzen (pl)
    lines = console.export_text(styles=True).split("\n")
    header = lines[1]
    nom = next(l for l in lines if "Nom" in l)
    gen = next(l for l in lines if "Gen" in l)
    red, grey = "3;38;5;160mdie", "3;38;5;242mdie"
    assert red in header and grey in header           # die Katze · … · die Katzen
    assert header.index(red) < header.index(grey)     # singular first, plural last
    assert red in nom and grey in nom                 # Nom: die Katze | die Katzen
    assert header.count(red) == 1 and nom.count(red) == 1
    assert "3;38;5;33mder" in gen                     # Gen: der Katze | der Katzen (plural der stays blue)


@pytest.mark.parametrize("term", ["screen", "xterm", "tmux"])
def test_console_upgrades_8_color_terminals_to_256(monkeypatch, term):
    monkeypatch.setenv("TERM", term)
    monkeypatch.delenv("COLORTERM", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert cli._make_console(force_terminal=True).color_system == "256"


def test_console_keeps_truecolor_and_no_color(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    assert cli._make_console(force_terminal=True).color_system == "truecolor"
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("COLORTERM")
    assert cli._make_console(force_terminal=True).color_system is None


def test_only_verb_endings_are_underlined(dictionary):
    from rich.console import Console

    def styled(word):
        console = Console(width=120, record=True, force_terminal=True, color_system="256")
        console.print(render_card(dictionary.find_lemma(word)))
        return console.export_text(styles=True)

    verb, noun = styled("gehen"), styled("Haus")
    assert "\x1b[1;4mt\x1b[0m" in verb and "\x1b[1;4mgangen" in verb  # geh[t], ge[gangen]
    assert "\x1b[1;4m" not in noun and "\x1b[4m" not in noun  # noun endings stay plain bold


def test_card_shows_all_examples(dictionary):
    gehen = dictionary.find_lemma("gehen")
    gehen.examples = [(f"Satz {i}", f"sentence {i}") for i in range(7)]
    out = _render(gehen)
    assert all(f"Satz {i}" in out and f"sentence {i}" in out for i in range(7))


def test_importer_keeps_more_examples(tmp_path):
    raw = json.loads(next(l for l in open("tests/fixtures/german_sample.jsonl", encoding="utf-8") if '"gehen"' in l))
    raw["senses"][0]["examples"] = [{"text": f"Satz {i}", "english": f"s {i}"} for i in range(MAX_EXAMPLES + 5)]
    src = tmp_path / "one.jsonl"
    src.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    import_file(src, tmp_path / "d.db")
    assert len(Dictionary(tmp_path / "d.db").find_lemma("gehen").examples) == MAX_EXAMPLES


def test_wort_word_logs_query(home, capsys):
    cli.main(["gehen"])
    assert "Präsens" in capsys.readouterr().out
    assert _queries() == [("gehen", True)]
    assert Store(paths.user_db()).words() == []  # a lookup does not touch the practice list


def test_wort_form_and_english_queries_log_what_was_typed(home):
    cli.main(["ging"])
    cli.main(["house"])
    assert _queries() == [("ging", True), ("house", True)]


def test_not_found_is_explicit_and_still_logged(home, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["qwertzuiop"])
    assert e.value.code == 1
    assert "Nothing found" in capsys.readouterr().out
    assert _queries() == [("qwertzuiop", False)]


def test_command_words_need_explicit_t(home, capsys):
    with pytest.raises(SystemExit):  # not in the fixture dictionary: exit code 1
        cli.main(["t", "list"])  # `wort list` alone would be the command
    assert _queries() == [("list", False)]


def test_session_looks_up_each_line_until_quit(home, monkeypatch, capsys):
    _stdin(monkeypatch, "gehen\n\n  Haus  \nqwertzuiop\nquit\nnever reached\n")
    cli.main([])
    out = capsys.readouterr().out
    assert "Präsens" in out and "Nothing found" in out
    assert _queries() == [("gehen", True), ("Haus", True), ("qwertzuiop", False)]


def test_session_ends_on_eof(home, monkeypatch):
    _stdin(monkeypatch, "gehen\n")
    cli.main([])
    assert _queries() == [("gehen", True)]


def test_session_treats_command_words_as_words(home, monkeypatch):
    _stdin(monkeypatch, "list\nquit\n")
    cli.main([])
    assert _queries() == [("list", False)]


def test_session_without_dictionary_explains(monkeypatch, capsys):
    _stdin(monkeypatch, "gehen\n")
    with pytest.raises(SystemExit):
        cli.main([])
    assert "has not been imported" in capsys.readouterr().out


def test_history_command(home, capsys):
    cli.main(["gehen"])
    capsys.readouterr()
    cli.main(["history"])
    out = capsys.readouterr().out
    assert "gehen" in out and "yes" in out and "┌" in out


def test_export_roundtrip(home, tmp_path):
    cli.main(["Haus"])
    cli.main(["add", "gehen"])
    with pytest.raises(SystemExit):
        cli.main(["qwertzuiop"])
    target = tmp_path / "out.json"
    cli.main(["export", str(target)])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["format_version"] == FORMAT_VERSION
    assert set(data["queries"][0]) == {"query", "found", "queried_at"}
    assert set(data["words"][0]) == {"lemma", "pos", "added_at"}  # no db ids

    doc = parse_export(data)
    assert [(w.lemma, w.pos) for w in doc.words] == [("gehen", "verb")]
    assert [(q.query, q.found) for q in doc.queries] == [("Haus", True), ("qwertzuiop", False)]


def test_export_to_stdout(home, capsys):
    cli.main(["export"])
    data = json.loads(capsys.readouterr().out)
    assert data["words"] == [] and data["queries"] == []


GOOD_Q = {"query": "Haus", "found": True, "queried_at": "2026-10-04T10:00:00"}
GOOD_W = {"lemma": "Haus", "pos": "noun", "added_at": "2026-10-04T10:00:00"}


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"format_version": 1, "words": [], "queries": []},
        {"format_version": 2, "words": [], "queries": "x"},
        {"format_version": 2, "words": [], "queries": [1]},
        {"format_version": 2, "words": [{"lemma": "Haus", "pos": "noun"}], "queries": []},
        {"format_version": 2, "words": [{**GOOD_W, "lemma": ""}], "queries": []},
        {"format_version": 2, "words": [{**GOOD_W, "lemma": "x" * 101}], "queries": []},
        {"format_version": 2, "words": [{**GOOD_W, "added_at": "yesterday"}], "queries": []},
        {"format_version": 2, "words": [], "queries": [{**GOOD_Q, "found": "yes"}]},
        {"format_version": 2, "words": [], "queries": [{**GOOD_Q, "query": ""}]},
        {"format_version": 2, "words": [], "queries": [{**GOOD_Q, "queried_at": "x"}]},
    ],
)
def test_parse_export_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_export(bad)


def test_export_words_empty(store):
    doc = export_words(store)
    assert doc["words"] == [] and doc["queries"] == []


def _interactive(monkeypatch, text: str, rows: int = 100) -> None:
    import os

    _stdin(monkeypatch, text, tty=True)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli.shutil, "get_terminal_size", lambda *a, **k: os.terminal_size((80, rows)))


def test_session_collapses_previous_card_into_one_line(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nHaus\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    erases = [int(n) for n in re.findall(r"\x1b\[(\d+)A\x1b\[J", out)]
    assert len(erases) == 2  # Haus replaces the gehen card; quit replaces the Haus card
    assert erases[0] == _card_lines(out, "gehen") + 1 + 1  # echo line + card + the line just typed
    assert "gehen — to go, to walk" in out
    assert "Haus — house; home" in out
    assert _queries() == [("gehen", True), ("Haus", True)]


def _card_lines(out: str, word: str) -> int:
    start = out.index(f"wort> {word}")
    return out[start : out.index("┘", start)].count("\n")  # lines between the echo line and the card's last line


def test_collapse_summary_for_english_query_and_not_found(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nqwertzuiop\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    assert "house — das Haus / das Gebäude" in out
    assert "qwertzuiop — nothing found" in out


def test_blank_lines_are_counted_when_collapsing(home, monkeypatch, capsys):
    _interactive(monkeypatch, "qwertzuiop\n\n\nHaus\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    # echo line + "Nothing found." + two blank inputs + the line just typed
    assert re.findall(r"\x1b\[(\d+)A\x1b\[J", out)[0] == "5"


def test_tall_card_is_erased_only_as_far_as_the_screen_reaches(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nHaus\nquit\n", rows=10)
    cli.main([])
    out = capsys.readouterr().out
    assert re.findall(r"\x1b\[(\d+)A\x1b\[J", out)[0] == "9"  # rows - 1, never more than the cursor can move
    assert "gehen — to go, to walk" in out


def _plain(out: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", out)


def test_session_shows_banner_on_a_terminal_only(home, monkeypatch, capsys):
    _interactive(monkeypatch, "quit\n")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert all(line.rstrip() in out for line in cli.BANNER.split("\n"))
    assert out.index(cli.BANNER.split("\n")[0].rstrip()) < out.index("Type a word")

    _stdin(monkeypatch, "quit\n")  # not a terminal: no banner, nothing but results
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    cli.main([])
    assert cli.BANNER.split("\n")[1] not in _plain(capsys.readouterr().out)


def test_wort_with_a_word_does_not_show_the_banner(home, capsys):
    cli.main(["gehen"])
    assert cli.BANNER.split("\n")[1] not in _plain(capsys.readouterr().out)


def test_clear_keeps_the_banner(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nclear\nHaus\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    first = cli.BANNER.split("\n")[1]
    clear_at = out.index("\x1b[H\x1b[2J")
    assert first in _plain(out[:clear_at])  # banner at the start
    assert first in _plain(out[clear_at:])  # and again right after the screen was cleared
    assert _queries() == [("gehen", True), ("Haus", True)]  # `clear` is not a lookup


def test_clear_resets_collapsing(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nclear\nHaus\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    # Haus must not erase lines that no longer exist: only its own collapse on `quit`
    assert len(re.findall(r"\x1b\[\d+A\x1b\[J", out)) == 1


def test_clear_does_nothing_when_piped(home, monkeypatch, capsys):
    _stdin(monkeypatch, "clear\nquit\n")
    cli.main([])
    assert "\x1b[2J" not in capsys.readouterr().out and _queries() == []


def test_ctrl_l_is_bound_to_clear(home, monkeypatch):
    import readline

    calls = []
    monkeypatch.setattr(readline, "parse_and_bind", calls.append)
    monkeypatch.setattr(readline, "backend", "readline", raising=False)
    _interactive(monkeypatch, "quit\n")
    cli.main([])
    assert calls == [r'"\C-l": "\C-a\C-kclear\C-m"']
