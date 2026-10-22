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

## D00c — Offline sentence translation in CLI/TUI (Argos Translate)

- **Decision (2026-10-21):** a sentence (3+ words that is not in the dictionary
  as a whole) shows a whole-sentence translation as text (de→en, or en→de when more words are English-only than German), then one card
  per word (picker in the session, cards in the TUI). Engine: Argos Translate,
  offline, two models (de→en, en→de), optional dependency group `mt`, model installed once by hand with
  `wort install-translation` (~100 MB, the only network use). *Superseded by D00d (2026-10-21): the CLI no longer downloads; `scripts/fetch_data.py models` fetches the files and `wort install-translation FILE...` installs them.* **CLI/TUI only;
  not in the web app** (RAM on the shared Pi not measured).
- **Why:** D0 forbids an LLM API, not local models; the dictionary only has
  word glosses. No model or no package → a visible "No sentence translation"
  line, never a silent skip. Input is length-capped (500 chars).
- **Limits:** phrase word limit 5 → 30; translation quality is not measured yet.
- **Open:** quality check on real sentences once the model is installed.
- **Confirmed by maintainer:** 2026-10-21 (variant A, CLI/TUI only)

## D0r — Revisit D0: Haiku for sentence feedback (CONFIRMED 2026-10-21)

> **Status: confirmed by the maintainer 2026-10-21** ("outbound access for the AI from the server
> side"): the web backend may call the API. Still open and not decided by this entry: the host egress
> design (DEPLOY.md §6), the separate spend-limited key, the Haiku-vs-Sonnet test. The code (`app/ai/`)
> stays behind `WORT_AI_ENABLED`, off until the key is installed.

- **Question:** allow a hosted model (Haiku) for the checks the local stack cannot do well:
  sentence feedback (corrections, "Natürlicher", per-word results, rule name), "Fehler erklären",
  "Doch richtig?", more tasks for one rule, free-answer grading in Abfrage.
- **Proposed:** `claude-haiku-5-5` for all of them. `claude-sonnet-5-5` only for the sentence check,
  and only if Haiku misses errors on 20-30 real learner mistakes (`spikes/ai_eval.md`, run by the
  maintainer; record the numbers here).
- **Rules if confirmed:** backend only, browser never calls the API; one key in a separate workspace
  with a spend limit, in the server env file only; only the sentence/answer, target forms and task are
  sent (never photos or whole Texte); structured JSON validated by the backend, invalid reply = no score
  change; per-user daily cap; fallback to the local check; explanations only on click.
- **What it costs us (security):** the host gets a spend-capable key and an outbound path to
  `api.anthropic.com`, so `IPAddressDeny=any` / "no outbound network" in CLAUDE.md no longer hold as
  written; learner text leaves the network. Blast radius if the service is compromised: spend on the
  key (capped by the workspace limit) and every sentence sent. Needs the egress design in DEPLOY.md §6.
- **Call sites and what each sends** (all behind `WORT_AI_FEATURES`, default all, only when
  `WORT_AI_ENABLED=1`; each falls back to the local behaviour):
  `check` sentence + required forms + task; `explain` (on click) answer + error list + rule name;
  `tasks` the selected lemmas (one call per session); `recheck` ("Doch richtig?", once per answer)
  sentence + forms + task + the learner's objection (max 300 characters); `rule` ("Diese Regel üben")
  the rule's name only; `answer` (Abfrage free answers) question + answer + dictionary glosses.
  A revised verdict re-applies the score of that one answer (`WebStore.revise_attempt`); invalid,
  failed or capped calls change no score.
- **Still local:** translation and forms (Wiktionary), OCR (Tesseract), tooltips (dictionary + spaCy),
  scores and filters.
- **Confirmed by maintainer:** 2026-10-21 (in session: outbound access for the AI from the server side;
  scope as above: web backend only, one host, off until the key is installed)

## D00d — Network model: CLI offline except one write-only sync port

- **Decision (2026-10-21, requested by the maintainer):** only the web side may have outbound network
  access (the AI API host only; D0r confirmed 2026-10-21, off until the key is installed). The CLI has none except loopback and one
  HTTPS endpoint that receives its words JSON.
- **Mechanism:** `wort sync` → `POST https://<server-ip>:8456/sync` with `Authorization: Bearer <token>`.
  The token is created on the server (`scripts/synctoken.py`), stored hashed, scoped to one user, can only
  push words/history, is revocable, and lives in a mode-600 file on the CLI machine. The server side is a
  separate process/port with exactly one route (`app/sync_app.py`), rate-limited per user and in nginx,
  size-capped (20 MiB), per-user word cap 20 000, TLS with the server's own certificate pinned on the client.
- **CLI side:** no downloads (`import --download` and the model download are gone; `scripts/fetch_data.py`
  does them, separately). `scripts/wort-offline` cuts the network at the OS level (Linux: systemd
  `IPAddressDeny`, by IP; optional nftables for the port; macOS: sandbox profile, IP and port);
  `src/wort/netguard.py` also blocks it inside the process. Loopback stays open for a local LanguageTool.
- **Access and blast radius:** the token bridges the CLI machine to one user's word list on the server:
  if it leaks, someone on the LAN can add junk words/history to that user (capped, rate-limited, revocable);
  they cannot read or sign in. The CLI initiates the connection; nothing on the server can reach the CLI
  machine. The in-process guard is bypassable by code in the same process; the OS rule is the boundary and
  was **not run in the dev container** (no user systemd/macOS): run `scripts/wort-offline --check` on the
  real machine.
- **Open:** the server-side egress rule for the AI API (DEPLOY.md §6). nginx.conf/compose changes are not
  run here either.
- **Confirmed by maintainer:** 2026-10-21 (requested in session; variant: HTTPS push + write-only token,
  OS rule + in-code guard, downloads moved out of the CLI)

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
  - dis-system follows **`main`** (2026-10-18: the `dev-isolated` branch does
    not exist on GitHub; the maintainer's updates are on `main`). Pinned tag
    vs `main` is still open.
  - Web app: own SQLite DB (`web.db`, history + favorites), UI composed from
    dis-system Jinja templates (`app/ds.py` adds the `vendor/dis-system` root to
    the template loader and serves its tokens/components/icons under `/ds`).
    Forms need dis-system props that were missing (`input` `name`/`label`,
    `text-button` `submit`, `table-cell` `1-action` `submit`): added in
    dis-system PR #2 (`form-props`), merged to its `main` on 2026-10-21.
    Gaps still without a component: file input (native control used),
    textarea-free sentence result block (empty-state used for text lines).
- **dis-system commit in use:** `bc4e8de` (2026-10-22: `main` after the merge of dis-system PR #2,
  `dsgnrfhmn/form-props`). The form props (input name/id/label/disabled/required/autocomplete/password,
  text-button submit/href, table-cell and table-header-actions submit, table-row extra_attrs) are now in `main`;
  `d8811df` (the branch head wort used until now) is its ancestor, so no component file changed. Earlier hashes:
  `6d58745` (unpublished), `1e1d505`, `d8811df`. The submodule follows `main` (`.gitmodules` branch = main).
  _(record at each bump)_
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
