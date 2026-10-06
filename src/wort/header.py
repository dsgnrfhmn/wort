"""The banner pinned to the top of the terminal and the command list pinned to the bottom, while the
session scrolls between them.

Done with a terminal scroll region (DECSTBM): the rows above and below it never scroll. A resize redraws
both and moves the region. A window too small for the banner, the footer and some working room gets
nothing pinned (the session then works exactly as it would without it).
"""

from __future__ import annotations

import contextlib
import os
import select
import shutil
import signal
import sys
from typing import Callable, Iterator

from rich.console import Console
from rich.text import Text

from wort.render.card import MUTED

RECENT_WORDS = 5
WORKING_ROWS = 9  # rows that must stay free between the pinned parts, or nothing is pinned
FOOTER_ROWS = 1


class Header:
    def __init__(self, console: Console, banner: str, footer: str, screen_rows: Callable[[], int] | None = None):
        self.console, self.banner, self.footer = console, banner, footer
        self.screen_rows = screen_rows or (lambda: shutil.get_terminal_size().lines)
        self.active = False
        self.recent_visible = True  # shown while idle; hidden while a search or a selection is on screen
        self.recent: list[tuple[str, str]] = []  # (query, translation), newest first: the bullets under the banner
        self.base = len(banner.split("\n"))  # banner rows
        self._extra = 0  # rows for the recent words; decided when the screen is wiped, only ever lowered on a resize
        self._painted = 0  # rows covered by the last paint, so a shrinking header can blank what it leaves
        self._footer_row = 0  # where the footer was last drawn

    @property
    def height(self) -> int:
        """Pinned rows at the top: the banner, plus the recent words while idle."""
        return self.base + self._extra if self.recent_visible else self.base

    def _room_for_bullets(self) -> int:
        """Rows for the recent words: as many as there are (up to five) if the window has room for them."""
        wanted = min(len(self.recent), RECENT_WORDS)
        return wanted if self.screen_rows() >= self.base + wanted + FOOTER_ROWS + WORKING_ROWS else 0

    def fits(self) -> bool:
        return self.screen_rows() >= self.height + FOOTER_ROWS + WORKING_ROWS

    def usable_rows(self) -> int:
        """Rows the session can scroll in (the cursor cannot move above them)."""
        return self.screen_rows() - (self.height + FOOTER_ROWS if self.active else 0)

    def _lines(self, bullets: bool = True) -> list[str]:
        """The pinned top rows as terminal lines: the banner, then (while idle) the recent words as bullets."""
        width = max(self.console.width - 1, 10)
        with self.console.capture() as captured:
            self.console.print(Text(self.banner, style="bold"), markup=False)
        lines = captured.get().rstrip("\n").split("\n")
        if bullets and self.recent_visible:
            lines += [self._render(_bullet(q, meaning, width)) for q, meaning in self.recent[: self._extra]]
        return lines

    def _render(self, text: Text) -> str:
        with self.console.capture() as captured:
            self.console.print(text, markup=False)
        return captured.get().rstrip("\n")

    @contextlib.contextmanager
    def recent_hidden(self) -> Iterator[None]:
        """Hide the recent words while a selection view is open (back afterwards, if they were shown)."""
        was, self.recent_visible = self.recent_visible, False
        try:
            yield
        finally:
            self.recent_visible = was

    def pinned_lines(self) -> list[str]:
        """The banner as rendered lines, for full-screen views that draw it themselves ([] if too small).

        The recent words are left out: a selection view is no place for them.
        """
        return self._lines(bullets=False) if self.screen_rows() >= self.base + WORKING_ROWS else []

    def _paint(self, cursor: str) -> None:
        """Draw the banner and the footer and set the scroll region between them (which homes the cursor),
        then run `cursor`."""
        rows = self.screen_rows()
        lines = self._lines()
        lines += [""] * (self._painted - len(lines))  # rows the header no longer uses are blanked
        self._painted = self.height
        body = "\r\n".join(f"\x1b[2K{line}" for line in lines)
        stale = f"\x1b[{self._footer_row};1H\x1b[2K" if 0 < self._footer_row < rows else ""  # footer's old place
        footer = self._render(Text(self.footer[: max(self.console.width - 1, 10)], style=MUTED))
        self._footer_row = rows
        region = f"\x1b[{self.height + 1};{rows - FOOTER_ROWS}r"
        sys.stdout.write(
            f"\x1b[?2026h{stale}\x1b[{rows};1H\x1b[2K{footer}\x1b[H{body}{region}{cursor}\x1b[?2026l"
        )
        sys.stdout.flush()

    @property
    def _first_free_row(self) -> str:
        return f"\x1b[{self.height + 1};1H"

    def start(self) -> bool:
        """Clear the screen and pin the banner and the footer. False (nothing pinned) when the window is too small."""
        if not self.fits():
            return False
        sys.stdout.write("\x1b[H\x1b[2J")
        self._extra, self._painted, self._footer_row = self._room_for_bullets(), 0, 0
        self._paint(self._first_free_row)
        self.active = True
        with contextlib.suppress(ValueError):  # signals only work on the main thread
            signal.signal(signal.SIGWINCH, lambda *_: self.refresh())
        return True

    def clear(self) -> None:
        """The `clear` command: wipe the working area, keep what is pinned."""
        sys.stdout.write("\x1b[H\x1b[2J")
        self._extra, self._painted, self._footer_row = self._room_for_bullets(), 0, 0  # empty screen: may grow again
        self._paint(self._first_free_row)

    def _shrink_to_fit(self) -> None:
        """Drop the recent words if the window no longer has room for them (growing waits for `clear`)."""
        if not self.fits():
            self._extra = 0

    def hide_recent(self) -> None:
        """A search is on screen: drop the recent words and close the gap they leave.

        The working area grows upwards: its content is scrolled up by the rows freed (it is only the prompt
        lines at this point), so there is no empty space between the banner and the text.
        """
        if not self.recent_visible:
            return
        before = self.height
        self.recent_visible = False
        if not self.active:
            return
        gap = before - self.height
        sys.stdout.write("\x1b7")  # setting the region homes the cursor; come back, then move up with the content
        self._paint(f"\x1b8\x1b[{gap}S\x1b[{gap}A" if gap else "\x1b8")

    def refresh(self) -> None:
        """The window changed size: redraw what is pinned and move the region; the cursor stays where it was."""
        if not self.active:
            return
        self._shrink_to_fit()
        if not self.fits():
            self.stop()
            return
        sys.stdout.write("\x1b7")  # save the cursor: setting the region homes it
        self._paint("\x1b8")

    def stop(self) -> None:
        """Back to a normal screen; the cursor stays where it is."""
        if self.active:
            sys.stdout.write("\x1b7\x1b[r\x1b8")  # resetting the region homes the cursor
            sys.stdout.flush()
            self.active = False
            with contextlib.suppress(ValueError):
                signal.signal(signal.SIGWINCH, signal.SIG_DFL)

    @contextlib.contextmanager
    def suspended(self) -> Iterator[None]:
        """Release the region for a full-screen view and bring it back, cursor included, afterwards.

        Needs the terminal in cbreak mode: the cursor row is read back from the terminal (the alternate
        screen overwrites the terminal's own saved cursor, so that cannot be relied on).
        """
        if not self.active:
            yield
            return
        row = _cursor_row()
        sys.stdout.write("\x1b[r")
        sys.stdout.flush()
        try:
            yield
        finally:
            top = self.height + 1
            back = f"\x1b[{max(top, min(row, self.screen_rows() - FOOTER_ROWS))};1H" if row else self._first_free_row
            self._shrink_to_fit()
            if self.fits():
                self._paint(back)
            else:  # shrunk below the limit while away: nothing pinned any more
                self.active = False
                sys.stdout.write(back)
                sys.stdout.flush()


def _cursor_row() -> int | None:
    """Ask the terminal where the cursor is (1-based row); None if it does not answer."""
    try:
        fd = sys.stdin.fileno()
        sys.stdout.write("\x1b[6n")
        sys.stdout.flush()
        reply = b""
        while not reply.endswith(b"R"):
            if not select.select([fd], [], [], 0.3)[0]:
                return None
            reply += os.read(fd, 32)
        return int(reply.rsplit(b"[", 1)[1].split(b";")[0])
    except (OSError, ValueError, IndexError):
        return None


def _bullet(query: str, meaning: str, width: int) -> Text:
    """'• query — translation': the query in the normal foreground, the translation muted, cut to one line."""
    line = Text("• ")
    line.append(query)
    line.append(f" — {meaning}", style=MUTED)
    line.truncate(width, overflow="ellipsis")
    return line
