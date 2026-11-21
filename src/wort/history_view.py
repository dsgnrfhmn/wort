"""The query history as an accordion, in the style of the search results (the `/history` view).

Two tabs, Words and Sentences (`Tab` switches). Each is a list of `text — translation` rows (a noun in its article's color), newest first (the
caller passes them in that order); the
selected row starts with `>`, the others with a space. `l`/Enter opens a row: a word shows its results
as compact cards, a sentence shows its translation block, and a card opens into the full word
card (a card taller than its place opens on a screen of its own, with scrolling). In a narrow window the results
open in place, below the row. From `SPLIT_MIN_WIDTH` columns on, `l` opens a side pane instead: the list narrows to the
left half and the results of the row appear on the right, under the row's word, and the `>` moves into them (`j`/`k`, digits,
`l`, `s` work there as everywhere); the row stays marked in the list by a grey `>` and bold text. One `h` (or `q`) closes
the pane and puts the cursor back on the row. Without an open row the list has the whole width. `x` deletes the selected
row after a `y/n` question in the bottom line. `s` saves the selected result of an open word row instead of the
row's own text (a misspelled word becomes the word that was meant). Runs on the alternate screen, with the banner fixed at the
top, like the picker. A thin line separates the tabs from the list.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from rich.console import Console, RenderableType
from rich.text import Text

from wort import picker
from wort.dictionary.lookup import Entry
from wort.render.card import MUTED, render_card, render_compact

INDENT = 4
GUTTER = 2  # the width of the `> ` in front of a result in the right-hand pane
SPLIT_MIN_WIDTH = 120  # columns: from here on the results are shown beside the list, not below the row
HINT = "j k move · l open · 1-9 pick · s save · x delete · Tab {other} · q close"
PANE_HINT = "j k move · l open · 1-9 pick · s save · h back · q close"  # while the cursor is in the side pane
MARK = ">"  # in front of the selected row (and of the selected result of an open row)
BLANK = " "  # in front of the other rows: no bullet

# Moving the selection. A held key repeats about 30 times a second; a slow terminal cannot redraw that often, so the
# presses that are already waiting are read together and drawn once (the selection stops when the key is let go), and
# a key held down moves twice as fast as single presses.
NAVIGATION = {"j": 1, "down": 1, "k": -1, "up": -1}
HELD_WINDOW = 0.12  # seconds: the same key again this soon after the last move is a held key
HELD_STEP = 2  # rows per repeat of a held key; a single press moves one
MAX_READ_AHEAD = 1000  # presses taken in one go
ROW_CACHE = 4000  # rendered rows kept


@dataclass
class Item:
    query: str
    found: bool
    count: int
    ts: datetime
    meaning: str | None  # None: no translation column (sentences are translated only when opened)
    style: str = ""  # the color of the text (a noun's article color), "" for none


@dataclass
class Loaded:
    """What an open row shows: word results (cards) and/or ready-made blocks (a sentence translation)."""

    entries: list[Entry] = field(default_factory=list)
    note: str = ""
    blocks: list[RenderableType] = field(default_factory=list)


Loader = Callable[[Item], Loaded]  # a row's results (or, for a miss, suggestions)


@dataclass
class Tab:
    title: str
    kind: str  # "word" or "sentence"
    items: list[Item]
    load: Loader
    empty: str  # shown when there is nothing in the tab
    status: str = ""  # shown in the bottom line while `load` runs (it can be slow)


@dataclass
class _State:
    """The view of one tab; switching tabs keeps each tab's place."""

    cursor: tuple[int, int | None]  # (row, result of the open row)
    open_item: int | None = None  # the expanded row (one at a time)
    open_child: int | None = None  # its result shown as a full card in place
    top: int = 0
    right_top: int = 0  # the first visible line of the results pane (split view)
    right_for: int | None = None  # the row whose results the pane scroll belongs to
    loaded: dict[int, Loaded] = field(default_factory=dict)


def _console_of(console: Console, width: int) -> Console:
    """A console `width` columns wide, same colors, for rendering what is shown in a narrower place."""
    return Console(
        width=max(width, 20),
        file=io.StringIO(),
        force_terminal=console.is_terminal,
        color_system=console.color_system,
        highlight=False,
    )


def _panes(width: int) -> tuple[int, int] | None:
    """(columns of the list, columns of the results) when the window is wide enough to show them side by side,
    else None. One more column in between holds the separating line."""
    if width < SPLIT_MIN_WIDTH:
        return None
    left = (width - 1) // 2  # half and half (the separator column is taken off first)
    return left, width - left - 1


def _row(item: Item, selected: bool, width: int, pad: bool = False, dim: bool = False) -> Text:
    """One row: `text — translation` (translation in grey), `>` in front when selected, a space otherwise, cut to one line
    (and filled with spaces up to `width` when `pad` asks, so that a column can follow). `dim` is a selected row whose
    results have the cursor: its arrow is grey and the word bold, so it is still easy to see which one it is."""
    line = Text()
    line.append(f"{MARK if selected else BLANK} ", style=MUTED if dim else "")
    line.append(item.query, style=f"bold {item.style}".strip() if dim else item.style)
    if item.meaning is not None:
        line.append(f" — {item.meaning or 'nothing found'}", style=MUTED)
    line.truncate(width, overflow="ellipsis", pad=pad)
    return line


def _tab_line(tabs: list[Tab], active: int) -> Text:
    line = Text()
    for i, tab in enumerate(tabs):
        if i:
            line.append("  |  ", style=MUTED)
        line.append(f"{tab.title} ({len(tab.items)})", style="bold" if i == active else MUTED)
    return line


def _rule(console: Console) -> Text:
    """A thin grey line under the tabs, above the list."""
    return Text("─" * console.width, style=MUTED)


@dataclass(frozen=True)
class _Order:
    """The places the cursor can be in one tab, top to bottom: every row, and right after the open row its results.
    Works out positions from three numbers, so nothing is built per row."""

    rows: int
    open_item: int | None
    results: int  # results of the open row

    def __len__(self) -> int:
        return max(self.rows, 1) + (self.results if self.open_item is not None else 0)

    def key(self, at: int) -> tuple[int, int | None]:
        if self.rows == 0:
            return (-1, None)
        if self.open_item is None or at <= self.open_item:
            return (at, None)
        if at <= self.open_item + self.results:
            return (self.open_item, at - self.open_item - 1)
        return (at - self.results, None)

    def index(self, key: tuple[int, int | None]) -> int:
        row, child = key
        if self.rows == 0:
            return 0
        if child is not None:
            return self.open_item + 1 + child
        if self.open_item is None or row <= self.open_item:
            return row
        return row + self.results

    def __contains__(self, key: object) -> bool:
        row, child = key  # type: ignore[misc]
        if self.rows == 0:
            return key == (-1, None)
        if child is None:
            return 0 <= row < self.rows
        return row == self.open_item and 0 <= child < self.results


@dataclass(frozen=True)
class _ChildOrder:
    """The cursor positions while it is among the results of the open row (the split view): just those results."""

    row: int
    results: int

    def __len__(self) -> int:
        return self.results

    def key(self, at: int) -> tuple[int, int | None]:
        return (self.row, at)

    def index(self, key: tuple[int, int | None]) -> int:
        return key[1] or 0

    def __contains__(self, key: object) -> bool:
        row, child = key  # type: ignore[misc]
        return row == self.row and child is not None and 0 <= child < self.results


def _gutter(lines: list[str], selected: bool, indent: int = INDENT) -> list[str]:
    """Indent a block of rendered lines; the first one carries `>` when the block is selected."""
    pad = " " * indent
    marked = " " * (indent - 2) + MARK + " "
    return [(marked if selected and i == 0 else pad) + line for i, line in enumerate(lines)]


def _target(tab: Tab, st: _State) -> tuple[Item, Entry] | str:
    """The row and the result `s` means, or a message saying what to do first."""
    if tab.kind != "word":
        return "Only a word row has variants to save"
    row, child = st.cursor
    if row < 0 or row >= len(tab.items) or st.open_item != row:
        return "Open a row (l) and pick a variant (1-9) first"
    entries = st.loaded[row].entries
    if child is not None:
        return tab.items[row], entries[child]
    if len(entries) == 1:
        return tab.items[row], entries[0]
    return "Pick a variant (1-9) first"


def _save_variant(tab: Tab, st: _State, save: Callable | None) -> tuple[str, bool]:
    """Handle `s`: (the message for the bottom line, whether the tab's rows were replaced)."""
    target = _target(tab, st)
    if isinstance(target, str):
        return target, False
    if save is None:
        return "Saving is not available here", False
    item, entry = target
    rows, message = save(tab, item, entry)
    if rows is None:
        return message, False
    tab.items[:] = rows
    st.cursor = (next((n for n, r in enumerate(rows) if r.query.casefold() == entry.lemma.casefold()), 0), None)
    return message, True


def browse(
    tabs: list[Tab],
    console: Console,
    screen_rows: Callable[[], int],
    delete: Callable[[Tab, Item], str | None],
    keys: Callable[[], str] | None = None,
    banner: Callable[[], list[str]] | None = None,
    save: Callable[[Tab, Item, Entry], tuple[list[Item] | None, str]] | None = None,
    waiting: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Show the history until the user closes it. Call inside `picker.fullscreen()` and `picker.cbreak()`.

    `delete(tab, item)` removes the row from the stored history; the view drops it from the tab itself. It returns
    a message (shown in the bottom line, the row stays) when it could not.
    `save(tab, item, entry)` saves `entry`'s word instead of the row's text; it returns the tab's rows afresh (newest
    first), or None when nothing changed, and a message for the bottom line.
    `waiting()` says whether another key is already waiting (default: the terminal's), `clock()` is the time in
    seconds; both exist so that tests can play a held key.
    """
    keys = keys or picker.read_key
    waiting = waiting or picker.key_waiting
    states = [_State(cursor=(0 if tab.items else -1, None)) for tab in tabs]  # the rows come newest first: each starts on the top one
    active = 0 if tabs[0].items or not tabs[-1].items else len(tabs) - 1
    confirming: int | None = None  # the row `x` asked about
    message = ""  # the answer to the last `s`, shown in the bottom line until the next key
    pushback: list[str] = []  # a key read ahead that is not a move: handled next
    held_direction: int | None = None  # the direction of the last move, while moves follow each other
    cache: dict[tuple, str] = {}  # rendered rows: only the selected row changes when the cursor moves

    def read() -> str:
        try:
            return keys()
        except KeyboardInterrupt:
            return "esc"

    def row_line(item: Item, selected: bool, width: int, pad: bool = False, dim: bool = False) -> str:
        key = (item.query, item.meaning, item.style, selected, width, pad, dim)
        line = cache.get(key)
        if line is None:
            if len(cache) >= ROW_CACHE:
                cache.clear()
            line = cache[key] = picker.render_lines(console, [_row(item, selected, width, pad, dim)])[0]
        return line

    consoles: dict[int, Console] = {}  # consoles of a given width, for rendering what is shown narrower than the window

    def console_for(width: int) -> Console:
        if width not in consoles:
            if len(consoles) > 8:
                consoles.clear()
            consoles[width] = _console_of(console, width)
        return consoles[width]

    separator = picker.render_lines(console, [Text("│", style=MUTED)])[0]  # between the list and the results

    while True:
        tab, st = tabs[active], states[active]
        items = tab.items
        count = len(items)
        rows = max(screen_rows(), 5)
        fixed = banner() if banner else []
        if len(fixed) > rows - 5:
            fixed = []
        fixed = fixed + picker.render_lines(console, [_tab_line(tabs, active), _rule(console)])  # the tabs, a line, then the list
        room = rows - len(fixed) - 1
        width = max(console.width - 1, 10)
        wide = _panes(console.width)  # (list columns, result columns) when the window is wide enough for a side pane
        narrow = console_for(max(console.width - INDENT, 20))
        if wide:  # where a card would be shown: the side pane (below its word and a note)
            result_console, result_room = console_for(max(wide[1] - GUTTER, 20)), room - 4
        else:
            result_console, result_room = narrow, room

        if st.open_item is not None and (st.open_item >= count or st.open_item not in st.loaded):
            st.open_item = st.open_child = None
        open_i = st.open_item
        results = len(st.loaded[open_i].entries) if open_i is not None else 0
        panes = wide if open_i is not None else None  # the side pane exists only while a row is open
        if panes:
            # the cursor is in the pane: on one of the results (the first when it opens), or on the word when there are none
            child = st.cursor[1] if st.cursor[0] == open_i else None
            if child is None or child >= results:
                child = 0 if results else None
            st.cursor = (open_i, child)
            order = _ChildOrder(open_i, results)
        else:
            order = _Order(count, open_i, results)
            if st.cursor not in order:
                st.cursor = (st.cursor[0], None)
            if st.cursor not in order:
                st.cursor = order.key(0)

        if panes:
            # Side pane: the list narrows to the left (one line per row, nothing expands), the open row's word and its
            # results are on the right; the word stays at the top of the pane, the rest of it scrolls.
            left_w, right_w = panes
            pane = console_for(right_w)
            cards = console_for(max(right_w - GUTTER, 20))
            loaded = st.loaded[open_i]
            opened = items[open_i]
            title = Text()
            if results == 0:  # nothing to pick: the arrow is on the word itself
                title.append(f"{MARK} ")
            title.append(opened.query, style=f"bold {opened.style}".strip())
            title.truncate(right_w, overflow="ellipsis")
            title_line = picker.render_lines(pane, [title])[0]
            body: list[str] = []
            heading = loaded.note or ("" if loaded.entries or loaded.blocks else "Nothing found.")
            if heading:
                body += picker.render_lines(pane, [Text(heading, style=MUTED)])
            for block in loaded.blocks:
                body += picker.render_lines(pane, [block])
            head_rows = len(body)
            child_heights: list[int] = []
            for j, entry in enumerate(loaded.entries):
                shown = render_card(entry) if j == st.open_child else render_compact(entry, j + 1, False)
                lines = _gutter(picker.render_lines(cards, [shown]), st.cursor == (open_i, j), GUTTER)
                child_heights.append(len(lines))
                body += lines
            body_room = room - 1
            if st.right_for != open_i:
                st.right_top, st.right_for = 0, open_i
            if st.cursor[1] is not None:  # keep the picked result in view
                r_start = head_rows + sum(child_heights[: st.cursor[1]])
                r_end = r_start + child_heights[st.cursor[1]]
            else:
                r_start = r_end = 0
            if r_start < st.right_top:
                st.right_top = r_start
            if r_end > st.right_top + body_room:
                st.right_top = r_end - body_room
            if st.right_top > r_start:  # a result taller than the room: show its beginning
                st.right_top = r_start
            st.right_top = max(0, min(st.right_top, len(body) - body_room))

            if open_i < st.top:  # keep the open row in view in the narrowed list
                st.top = open_i
            if open_i + 1 > st.top + room:
                st.top = open_i + 1 - room
            st.top = max(0, min(st.top, count - room))
            listed = [row_line(items[r], r == open_i, left_w, True, dim=r == open_i) for r in range(st.top, min(st.top + room, count))]
            visible = []
            for k in range(room):
                if k == 0:
                    shown_right = title_line
                else:
                    at_body = st.right_top + k - 1
                    shown_right = body[at_body] if at_body < len(body) else ""
                visible.append((listed[k] if k < len(listed) else " " * left_w) + separator + shown_right)
        else:
            # Narrow window: the open row expands in place. Closed rows are one line each, so only the open row and what is
            # visible are rendered.
            placeholder = picker.render_lines(console, [Text(tab.empty, style=MUTED)]) if count == 0 else []
            open_lines: list[str] = []  # the open row with its heading, then its results
            row_height = 0
            child_heights = []
            if open_i is not None:
                loaded = st.loaded[open_i]
                open_lines = [row_line(items[open_i], st.cursor == (open_i, None), width)]
                heading = loaded.note or ("" if loaded.entries or loaded.blocks else "Nothing found.")
                if heading:
                    open_lines += picker.render_lines(narrow, [Text(heading, style=MUTED)])
                for block in loaded.blocks:
                    open_lines += [" " * INDENT + line for line in picker.render_lines(narrow, [block])]
                row_height = len(open_lines)
                for j, entry in enumerate(loaded.entries):
                    shown = render_card(entry) if j == st.open_child else render_compact(entry, j + 1, False)
                    lines = _gutter(picker.render_lines(narrow, [shown]), st.cursor == (open_i, j))
                    child_heights.append(len(lines))
                    open_lines += lines
            total = len(placeholder) if count == 0 else count - 1 + len(open_lines) if open_i is not None else count

            row, child = st.cursor
            if count == 0:
                start, end = 0, len(placeholder)
            elif open_i is None or (row < open_i and child is None):
                start, end = row, row + 1
            elif child is not None:
                start = open_i + row_height + sum(child_heights[:child])
                end = start + child_heights[child]
            elif row == open_i:
                start, end = open_i, open_i + row_height
            else:
                start = open_i + len(open_lines) + (row - open_i - 1)
                end = start + 1
            if start < st.top:  # keep the cursor's block in view
                st.top = start
            if end > st.top + room:
                st.top = end - room
            if st.top > start:  # a block taller than the room: show its beginning
                st.top = start
            st.top = max(0, min(st.top, total - room))

            top, bottom = st.top, st.top + room
            if count == 0:
                visible = placeholder[top:bottom]
            elif open_i is None:
                visible = [row_line(items[r], st.cursor == (r, None), width) for r in range(top, min(bottom, count))]
            else:
                visible = [row_line(items[r], st.cursor == (r, None), width) for r in range(top, min(bottom, open_i))]
                lo, hi = max(top - open_i, 0), min(bottom - open_i, len(open_lines))
                if lo < hi:
                    visible += open_lines[lo:hi]
                after = open_i + len(open_lines)  # the line of the first row below the open one
                for line_no in range(max(top, after), bottom):
                    r = open_i + 1 + (line_no - after)
                    if r >= count:
                        break
                    visible.append(row_line(items[r], st.cursor == (r, None), width))

        if confirming is not None:
            hint = f'Delete "{items[confirming].query}"? y/n'
        elif message:
            hint = message
        elif panes:
            hint = PANE_HINT
        else:
            hint = HINT.format(other=tabs[(active + 1) % len(tabs)].title.lower())
        picker.paint(console, fixed, visible, hint, rows)
        idle_since = clock()
        key = pushback.pop() if pushback else read()
        waited = clock() - idle_since  # how long the screen waited for this key
        if key != "resize":
            message = ""

        if confirming is not None:  # the answer to the delete question: only `y` deletes, anything else keeps
            if key == "resize":
                continue
            i, confirming = confirming, None
            if key == "y":
                failed = delete(tab, items[i])
                if failed:
                    message = failed
                else:
                    items.pop(i)
                    st.loaded.clear()
                    st.open_item = st.open_child = None
                    st.cursor = (min(i, len(items) - 1), None)
            held_direction = None
            continue

        if key in NAVIGATION:
            if len(order) == 0:  # a side pane with nothing to pick
                continue
            # One press moves one row; the same key again right after the last move is a held key: two rows. Presses
            # already waiting (the screen is behind a held key) are taken together, so the selection stops soon after
            # the key is let go.
            direction = NAVIGATION[key]
            at = order.index(st.cursor)
            step = HELD_STEP if held_direction == direction and waited < HELD_WINDOW else 1
            at = min(max(at + direction * step, 0), len(order) - 1)
            held_direction = direction
            for _ in range(MAX_READ_AHEAD):
                if not waiting():
                    break
                ahead = read()
                if ahead not in NAVIGATION:
                    pushback.append(ahead)
                    break
                held_direction = NAVIGATION[ahead]
                at = min(max(at + held_direction * HELD_STEP, 0), len(order) - 1)
            st.cursor = order.key(at)
            continue
        if key != "resize":
            held_direction = None

        at = order.index(st.cursor)

        def activate(target: tuple[int, int | None]) -> None:
            """Open what the cursor is on: a row in place, or one of its results as a full card."""
            i, j = target
            if j is None:
                if st.open_item == i:
                    st.open_item = st.open_child = None
                    return
                st.open_item, st.open_child = i, None
                if i not in st.loaded:
                    if tab.status:
                        picker.paint(console, fixed, visible, tab.status, rows)
                    st.loaded[i] = tab.load(items[i])
                if len(st.loaded[i].entries) == 1 and fits(st.loaded[i].entries[0]):  # nothing to choose: show the card itself
                    st.open_child = 0
                if wide:  # the side pane takes the cursor
                    st.cursor = (i, 0 if st.loaded[i].entries else None)
            elif st.open_child == j:
                st.open_child = None
            elif fits(st.loaded[i].entries[j]):
                st.open_child = j
            else:  # taller than its place: a screen of its own, with scrolling
                picker.run([st.loaded[i].entries[j]], console, screen_rows, keys, banner=banner, active_card=True)
                if wide:  # with a side pane, back from the card is back at the list: one key, not two
                    st.open_item = st.open_child = None
                    st.cursor = (i, None)

        def fits(entry: Entry) -> bool:
            return len(picker.render_lines(result_console, [render_card(entry)])) <= result_room

        if key == "\t":
            active = (active + 1) % len(tabs)
        elif key == "g":
            if len(order):
                st.cursor = order.key(0)
        elif key == "G":
            if len(order):
                st.cursor = order.key(len(order) - 1)
        elif key in ("l", "enter"):
            if items:
                activate(st.cursor)
        elif key == "h":
            i, j = st.cursor
            if panes:  # the side pane: one `h` goes back to the list, whatever the pane shows
                st.open_item = st.open_child = None
                st.cursor = (i, None)
            elif j is None:
                if st.open_item == i:
                    st.open_item = st.open_child = None
            elif st.open_child == j:
                st.open_child = None
            else:
                st.cursor = (i, None)
        elif key == "s":
            message, changed = _save_variant(tab, st, save)
            if changed:  # the rows were replaced: nothing stays open, the cursor is on the saved word
                st.loaded.clear()
                st.open_item = st.open_child = None
        elif key == "x":
            if items and st.cursor[1] is None and not panes:  # on a row of the list, not in an open row's results
                confirming = st.cursor[0]
        elif key in ("q", "esc"):
            if st.open_item is None:
                return
            st.cursor = (st.open_item, None)
            st.open_item = st.open_child = None
        elif key.isdigit() and key != "0":
            n = int(key) - 1
            if st.open_item is not None:  # while a row is open, digits pick among its results
                if n < len(st.loaded[st.open_item].entries):
                    st.cursor = (st.open_item, n)
                    if st.open_child != n:
                        activate(st.cursor)
        # anything else (unknown sequence, blank, other letters): ignored
