"""The query history as an accordion, in the style of the search results (the `/history` view).

The history is a bullet list, `• word — translation`; the selected entry is bracketed by two grey separators. `l`/Enter opens it
in place: its results appear below as compact cards, and a card opens in place into the full word card.
A full card taller than the screen opens on a screen of its own instead (with scrolling). Runs on the
alternate screen, with the banner fixed at the top, like the picker.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from rich.console import Console
from rich.text import Text

from wort import picker
from wort.dictionary.lookup import Entry
from wort.render.card import MUTED, render_card, render_compact

INDENT = 4
HINT = "j k move · l open · h back · 1-9 pick result · q close"


@dataclass
class Item:
    query: str
    found: bool
    count: int
    ts: datetime
    meaning: str


Loader = Callable[[Item], tuple[list[Entry], str]]  # an item's results (or, for a miss, suggestions) and a note


def _sub(console: Console, indent: int) -> Console:
    """A console `indent` columns narrower, same colors, for rendering what is shown indented."""
    return Console(
        width=max(console.width - indent, 20),
        file=io.StringIO(),
        force_terminal=console.is_terminal,
        color_system=console.color_system,
        highlight=False,
    )


def _row(item: Item, width: int) -> Text:
    """One bullet: `• word — translation` (translation in grey), cut to one line."""
    line = Text("• ")
    line.append(item.query)
    line.append(f" — {item.meaning or 'nothing found'}", style=MUTED)
    line.truncate(width, overflow="ellipsis")
    return line


def _rule(console: Console) -> Text:
    """A heavy grey separator: the selected entry is bracketed by two of them."""
    return Text("━" * console.width, style=MUTED)


def browse(
    items: list[Item],
    load: Loader,
    console: Console,
    screen_rows: Callable[[], int],
    keys: Callable[[], str] | None = None,
    banner: Callable[[], list[str]] | None = None,
) -> None:
    """Show the history until the user closes it. Call inside `picker.fullscreen()` and `picker.cbreak()`."""
    keys = keys or picker.read_key
    loaded: dict[int, tuple[list[Entry], str]] = {}
    open_item: int | None = None  # the expanded history entry (one at a time)
    open_child: int | None = None  # its result shown as a full card in place
    cursor: tuple[int, int | None] = (len(items) - 1, None)  # (history entry, result of the open entry)
    top = 0

    while True:
        rows = max(screen_rows(), 4)
        fixed = banner() if banner else []
        if len(fixed) > rows - 4:
            fixed = []
        room = rows - len(fixed) - 1
        narrow = _sub(console, INDENT)

        blocks: list[tuple[tuple[int, int | None], list[str]]] = []
        for i, item in enumerate(items):
            row = _row(item, max(console.width - 1, 10))
            shown = [_rule(console), row, _rule(console)] if cursor == (i, None) else [row]
            lines = picker.render_lines(console, shown)
            if i == open_item:
                entries, note = loaded[i]
                heading = note or ("" if entries else "Nothing found.")
                if heading:
                    lines += picker.render_lines(narrow, [Text(heading, style=MUTED)])
            blocks.append(((i, None), lines))
            if i == open_item:
                for j, entry in enumerate(loaded[i][0]):
                    shown = (
                        render_card(entry, selected=cursor == (i, j))
                        if j == open_child
                        else render_compact(entry, j + 1, cursor == (i, j))
                    )
                    blocks.append(((i, j), [" " * INDENT + line for line in picker.render_lines(narrow, [shown])]))

        order = [key for key, _ in blocks]
        if cursor not in order:
            cursor = (cursor[0], None)
        flat = [line for _, lines in blocks for line in lines]
        start = sum(len(lines) for key, lines in blocks[: order.index(cursor)])
        end = start + len(blocks[order.index(cursor)][1])
        if start < top:  # keep the cursor's block in view
            top = start
        if end > top + room:
            top = end - room
        if top > start:  # a block taller than the room: show its beginning
            top = start
        top = max(0, min(top, len(flat) - room))

        picker.paint(console, fixed, flat[top : top + room], HINT, rows)
        try:
            key = keys()
        except KeyboardInterrupt:
            key = "esc"
        at = order.index(cursor)

        def activate(target: tuple[int, int | None]) -> None:
            """Open what the cursor is on: a history entry in place, or one of its results as a full card."""
            nonlocal open_item, open_child
            i, j = target
            if j is None:
                if open_item == i:
                    open_item = open_child = None
                    return
                open_item, open_child = i, None
                if i not in loaded:
                    loaded[i] = load(items[i])
                if len(loaded[i][0]) == 1 and fits(loaded[i][0][0]):  # nothing to choose: show the card itself
                    open_child = 0
            elif open_child == j:
                open_child = None
            elif fits(loaded[i][0][j]):
                open_child = j
            else:  # taller than the screen: a screen of its own, with scrolling
                picker.run([loaded[i][0][j]], console, screen_rows, keys, banner=banner, active_card=True)

        def fits(entry: Entry) -> bool:
            return len(picker.render_lines(narrow, [render_card(entry)])) <= room

        if key in ("j", "down"):
            cursor = order[min(at + 1, len(order) - 1)]
        elif key in ("k", "up"):
            cursor = order[max(at - 1, 0)]
        elif key == "g":
            cursor = order[0]
        elif key == "G":
            cursor = order[-1]
        elif key in ("l", "enter"):
            activate(cursor)
        elif key == "h":
            i, j = cursor
            if j is None:
                if open_item == i:
                    open_item = open_child = None
            elif open_child == j:
                open_child = None
            else:
                cursor = (i, None)
        elif key in ("q", "esc"):
            if open_item is None:
                return
            cursor = (open_item, None)
            open_item = open_child = None
        elif key.isdigit() and key != "0":
            n = int(key) - 1
            if open_item is not None:  # while an entry is open, digits pick among its results
                if n < len(loaded[open_item][0]):
                    cursor = (open_item, n)
                    if open_child != n:
                        activate(cursor)
        # anything else (unknown sequence, blank, other letters): ignored
