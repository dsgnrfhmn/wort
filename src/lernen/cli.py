"""Command line entry point.

`wort`            interactive session: type words, `quit` to leave
`wort WORD`       look a word up once (every lookup is logged in user.db)
`wort tui|import|add|list|history|export|t WORD`   other commands
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from lernen import paths
from lernen.dictionary.grammar import GENDER_ARTICLE
from lernen.dictionary.lookup import Dictionary, Entry
from lernen.store import Store
from lernen.transfer import export_words

def _make_console(**kwargs) -> Console:
    """Monochrome output (plus the article colors): no automatic number/string highlighting.

    Under tmux or TERM=screen rich detects only 8 colors and would map the fixed 256-color
    article colors onto the terminal theme's ANSI palette; those terminals do support 256.
    """
    console = Console(highlight=False, **kwargs)
    if console.color_system == "standard":
        console = Console(highlight=False, color_system="256", **kwargs)
    return console


console = _make_console()

BANNER = """
█   █  ███  █ ██   █
█   █ █   █ ██  █ █████
█ █ █ █   █ █      █
██ ██ █   █ █      █
█   █  ███  █      ██
""".strip("\n")  # solid block letters

COMMANDS = {"tui", "import", "t", "add", "list", "history", "export"}
QUIT_WORDS = {"quit"}
CLEAR_WORDS = {"clear"}


def _print(text: str) -> None:
    """Print text as is (no markup parsing: it may come from the user)."""
    console.print(text, markup=False)


def _open_dictionary() -> Dictionary:
    try:
        return Dictionary(paths.dictionary_db())
    except FileNotFoundError:
        _print(
            "The dictionary has not been imported yet.\n"
            "Run `wort import --download` (≈1 GB from kaikki.org, once)\n"
            "or `wort import --file kaikki.org-dictionary-German.jsonl`."
        )
        sys.exit(1)


def cmd_import(args: argparse.Namespace) -> None:
    from lernen.dictionary import importer

    if args.file:
        source = Path(args.file)
    else:
        source = paths.data_dir() / "kaikki-german.jsonl"
        if not source.exists() or args.download:
            _print(f"Downloading {importer.KAIKKI_URL}")
            with console.status("", spinner_style="none") as status:
                importer.download(source, progress=lambda n: status.update(f"{n / 1e6:.0f} MB"))
    with console.status("Importing…", spinner_style="none") as status:
        count = importer.import_file(source, paths.dictionary_db(), progress=lambda n: status.update(f"Importing… {n} entries"))
    _print(f"Done: {count} entries → {paths.dictionary_db()}")
    if not args.file and not args.keep:
        source.unlink(missing_ok=True)


def find(dictionary: Dictionary, store: Store, query: str) -> tuple[list[Entry], str]:
    """Look `query` up, log it, and return (entries, one-line summary 'query — translation')."""
    query = " ".join(query.split())
    german, english = dictionary.lookup(query)
    store.log_query(query, bool(german or english))
    return german + english, _summary(query, german, english)


def _summary(query: str, german: list[Entry], english: list[Entry]) -> str:
    if not (german or english):
        return f"{query} — nothing found"
    if german:  # a German word: show its English meaning(s), ignore weaker English-side matches
        parts = ["; ".join(e.glosses[:2]) for e in german]
    else:  # an English word: show the German equivalents
        parts = [f"{GENDER_ARTICLE[e.gender]} {e.lemma}" if e.pos == "noun" and e.gender in GENDER_ARTICLE else e.lemma for e in english]
    unique = list(dict.fromkeys(p for p in parts if p))
    return f"{query} — {' / '.join(unique[:3])}"


def show(entries: list[Entry]) -> int:
    """Print the cards (or a not-found line); returns how many terminal lines that took."""
    from lernen.render.card import render_card

    with console.capture() as captured:
        if not entries:
            _print("Nothing found.")
        for entry in entries:
            console.print(render_card(entry))
    out = captured.get()
    sys.stdout.write(out)
    sys.stdout.flush()
    return out.count("\n")


def cmd_lookup(args: argparse.Namespace) -> None:
    query = " ".join(args.word).strip()
    if not query:
        sys.exit(1)
    entries, _ = find(_open_dictionary(), Store(paths.user_db()), query)
    show(entries)
    if not entries:
        sys.exit(1)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _screen_lines(text: str) -> int:
    """Terminal lines a typed line occupies (long input wraps)."""
    return max(1, -(-len(text) // max(console.width, 1)))


def _fit(text: str) -> str:
    width = max(console.width - 1, 10)
    return text if len(text) <= width else text[: width - 1] + "…"


def _banner() -> None:
    console.print(Text(BANNER, style="bold"), markup=False)


def _clear_screen() -> None:
    """Clear the screen (not the scrollback) and bring the banner back."""
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.flush()
    _banner()


def _bind_ctrl_l() -> None:
    """Ctrl-L behaves like typing `clear`, so the banner survives it (GNU readline only)."""
    try:
        import readline
    except ImportError:
        return
    if getattr(readline, "backend", "readline") == "readline":
        # kill whatever is typed so far, type `clear`, accept the line
        readline.parse_and_bind(r'"\C-l": "\C-a\C-kclear\C-m"')


def cmd_session(args: argparse.Namespace | None = None) -> None:
    """Interactive session: every line is a word to look up; `quit` leaves.

    On a terminal, the previous word's card collapses into one `query — translation`
    line as soon as the next word is typed.
    """
    try:
        import readline  # noqa: F401  (line editing and history for input())
    except ImportError:
        pass
    dictionary, store = _open_dictionary(), Store(paths.user_db())
    interactive = _interactive()
    prompt = "wort> " if interactive else ""
    if interactive:
        _bind_ctrl_l()
        _banner()
        _print("Type a word (German or English). `quit` to leave, `clear` or Ctrl-L to clear the screen.")
    last: tuple[int, str] | None = None  # (screen lines used by the last query+cards, its summary)
    below = 0  # screen lines added after it (blank inputs)

    def collapse(typed_lines: int) -> None:
        nonlocal last, below
        if last is None:
            return
        rows, summary = last
        # Up to the old query line, then clear to the end. A card taller than the
        # screen can only be erased as far as the cursor can reach (its top has scrolled off).
        erase = min(rows + below + typed_lines, shutil.get_terminal_size().lines - 1)
        sys.stdout.write(f"\x1b[{erase}A\x1b[J")
        console.print(Text(_fit(summary)), markup=False)
        last, below = None, 0

    while True:
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            if interactive:
                print()
            return
        query = " ".join(line.split())
        typed = _screen_lines(prompt + line)
        if not query:
            below += typed
            continue
        if query.lower() in QUIT_WORDS:
            if interactive:
                collapse(typed)
            return
        if query.lower() in CLEAR_WORDS:
            if interactive:
                _clear_screen()
                last, below = None, 0  # nothing of the old screen is left to collapse
            continue
        entries, summary = find(dictionary, store, query)
        if not interactive:
            show(entries)
            continue
        collapse(typed)
        echo = prompt + query
        console.print(Text(echo), markup=False)
        last = (_screen_lines(echo) + show(entries), summary)


def cmd_add(args: argparse.Namespace) -> None:
    dictionary = _open_dictionary()
    query = " ".join(args.word)
    german, english = dictionary.lookup(query)
    candidates = [e for e in german + english if args.pos is None or e.pos == args.pos]
    if not candidates:
        _print("Nothing found.")
        sys.exit(1)
    entry = candidates[0]
    Store(paths.user_db()).add_word(entry.lemma, entry.pos, entry.id)
    _print(f"Added: {entry.lemma} ({entry.pos}) — {'; '.join(entry.glosses[:2])}")


def _table(*columns: str) -> Table:
    return Table(*columns, box=box.SQUARE, header_style="bold")


def cmd_list(args: argparse.Namespace) -> None:
    store = Store(paths.user_db())
    table = _table("Word", "Type", "Mastery", "Attempts", "Next")
    for s in store.all_stats():
        table.add_row(s.word.lemma, s.word.pos, f"{s.mastery}%", str(s.attempts), s.due.strftime("%d.%m %H:%M") if s.due else "—")
    console.print(table)


def cmd_history(args: argparse.Namespace) -> None:
    table = _table("Time", "Query", "Found")
    for q in Store(paths.user_db()).queries()[-args.limit :]:
        table.add_row(q.ts.strftime("%Y-%m-%d %H:%M"), q.query, "yes" if q.found else "no")
    console.print(table)


def cmd_export(args: argparse.Namespace) -> None:
    text = json.dumps(export_words(Store(paths.user_db())), ensure_ascii=False, indent=2) + "\n"
    if args.file in (None, "-"):
        sys.stdout.write(text)
        return
    Path(args.file).write_text(text, encoding="utf-8")
    _print(f"Exported: {args.file}")


def cmd_tui(args: argparse.Namespace) -> None:
    from lernen.tui.app import LernenApp

    LernenApp(_open_dictionary(), Store(paths.user_db())).run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wort",
        description="Learn German words in the terminal. `wort` starts a session, `wort WORD` looks a word up.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("tui", help="full-screen interface (translate, practice, overview)")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("import", help="import the Wiktionary dictionary (kaikki.org)")
    p.add_argument("--file", help="ready-made JSONL from kaikki.org")
    p.add_argument("--download", action="store_true", help="download the dump again")
    p.add_argument("--keep", action="store_true", help="keep the downloaded JSONL after import")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("t", help="look a word up explicitly (needed for words like `list` or `add`)")
    p.add_argument("word", nargs="+")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("add", help="add a word to your practice list")
    p.add_argument("word", nargs="+")
    p.add_argument("--pos", help="part of speech: noun, verb, adj…")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="show your practice words and mastery")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("history", help="show what you looked up")
    p.add_argument("--limit", type=int, default=50, help="how many recent queries to show (default 50)")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("export", help="export history and practice words as JSON (for import into the web app)")
    p.add_argument("file", nargs="?", help="destination file (omit or use '-' for stdout)")
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return cmd_session()
    if argv[0] not in COMMANDS and not argv[0].startswith("-"):
        return cmd_lookup(argparse.Namespace(word=argv))
    args = build_parser().parse_args(argv)
    (getattr(args, "func", None) or cmd_session)(args)
