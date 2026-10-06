"""Choose between several lookup results in the interactive session, lazygit style.

The results are drawn as a numbered compact list. `j`/`k` (or the arrow keys) move the
selection, a digit, `l` or Enter opens the full card, `h` (or `q`/Esc) goes back to the list;
`q`/Esc in the list closes it. In the full card `j`/`k` scroll (space / `b` page down / up, `g`/`G` top / bottom) and a digit
switches to another result. A card or list taller than the screen shows one page at a time.
In the list, any other printable key closes the picker and is handed back, so it can start the next word.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import sys
from typing import Callable, Iterator

from rich.console import Console
from rich.text import Text

from wort.dictionary.lookup import Entry
from wort.render.card import MUTED, render_card, render_compact

try:
    import termios
    import tty
except ImportError:  # no terminal control (Windows): results are printed in full instead
    termios = tty = None

HINT_LIST = "1-9 / l open · j k move · q close"
HINT_CARD = "1-9 other result · h back"
HINT_CARD_SCROLL = "j k scroll · space b page · h back"


def usable() -> bool:
    """True when stdin is a real terminal we can read single keys from."""
    return has_terminal()


def has_terminal() -> bool:
    """The actual check behind `usable` (tests replace `usable` to fake key input; this one stays honest)."""
    if termios is None:
        return False
    try:
        termios.tcgetattr(sys.stdin.fileno())
    except (OSError, ValueError, termios.error):  # not a tty, or no fileno (redirected / replaced stdin)
        return False
    return True


_wake_fd: int | None = None  # read end of the pipe SIGWINCH writes to while cbreak() is active


@contextlib.contextmanager
def cbreak() -> Iterator[None]:
    """Single-key input without Enter; Ctrl-C still raises KeyboardInterrupt. Always restores the terminal.

    While active, a terminal resize (SIGWINCH) wakes up `read_key`, which then returns 'resize'.
    """
    global _wake_fd
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    read_end, write_end = os.pipe()
    os.set_blocking(read_end, False)
    os.set_blocking(write_end, False)
    old_handler = old_wakeup = None
    try:
        # a Python-level handler is needed for the wakeup fd to be written; signals only work on the main thread
        old_handler = signal.signal(signal.SIGWINCH, lambda *_: None)
        old_wakeup = signal.set_wakeup_fd(write_end, warn_on_full_buffer=False)
        _wake_fd = read_end
    except ValueError:  # not the main thread: no resize events, everything else works
        pass
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        _wake_fd = None
        if old_handler is not None:
            signal.set_wakeup_fd(-1 if old_wakeup is None else old_wakeup)
            signal.signal(signal.SIGWINCH, old_handler)
        os.close(read_end)
        os.close(write_end)


@contextlib.contextmanager
def fullscreen() -> Iterator[None]:
    """The terminal's alternate screen (like lazygit): redrawn from scratch on every change, so a resize
    cannot leave debris, and the normal screen comes back exactly as it was."""
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


def wait_for_key() -> None:
    """Block until a key is pressed, without consuming it (the next `input()` still receives it).

    A terminal in line mode reports input only after Enter, so for the wait it is put in cbreak mode
    (echo off too: readline shows the key itself once it takes over). Pending typeahead is kept.
    """
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd, termios.TCSADRAIN)  # TCSAFLUSH, the default, would throw typeahead away
        select.select([fd], [], [])
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def read_key() -> str:
    """One key: 'enter', 'esc', 'up', 'down', 'resize' (terminal size changed), or the typed character.

    Unknown escape sequences give ''.
    """
    fd = sys.stdin.fileno()
    waiting = [fd] if _wake_fd is None else [fd, _wake_fd]
    while True:
        ready = select.select(waiting, [], [])[0]
        if _wake_fd in ready:
            with contextlib.suppress(BlockingIOError):
                os.read(_wake_fd, 64)  # drain; other signals (Ctrl-C) are handled by Python itself
            return "resize"
        if fd in ready:
            break
    first = os.read(fd, 1)
    if not first:
        return "esc"  # EOF
    if first in (b"\r", b"\n"):
        return "enter"
    if first == b"\x04":  # Ctrl-D
        return "esc"
    if first == b"\x1b":
        if not select.select([fd], [], [], 0.05)[0]:
            return "esc"
        seq = os.read(fd, 2)
        return {b"[A": "up", b"[B": "down"}.get(seq, "")
    lead = first[0]
    extra = 3 if lead >= 0xF0 else 2 if lead >= 0xE0 else 1 if lead >= 0xC0 else 0  # UTF-8 continuation bytes
    raw = first + (os.read(fd, extra) if extra else b"")
    return raw.decode("utf-8", errors="replace")


def render_lines(console: Console, renderables: list) -> list[str]:
    """Render to terminal lines (ANSI included); every line closes its own styles, so any slice is safe to print."""
    with console.capture() as captured:
        for item in renderables:
            console.print(item)
    return captured.get().rstrip("\n").split("\n")


def paint(console: Console, banner: list[str], lines: list[str], hint: str, rows: int) -> None:
    """Paint one full-screen frame: the fixed `banner` rows, then `lines`, the hint on the last row.

    The whole frame is one synchronized write (no flashing). Each line is cleared before it is written:
    clearing after a full-width line could eat its last character.
    """
    with console.capture() as captured:
        console.print(Text(hint[: max(console.width - 1, 10)], style=MUTED), markup=False)  # one line, never wrapped
    body = lines[: rows - 1 - len(banner)]
    frame = [*banner, *body, *[""] * (rows - 1 - len(banner) - len(body)), captured.get().rstrip("\n")]
    out = "\r\n".join(f"\x1b[2K{line}" for line in frame)
    sys.stdout.write(f"\x1b[?2026h\x1b[H{out}\x1b[J\x1b[?2026l")  # 2026: synchronized update, ignored if unsupported
    sys.stdout.flush()


def too_tall(entry: Entry, console: Console, screen_rows: int) -> bool:
    """True when the full card of this entry does not fit on the screen (so it needs scrolling)."""
    return len(render_lines(console, [render_card(entry)])) > max(screen_rows - 2, 3)


def run(
    entries: list[Entry],
    console: Console,
    screen_rows: Callable[[], int],
    keys: Callable[[], str] | None = None,
    heading: str = "",
    listed: bool = False,
    banner: Callable[[], list[str]] | None = None,
    active_card: bool = False,
) -> str | None:
    """Run the picker (on whatever screen is current) until it is closed. Returns the key that closed it, if it was a character.

    The screen is re-measured before every frame, and a resize redraws at once. `banner` gives lines that
    stay fixed at the top of every frame while the rest scrolls below them.

    `active_card` draws an open card with the selected (heavy, bold) border.

    `heading` is a muted line above the list (not above an open card). A single entry opens as a card
    (for scrolling) unless `listed` asks for the list anyway (suggestions).
    """
    keys = keys or read_key
    single = len(entries) == 1 and not listed  # one tall card: shown open from the start, closing it leaves the picker
    selected, opened = 0, single
    list_top = card_top = 0  # first visible line of the list / of the open card
    while True:
        rows = max(screen_rows(), 4)
        fixed = banner() if banner else []
        if len(fixed) > rows - 4:  # keep some working room, whatever the window
            fixed = []
        room = rows - len(fixed) - 1  # the last row is the hint
        if opened:
            lines = render_lines(console, [render_card(entries[selected], footer=None if single else f"{selected + 1}/{len(entries)}", selected=active_card)])
            card_top = max(0, min(card_top, len(lines) - room))
            hint = HINT_CARD
            if len(lines) > room:
                hint = f"{HINT_CARD_SCROLL} · {card_top + 1}-{min(card_top + room, len(lines))}/{len(lines)}"
            if single:
                hint = hint.replace("1-9 other result · h back", "q close").replace("h back", "q close")
        else:
            blocks = [render_lines(console, [render_compact(e, i + 1, i == selected)]) for i, e in enumerate(entries)]
            top_lines = render_lines(console, [Text(heading, style=MUTED)]) if heading else []
            lines = top_lines + [line for block in blocks for line in block]
            start = len(top_lines) + sum(len(b) for b in blocks[:selected])
            end = start + len(blocks[selected])
            if start < list_top:  # keep the selection in view
                list_top = start
            if end > list_top + room:
                list_top = end - room
            list_top = max(0, min(list_top, len(lines) - room))
            hint = HINT_LIST
        top = card_top if opened else list_top
        paint(console, fixed, lines[top : top + room], hint, rows)
        try:
            key = keys()
        except KeyboardInterrupt:
            key = "esc"

        if opened and key in ("j", "down"):
            card_top += 1
        elif opened and key in ("k", "up"):
            card_top -= 1
        elif opened and key == " ":
            card_top += room
        elif opened and key == "b":
            card_top -= room
        elif opened and key == "g":
            card_top = 0
        elif opened and key == "G":
            card_top = len(lines)  # clamped on the next draw
        elif not opened and key in ("j", "down"):
            selected = (selected + 1) % len(entries)
        elif not opened and key in ("k", "up"):
            selected = (selected - 1) % len(entries)
        elif key.isdigit() and 1 <= int(key) <= len(entries):
            selected, opened, card_top = int(key) - 1, True, 0
        elif key in ("l", "enter") and not opened:
            opened, card_top = True, 0
        elif key in ("h", "q", "esc") and single:
            return None
        elif key == "h":
            opened = False
        elif key in ("q", "esc"):
            if not opened:
                return None
            opened = False
        elif len(key) == 1 and key.strip() and key.isprintable() and not key.isdigit() and not opened:
            return key  # starts the next word
        # anything else (unknown sequence, blank, a digit out of range, other keys inside a card): ignored


def pick(
    entries: list[Entry],
    console: Console,
    screen_rows: Callable[[], int],
    keys: Callable[[], str] | None = None,
    heading: str = "",
    listed: bool = False,
    banner: Callable[[], list[str]] | None = None,
) -> str | None:
    """`run` on the alternate screen: the picker takes the whole terminal and gives it back untouched."""
    with fullscreen():
        return run(entries, console, screen_rows, keys, heading, listed, banner)
