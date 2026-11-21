"""Command line entry point.

`wort`            interactive session: type words, `quit` to leave
`wort WORD`       look a word or sentence up once (saved in the history files)
`wort tui|import|add|list|history|sync|t WORD`   other commands (`sync` is the only one that uses the network)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wort import dataschema, datarepo, history, paths, sentence
from wort.history import HistoryStore
from wort.output import console, print_text, table, working
from wort.dictionary.lookup import Dictionary
from wort.search import did_you_mean, find, is_sentence, open_dictionary, show_result
from wort.sentence import MIN_SENTENCE_WORDS
from wort.session import cmd_session
from wort.store import Store

COMMANDS = {"tui", "import", "import-uk", "import-de", "import-en-uk", "t", "add", "list", "history", "migrate-history", "init-data", "sync", "install-translation"}


def _require_file(path: str, hint: str) -> Path:
    source = Path(path)
    if not source.is_file():
        print_text(f"No such file: {source}. {hint}")
        sys.exit(1)
    return source


def _import(source: Path, run, target: Path, done: str) -> None:
    """Run an importer under a progress line and report `done` with the entry count and target."""
    with console.status("Importing…", spinner_style="none") as status:
        count = run(source, target, progress=lambda n: status.update(f"Importing… {n} entries read"))
    print_text(done.format(count=count, target=target))


def cmd_import(args: argparse.Namespace) -> None:
    from wort.dictionary import importer

    source = _require_file(args.file, "Fetch the dump with scripts/fetch_data.py first.")
    _import(source, importer.import_file, paths.dictionary_db(), "Done: {count} entries → {target}")


def cmd_import_uk(args: argparse.Namespace) -> None:
    from wort.dictionary import ukrainian

    source = _require_file(args.file, "Fetch the dump with scripts/fetch_data.py uk first.")
    _import(source, ukrainian.import_file, paths.dictionary_uk_db(), "Done: {count} words with Ukrainian translations → {target}")


def cmd_import_de(args: argparse.Namespace) -> None:
    from wort.dictionary import german

    source = _require_file(args.file, "Fetch the dump with scripts/fetch_data.py uk first (the same German dump).")
    _import(source, german.import_file, paths.dictionary_de_db(), "Done: {count} words with German definitions → {target}")


def cmd_import_en_uk(args: argparse.Namespace) -> None:
    from wort.dictionary import ukrainian

    source = _require_file(args.file, "Fetch it with scripts/fetch_data.py en-uk first.")
    _import(source, ukrainian.import_english, paths.dictionary_en_uk_db(), "Done: {count} English words with Ukrainian translations → {target}")


def cmd_lookup(args: argparse.Namespace) -> None:
    query = " ".join(args.word).strip()
    if not query:
        sys.exit(1)
    dictionary = open_dictionary()
    result = find(dictionary, HistoryStore(paths.data_repo()), query, working=working if sys.stdout.isatty() else None)
    if result.note:
        print_text(result.note)
    show_result(result)
    if result.warning:
        print_text(result.warning)
    if result.kind == "word" and not result.entries:
        if similar := dictionary.suggest(query):
            print_text(did_you_mean(similar))
        sys.exit(1)


def cmd_add(args: argparse.Namespace) -> None:
    dictionary = open_dictionary()
    query = " ".join(args.word)
    german, english = dictionary.lookup(query)
    candidates = [e for e in german + english if args.pos is None or e.pos == args.pos]
    if not candidates:
        print_text("Nothing found.")
        sys.exit(1)
    entry = candidates[0]
    Store(paths.user_db()).add_word(entry.lemma, entry.pos, entry.id)
    print_text(f"Added: {entry.lemma} ({entry.pos}) — {'; '.join(entry.glosses[:2])}")


def cmd_list(args: argparse.Namespace) -> None:
    store = Store(paths.user_db())
    grid = table("Word", "Type", "Mastery", "Attempts", "Next")
    for s in store.all_stats():
        grid.add_row(s.word.lemma, s.word.pos, f"{s.mastery}%", str(s.attempts), s.due.strftime("%d.%m %H:%M") if s.due else "—")
    console.print(grid)


def cmd_history(args: argparse.Namespace) -> None:
    store = HistoryStore(paths.data_repo())
    rows = sorted(
        ((i.ts, n, kind, i.text, i.found) for kind in dataschema.FILES for n, i in enumerate(store.unique(kind))),
        key=lambda row: row[:2],  # the time; within one second, the position in the file
        reverse=True,  # newest first
    )
    grid = table("Time", "Type", "Query", "Found")
    for when, _, kind, text, found in rows[: args.limit]:
        grid.add_row(when.astimezone().strftime("%Y-%m-%d %H:%M"), kind, text, "yes" if found else "no")
    console.print(grid)
    for kind, count in store.skipped.items():
        if count:
            print_text(f"{count} invalid line(s) in {dataschema.FILES[kind]} were ignored.")


def cmd_migrate_history(args: argparse.Namespace) -> None:
    """Merge the old query log from user.db into the history files (words.jsonl, sentences.jsonl); safe to repeat."""
    store = HistoryStore(paths.data_repo())
    if not history.legacy_count(paths.user_db()):
        print_text("Nothing to migrate: user.db has no old history.")
        return
    try:
        dictionary = Dictionary(paths.dictionary_db())
        classify = lambda text, found: is_sentence(dictionary, text)  # noqa: E731  (the same test as a live lookup)
    except FileNotFoundError:
        print_text(f"The dictionary is not imported: sentences are told apart by their length only ({MIN_SENTENCE_WORDS}+ words and not found).")
        classify = history.legacy_kind
    result = history.migrate(paths.user_db(), store, classify)
    extra = [f"{result.present} already there" if result.present else "", f"{result.skipped} skipped (they break the storage rules)" if result.skipped else ""]
    print_text(f"Migrated {result.words} words and {result.sentences} sentences to {store.root}" + "".join(f"; {x}" for x in extra if x) + ".")


def cmd_sync(args: argparse.Namespace) -> None:
    """Push the two history files to `main` of the data repository (git; the only network use)."""
    try:
        print_text(datarepo.sync(paths.data_repo()))
    except datarepo.SyncError as exc:
        print_text(f"Sync failed: {exc}")
        sys.exit(1)


def cmd_init_data(args: argparse.Namespace) -> None:
    """Create or refresh the data repository (git init, scaffold, validator) so that `wort sync` has somewhere to push."""
    root = Path(args.dir).expanduser() if args.dir else paths.data_repo()
    try:
        notes = datarepo.init(root, args.remote)
    except datarepo.SyncError as exc:
        print_text(f"init-data failed: {exc}")
        sys.exit(1)
    for note in notes:
        print_text(note)


def cmd_install_translation(args: argparse.Namespace) -> None:
    try:
        count = sentence.install([Path(f) for f in args.files])
    except (sentence.TranslationUnavailable, RuntimeError) as exc:
        print_text(str(exc))
        sys.exit(1)
    print_text(f"Installed {count} sentence translation model(s).")


def cmd_tui(args: argparse.Namespace) -> None:
    from wort.tui.app import WortApp

    WortApp(open_dictionary(), Store(paths.user_db())).run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wort",
        description="Learn German words in the terminal. `wort` starts a session, `wort WORD` looks a word up.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("tui", help="full-screen interface (translate, practice, overview)")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("install-translation", help="install offline sentence-translation models from .argosmodel files")
    p.add_argument("files", nargs="+", help="model files fetched with scripts/fetch_data.py")
    p.set_defaults(func=cmd_install_translation)

    p = sub.add_parser("import", help="import the Wiktionary dictionary from a kaikki.org JSONL file")
    p.add_argument("--file", required=True, help="JSONL fetched with scripts/fetch_data.py")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("import-uk", help="import Ukrainian translations from the German Wiktionary dump (kaikki.org dewiktionary)")
    p.add_argument("--file", required=True, help="raw-wiktextract-data.jsonl.gz fetched with scripts/fetch_data.py uk")
    p.set_defaults(func=cmd_import_uk)

    p = sub.add_parser("import-de", help="import German definitions from the German Wiktionary dump (kaikki.org dewiktionary)")
    p.add_argument("--file", required=True, help="raw-wiktextract-data.jsonl.gz fetched with scripts/fetch_data.py uk")
    p.set_defaults(func=cmd_import_de)

    p = sub.add_parser("import-en-uk", help="import English→Ukrainian translations (English Wiktionary), used when the German dump has none")
    p.add_argument("--file", required=True, help="kaikki-English-uk.jsonl.gz fetched with scripts/fetch_data.py en-uk")
    p.set_defaults(func=cmd_import_en_uk)

    p = sub.add_parser("t", help="look a word up explicitly (needed for words like `list` or `add`)")
    p.add_argument("word", nargs="+")
    p.set_defaults(func=cmd_lookup)

    p = sub.add_parser("add", help="add a word to your practice list")
    p.add_argument("word", nargs="+")
    p.add_argument("--pos", help="part of speech: noun, verb, adj…")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="show your practice words and mastery")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("history", help="show what you looked up, newest first")
    p.add_argument("--limit", type=int, default=50, help="how many recent queries to show (default 50)")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("migrate-history", help="move the old history from user.db into the history files")
    p.set_defaults(func=cmd_migrate_history)

    p = sub.add_parser("init-data", help="create or refresh the data repository for the history files")
    p.add_argument("dir", nargs="?", help="where it lives (default: WORT_DATA_REPO, else ~/wort-data)")
    p.add_argument("--remote", help="its GitHub URL, e.g. https://github.com/USER/wort-data.git")
    p.set_defaults(func=cmd_init_data)

    p = sub.add_parser("sync", help="push the history files to the data repository on GitHub (the only network use)")
    p.set_defaults(func=cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return cmd_session()
    if argv[0] not in COMMANDS and not argv[0].startswith("-"):
        return cmd_lookup(argparse.Namespace(word=argv))
    args = build_parser().parse_args(argv)
    (getattr(args, "func", None) or cmd_session)(args)
