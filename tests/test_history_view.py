"""Moving the selection in the history view: one row per press, two for a held key, and no lag behind it."""

import io
import os
import re
import sys
from datetime import datetime

import pytest
from rich.console import Console
from rich.text import Text

from wort import history_view as hv
from wort import picker

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class Clock:
    """Every reading is `step` seconds later: a small step plays a held key, a large one slow presses."""

    def __init__(self, step: float):
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class Screen:
    """Runs `browse` with scripted keys and keeps every frame it paints."""

    def __init__(self, monkeypatch, rows: int = 100, keys: list[str] | None = None, read_ahead: bool = False, step: float = 0.03,
                 height: int = 24, loaded=None, width: int = 80):
        self.frames: list[tuple[list[str], str]] = []
        self.deleted: list[str] = []
        self.pending = list(keys or [])
        monkeypatch.setattr(picker, "paint", lambda console, banner, lines, hint, rows_: self.frames.append((list(lines), hint)))
        console = Console(file=io.StringIO(), width=width, force_terminal=True, color_system="256", highlight=False)
        self.items = [hv.Item(f"item{n}", True, 1, datetime(2026, 1, 1), None) for n in range(rows)]
        tabs = [hv.Tab("Words", "word", self.items, loaded or (lambda item: hv.Loaded()), "none"),
                hv.Tab("Sentences", "sentence", [], lambda item: hv.Loaded(), "none")]
        hv.browse(tabs, console, lambda: height, lambda tab, item: self.deleted.append(item.query), keys=self._read,
                  waiting=(lambda: bool(self.pending)) if read_ahead else (lambda: False), clock=Clock(step))

    def _read(self) -> str:
        return self.pending.pop(0)

    def selected(self, frame: int = -1) -> str:
        """The row marked `>` in a frame (by default the last one, painted before the closing key)."""
        lines = [ANSI.sub("", l) for l in self.frames[frame][0]]
        return next(l[2:] for l in lines if l.startswith("> "))


def test_a_nouns_row_is_drawn_in_its_color(monkeypatch):
    console = Console(file=io.StringIO(), width=40, force_terminal=True, color_system="256", highlight=False)
    noun = hv.Item("Haus", True, 1, datetime(2026, 1, 1), "house", "color(34)")
    with console.capture() as cap:
        console.print(hv._row(noun, False, 39))
    assert "\x1b[38;5;34mHaus" in cap.get()  # das: green
    with console.capture() as cap:
        console.print(hv._row(noun, True, 39))
    assert cap.get().startswith("> ") and "\x1b[38;5;34mHaus" in cap.get()  # the arrow is plain, the word keeps its color
    plain = hv.Item("gehen", True, 1, datetime(2026, 1, 1), "to go")
    with console.capture() as cap:
        console.print(hv._row(plain, False, 39))
    assert cap.get().startswith("  gehen\x1b[38;5;242m")  # the word itself is plain; only the grey of the translation follows


def test_the_view_draws_the_colors_and_does_not_mix_up_cached_rows(monkeypatch):
    screen = Screen(monkeypatch, rows=0, keys=["q"])  # (builds the console and the frame spy)
    items = [hv.Item("Haus", True, 1, datetime(2026, 1, 1), None, "color(34)"), hv.Item("Haus", True, 1, datetime(2026, 1, 1), None, "")]
    console = Console(file=io.StringIO(), width=80, force_terminal=True, color_system="256", highlight=False)
    frames = []
    monkeypatch.setattr(picker, "paint", lambda c, b, lines, hint, rows: frames.append(list(lines)))
    pending = ["j", "q"]
    hv.browse([hv.Tab("Words", "word", items, lambda i: hv.Loaded(), "none"), hv.Tab("Sentences", "sentence", [], lambda i: hv.Loaded(), "none")],
              console, lambda: 24, lambda t, i: None, keys=lambda: pending.pop(0), waiting=lambda: False)
    assert "38;5;34" in frames[0][0] and "38;5;34" not in frames[0][1]  # same text, different color: two different rows


def test_one_press_moves_one_row(monkeypatch):
    assert Screen(monkeypatch, keys=["j", "q"]).selected() == "item1"
    assert Screen(monkeypatch, keys=["j", "j", "k", "q"], step=0.5).selected() == "item1"  # slow presses: a row each


def test_a_held_key_moves_two_rows_a_repeat(monkeypatch):
    # the first press and the first repeat are slow (the keyboard's start delay), then the repeats run fast
    screen = Screen(monkeypatch, keys=["j"] * 5 + ["q"], step=0.03)
    assert screen.selected() == "item9"  # 1 + 4 * 2
    assert Screen(monkeypatch, keys=["k", "q"], step=0.03).selected() == "item0"  # already on top: stays
    assert Screen(monkeypatch, keys=["j"] * 5 + ["q"], step=0.5).selected() == "item5"  # slow presses: no speed-up


def test_arrow_keys_count_like_j_and_k(monkeypatch):
    assert Screen(monkeypatch, keys=["down", "down", "down", "up", "q"], step=0.03).selected() == "item4"  # 1 + 2 + 2 - 1


def test_changing_direction_or_pressing_another_key_ends_the_speed_up(monkeypatch):
    assert Screen(monkeypatch, keys=["j", "j", "k", "q"], step=0.03).selected() == "item2"  # 1 + 2, then 1 back
    assert Screen(monkeypatch, keys=["j", "h", "j", "q"], step=0.03).selected() == "item2"  # `h` between: two single presses


def test_waiting_presses_are_read_together_and_drawn_once(monkeypatch):
    screen = Screen(monkeypatch, keys=["j"] * 10 + ["q"], read_ahead=True)
    assert len(screen.frames) == 2  # the first frame, and one for all ten presses
    assert screen.selected() == "item19"  # 1 + 9 * 2: the same place as ten repeats one by one


def test_nothing_waiting_is_ever_lost_or_reordered(monkeypatch):
    # a key that is not a move ends the batch; it is handled right after, on the row the moves reached
    screen = Screen(monkeypatch, keys=["j", "j", "j", "x", "y", "q"], read_ahead=True)
    assert screen.deleted == ["item5"]  # 1 + 2 + 2
    assert 'Delete "item5"? y/n' in [f[1] for f in screen.frames]


def test_read_ahead_stops_at_the_ends_of_the_list(monkeypatch):
    assert Screen(monkeypatch, rows=5, keys=["j"] * 20 + ["q"], read_ahead=True).selected() == "item4"
    assert Screen(monkeypatch, rows=5, keys=["j"] * 20 + ["k"] * 30 + ["q"], read_ahead=True).selected() == "item0"


def test_g_and_G_jump_to_the_ends(monkeypatch):
    screen = Screen(monkeypatch, rows=5000, keys=["G", "g", "q"])
    assert screen.selected(1) == "item4999" and screen.selected(2) == "item0"


def test_the_list_scrolls_to_keep_the_selection_in_view(monkeypatch):
    screen = Screen(monkeypatch, rows=5000, keys=["j"] * 60 + ["q"], step=0.5, height=24)
    lines, _ = screen.frames[-1]
    assert 0 < len(lines) <= 24 and screen.selected() == "item60"
    first = int(ANSI.sub("", lines[0]).strip()[4:])
    assert 30 < first <= 60  # scrolled down with the selection (item60 is on screen), not left at the top


def test_only_the_visible_rows_are_rendered(monkeypatch):
    """The lag came from rendering every row of the history for every key press."""
    calls = []
    real = hv._row
    monkeypatch.setattr(hv, "_row", lambda item, selected, width, *rest: calls.append(item.query) or real(item, selected, width, *rest))
    screen = Screen(monkeypatch, rows=5000, keys=["j"] * 40 + ["q"], step=0.5, height=24)
    assert len(screen.frames) == 41
    assert len(calls) < 200  # about a screenful once, then two rows per move; never thousands
    assert len(set(calls)) < 80


def test_an_empty_tab_has_a_cursor_that_goes_nowhere(monkeypatch):
    screen = Screen(monkeypatch, rows=0, keys=["j", "k", "x", "l", "q"])
    assert "none" in ANSI.sub("", screen.frames[-1][0][0])  # the empty message, nothing broke


# --- positions ---------------------------------------------------------------------------------------------


def test_order_maps_positions_and_cursor_keys_both_ways():
    order = hv._Order(rows=5, open_item=2, results=3)
    keys = [(0, None), (1, None), (2, None), (2, 0), (2, 1), (2, 2), (3, None), (4, None)]
    assert len(order) == len(keys) == 8
    assert [order.key(at) for at in range(8)] == keys
    assert [order.index(key) for key in keys] == list(range(8))
    assert (2, 3) not in order and (5, None) not in order and (1, 0) not in order and (3, None) in order


def test_order_without_an_open_row_and_when_empty():
    order = hv._Order(rows=3, open_item=None, results=0)
    assert len(order) == 3 and order.key(2) == (2, None) and order.index((1, None)) == 1
    empty = hv._Order(rows=0, open_item=None, results=0)
    assert len(empty) == 1 and empty.key(0) == (-1, None) and empty.index((-1, None)) == 0 and (-1, None) in empty


# --- the terminal side -------------------------------------------------------------------------------------


def test_key_waiting_sees_typed_ahead_input(monkeypatch):
    read_end, write_end = os.pipe()

    class Stdin:
        def fileno(self):
            return read_end

    monkeypatch.setattr(sys, "stdin", Stdin())
    try:
        assert picker.key_waiting() is False  # nothing typed
        os.write(write_end, b"j")
        assert picker.key_waiting() is True  # a key is waiting
    finally:
        os.close(read_end)
        os.close(write_end)


def test_key_waiting_is_false_without_a_terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("jjj"))  # no file descriptor
    assert picker.key_waiting() is False


# --- the side pane: opens on `l`, takes the cursor, one `h` closes it -------------------------------------


def _plain_lines(frame) -> list[str]:
    return [ANSI.sub("", line) for line in frame[0]]


def _block_loader(item):
    return hv.Loaded(blocks=[Text("TRANSLATION OF " + item.query)])  # a plain block: no card borders to confuse the columns


def _entries(dictionary):
    return [dictionary.find_lemma("Haus"), dictionary.find_lemma("gehen")]


COLUMN = hv._panes(140)[0]  # 46: where the separator is in a 140-column window


def test_the_window_is_split_from_120_columns_on():
    assert hv._panes(119) is None and hv._panes(80) is None
    assert hv._panes(120) == (40, 79)  # a third for the list, the rest for the results
    assert hv._panes(150) == (50, 99)
    assert hv._panes(300) == (56, 243)  # the list stops growing
    assert hv._panes(120)[0] + 1 + hv._panes(120)[1] == 120  # the separator is the one column left


def test_a_narrow_window_opens_a_row_in_place(monkeypatch):
    screen = Screen(monkeypatch, rows=3, keys=["l", "q", "q"], loaded=_block_loader, width=100)
    lines = _plain_lines(screen.frames[1])  # after `l`
    assert not any("│" in line for line in lines)  # no columns
    assert [l.strip() for l in lines[:3]] == ["> item0", "TRANSLATION OF item0", "item1"]  # between the row and the next one


def test_a_wide_window_has_no_side_pane_until_a_row_is_opened(monkeypatch):
    screen = Screen(monkeypatch, rows=6, keys=["j", "q"], loaded=_block_loader, width=140)
    for frame in screen.frames:
        assert not any("│" in line for line in _plain_lines(frame))  # the list has the whole window
    assert _plain_lines(screen.frames[1])[1].startswith("> item1")  # and the cursor moves along it as usual


def test_l_opens_the_side_pane_and_moves_the_arrow_into_it(monkeypatch):
    screen = Screen(monkeypatch, rows=6, keys=["l", "q", "q"], loaded=_block_loader, width=140)
    before, opened = screen.frames[0][0], screen.frames[1][0]
    lines = [ANSI.sub("", l) for l in opened]
    assert all(l.index("│") == COLUMN for l in lines)  # a straight separator, top to bottom
    assert lines[0][COLUMN + 1 :] == "> item0"  # the pane starts with the word, and the arrow is on it (nothing to pick)
    assert "TRANSLATION OF item0" in lines[1][COLUMN:]
    assert lines[1].startswith("  item1") and lines[2].startswith("  item2")  # the list did not expand and its arrow is gone
    assert all("TRANSLATION" not in l[:COLUMN] for l in lines)
    assert screen.frames[1][1].startswith("j k move · l open · 1-9 pick · s save · h back")  # the hints are the pane's


def test_the_opened_word_stays_visible_in_the_list(monkeypatch):
    screen = Screen(monkeypatch, rows=6, keys=["l", "q", "q"], loaded=_block_loader, width=140)
    row = screen.frames[1][0][0]
    assert ANSI.sub("", row).startswith("> item0")  # the row keeps an arrow...
    assert "\x1b[38;5;242m> " in row and "\x1b[1mitem0" in row  # ...a grey one, and the word is bold
    plain = screen.frames[0][0][0]
    assert "\x1b[38;5;242m> " not in plain and "\x1b[1mitem0" not in plain  # (an ordinary selected row is neither)


def test_one_h_closes_the_pane_and_returns_to_the_list(monkeypatch, dictionary):
    entries = _entries(dictionary)
    for keys in (["l", "h"], ["l", "2", "h"], ["l", "2", "k", "j", "h"]):  # whatever the pane shows, one `h` is enough
        screen = Screen(monkeypatch, rows=4, keys=keys + ["q"], loaded=lambda item: hv.Loaded(entries=entries), width=140)
        last = _plain_lines(screen.frames[-1])
        assert not any("│" in l for l in last), keys  # the pane is gone
        assert last[0].startswith("> item0") and screen.frames[-1][1].startswith("j k move · l open"), keys  # the cursor is on the row
    single = Screen(monkeypatch, rows=4, keys=["l", "h", "q"], loaded=lambda item: hv.Loaded(entries=entries[:1]), width=140)
    assert not any("│" in l for l in _plain_lines(single.frames[-1]))  # a word with one result (a card opens at once) too


def test_a_card_too_tall_for_the_pane_opens_on_its_own_screen_and_back_is_the_list(monkeypatch, dictionary):
    entries = _entries(dictionary)
    shown = []
    monkeypatch.setattr(picker, "run", lambda items, *a, **k: shown.append(items[0].lemma))  # the card's own screen: closed at once
    screen = Screen(monkeypatch, rows=3, keys=["l", "2", "q"], loaded=lambda item: hv.Loaded(entries=entries), width=140, height=12)
    assert shown == ["gehen"]  # a verb card does not fit in 12 rows
    last = _plain_lines(screen.frames[-1])
    assert not any("│" in l for l in last) and last[0].startswith("> item0")  # back from it: the list, not the pane
    assert screen.frames[-1][1].startswith("j k move · l open")


def test_the_results_have_the_arrow_and_the_usual_navigation(monkeypatch, dictionary):
    entries = _entries(dictionary)
    screen = Screen(monkeypatch, rows=4, keys=["l", "j", "j", "k", "g", "G", "q", "q"], loaded=lambda item: hv.Loaded(entries=entries), width=140, step=0.5)
    right = lambda n: [l[COLUMN + 1 :] for l in _plain_lines(screen.frames[n])]
    marked = lambda n: [l for l in right(n) if l.startswith("> ")]
    opened = right(1)
    assert opened[0] == "item0" and any("[1]" in l for l in opened) and any("[2]" in l for l in opened)  # the word, then both results
    assert len(marked(1)) == 1 and "[1]" in marked(1)[0]  # the arrow is on the first result
    assert "[2]" in marked(2)[0]  # j: the second
    assert "[2]" in marked(3)[0]  # j: the last one, it stays
    assert "[1]" in marked(4)[0]  # k: the first again
    assert "[2]" in marked(6)[0] and "[1]" in marked(5)[0]  # g: first, G: last
    for n in range(1, 7):  # the list never moved: j and k are for the results while the pane has the cursor
        assert _plain_lines(screen.frames[n])[0].startswith("> item0") and _plain_lines(screen.frames[n])[1].startswith("  item1")


def test_a_digit_picks_a_result_and_l_toggles_its_card(monkeypatch, dictionary):
    entries = _entries(dictionary)
    screen = Screen(monkeypatch, rows=3, keys=["l", "2", "l", "q", "q"], loaded=lambda item: hv.Loaded(entries=entries), width=140, step=0.5)
    right = lambda n: " ".join(l[COLUMN + 1 :] for l in _plain_lines(screen.frames[n]))
    assert "Präsens" not in right(1) and "[2]" in right(1)  # compact cards at first
    assert "Präsens" in right(2)  # the digit: the second result as a full card
    assert "Präsens" not in right(3) and "[2]" in right(3)  # l again: back to the compact card, the pane stays


def test_the_word_stays_at_the_top_of_the_pane_while_the_results_scroll(monkeypatch, dictionary):
    entries = (_entries(dictionary) * 5)[:9]  # nine compact cards: taller than the pane
    screen = Screen(monkeypatch, rows=3, keys=["l", "9", "q", "q"], loaded=lambda item: hv.Loaded(entries=entries), width=140, height=20)
    before, after = _plain_lines(screen.frames[1]), _plain_lines(screen.frames[2])
    assert before[0][COLUMN + 1 :] == "item0" and after[0][COLUMN + 1 :] == "item0"  # always on top
    assert any("[1]" in l[COLUMN:] for l in before) and not any("[1]" in l[COLUMN:] for l in after)  # the results scrolled
    assert any(l[COLUMN + 1 :].startswith("> ") for l in after)  # to the ninth, which has the arrow


def test_x_is_for_the_list_not_for_the_pane(monkeypatch):
    screen = Screen(monkeypatch, rows=3, keys=["l", "x", "y", "q", "q"], loaded=_block_loader, width=140)  # (the first q closes the pane)
    assert screen.deleted == []  # no question was asked, nothing was deleted
    assert all(not f[1].startswith("Delete") for f in screen.frames)
    closed = Screen(monkeypatch, rows=3, keys=["l", "h", "x", "y", "q"], loaded=_block_loader, width=140)
    assert closed.deleted == ["item0"] and _plain_lines(closed.frames[-1])[0].startswith("> item1")  # after h it works


def test_keys_do_nothing_harmful_in_a_pane_with_nothing_to_pick(monkeypatch):
    screen = Screen(monkeypatch, rows=3, keys=["l", "j", "k", "g", "G", "5", "q", "q"], loaded=_block_loader, width=140)
    assert _plain_lines(screen.frames[6])[0][COLUMN + 1 :] == "> item0"  # after all those keys (frame 6): still there, nothing broke


def test_an_empty_tab_in_a_wide_window(monkeypatch):
    screen = Screen(monkeypatch, rows=0, keys=["l", "j", "x", "q"], width=140)
    for frame in screen.frames:
        assert not any("│" in l for l in _plain_lines(frame))  # no row, so no pane
    assert _plain_lines(screen.frames[0])[0].startswith("none")


class _Resizable(Console):
    """A console whose width the test changes while the view runs (a window being resized)."""

    columns = 100

    @property
    def width(self) -> int:
        return self.columns


def test_resizing_between_the_two_layouts_keeps_the_open_row(monkeypatch):
    """The width is read for every frame: the same open row is drawn in place when narrow and in a side pane when wide."""
    console = _Resizable(file=io.StringIO(), force_terminal=True, color_system="256", highlight=False)
    frames = []
    monkeypatch.setattr(picker, "paint", lambda c, b, lines, hint, rows: frames.append([ANSI.sub("", l) for l in lines]))
    pending = [("l", 100), ("resize", 140), ("resize", 100), ("q", 100), ("q", 100)]

    def read():
        key, console.columns = pending.pop(0)
        return key

    items = [hv.Item(f"item{n}", True, 1, datetime(2026, 1, 1), None) for n in range(3)]
    hv.browse([hv.Tab("Words", "word", items, _block_loader, "none"), hv.Tab("Sentences", "sentence", [], _block_loader, "none")],
              console, lambda: 20, lambda t, i: None, keys=read, waiting=lambda: False)
    narrow_open, wide, narrow_again = frames[1], frames[2], frames[3]
    assert [l.strip() for l in narrow_open[:3]] == ["> item0", "TRANSLATION OF item0", "item1"]  # in place
    assert all(l.index("│") == COLUMN for l in wide) and "TRANSLATION OF item0" in wide[1]  # a side pane, still open
    assert [l.strip() for l in narrow_again[:3]] == ["> item0", "TRANSLATION OF item0", "item1"]  # and back in place
