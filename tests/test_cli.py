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
from wort.render.card import render_card, render_compact
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
    assert used <= {"242"}  # grey text only: a verb has no color of its own
    assert not re.search(r"38;2;", out)  # no truecolor foregrounds
    assert not re.search(r"\x1b\[(?:\d+;)*(?:3[0-8]|9[0-7])m", out)  # no 16-color foregrounds (39 = the terminal's default is fine)


def _first_content_line(dictionary, word: str) -> str:
    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="256")
    console.print(render_card(dictionary.find_lemma(word)))
    return console.export_text(styles=True).split("\n")[1]  # the card's main line


def test_main_line_takes_the_word_class_color(dictionary):
    verb = _first_content_line(dictionary, "gehen")
    assert "\x1b[1;39mgeh" in verb and "38;5;88" not in verb  # verb: bold in the terminal's text color (black on light)
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
    assert "38;5;242mdes" in line and "38;5;34mdes" not in line  # genitive article: grey


def test_only_nominative_singular_article_is_colored(dictionary):
    import re

    from rich.console import Console

    console = Console(width=120, record=True, force_terminal=True, color_system="256")
    console.print(render_card(dictionary.find_lemma("Haus")))  # das Haus, die Häuser, der/den/des in the table
    out = console.export_text(styles=True)
    assert re.search(r"\x1b\[(?:\d+;)*38;5;34m(?:das)", out)    # das: green
    assert not re.search(r"38;5;33m(?:der|den)", out)            # der/den (gen/dat/acc/plural) are not colored
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
    assert "3;38;5;242mder" in gen and "38;5;33m" not in gen  # Gen: der Katze | der Katzen, both grey


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


def test_session_history_shows_unique_queries_and_is_not_logged(home, monkeypatch, capsys):
    _stdin(monkeypatch, "gehen\nHaus\nhaus\ngehen\n/history\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    table = out[out.rindex("Query"):]
    assert table.count("gehen") == 1 and table.lower().count("haus") == 1  # no duplicates, case-insensitive
    assert re.search(r"│\s*1\s*│\s*haus", table) and re.search(r"│\s*2\s*│\s*gehen", table)  # numbered; order = last asked, newest at the bottom
    assert "Meaning" in table and "to go" in table and "house" in table and "Last" not in table
    assert "haus" in table and "Haus" not in table  # latest spelling wins
    assert [q for q, _ in _queries()] == ["gehen", "Haus", "haus", "gehen"]  # /history itself is not logged


def test_session_unknown_slash_command_is_not_looked_up_or_logged(home, monkeypatch, capsys):
    _stdin(monkeypatch, "/foo\n/history\n")
    cli.main([])
    assert "Unknown command: /foo" in capsys.readouterr().out
    assert _queries() == []


def test_session_history_without_queries(home, monkeypatch, capsys):
    _stdin(monkeypatch, "/history\n")
    cli.main([])
    assert "No queries yet." in capsys.readouterr().out


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
    start = out.index(f"{cli.PROMPT}{word}")
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
    assert cli.FOOTER in out and "type a word" not in out  # the command list, and no sentence about typing

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
    clear_at = out.rindex("\x1b[H\x1b[2J")
    assert clear_at > 0 and first in _plain(out[:clear_at])  # banner at the start
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


def _keys(monkeypatch, *keys: str) -> list[str]:
    """Pretend the terminal supports single-key input and feed the picker these keys."""
    import contextlib

    from wort import picker

    pending = list(keys)
    monkeypatch.setattr(picker, "usable", lambda: True)
    monkeypatch.setattr(picker, "cbreak", contextlib.nullcontext)
    monkeypatch.setattr(picker, "read_key", lambda: pending.pop(0))
    return pending


def test_several_results_show_a_numbered_compact_list(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    _keys(monkeypatch, "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "[1]" in out and "[2]" in out and "Haus" in out and "Gebäude" in out
    assert "Singular" not in out  # compact: nothing from the tables on
    assert "»" not in out  # nor the example sentences
    assert _queries() == [("house", True)]


def test_digit_opens_the_full_card_and_q_goes_back(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    left = _keys(monkeypatch, "1", "q", "q")
    cli.main([])
    assert "Singular" in _plain(capsys.readouterr().out)  # Haus opened in full
    assert left == []  # card, back to the list, closed


def test_j_moves_the_selection_and_enter_opens_it(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    _keys(monkeypatch, "j", "enter", "q", "q")
    cli.main([])
    assert "2/2" in _plain(capsys.readouterr().out)  # footer of the opened card: the second result


def test_digit_inside_an_open_card_switches_result(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    _keys(monkeypatch, "1", "2", "h", "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert out.index("1/2") < out.index("2/2")


def test_j_k_scroll_a_tall_card_by_pages(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n", rows=12)  # a full card is taller than 12 rows
    _keys(monkeypatch, "1", "j", "j", " ", "G", "g", "h", "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "j k scroll" in out and "1-11/" in out  # first page: 11 lines of the card (12 rows minus the hint row)
    assert "2-12/" in out  # one `j` later
    first_page = out.split("1-11/")[0].rsplit("┌─ Haus", 1)[1]
    assert "1/2" not in first_page and "Singular" in first_page  # the footer (last line) is not on the first page
    pages = [tuple(map(int, m)) for m in re.findall(r"(\d+)-(\d+)/(\d+)", out)]
    assert any(last == total for _, last, total in pages)  # space / G reach the end and stop there
    assert all(last <= total for _, last, total in pages)  # never scrolls past it


def test_other_key_closes_picker_and_prefills_next_word(home, monkeypatch, capsys):
    import readline

    _interactive(monkeypatch, "house\nquit\n")
    left = _keys(monkeypatch, "g")
    hooks = []
    monkeypatch.setattr(readline, "set_startup_hook", lambda f=None: hooks.append(f))
    cli.main([])
    assert left == []
    assert [h for h in hooks if h is not None]  # a hook that types "g" was installed for the next prompt


def test_picker_erases_its_own_output(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    _keys(monkeypatch, "q")
    cli.main([])
    assert re.search(r"\x1b\[\d+A\x1b\[J", capsys.readouterr().out)


def test_single_result_has_no_picker(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nquit\n")
    _keys(monkeypatch)  # reading any key would raise
    cli.main([])
    assert "Präsens" in _plain(capsys.readouterr().out)


def test_l_opens_the_selected_and_h_returns_to_the_list(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    left = _keys(monkeypatch, "j", "l", "l", "h", "q")  # open 2nd; `l` in a card does nothing; back; close
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "2/2" in out and left == []
    assert _queries() == [("house", True)]  # h/l were navigation, not the start of a word


def test_selection_is_a_border_not_a_fill(dictionary):
    from rich.console import Console

    def render(selected: bool) -> str:
        console = Console(width=60, record=True, force_terminal=True, color_system="256")
        console.print(render_compact(dictionary.find_lemma("Haus"), 1, selected))
        return console.export_text(styles=True)

    on, off = render(True), render(False)
    assert "┏" in on and "┃" in on and "┌" not in on  # heavy bold border: visible on any theme
    assert "┌" in off and "┏" not in off and "38;5;242m┌" in off  # thin grey border
    assert ";7;" not in on and "\x1b[7" not in on  # no reverse video anywhere


def test_damerau_levenshtein_counts_a_swap_as_one_edit():
    from wort.text import damerau_levenshtein as d

    assert d("haus", "hasu") == 1 and d("haus", "hause") == 1 and d("haus", "haus") == 0
    assert d("katze", "kaztee") == 2


@pytest.mark.parametrize(
    "typo, lemma",
    [("Hasu", "Haus"), ("gehn", "gehen"), ("Katz", "Katze"), ("schon", "schön"), ("Gebaeude", "Gebäude")],
)
def test_suggest_finds_typos(dictionary, typo, lemma):
    assert lemma in [e.lemma for e in dictionary.suggest(typo)]


def test_suggest_stays_quiet(dictionary):
    assert dictionary.suggest("xyzzy") == []
    assert dictionary.suggest("ha") == []  # too short to guess
    assert "Haus" not in [e.lemma for e in dictionary.suggest("Haus")]  # an exact word is not its own suggestion


def test_lookup_without_result_suggests_on_stdout(home, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["Hasu"])
    assert e.value.code == 1  # still "not found"
    out = capsys.readouterr().out
    assert "Nothing found" in out and "Did you mean: Haus?" in out
    assert _queries() == [("Hasu", False)]  # the original query is what gets logged


def test_session_offers_suggestions_in_the_numbered_list(home, monkeypatch, capsys):
    _interactive(monkeypatch, "Hasu\nquit\n")
    left = _keys(monkeypatch, "1", "h", "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "Nothing found." in out and "Did you mean:" in out and "[1]" in out
    assert "Singular" in out and left == []  # `1` opened the card of Haus
    assert _queries() == [("Hasu", False)]  # picking a suggestion does not change the history


def test_no_suggestion_without_close_match(home, monkeypatch, capsys):
    _interactive(monkeypatch, "qwertzuiop\nquit\n")
    _keys(monkeypatch)  # no picker: any key read would raise
    cli.main([])
    assert "Did you mean" not in _plain(capsys.readouterr().out)


def test_picker_uses_the_alternate_screen_and_repaints_each_frame(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n")
    _keys(monkeypatch, "j", "j", "k", "q")  # four frames
    cli.main([])
    out = capsys.readouterr().out
    assert out.count("\x1b[?1049h") == 1 and out.count("\x1b[?1049l") == 1  # entered once, left once
    assert out.index("\x1b[?1049h") < out.index("[1]") < out.index("\x1b[?1049l")  # everything between
    view = out[out.index("\x1b[?1049h") : out.index("\x1b[?1049l")]
    assert view.count("\x1b[?2026h") == 4 and view.count("\x1b[?2026l") == 4  # each frame: one synchronized write
    assert view.count("\x1b[H") == 4  # painted from the top-left every time, nothing to erase or to get out of step
    assert "\x1b[?25l" in out and "\x1b[?25h" in out  # cursor hidden while it is open, back afterwards


def test_picker_remeasures_the_screen_on_resize(dictionary, capsys):
    from rich.console import Console

    from wort import picker

    entries = dictionary.lookup("house")[1]
    sizes = iter([40, 40, 8])  # one measurement per frame; the third is after the window got smaller
    keys = iter(["j", "resize", "q"])
    picker.pick(entries, Console(width=60, force_terminal=True), lambda: next(sizes), keys=lambda: next(keys))
    frames = capsys.readouterr().out.split("\x1b[H")[1:]
    assert len(frames) == 3
    assert frames[0].count("\r\n") == 39 and frames[2].count("\r\n") == 7  # painted to the current height



def test_phrase_is_looked_up_word_by_word(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen Haus\nquit\n")
    left = _keys(monkeypatch, "2", "h", "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "One result per word" in out and "[1]" in out and "[2]" in out
    assert "gehen" in out and "Haus" in out and left == []
    assert _queries() == [("gehen Haus", True)]  # logged as typed
    assert "• gehen Haus — to go, to walk / house" in out  # the collapsed summary: one gloss per word


def test_phrase_corrects_typos_per_word(home, capsys):
    cli.main(["Hasu", "gehen"])
    out = capsys.readouterr().out
    assert "corrected Hasu → Haus" in out and "Präsens" in out and "Singular" in out
    assert _queries() == [("Hasu gehen", True)]


def test_phrase_with_nothing_known_is_not_found(home, capsys):
    with pytest.raises(SystemExit):
        cli.main(["xyzzy", "qwertz"])
    assert "Nothing found" in capsys.readouterr().out
    assert _queries() == [("xyzzy qwertz", False)]


def test_phrase_longer_than_five_words_is_refused(home, monkeypatch, capsys):
    _interactive(monkeypatch, "Haus gehen Katze schön Gebäude Haus\nquit\n")
    _keys(monkeypatch)  # no picker
    cli.main([])
    assert "Too many words" in _plain(capsys.readouterr().out)
    assert _queries() == [("Haus gehen Katze schön Gebäude Haus", False)]


def test_single_tall_result_opens_as_a_scrollable_card(home, monkeypatch, capsys):
    _interactive(monkeypatch, "Haus\nquit\n", rows=8)  # the Haus card is taller than 8 rows
    left = _keys(monkeypatch, "j", " ", "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "j k scroll" in out and "q close" in out and "[1]" not in out  # no list, no number
    assert re.search(r"1-7/\d+", out) and re.search(r"2-8/\d+", out)  # j scrolled by one line
    assert left == []


def test_single_result_that_fits_is_printed_as_before(home, monkeypatch, capsys):
    _interactive(monkeypatch, "qwertzuiop\nHaus\nquit\n", rows=100)
    _keys(monkeypatch)  # no picker for a card that fits: reading a key would raise
    cli.main([])
    assert "Singular" in _plain(capsys.readouterr().out)


def test_banner_is_pinned_in_a_scroll_region(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nquit\n", rows=40)
    cli.main([])
    out = capsys.readouterr().out
    height = len(cli.BANNER.split("\n"))  # nothing asked yet: just the banner on top
    assert f"\x1b[{height + 1};39r" in out  # between banner and the footer row (40) it scrolls, they do not
    assert f"\x1b[40;1H\x1b[2K" in out and cli.FOOTER in out  # the command list sits on the last row
    assert out.rstrip("\n").endswith("\x1b7\x1b[r\x1b8")  # the region is released on the way out


def test_collapse_cannot_reach_into_the_pinned_banner(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nHaus\nquit\n", rows=20)  # the gehen card is taller than the 9 working rows
    cli.main([])
    out = capsys.readouterr().out
    height = len(cli.BANNER.split("\n")) + 1  # banner rows and the footer row are pinned
    assert re.findall(r"\x1b\[(\d+)A\x1b\[J", out)[0] == str(20 - height - 1)  # the region's height - 1


def test_small_window_gets_no_pinned_banner(home, monkeypatch, capsys):
    _interactive(monkeypatch, "quit\n", rows=12)
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "r\x1b[" not in out and not re.search(r"\x1b\[\d+;\d+r", out)  # no scroll region
    assert all(line.rstrip() in out for line in cli.BANNER.split("\n"))  # but the banner is still printed once


def test_banner_is_redrawn_after_resize(monkeypatch, capsys):
    from rich.console import Console

    from wort.header import Header

    rows = [30]
    header = Header(Console(width=80, force_terminal=True), cli.BANNER, "footer", lambda: rows[0])
    assert header.start()
    capsys.readouterr()
    rows[0] = 45
    header.refresh()
    out = capsys.readouterr().out
    assert "\x1b[6;44r" in out and out.startswith("\x1b7") and out.rstrip().endswith("\x1b8\x1b[?2026l".rstrip())  # new region, cursor kept
    assert "\x1b[30;1H\x1b[2K\x1b[45;1H" in out  # the old footer row is blanked, the footer moves to the new last row
    rows[0] = 10
    header.refresh()  # too small now: the banner is released
    assert not header.active and "\x1b[r" in capsys.readouterr().out


def test_picker_keeps_the_banner_fixed_while_scrolling(home, monkeypatch, capsys):
    _interactive(monkeypatch, "Haus\nquit\n", rows=18)  # the Haus card (13 lines) does not fit under the banner
    _keys(monkeypatch, "j", " ", "G", "q")
    cli.main([])
    out = capsys.readouterr().out
    view = out[out.index("\x1b[?1049h") : out.index("\x1b[?1049l")]
    frames = view.split("\x1b[H")[1:]
    assert len(frames) == 4
    banner_top = cli.BANNER.split("\n")[0].rstrip()
    for frame in frames:  # the banner heads every frame; each frame is exactly one screen high
        assert banner_top in _plain(frame).split("\r\n")[0]
        assert frame.count("\r\n") == 17
    height = len(cli.BANNER.split("\n"))  # the picker pins the banner, nothing else
    first, last = map(int, re.search(r"(\d+)-(\d+)/\d+", _plain(frames[0])).groups())
    assert last - first + 1 == 18 - height - 1  # room = rows - banner - hint row


def test_picker_has_no_banner_in_a_small_window(dictionary, capsys):
    from rich.console import Console

    from wort import picker
    from wort.header import Header

    console = Console(width=60, force_terminal=True)
    header = Header(console, cli.BANNER, "hint", lambda: 12)  # too small to pin
    keys = iter(["q"])
    picker.pick(dictionary.lookup("house")[1], console, lambda: 12, keys=lambda: next(keys), banner=header.pinned_lines)
    assert cli.BANNER.split("\n")[0].rstrip() not in _plain(capsys.readouterr().out)


def test_footer_stays_pinned_and_there_is_no_typing_hint(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nclear\nquit\n", rows=40)
    cli.main([])
    out = capsys.readouterr().out
    assert cli.FOOTER == "/history . /clear-history . clear . quit" and "type a word" not in out
    assert out.count("\x1b[40;1H\x1b[2K") >= 3  # painted at the start, again when the recent words went, and on `clear`
    assert "─" * 20 not in _plain(out.split("Präsens")[0].split("\x1b[H")[1].split("\x1b[6;")[0])  # no separator in the header


def test_recent_words_are_bullets_under_the_banner_while_idle(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nHaus\nhaus\nKatze\nclear\nquit\n", rows=40)
    cli.main([])
    out = capsys.readouterr().out
    assert "• " not in _plain(out[: out.index("Präsens")]).split(cli.PROMPT.strip())[0]  # nothing asked yet: no bullets
    idle = _plain(out[out.rindex("\x1b[H\x1b[2J") :]).split(cli.PROMPT.strip())[0]  # the header repainted by `clear`
    bullets = re.findall(r"• (\S+) — ([^\r\n]*)", idle)
    assert [q for q, _ in bullets] == ["Katze", "haus", "gehen"]  # newest first, no duplicates
    assert all(meaning.strip() for _, meaning in bullets)  # each with its translation


def test_only_the_last_five_words_are_kept(store, dictionary):
    for word in ["a1", "b2", "c3", "d4", "e5", "f6", "b2"]:
        store.log_query(word, False)
    assert [q for q, _ in cli._recent(store, dictionary)] == ["b2", "f6", "e5", "d4", "c3"]
    store.log_query("Haus", True)
    assert cli._recent(store, dictionary)[0] == ("Haus", "house; home")


def test_small_windows_get_no_bullets(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nclear\nquit\n", rows=15)  # room for the banner and the footer, not for a bullet
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "• " not in out[out.rindex("\x1b[H\x1b[2J") :].split(cli.PROMPT.strip())[0] and cli.FOOTER in out


def test_bullets_are_hidden_in_the_history_view(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nclear\n/history\nquit\n", rows=40)
    _keys(monkeypatch, "q")  # close the history
    cli.main([])
    out = capsys.readouterr().out
    view = _plain(out[out.rindex("\x1b[?1049h") : out.rindex("\x1b[?1049l")])
    assert cli.BANNER.split("\n")[0].rstrip() in view and cli.FOOTER not in view
    assert view.split("\x1b[H")[-1].count("• gehen") == 1  # only the history's own bullet, not a recent-words bullet
    back = _plain(out[out.rindex("\x1b[?1049l") :])
    assert cli.FOOTER in back and "• gehen" in back  # both are back when the view is closed


def test_footer_is_not_in_the_picker_banner(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\nquit\n", rows=40)
    _keys(monkeypatch, "q")
    cli.main([])
    out = capsys.readouterr().out
    view = out[out.index("\x1b[?1049h") : out.index("\x1b[?1049l")]
    assert cli.FOOTER not in view and cli.BANNER.split("\n")[0].rstrip() in view


def _history_screen(out: str) -> str:
    """Everything the history view painted (it runs on the alternate screen, after any search view)."""
    return _plain(out[out.rindex("\x1b[?1049h") : out.rindex("\x1b[?1049l")])


def test_history_is_an_accordion_of_bullets(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nhouse\nqwertzuiop\n/history\nquit\n")
    # the `house` results picker takes the first key; then the history: up to `house`, open it, open the 2nd
    # result in place, close that, close the entry, close the view
    left = _keys(monkeypatch, "q", "k", "l", "2", "h", "q", "q")
    cli.main([])
    assert left == []
    out = capsys.readouterr().out
    screen = _history_screen(out)
    rows = [l.replace("\x1b[2K", "") for l in screen.split("\r\n")]
    qw = next(l for l in rows if "qwertzuiop" in l)  # a history entry is one bullet line: word, then its translation
    assert qw.startswith("• qwertzuiop — nothing found")
    assert next(l for l in rows if "gehen" in l and l.startswith("• ")).endswith("to work, to function")
    assert "Gebäude" in screen and "Singular" in screen  # the 2nd result opened into its full card in place
    assert _queries() == [("gehen", True), ("house", True), ("qwertzuiop", False)]  # viewing logs nothing


def test_history_miss_opens_as_nothing_found_with_suggestions(home, monkeypatch, capsys):
    _interactive(monkeypatch, "Hasu\n/history\nquit\n")
    left = _keys(monkeypatch, "q", "l", "q", "q")  # close the `Did you mean` list; open the entry; collapse; close
    cli.main([])
    assert left == []
    screen = _history_screen(capsys.readouterr().out)
    assert "Nothing found. Did you mean:" in screen and "Haus" in screen and "Singular" in screen  # one suggestion: its card
    assert _queries() == [("Hasu", False)]


def test_history_card_taller_than_the_screen_opens_on_its_own_screen(home, monkeypatch, capsys):
    _interactive(monkeypatch, "Haus\n/history\nquit\n", rows=10)  # the Haus card does not fit in 9 rows
    # (`Haus` itself is a tall single card: its own view takes `q` first.) Then: open the entry, step to its
    # result, open it (too tall: own screen), scroll, close that screen, collapse, close
    left = _keys(monkeypatch, "q", "l", "j", "l", "j", "q", "q", "q")
    cli.main([])
    assert left == []
    out = capsys.readouterr().out
    screen = _history_screen(out)
    assert "j k scroll" in screen and re.search(r"2-\d+/\d+", screen)  # the full card scrolled on its own screen
    assert "┏━ Haus" in screen  # and it is drawn as the selected card there too
    assert out.count("\x1b[?1049h") == 2 and out.count("\x1b[?1049l") == 2  # no nested alternate screen


def test_history_without_a_terminal_is_still_the_table(home, monkeypatch, capsys):
    _stdin(monkeypatch, "gehen\n/history\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    assert "Meaning" in out and "gehen" in out and "\x1b[?1049h" not in out


def test_history_active_card_keeps_the_selected_border(home, monkeypatch, capsys):
    _interactive(monkeypatch, "house\n/history\nquit\n")
    left = _keys(monkeypatch, "q", "l", "2", "q", "q")  # close the search picker; open the entry; open result 2; close both
    cli.main([])
    assert left == []
    out = capsys.readouterr().out
    view = out[out.rindex("\x1b[?1049h") : out.rindex("\x1b[?1049l")]
    frames = view.split("\x1b[H")[1:]
    opened = [f for f in frames if "Singular" in _plain(f)]  # frames with the full Gebäude card in place
    assert opened and all("┏━ Gebäude" in _plain(f) for f in opened)  # heavy border: it is the selected one
    assert all("┌─ Gebäude" not in _plain(f) for f in opened)


def test_history_row_is_a_bullet_cut_to_one_line(dictionary):
    from datetime import datetime

    from rich.console import Console

    from wort.history_view import Item, _row

    console = Console(width=40, force_terminal=False)
    item = Item("Katze", True, 3, datetime(2026, 10, 6), "house cat")
    with console.capture() as cap:
        console.print(_row(item, 39))
    assert cap.get().rstrip("\n") == "• Katze — house cat"  # no status, no date

    long = Item("durchbringen", True, 1, datetime(2026, 10, 6), "to be able to bring (something) through; to cause")
    with console.capture() as cap:
        console.print(_row(long, 39))
    (line,) = cap.get().rstrip("\n").split("\n")
    assert line.startswith("• durchbringen — to be") and line.endswith("…") and len(line) == 39


def test_history_selected_entry_is_bracketed_by_two_grey_separators(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\nHaus\n/history\nquit\n")
    _keys(monkeypatch, "k", "q")  # up to `gehen`, then close
    cli.main([])
    out = capsys.readouterr().out
    view = out[out.rindex("\x1b[?1049h") : out.rindex("\x1b[?1049l")]
    rows = [l.replace("\x1b[2K", "") for l in _plain(view.split("\x1b[H")[-1]).split("\r\n")]
    at = next(n for n, l in enumerate(rows) if l.startswith("• gehen —"))
    assert set(rows[at - 1].strip()) == {"━"} and set(rows[at + 1].strip()) == {"━"}  # above and below
    other = next(n for n, l in enumerate(rows) if l.startswith("• Haus —"))
    assert "━" not in rows[other + 1]  # the others are plain bullets (the line above it is `gehen`'s lower separator)
    assert sum(set(l.strip()) == {"━"} for l in rows) == 2  # exactly two separators in the whole list


def test_no_state_label_next_to_the_banner(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\n/history\nquit\n", rows=40)
    _keys(monkeypatch, "q")
    cli.main([])
    out = _plain(capsys.readouterr().out)
    assert "translate\n" not in out.replace("translate>", "") and "history" not in out.split("/history")[0]  # no label anywhere
    assert not re.search(r"█\s+(translate|history)\b", out)  # nor beside the block letters, on the main screen or in the view


def test_hiding_the_recent_words_closes_the_gap(monkeypatch, capsys):
    from rich.console import Console

    from wort.header import Header

    header = Header(Console(width=80, force_terminal=True), cli.BANNER, "footer", lambda: 40)
    header.recent = [("Haus", "house"), ("gehen", "to go")]
    assert header.start() and header.height == 5 + 2  # banner and two bullets
    capsys.readouterr()
    header.hide_recent()
    out = capsys.readouterr().out
    assert header.height == 5 and "\x1b[2S\x1b[2A" in out  # content scrolled up by the freed rows, cursor with it
    assert "\x1b[6;39r" in out  # the region now starts right under the banner
    assert out.startswith("\x1b7") and "\x1b8" in out
    header.hide_recent()  # idempotent
    assert capsys.readouterr().out == ""



def test_history_keeps_everything_but_recent_words_are_per_session(home, monkeypatch, capsys):
    old = Store(paths.user_db())
    old.log_query("Katze", True)  # an earlier session
    old.log_query("Haus", True)
    _interactive(monkeypatch, "gehen\nclear\n/history\nquit\n", rows=40)
    _keys(monkeypatch, "q")  # close the history view
    cli.main([])
    out = capsys.readouterr().out
    view = _history_screen(out)
    assert all(word in view for word in ("Katze", "Haus", "gehen"))  # /history: the whole stored history
    assert [q for q, _ in _queries()] == ["Katze", "Haus", "gehen"]
    start = _plain(out[: out.index("Präsens")]).split(cli.PROMPT.strip())[0]
    assert "• Katze" not in start and "• Haus" not in start  # the bullets under the banner start empty in a new session
    idle = _plain(out[out.rindex("\x1b[H\x1b[2J") :]).split(cli.PROMPT.strip())[0]
    assert "• gehen" in idle and "Katze" not in idle  # ...and fill from this session's queries only


def test_history_table_without_a_terminal_lists_everything(home, monkeypatch, capsys):
    Store(paths.user_db()).log_query("Katze", True)  # an earlier session
    _stdin(monkeypatch, "/history\nquit\n")
    cli.main([])
    assert "Katze" in capsys.readouterr().out


def test_unique_queries_after_a_marker(store):
    store.log_query("a", True)
    mark = store.last_query_id()
    assert store.unique_queries(mark) == [] and mark > 0
    store.log_query("A", True)
    store.log_query("b", False)
    assert [(q, f, n) for q, f, n, _ in store.unique_queries(mark)] == [("A", True, 1), ("b", False, 1)]
    assert [n for *_, n, _ in store.unique_queries()][0] == 2  # without a marker: all history, `a`/`A` merged


def test_recent_words_start_empty_in_a_new_session(store, dictionary):
    store.log_query("Haus", True)
    mark = store.last_query_id()
    assert cli._recent(store, dictionary, mark) == []
    store.log_query("gehen", True)
    assert [q for q, _ in cli._recent(store, dictionary, mark)] == ["gehen"]


def test_prompt_follows_the_header_directly(home, monkeypatch, capsys):
    _interactive(monkeypatch, "quit\n", rows=40)
    cli.main([])
    out = capsys.readouterr().out
    header = out[out.index("\x1b[H\x1b[2K█") : out.index("\x1b[6;39r")]  # what is painted above the region
    assert len(header.split("\r\n")) == 5  # the five banner rows and nothing after them
    assert "\x1b[6;1H" in out  # the prompt starts on the very next row


def test_clear_history_asks_and_deletes_only_the_history(home, monkeypatch, capsys):
    store = Store(paths.user_db())
    store.add_word("Haus", "noun", None)  # a practice word must survive
    _stdin(monkeypatch, "gehen\nHaus\n/clear-history\nn\n/history\n/clear-history\ny\n/history\nquit\n")
    cli.main([])
    out = capsys.readouterr().out
    assert "Delete the whole history (2 words" in out and "Kept." in out  # first answer: no
    assert "History cleared." in out and "No queries yet." in out  # second answer: yes; then it is empty
    assert _queries() == []
    assert [w.lemma for w in Store(paths.user_db()).words()] == ["Haus"]  # practice words are not history


def test_clear_history_on_an_empty_history_asks_nothing(home, monkeypatch, capsys):
    _stdin(monkeypatch, "/clear-history\nquit\n")
    cli.main([])
    assert "The history is already empty." in capsys.readouterr().out


def test_words_asked_after_clearing_show_up_again(home, monkeypatch, capsys):
    _interactive(monkeypatch, "gehen\n/clear-history\ny\nHaus\nclear\nquit\n", rows=40)
    cli.main([])
    out = capsys.readouterr().out
    idle = _plain(out[out.rindex("\x1b[H\x1b[2J") :]).split(cli.PROMPT.strip())[0]
    assert "• Haus" in idle and "gehen" not in idle  # the new session starts from nothing (ids restart too)
    assert [q for q, _ in _queries()] == ["Haus"]


def test_unknown_command_lists_both(home, monkeypatch, capsys):
    _stdin(monkeypatch, "/nope\nquit\n")
    cli.main([])
    assert "Available: /history, /clear-history" in capsys.readouterr().out


def test_history_separator_is_grey_not_bold():
    from rich.console import Console

    from wort.history_view import _rule

    console = Console(width=20, force_terminal=True, color_system="256")
    with console.capture() as cap:
        console.print(_rule(console))
    assert cap.get() == "\x1b[38;5;242m" + "━" * 20 + "\x1b[0m\n"  # the muted grey, no bold attribute
