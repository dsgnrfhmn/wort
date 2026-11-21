"""Shared terminal output: the console, the banner and small print helpers."""

from __future__ import annotations

import contextlib
import sys
from typing import Iterator

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


def make_console(**kwargs) -> Console:
    """Monochrome output (plus the article colors): no automatic number/string highlighting.

    Under tmux or TERM=screen rich detects only 8 colors and would map the fixed 256-color
    article colors onto the terminal theme's ANSI palette; those terminals do support 256.
    """
    console = Console(highlight=False, **kwargs)
    if console.color_system == "standard":
        console = Console(highlight=False, color_system="256", **kwargs)
    return console


console = make_console()

BANNER = """
█   █  ███  █ ██   █
█   █ █   █ ██  █ █████
█ █ █ █   █ █      █
██ ██ █   █ █      █
█   █  ███  █      ██
""".strip("\n")  # solid block letters


def print_text(text: str) -> None:
    """Print text as is (no markup parsing: it may come from the user)."""
    console.print(text, markup=False)


def table(*columns: str) -> Table:
    return Table(*columns, box=box.SQUARE, header_style="bold")


def screen_lines(text: str) -> int:
    """Terminal lines a typed line occupies (long input wraps)."""
    return sum(max(1, -(-len(part) // max(console.width, 1))) for part in text.split("\n"))


def fit(text: Text) -> Text:
    text.truncate(max(console.width - 1, 10), overflow="ellipsis")
    return text


def banner() -> None:
    console.print(Text(BANNER, style="bold"), markup=False)


def clear_screen() -> None:
    """Clear the screen (not the scrollback) and bring the banner back."""
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.flush()
    banner()


@contextlib.contextmanager
def working(message: str) -> Iterator[None]:
    """Show `message` on the current line while a slow step runs, then erase it.

    The caller decides when this is right (only when talking to a terminal). Plain escape codes rather
    than a rich `Live`, so it does not fight the pinned banner and footer.
    """
    sys.stdout.write(f"\x1b[38;5;242m{message}\x1b[0m")
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write("\r\x1b[2K")
        sys.stdout.flush()
