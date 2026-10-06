# wort — Decisions

One entry per decision, with evidence (measured numbers, commands, output),
not opinion. Numbers that depend on hardware are measured **on the server**.
Template per entry: *Question → Options tried → Measurements → Decision →
Confirmed by maintainer (date)*.

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

## D00 — Scope and note language

- **Decision (2026-10-04):** notes and translations are in **English**
  (replaces Ukrainian). MVP = Steps 0–3 and 5 of `PLAN.md`; photo/OCR (4),
  LanguageTool sentence practice (6) and operations (7) are post-MVP.
  Security/deploy simplified to the shared-host protections in `CLAUDE.md`;
  upload/LanguageTool/cap rules apply when those features ship.
- **Confirmed by maintainer:** 2026-10-04

## D00b — CLI track, TUI kept, dis-system source

- **Decision (2026-10-04):**
  - A fully local CLI stays a product of its own, command **`wort`**
    (replaces the earlier name `lernen`; renamed everywhere on 2026-10-04: package `wort`, data dir `~/.local/share/wort`, env vars `WORT_*`). `wort`
    opens an interactive session, `wort WORD` looks one word up, the TUI is
    `wort tui`. It is no longer removed on Step 1.
  - **Every query is saved automatically** as history (only what was typed,
    plus found yes/no and time). The practice word list is separate
    (`wort add`); a lookup never changes it. No save key.
  - In the session the previous card collapses into one `query — translation`
    line when the next word is typed (terminal only; piped input prints full cards).
  - Output is monochrome (greys, bold, italic; underline only on verb conjugation endings) with square box lines;
    colors: the articles (der blue, die red, das green) and the card's main
    line by word class (noun: article color, verb: burgundy, adj/adv: dark
    purple); fixed 256-color indices, not the theme's ANSI palette.
  - Examples: importer keeps up to 10 per entry (was 3); more only via an
    extra corpus (Tatoeba), still open.
  - **Missing inflected forms:** `zigtausende` was not found because the lemma
    `zigtausend` has no form table and the importer dropped Wiktionary's
    separate "form of X" entries (171 of 228 numerals have no forms). Those
    entries now become form → lemma pointers in the form index (same part of
    speech preferred, any other if the lemma has only that). Needs a re-import.
    A second dictionary / lemmatizer fallback stays open until the Step 0
    coverage numbers (D1/D2) show it is needed.
  - Link CLI → web is **export/import** (versioned JSON, format_version 2:
    queries + practice words). No network path from the dev machine.
  - CLI/TUI and web keep separate practice progress (scores do not sync).
  - dis-system is taken from branch **`dev-isolated`** for now. To be
    revisited: pinned tag vs `main`.
- **dis-system commit in use:** _(record at each bump)_
- **Confirmed by maintainer:** 2026-10-04

## Step 0 spikes (MVP)

### D1 — Dictionary dataset and English glosses

- Datasets tried: _
- 200-word list: `spikes/words_200.txt` (_to add_)
- % found: _
- % with inflection tables: _
- % with English glosses: _
- % with example sentences: _
- License: _
- Decision: _
- Confirmed by maintainer: _

### D2 — Lemmatizer

- Candidates: `simplemma`, spaCy `de_core_news_sm`, lexicon form index
- 100 inflected forms: `spikes/forms_100.txt` (_to add_)

| Option | Accuracy | RAM | Startup (server) |
|---|---|---|---|
| simplemma | _ | _ | _ |
| spaCy sm | _ | _ | _ |
| lexicon form index | _ | _ | _ |

- Decision: _
- Confirmed by maintainer: _

## Post-MVP spikes

### D3 — OCR preprocessing (Step 4, post-MVP)

| Photo | Raw: time / quality | Grayscale+threshold+deskew: time / quality |
|---|---|---|
| book page | _ | _ |
| sign | _ | _ |
| screenshot | _ | _ |
| menu | _ | _ |
| low light | _ | _ |

- Decision: _
- Confirmed by maintainer: _

### D4 — LanguageTool on the server (Step 6, post-MVP)

- Server model / total RAM: _
- Setup tried (Java / Docker), unix user: _
- RAM idle / under 10 checks: _
- Startup time: _
- Time per sentence: _
- Message language available (uk / de / en): _
- Catch rate on 10 hand-made sentences (5 correct, 5 errors): _
- Go / no-go for Step 6: _
- Confirmed by maintainer: _

## Known limitations

### D5 — Separable verbs and compounds

- Separable verbs (`fängt … an`) and compounds: tooltip shows the token's own
  lemma only in MVP. _Examples observed:_

## Step 1

### D6 — Sandbox evidence

- `systemd-analyze security wort`: _(paste)_
- Reading other services' files as the wort user: _(command + permission error)_
- Outbound request from the sandbox: _(command + failure)_
