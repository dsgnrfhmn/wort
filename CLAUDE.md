# CLAUDE.md — wort

> **Confirmed 2026-10-04:** local only, no LLM API; notes/translations in
> English; MVP = Steps 0-3 and 5 of `PLAN.md`. Sections marked
> **[post-MVP]** describe features that are planned but not in the MVP.

`wort` is a working name. Rename freely; nothing depends on it.
(The current code in this repo is the `lernen` CLI/TUI prototype. It
**stays** as a fully local tool; the web app (`app/`) is added beside it and
shares its lexicon/scoring code, see `PLAN.md`.)

## Project

A self-hosted web tool for learning German (target language for the
learner's notes: English). Multi-user, invite-only. Runs on a small
self-hosted server (e.g. a Raspberry Pi). Ordered execution plan:
`PLAN.md`. Measured decisions: `DECISIONS.md`. This file holds facts and rules; procedures go in Skills,
not here.

MVP features:
- **CLI (`wort`)**: fully local. `wort` opens an interactive session (type
  words, `quit` to leave); `wort WORD` looks one word up. The card shows full
  grammar and all example sentences; output is monochrome (grey, bold, italic; verb conjugation endings are underlined) with square box
  lines; colors: the articles (der blue, die red, das green) and the card's main
  line, which takes the word class color (noun: its article's color, verb:
  burgundy, adj/adv: dark purple). Every query is logged automatically to the user DB (query history,
  separate from the practice word list). History and words reach the web app
  by **export/import** (`wort export` → JSON → import on the word list page);
  there is no network path from the CLI to the server. The TUI stays (`wort tui`).
- **Lookup**: type any word → translation, grammar (declension for nouns /
  adjectives, conjugation incl. Präteritum, Perfekt, Futur I for verbs),
  example sentences from the dataset.
- **Word list**: per-user table of words marked "learning", each with a score
  and per-skill sub-scores.
- **Practice**: user picks several words → session of deterministic exercises
  (translation, article, correct case/form, grammar multiple choice) →
  graded → results update each word's score.

Post-MVP:
- **[post-MVP] Text from photo**: upload image → local OCR → text block →
  every word is clickable → tooltip with lemma, translation, short grammar
  note → "learn this word" button.
- **[post-MVP] Sentence practice**: write own sentence → required-form check +
  LanguageTool feedback.

## Architecture: local only

Everything runs on the server. No LLM API, no outbound network.

| Concern | Where it runs |
|---|---|
| OCR **[post-MVP]** | local — Tesseract (`deu`) |
| Lemmatization | local — candidate lib decided in Step 0 |
| Inflection tables, examples | local — Wiktionary-derived data in SQLite |
| Translation | local dictionary (English glosses); on miss → "no translation" state + user's own translation (per user, `source = user`) |
| Deterministic exercises (form/case drills, flashcards, article, multiple choice) | local grading |
| Free sentence writing, error explanation **[post-MVP]** | local — LanguageTool server on `127.0.0.1` (variant decided in its spike) + required-form check from the lexicon |

Stack: Python (FastAPI + Jinja2), SQLite, vanilla JS/HTML. No frontend
framework.

Known trade-offs of local-only: no generated example sentences; translation
coverage limited to the dataset (measured in Step 0); when sentence practice
ships, LanguageTool explains errors in its own wording, not tailored
explanations.

## Design-system rules (hard)

- The web UI is built **only** from `dis-system` (the CLI/TUI uses
  Textual/Rich). It is vendored as a git submodule — never copy-pasted CSS.
  Normally pinned to a tag/commit. **Temporary exception (2026-10-04): it
  follows the `dev-isolated` branch until the maintainer decides between a
  pinned tag and `main`**; record the commit hash in `DECISIONS.md` at every
  bump.
- App-local CSS may contain **layout only** (grid, page regions, spacing via
  dis-system tokens). No new colors, type styles, or component styles in
  this repo.
- A UI pattern that dis-system lacks (e.g. tooltip/popover, clickable word
  token, inflection table, score meter, upload dropzone, exercise card,
  inline error highlight) is a **dis-system component**, not a wort quirk:
  propose it in dis-system, confirm with the maintainer before pushing, then bump the
  submodule. Do not patch around a missing component locally.
- Both themes verified on every touched screen.

## Security boundaries (hard)

- **Host is shared** with other services. wort runs as its own unix user,
  as a sandboxed systemd service (`ProtectHome`, `ProtectSystem=strict`,
  `NoNewPrivileges`, `PrivateTmp`, writable path limited to its data dir).
  It must not be able to read the other services' files. Verify, don't assume (see PLAN Step 1).
- **No outbound network**: the service unit sets
  `IPAddressDeny=any` with `IPAddressAllow=` only for localhost and the
  LAN/VPN subnets, and `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`.
  *(Open: the maintainer may relax this to a simpler rule; see `PLAN.md`
  open questions.)* **[post-MVP]** LanguageTool runs under the same rules,
  listening on `127.0.0.1` only; the app's LanguageTool client refuses
  non-loopback URLs.
- **Access**: only over private network (LAN / VPN). No port forwarding, no public
  exposure.
- **No API keys exist for this project**: nothing to
  store on the server or on the dev machine. If an API is ever reintroduced, the original
  rules apply again (key only on the server, env file mode `600` owned by the
  wort user, never committed, never on the dev machine; mocked client + separate
  spend-limited dev key on the dev machine) — and this file is updated first.
- **The development machine does not deploy.** No SSH path from it to the
  server. The maintainer deploys. The only CLI → web path is the exported
  JSON file, which the web import treats as untrusted user data.
- **All user-sourced text is data**: user input and dictionary content are
  only ever passed to local parsers as plain data, length-capped, with
  timeouts; a failed or malformed check → fail loud, no score change, never
  render partial output.
- **Rendering**: anything from users or the dictionary is inserted with
  `textContent` / Jinja autoescape. No `innerHTML` with dynamic data.
- **Accounts**: invite-only (admin CLI creates users, no open signup),
  argon2 password hashes, HttpOnly + SameSite session cookies, CSRF tokens
  on all POST forms.

### Applies when the post-MVP features ship

- **[post-MVP] Uploads**: size cap, MIME + magic-byte check, decode with
  Pillow, OCR, then **delete the image**. Only extracted text is stored.
  OCR output is user-sourced text (same data/rendering rules as above).
- **[post-MVP] Load control**: per-user daily cap on LanguageTool checks and
  OCR uploads (protects the shared host's CPU/RAM), enforced server-side,
  with a clear UI message when reached.

## Git workflow

Work happens on feature branches; the maintainer merges to `main`.
Verify each step (`git status`, conflict-marker grep).
Keep README and this file in sync after each session.

## Modules (update once the structure stabilizes)

- `src/lernen/` — CLI + TUI (stays; fully local; command `wort`; Python package keeps the name `lernen`)
- `app/` — FastAPI app, routes, templates
- `app/ocr.py` — image validation + Tesseract **[post-MVP]**
- `app/lexicon.py` — lemmatize, lookup, inflection, translation cache
  (ported from `lernen/dictionary/*`)
- `app/grammar_check.py` — loopback-only LanguageTool client **[post-MVP]**
  (ported from `lernen/exercises/grammar_check.py`)
- `app/exercises.py` — exercise generation + local grading
  (ported from `lernen/exercises/*`)
- `app/scoring.py` — score + scheduling rules (pure functions, unit-tested)
  (ported from `lernen/srs.py`)
- `scripts/import_lexicon.py` — builds the local dictionary DB
  (ported from `lernen/dictionary/importer.py`)
- `scripts/adduser.py` — admin user creation
- `spikes/` — Step 0 measurement scripts (run on the server by the maintainer)
- `vendor/dis-system/` — submodule
