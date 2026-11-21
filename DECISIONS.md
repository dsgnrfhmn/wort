# wort — Decisions

One entry per decision, with evidence (measured numbers, commands, output),
not opinion. Numbers that depend on hardware are measured **on the server**.
Template per entry: *Question → Options tried → Measurements → Decision →
Confirmed by maintainer (date)*.

*Removed with the web version on 2026-11-21 (full text in the git history before that change): D0r (Haiku for sentence feedback), D00d (CLI network model, write-only sync port), D00e/D00h (dis-system overrides and trial), D00f (podman compose deploy), D00g, D00i, D00j (web practice and interface language), D3 (OCR), D4 (LanguageTool on the server), D6 (sandbox evidence).*

## D0 — Local only, no LLM API

- **Question:** use an LLM API for translation misses, example generation
  and sentence grading (original hybrid design), or stay local?
- **Decision (2026-10-03, confirmed 2026-10-04):** local only. Translation
  misses → user's own translation; examples → dataset only; sentence grading
  (post-MVP) → LanguageTool on `127.0.0.1` + required-form check.
- **Why:** no API key on a host shared with other services; no user text
  leaves the network; the service can be denied all outbound traffic.
- **Cost:** no tailored error explanations, no generated examples (sizes
  measured in Step 0 entries below).
- **Confirmed by maintainer:** 2026-10-04

## D00c — Offline sentence translation in CLI/TUI (Argos Translate)

- **Decision (2026-10-21):** a sentence (3+ words, since 2026-11-21 2+, see D00k, that is not in the dictionary
  as a whole) shows a whole-sentence translation (de→en, or en→de when more words are English-only than German). *(2026-11-21, D00k: in the CLI session
  it is the only thing shown, as a two-line block; the TUI still adds one card per word.)* Engine: Argos Translate,
  offline, two models (de→en, en→de), optional dependency group `mt`, model installed once by hand with
  `wort install-translation` (~100 MB, the only network use). *Superseded by D00d (2026-10-21): the CLI no longer downloads; `scripts/fetch_data.py models` fetches the files and `wort install-translation FILE...` installs them.* **CLI/TUI only.**
- **Why:** D0 forbids an LLM API, not local models; the dictionary only has
  word glosses. No model or no package → a visible "No sentence translation"
  line, never a silent skip. Input is length-capped (500 chars).
- **Limits:** phrase word limit 5 → 30; translation quality is not measured yet.
- **Open:** quality check on real sentences once the model is installed.
- **Confirmed by maintainer:** 2026-10-21 (variant A, CLI/TUI only)

## D00 — Scope and note language

- **Decision (2026-10-04):** notes and translations are in **English**
  (replaces Ukrainian). MVP = Steps 0–3 and 5 of the former `PLAN.md` (now `PLAN.org`, CLI only); photo/OCR (4),
  LanguageTool sentence practice (6) and operations (7) are post-MVP.
  Security/deploy simplified to the shared-host protections in `CLAUDE.md`;
  upload/LanguageTool/cap rules apply when those features ship.
- **Confirmed by maintainer:** 2026-10-04

## D00b — CLI track, TUI kept

- **Decision (2026-10-04):**
  - A fully local CLI stays a product of its own, command **`wort`**
    (replaces the earlier name `lernen`; renamed everywhere on 2026-10-04: package `wort`, data dir `~/.local/share/wort`, env vars `WORT_*`). `wort`
    opens an interactive session, `wort WORD` looks one word up, the TUI is
    `wort tui`.
  - **Every query is saved automatically** as history (only what was typed,
    plus found yes/no and time). The practice word list is separate
    (`wort add`); a lookup never changes it. No save key. *(Storage changed 2026-11-21: D00k.)*
  - In the session the previous card collapses into one `query — translation`
    line when the next word is typed (terminal only; piped input prints full cards).
  - Output is monochrome (greys, bold, italic; underline only on verb conjugation endings) with square box lines;
    colors: the articles (der blue, die red, das green) and the card's main
    line by word class (noun: article color, verb: the terminal's own text color; *2026-11-21: adjectives and adverbs lost
    their dark purple, on cards and everywhere else, and have no color*); fixed 256-color indices,
    not the theme's ANSI palette. In `/history` a noun's text is drawn in its article's color (maintainer request
    2026-11-21); no other class is colored there.
  - Examples: importer keeps up to 10 per entry (was 3); more only via an
    extra corpus (Tatoeba), still open.
  - **Missing inflected forms:** `zigtausende` was not found because the lemma
    `zigtausend` has no form table and the importer dropped Wiktionary's
    separate "form of X" entries (171 of 228 numerals have no forms). Those
    entries now become form → lemma pointers in the form index (same part of
    speech preferred, any other if the lemma has only that). Needs a re-import.
    A second dictionary / lemmatizer fallback stays open until the Step 0
    coverage numbers (D1/D2) show it is needed.
- **Superseded 2026-11-21 (D00k):** the web app and its export/import link were removed; the dis-system
  submodule went with it.
- **Confirmed by maintainer:** 2026-10-04

## D00k — CLI only; history as two validated files in a data repository, pushed by `wort sync`

- **Decision (maintainer request 2026-11-21):**
  - **The web version is removed** (`app/`, `vendor/dis-system`, deploy files, web tests, `wort export`, the
    LAN `wort sync` and the network guard of D00d). One branch remains, `wip/cli-development`, built on the
    newest line (`origin/wip/dev-testing`, 2026-10-31) so that the Ukrainian/German dictionaries, `sanitize.py`
    and the sentence-practice fix are kept. The other branches are in `~/backups/wort-all-branches-2026-11-21.bundle`.
  - **History = two files** in a separate git repository (`~/wort-data` or `$WORT_DATA_REPO`):
    `words.jsonl` (`text`, `ts`, `found`) and `sentences.jsonl` (`text`, `ts`). A query is a *sentence* when it
    has 2+ words (3+ until 2026-11-21), is not in the dictionary as a whole and has at least one known word; everything else is a word.
    Translations of sentences are **not** stored (only what was typed); a sentence in `/history` is translated
    again when opened.
  - **Only words and sentences can be stored.** Allowlist in `src/wort/dataschema.py`: letters, digits, a plain
    space, `. , : ! ? ' ’ " „ “ ” « » ( ) - – — …`; at most 60 characters (word) or 500 (sentence); first
    character a letter, digit or opening quote/bracket; no `:` directly before a letter, no `www.`, no word
    starting with `-` (`--mt`, `-rf`: a command-line option); exact keys,
    UTC timestamp with `Z`, NFC. **`;` is deliberately not allowed** (a command separator); the cost is that
    sentences with a semicolon are translated but not saved. Rule-breaking text is refused whole, the lookup
    still works and says `Not saved to history: …`.
  - The same file is shipped to the data repository as `validate.py` (CI, other writers); `wort sync` refuses
    when the local copy differs. The remote copy is not compared (wort validates the remote *content* itself).
  - **`wort sync` is the only network use** and runs git only: see `CLAUDE.md`, "Security boundaries". Merge
    between machines: `*.jsonl merge=union`. `wort init-data` creates the repository and makes its first commit;
    `wort migrate-history` merges the old `queries` rows of `user.db` into the files (by time, no duplicates, safe to repeat); word or sentence is decided with the
    dictionary like a live lookup (the old log marked a sentence found whenever one of its words was; checked on the
    maintainer's real `user.db`: 123 rows, 19 with 3+ words, two were typed shell commands); rule-breaking rows are
    skipped and counted; the old table is left alone.
  - Sentences show **only the translation** in one two-line block (no cards for single words) with a
    `Translating…` line while it runs; `/history` has two tabs (`Tab`), `>` instead of separators, `x` + `y`/`n`.
- **Phrases (2026-11-21, maintainer request):** two words are translated like a sentence. The word-by-word result of
  `wie so` (`like / so, such, that`) was misleading; Argos gives `Like so`. A phrase that is a dictionary entry as a
  whole (`zu Hause`) keeps its entry, and a phrase with no word known as typed is still corrected word by word. Typing an
  article with a noun (`das Haus`) is now a translation (`The House`), not two cards. Without the translation models a
  two-word query shows `No sentence translation: …` where it used to show cards. A history that cannot be written
  (read-only, full disk) no longer breaks a lookup: it says `Not saved to history: …` and goes on. The loading warning of
  Argos's sentence splitter (stanza) is silenced; errors are not.
- **Saving a variant (2026-11-21, maintainer request):** after a misspelled lookup, `s` on a variant of the `Did you mean`
  list saves that word (`found`) instead of the typed text: only the newest try changes, and the typed text is
  added as the variant when it could not be saved at all. In `/history`, `s` on a picked result of an open word row
  changes every try of the row's text. The history is shown newest first. In the suggestion list `s` no longer
  starts a word (it did before: any printable key did); in other result lists it still does.
- **A side pane in a wide window (2026-11-21, maintainer request, reworked the same day):** from 120 columns on, `l` on a
  row opens a side pane on the right (the list narrows to half of the width; without an open row it has
  the whole window). The `>` moves into the pane (first result, or the word when there is nothing to pick) and the usual keys
  work there (`j`/`k`, `g`/`G`, digits, `l`, `s`); `x` and `Tab`-less list keys are for the list. The opened row stays
  marked in the list (grey `>`, bold word) and its word is fixed at the top of the pane while the results scroll under it.
  **One `h` or `q` closes the pane** from anywhere in it (a first version needed several: card, results, then pane), also from
  a card too tall for the pane, which opens on its own screen as before. Nothing is previewed while moving along the list
  (a sentence is translated only when opened: it is slow). Narrower than 120 columns a row opens in place. The width is
  read for every frame, so resizing switches the layout. 120 is a guess at where a verb card (about 70 columns) fits
  beside the list; it is `SPLIT_MIN_WIDTH`.
- **Moving the selection in `/history` (2026-11-21, maintainer request):** on an old machine the selection kept moving for
  seconds after a held `j`/`k` was let go, because every key press redrew every row (measured: 13 ms per press for 60
  rows, 106 ms for 500, 720 ms for 3000, against about 33 ms between repeats of a held key). Now only the visible rows
  are rendered (about 1 ms per press whatever the length: 0.9 ms for 60 rows, 1.5 ms for 3000, 1.2 ms for 20000), key
  presses already waiting in the input are read together and drawn once, and a key held down (the same direction again
  within 0.12 s of the last move) moves two rows per repeat; a single press moves one. The result lists of a lookup
  (`wort.picker`) are unchanged.
- **Known limits:** plain words that look like a command (`git push origin main`) cannot be told from a
  sentence by any rule and are stored as one; they are data and nothing ever executes them. An allowlist cannot stop an ordinary sentence that reads like an instruction (prompt
  injection for a future reader such as an AI assistant): the defence is the length limit and the rule that
  the files are data. A row deleted on one machine comes back if another machine adds the same text before it
  syncs. Timestamps have whole-second precision.
- **Not verified:** a push to the real GitHub repository (the sandbox blocks it; tests use a local bare
  repository), and the offline translation with real Argos models (tests and the live run use a stand-in).
- **Superseded:** D00d (LAN sync with a write-only token), the export/import path of D00b.
- **Confirmed by maintainer:** 2026-11-21 (branch base, file format, private repository `wort-data`)
