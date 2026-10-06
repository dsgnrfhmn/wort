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
