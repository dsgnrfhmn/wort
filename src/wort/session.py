"""The interactive session: type words, `quit` to leave; `/history` and `/clear-history`."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone

from rich.text import Text

from wort import history, history_view, paths, picker, sentence
from wort.dataschema import Invalid
from wort.dictionary.lookup import Dictionary, Entry
from wort.header import Header
from wort.history import HistoryStore
from wort.output import BANNER, banner, clear_screen, console, fit, print_text, screen_lines, table, working
from wort.render.card import MUTED, render_translation
from wort.search import MAX_PHRASE_WORDS, did_you_mean, find, open_dictionary, resolve, show, show_result, show_translation, summary_line, word_meaning

FOOTER = "/history . /clear-history . clear . quit"
PROMPT = "translate> "
QUIT_WORDS = {"quit"}
CLEAR_WORDS = {"clear"}
HISTORY_COMMAND = "/history"
CLEAR_HISTORY_COMMAND = "/clear-history"


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _bind_ctrl_l() -> None:
    """Ctrl-L behaves like typing `clear`, so the banner survives it (GNU readline only)."""
    try:
        import readline
    except ImportError:
        return
    if getattr(readline, "backend", "readline") == "readline":
        # kill whatever is typed so far, type `clear`, accept the line
        readline.parse_and_bind(r'"\C-l": "\C-a\C-kclear\C-m"')


def _print_history_tables(dictionary: Dictionary, store: HistoryStore) -> None:
    """The history as plain tables (no terminal for the accordion): words with their meaning, then sentences. Newest first."""
    words, sentences = store.unique("word")[::-1], store.unique("sentence")[::-1]
    if not words and not sentences:
        print_text("No queries yet.")
        return
    if words:
        grid = table("#", "Word", "Meaning", "Found", "Times")
        for number, item in enumerate(words, 1):
            meaning = resolve(dictionary, item.text)[1] if item.found else "—"  # lookup only, not saved
            grid.add_row(str(number), item.text, Text(meaning, style=MUTED), "yes" if item.found else "no", str(item.count))
        console.print(grid)
    if sentences:
        grid = table("#", "Sentence", "Times")
        for number, item in enumerate(sentences, 1):
            grid.add_row(str(number), item.text, str(item.count))
        console.print(grid)


def _browse(header: Header, entries: list[Entry], heading: str = "", listed: bool = False, on_save=None) -> str:
    """Let the user pick among several entries; returns a key that should start the next word, or ''."""
    with picker.cbreak(), header.suspended():
        return picker.pick(entries, console, lambda: shutil.get_terminal_size().lines, heading=heading, listed=listed, banner=header.pinned_lines, on_save=on_save) or ""


def _save_correction(store: HistoryStore, current: str, lemma: str) -> tuple[str, str]:
    """Save `lemma` instead of `current`, the text a lookup was saved under. Returns (the text now saved, a message).

    Only the newest try of `current` changes (the lookup that was just made). When the typed text was never saved
    (it broke a storage rule) the word is added instead.
    """
    if lemma == current:
        return current, f'"{lemma}" is already what is saved'
    try:
        if not store.replace("word", current, lemma, True, latest_only=True):
            store.add("word", lemma, True)
    except Invalid as exc:
        return current, f"Not saved: {exc}"
    except OSError as exc:
        return current, f"Not saved: {exc.strerror or exc}"
    return lemma, f'Saved "{lemma}" instead of "{current}"'


def _word_items(store: HistoryStore, dictionary: Dictionary) -> list[history_view.Item]:
    """The Words rows of the history view, newest first."""
    rows = []
    for i in reversed(store.unique("word")):
        meaning, style = word_meaning(dictionary, i.text) if i.found else ("nothing found", "")
        rows.append(history_view.Item(i.text, i.found, i.count, i.ts, meaning, style))
    return rows


def _recent(store: HistoryStore, dictionary: Dictionary, since: datetime | None = None) -> list[tuple[str, str]]:
    """The last five different words asked in this session with their translation, newest first."""
    asked = list(reversed(store.unique("word", since)))[:5]
    return [(i.text, resolve(dictionary, i.text)[1] if i.found else "nothing found") for i in asked]


def _browse_history(header: Header, dictionary: Dictionary, store: HistoryStore) -> None:
    """The `/history` view: words and sentences in two tabs; nothing in it is saved or added, only deleted."""
    words = _word_items(store, dictionary)
    sentences = [history_view.Item(i.text, True, i.count, i.ts, None) for i in reversed(store.unique("sentence"))]

    def load_word(item: history_view.Item) -> history_view.Loaded:
        if item.found:
            entries, _, note = resolve(dictionary, item.query)
            return history_view.Loaded(entries, note)
        similar = dictionary.suggest(item.query)
        return history_view.Loaded(similar, "Nothing found. Did you mean:" if similar else "")

    def load_sentence(item: history_view.Item) -> history_view.Loaded:
        return history_view.Loaded(blocks=[render_translation(item.query, sentence.run(dictionary, item.query))])

    tabs = [
        history_view.Tab("Words", "word", words, load_word, "No words yet."),
        history_view.Tab("Sentences", "sentence", sentences, load_sentence, "No sentences yet.", status="Translating…"),
    ]

    def delete(tab: history_view.Tab, item: history_view.Item) -> str | None:
        """Delete every try of the row; returns a message instead when the files cannot be written."""
        try:
            store.delete(tab.kind, item.query)
        except OSError as exc:
            return f"Not deleted: {exc.strerror or exc}"
        return None

    def save(tab: history_view.Tab, item: history_view.Item, entry: Entry) -> tuple[list[history_view.Item] | None, str]:
        """Save the chosen variant instead of the row's text (every try of it)."""
        if entry.lemma == item.query:
            return None, f'"{entry.lemma}" is already what is saved'
        try:
            store.replace("word", item.query, entry.lemma, True)
        except Invalid as exc:
            return None, f"Not saved: {exc}"
        except OSError as exc:
            return None, f"Not saved: {exc.strerror or exc}"
        return _word_items(store, dictionary), f'Saved "{entry.lemma}" instead of "{item.query}"'

    # order matters: the pinned banner is repainted by `suspended` on the way out, which must be after the
    # alternate screen was left
    with picker.cbreak(), header.suspended(), header.recent_hidden(), picker.fullscreen():
        history_view.browse(tabs, console, lambda: shutil.get_terminal_size().lines, delete, banner=header.pinned_lines, save=save)


def _clear_history(store: HistoryStore) -> bool:
    """Ask, then delete the whole stored history (words and sentences). True if it was deleted."""
    words, sentences = len(store.unique("word")), len(store.unique("sentence"))
    if not (words or sentences):
        print_text("The history is already empty.")
        return False
    answer = input(f"Delete the whole history ({words} words, {sentences} sentences; it cannot be undone)? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print_text("Kept.")
        return False
    try:
        store.clear()
    except OSError as exc:
        print_text(f"Not cleared: {exc.strerror or exc}.")
        return False
    print_text("History cleared.")
    return True


def _print_lines(text: str) -> int:
    print_text(text)
    return screen_lines(text)


def _input(prompt: str, prefill: str = "") -> str:
    """`input()`, optionally with text already typed (needs GNU readline; otherwise the text is dropped)."""
    try:
        import readline
    except ImportError:
        return input(prompt)
    if prefill:
        readline.set_startup_hook(lambda: readline.insert_text(prefill))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook()


def cmd_session(args: argparse.Namespace | None = None) -> None:
    header = Header(console, BANNER, FOOTER)
    try:
        _session(header)
    finally:
        header.stop()  # give the terminal its scroll region back


def _session(header: Header) -> None:
    """Interactive session: every line is a word to look up; `quit` leaves.

    On a terminal, the previous word's card collapses into one `• query — translation`
    line as soon as the next word is typed.
    """
    try:
        import readline  # noqa: F401  (line editing and history for input())
    except ImportError:
        pass
    dictionary, store = open_dictionary(), HistoryStore(paths.data_repo())
    since = datetime.now(timezone.utc).replace(microsecond=0)  # the recent words under the banner show only what is asked from now on
    interactive = _interactive()
    prompt = PROMPT if interactive else ""
    if interactive:
        _bind_ctrl_l()
        header.recent = _recent(store, dictionary, since)
        if not header.start():  # window too small to pin the banner: print it once, as plain output
            banner()
            print_text(FOOTER)
        if store.is_empty() and (old := history.legacy_count(paths.user_db())):
            print_text(f"The old history ({old} queries) is still in user.db: run `wort migrate-history` to move it to {paths.data_repo()}.")
    last: tuple[int, Text] | None = None  # (screen lines used by the last query+cards, its summary)
    below = 0  # screen lines added after it (blank inputs)

    def collapse(typed_lines: int) -> None:
        nonlocal last, below
        if last is None:
            return
        rows, summary = last
        # Up to the old query line, then clear to the end. A card taller than the
        # screen can only be erased as far as the cursor can reach (its top has scrolled off).
        erase = min(rows + below + typed_lines, header.usable_rows() - 1)
        sys.stdout.write(f"\x1b[{erase}A\x1b[J")
        console.print(fit(summary), markup=False)
        last, below = None, 0

    pending = ""  # a key that closed the picker: it is the first letter of the next word
    while True:
        try:
            if interactive and last is not None and picker.has_terminal():
                # the previous result collapses into its bullet line as soon as typing starts, not at Enter
                if not pending:
                    sys.stdout.write(prompt)
                    sys.stdout.flush()
                    picker.wait_for_key()
                collapse(0)  # the cursor is on a fresh line below the result: no typed line to count
            line = _input(prompt, pending)
        except (EOFError, KeyboardInterrupt):
            if interactive:
                print()
            return
        pending = ""
        query = " ".join(line.split())
        typed = screen_lines(prompt + line)
        if not query:
            if last is not None:
                below += typed
            continue
        if query.lower() in QUIT_WORDS:
            if interactive:
                collapse(typed)
            return
        if query.startswith("/"):  # session commands are never looked up or logged
            if interactive:
                collapse(typed)
            if query.lower() == HISTORY_COMMAND:
                if interactive and picker.usable() and not store.is_empty():
                    _browse_history(header, dictionary, store)
                    header.recent = _recent(store, dictionary, since)  # rows may have been deleted
                else:
                    _print_history_tables(dictionary, store)
            elif query.lower() == CLEAR_HISTORY_COMMAND:
                if _clear_history(store):
                    header.recent = []
            else:
                print_text(f"Unknown command: {query}. Available: {HISTORY_COMMAND}, {CLEAR_HISTORY_COMMAND}")
            continue
        if query.lower() in CLEAR_WORDS:
            if interactive:
                header.recent_visible = True  # nothing is being searched any more
                header.clear() if header.active else clear_screen()
                last, below = None, 0  # nothing of the old screen is left to collapse
            continue
        header.hide_recent()  # a search is on screen from here on
        result = find(dictionary, store, query, working=working if interactive else None)
        header.recent = _recent(store, dictionary, since)
        if not interactive:
            if result.note:
                print_text(result.note)
            show_result(result)
            if result.kind == "word" and not result.entries and (similar := dictionary.suggest(query)):
                print_text(did_you_mean(similar))
            if result.warning:
                print_text(result.warning)
            continue
        collapse(typed)
        echo = prompt + query
        console.print(Text(echo), markup=False)
        entries, summary, note = result.entries, result.summary, result.note
        if result.kind == "sentence":  # only the translation, in one block: no cards for the single words
            rows = show_translation(result) + (_print_lines(result.warning) if result.warning else 0)
            last = (screen_lines(echo) + rows, summary)
            continue
        if not entries:  # a typo? offer close matches in the same numbered list
            rows = show(entries)  # "Nothing found."
            if len(query.split()) > MAX_PHRASE_WORDS:
                rows += _print_lines(f"Too many words: a phrase is looked up word by word up to {MAX_PHRASE_WORDS}.")
            if result.warning:
                rows += _print_lines(result.warning)
            similar = dictionary.suggest(query)
            if similar and picker.usable():
                saved = [query]  # what is saved for this lookup now: the typed text, until `s` replaces it

                def save_choice(entry: Entry) -> str:
                    saved[0], message = _save_correction(store, saved[0], entry.lemma)
                    return message

                pending = _browse(header, similar, "Did you mean:", listed=True, on_save=save_choice)
                if saved[0] != query:  # a variant was saved instead of the typed text: the collapsed line shows it
                    summary = summary_line(saved[0], resolve(dictionary, saved[0])[1])
                    header.recent = _recent(store, dictionary, since)
            elif similar:
                rows += _print_lines(did_you_mean(similar))
            last = (screen_lines(echo) + rows, summary)
            continue
        rows_on_screen = header.usable_rows()
        if picker.usable() and (len(entries) > 1 or (entries and picker.too_tall(entries[0], console, rows_on_screen))):
            pending = _browse(header, entries, note)
            last = (screen_lines(echo), summary)  # the picker erased its own output
            if result.warning:
                last = (last[0] + _print_lines(result.warning), summary)
            continue
        rows = _print_lines(note) if note else 0
        rows += show(entries)
        if result.warning:
            rows += _print_lines(result.warning)
        last = (screen_lines(echo) + rows, summary)
