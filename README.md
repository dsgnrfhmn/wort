# wort

![preview-image](preview.png)

A terminal app for learning German words (EN↔DE). Works offline on Wiktionary data.

- **Translate.** Look up a word in German or English and get a compact card: principal forms, translation, IPA, a short grammar table (verbs: Präsens / Präteritum / Perfekt / Futur I plus Imperativ; nouns: 4 cases, singular and plural; adjectives: comparison degrees) and all the example sentences the dictionary has (up to 10). The output is monochrome with square box lines (inflection endings are bold; verb conjugation endings are also underlined); the colors are the articles (**der** blue, **die** red, **das** green) and the card's main line, which is bold and takes the word class color: nouns the color of their article, verbs burgundy, adjectives/adverbs dark purple.
- **History.** Every query you type is saved automatically (no save key). Your practice list is separate: `wort add WORD`.
- **Practice.** Five exercise types, each with graded answers:

  | Type | Example |
  |---|---|
  | Translation | `Translate to German: house` → `das Haus` (the article is checked too) |
  | Article | `___ Katze` → der / die / das |
  | Forms | `Plural: das Haus → die ___`, `Präteritum, ich: gehen`, `Perfekt: er ___ ___` |
  | Questions | "Which auxiliary verb does «gehen» take in the Perfekt?", "Is it separable?", "Partizip II of …?" (multiple choice) |
  | Sentence | "Write a sentence with «gehen» in the form: Präteritum, ich". The required form is checked, and grammar is checked by a local LanguageTool (if running) |

  Reviews follow the SM-2 algorithm: words that are due for review come first, then the weakest ones.
- **Overview.** A table of all your words: mastery (0–100 %), accuracy per exercise type, number of attempts, when to review. The weakest words are on top.

## Installation

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo> && cd language-learn-cli
uv sync
uv run wort import --download     # once: ~1 GB JSONL from kaikki.org → dictionary.db
uv run wort                       # interactive session
```

If the dump is already downloaded: `uv run wort import --file kaikki.org-dictionary-German.jsonl`.
Global install: `uv tool install .`, after which the `wort` command is available directly. The dictionary was imported with up to 3 examples per word before; run `wort import --download` again to get up to 10 (the same re-import also makes inflected forms like `zigtausende` findable).

## Commands

| Command | What it does |
|---|---|
| `wort` | interactive session: type a word (German or English, any inflected form) and get its card, then the next word. The previous word's card collapses into one `query — translation` line when you type the next word. Leave with `quit` (or Ctrl+D) |
| `wort gehen` / `wort house` | look one word up and exit. Exit code 1 if nothing was found |
| `wort t list` | explicit lookup, for words that are also commands (`list`, `add`, `import`, …). Inside the session no prefix is needed |
| `wort tui` | full-screen interface: tabs Translate (F1), Practice (F2), Overview (F3). Quit: Ctrl+Q |
| `wort add beabsichtigen [--pos verb]` | add a word to your practice list |
| `wort list` | mastery of your practice words |
| `wort history [--limit N]` | the queries you typed, newest last |
| `wort export [FILE]` | write history and practice words as JSON (stdout without a file or with `-`), for import into the web app |
| `wort import [--file F] [--download] [--keep]` | (re)import the dictionary. Progress is kept |

Every lookup (found or not) is written to `user.db` automatically. Only what you typed is stored, not the cards. A lookup never changes the practice list.

In the Overview tab: `p` practices the selected word, `d d` deletes it together with its history, `r` refreshes the table.

The export file contains `format_version` 2, the queries (`query`, `found`, `queried_at`) and the practice words (`lemma`, `pos`, `added_at`). Scores and review history are not exported.

## Grammar checking (optional, local)

For the Sentence exercise the app talks to [LanguageTool](https://languagetool.org/dev) running **on your own computer**:

```bash
docker run -d --name languagetool -p 127.0.0.1:8081:8010 erikvl87/languagetool
```

Without LanguageTool the exercise only checks that the required word form is in the sentence and says that grammar was not checked.

## Data and privacy

- Data is stored in `~/.local/share/lernen/` (or in `$XDG_DATA_HOME/lernen`, or in `$LERNEN_HOME`):
  - `dictionary.db` — the imported dictionary, read-only;
  - `user.db` — your words, answers, SRS state.
- **The program uses the network only once:** when it downloads the dump from `kaikki.org` with `wort import --download`. No API keys or cloud services are needed.
- The LanguageTool client accepts only loopback addresses (`127.0.0.1`, `localhost`, `::1`), so sentences never reach the public `api.languagetool.org`. The address is set with `LERNEN_LT_URL`. A remote server is allowed only explicitly: `LERNEN_LT_ALLOW_REMOTE=1`.
- The Docker command above publishes the port on `127.0.0.1` only, so the server is not reachable from the local network.

## Development

```bash
uv run pytest
```

Layout:

```
src/lernen/
  cli.py                 # commands, interactive session
  transfer.py            # export / import format (history + practice words)
  dictionary/importer.py # kaikki JSONL → SQLite
  dictionary/lookup.py   # DE/EN lookup (ä→ae, ß→ss normalization), word forms
  dictionary/grammar.py  # form selection by tags (tense, person, case, number)
  render/card.py         # compact word card (Rich)
  store.py, srs.py       # user.db, SM-2, mastery
  exercises/             # translate, article, forms, question, sentence, grammar_check
  tui/                   # Textual: Translate / Practice / Overview
tests/fixtures/german_sample.jsonl  # small sample in kaikki format for tests
```

The dictionary comes from [Wiktionary](https://en.wiktionary.org) (CC BY-SA), as parsed by [kaikki.org / wiktextract](https://kaikki.org).
