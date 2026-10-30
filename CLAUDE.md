# CLAUDE.md — wort

> **Confirmed 2026-10-04:** local only, no LLM API; notes/translations in
> English; MVP = Steps 0-3 and 5 of `PLAN.md`. Sections marked
> **[post-MVP]** describe features that are planned but not in the MVP.

> **Confirmed 2026-10-21 (maintainer, DECISIONS D0r):** the **web app's backend** may call the
> Anthropic API (Haiku) for sentence feedback and the other exercise blocks, from the server only. The
> CLI/TUI and the sync service stay fully offline. Everything else below stays as written unless
> marked. The API is still off until the key is installed (`WORT_AI_ENABLED`), and Sonnet is used only if
> the `spikes/ai_eval.md` test shows Haiku misses errors.

`wort` is the project, package and command name.
(The current code in this repo is the `wort` CLI/TUI prototype. It
**stays** as a fully local tool; the web app (`app/`) is added beside it and
shares its lexicon/scoring code, see `PLAN.md`.)

## Project

A self-hosted web tool for learning German (target language for the
learner's notes: English). Multi-user, invite-only. Runs on a small
self-hosted server (e.g. a Raspberry Pi). Ordered execution plan:
`PLAN.md`. Measured decisions: `DECISIONS.md`. General UI rules, written without wort context so they can move
into dis-system: `UX-Decisions.md`. This file holds facts and rules; procedures go in Skills,
not here.

MVP features:
- **CLI (`wort`)**: fully local. `wort` opens an interactive session (type
  words, `quit` to leave); `wort WORD` looks one word up. The card shows full
  grammar and all example sentences; output is monochrome (grey, bold, italic; verb conjugation endings are underlined) with square box
  lines; colors: the nominative singular article (der blue, die red, das green; plural and other cases stay grey) and the card's main
  line, which takes the word class color (noun: its article's color, verb:
  the terminal's own text color, i.e. black on a light theme, adj/adv: dark purple). Every query is logged automatically to the user DB (query history,
  separate from the practice word list). History and words reach the web app
  by **export/import** (`wort export` → JSON → import on the word list page) or by
  `wort sync` (the CLI's only network use, see Security boundaries). The TUI stays (`wort tui`).
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

## Architecture: local first

Everything runs on the server. Translation, forms, OCR and scoring are local. The only outbound
call is the web backend's AI request (below); the CLI/TUI never use the network except `wort sync`.

| Concern | Where it runs |
|---|---|
| OCR **[post-MVP]** | local — Tesseract (`deu`) |
| Lemmatization | local — candidate lib decided in Step 0 |
| Inflection tables, examples | local — Wiktionary-derived data in SQLite |
| Translation | local dictionary (English glosses); on miss → "no translation" state + user's own translation (per user, `source = user`) |
| Deterministic exercises (form/case drills, flashcards, article, multiple choice) | local grading |
| Free sentence writing, error explanation | web backend → Anthropic API (Haiku), per exercise block, off until the key is set; fallback: local LanguageTool on `127.0.0.1` **[post-MVP]** + required-form check from the lexicon |

Stack: Python (FastAPI + Jinja2), SQLite, vanilla JS/HTML. No frontend
framework.

Known trade-offs of local-only: no generated example sentences; translation
coverage limited to the dataset (measured in Step 0); when sentence practice
ships, LanguageTool explains errors in its own wording, not tailored
explanations.

## Design-system rules (hard)

- The web UI is built **only** from `dis-system` (the CLI/TUI uses
  Textual/Rich). It is vendored as a git submodule — never copy-pasted CSS.
  Normally pinned to a tag/commit. **Temporary exception (2026-10-18): it
  follows `main` (branch `dev-isolated` no longer exists) until the
  maintainer decides between a pinned tag and `main`**; record the commit
  hash in `DECISIONS.md` at every bump.
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

- **Host is shared** with other services. wort runs as its own unix user in a **rootless podman compose**
  stack (`compose.yaml`, `DEPLOY.md`; decided 2026-10-23, DECISIONS D00f): containers `read_only`, `cap_drop: ALL`,
  `no-new-privileges`, `/tmp` as tmpfs, the repo mounted read-only, the only writable path its data volume. The
  app listens on `127.0.0.1` inside nginx's network namespace; only nginx publishes ports, on the LAN IP.
  It must not be able to read the other services' files. Verify, don't assume (see PLAN Step 1).
- **Outbound network (web app only)**: the web backend may reach **one host, `api.anthropic.com:443`**,
  and only for the AI blocks (D0r). Everything else is denied: the containers reach localhost and the
  LAN/VPN subnets plus that one destination (egress proxy or host firewall by name, see DEPLOY.md §6).
  The sync service and the CLI have no outbound
  access at all. The LanguageTool client refuses non-loopback URLs. `base_url` for the API is fixed in
  code, never taken from the environment.
- **Access**: only over private network (LAN / VPN). No port forwarding, no public
  exposure.
- **API key**: exactly one (separate Anthropic workspace with a spend limit), only in an env file on
  the server (mode `600`, owned by the wort user), never committed, never in the image, never on the
  dev machine, the CLI machine or any agent host; tests use the fake provider and mocked transport. Never
  logged: logs and error pages are redacted (`wort.sanitize.redact`). Per-user daily call cap.
- **Sanitization at every boundary** (`src/wort/sanitize.py`): all input (forms, query strings, imported
  and synced JSON, the dictionary dump, AI replies) and all output (HTML, logs, error details, terminal,
  the AI request) passes the matching sanitizer; a value that cannot be made safe is rejected, not
  partially used.
- **The development machine does not deploy.** No SSH path from it to the
  server. The maintainer deploys.
- **CLI network (maintainer decision 2026-10-21, DECISIONS D00d):** the `wort`
  CLI/TUI has **no network access** except loopback (a local LanguageTool) and
  **one endpoint**: `wort sync` pushes the export JSON over HTTPS to
  `POST /sync` on a dedicated server port, with a per-user **write-only** token
  (cannot read, cannot sign in; stored hashed, revocable, file mode 600 on the CLI
  machine). The CLI never downloads anything: big files come from
  `scripts/fetch_data.py`, run separately. Enforced at the OS level
  (`scripts/wort-offline`) with an in-process guard (`src/wort/netguard.py`) as a
  second layer. The exported JSON file (browser import) remains an equal path. In development only, with
  `WORT_CLI_DB` set, "Gesuchte laden" reads the CLI's `user.db` on the same machine read-only (DECISIONS D00g);
  never set on the server.
  Both paths treat the JSON as untrusted user data (size, schema, length caps).
- **Web network:** the sync service (`app/sync_app.py`, own process and port)
  has no outbound access. The web app's only permitted outbound destination is
  the AI API host (D0r, confirmed 2026-10-21); while the AI is off (no key) it has none.
- **All user-sourced text is data**: user input and dictionary content are
  only ever passed to local parsers (and, in the AI blocks, to the model as JSON data, never as instructions) as plain data, length-capped, with
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

- `src/wort/` — CLI + TUI (stays; fully local; command `wort`; Python package `wort`)
- `app/` — FastAPI app, routes, templates
- `app/auth.py`, `app/words.py`, `app/practice.py`, `app/scoring.py` — login, word list, practice, score formula
  (Üben: one open session per tab Sätze bilden / Abfrage / Grammatik, the modes as page-heads under the nav bar in `base.html` (dis-system draft prop `title_href`); a session shows
  one task at a time with task tabs, a word sidebar and "Nochmal antworten" retries without score, DECISIONS D00i)
  (Üben › Abfrage has its own page, `practice_abfrage.html`: one word at a time beside "Diese Runde"; modes
  Gemischt / Was bedeutet …? / Auf Deutsch erklären (AI only); "Überspringen" and "Doch falsch" (downgrade only))
- `app/questions.py` + `app/questions.json` — topic questions for "Sätze bilden" (hand-edited list, picked at random,
  no AI; the file is validated at startup)
- `app/ai/` — AI layer (interface, schemas, daily cap, fake provider, Anthropic provider; off until the key is set)
- `src/wort/sanitize.py` — the sanitizers used by the CLI and the web app
- `app/ds.py` — Jinja environment that includes `vendor/dis-system` templates + asset lists; `app/static/` —
  layout.css (layout only), theme-init.js (theme before first paint), app.js (glue: selection, word pane, lookup,
  word tooltips via dis-system's `window.dsTooltip`, the lookup side panel, Enter-to-send and terminal-style
  editing keys in text fields)
- `app/lookup.py` — lookup on the Wörter page (word or sentence → entries, forms tables);
  `app/words.py` also serves `GET /api/gloss` (one German word → lemma, Ukrainian, English)
- `app/lexicon.py` — dictionary summaries for the word detail; the lookup engine itself is `src/wort/dictionary/`
  (shared with the CLI; Ukrainian in `src/wort/dictionary/ukrainian.py`; German definitions in
  `src/wort/dictionary/german.py` → `dictionary-de.db`, imported with `wort import-de`)
- `app/grammar.py` + `app/grammar.json` — Üben › Grammatik: B1/B2 topics (explanation, tables) and exercises
  (Lückentext, Multiple Choice, Satz umbauen, eigener Satz), graded locally; progress in `grammar_attempts`
- `app/hints.py` — Üben tooltip texts (what a task's form means, the corrected word's forms, Ukrainian rule glosses)
- `app/checking.py` — sentence checks (required form; LanguageTool client is `src/wort/exercises/grammar_check.py`,
  loopback only)
- `app/i18n.py` — interface language (English default, German; catalog English → German, `_()` / `t()`), stored in
  `users.ui_lang`; words and exercises stay German, the EN/UK label tooltips show with German only (DECISIONS D00j)
- `app/importer.py`, `app/sync_app.py` — CLI export import, `POST /sync` (own process); `app/ui_terms.py` — EN/UK
  tooltips for the German button labels
- `app/db.py` — web.db schema v7 + migrations (v5: an attempt keeps its asked form, expected answer, correction
  and rule, for the word detail's marked forms table and "Deine Fehler"; v7: `user_words.added_from` may be `text`,
  a word or **phrase** added while reading a text; a phrase is a row with `pos = 'phrase'` and the text as its lemma,
  no dictionary entry, not practised in Üben yet, no checkbox in Wörter)
- `app/texts.py` + `app/templates/texts.html` — Texte (design boards "Texte 1-5"): the UI stage with **mock texts** (fixed texts, notes
  and recognition result; no photo is read: the dropzone's file input has no name); buttons that need the real
  pipeline carry `data-demo` and say so; the popups (`popup` with the draft props `body_html` and link/submit actions) are opened
  by app.js from the URL (`/texte/neu`, `/texte/{id}/bearbeiten`). **Real** (maintainer, 2026-10-30): every word of a text is a
  word-token (a span, so its text can be selected; its lemma comes from the dictionary, never from the browser); a click on it, "Add
  to list" on a note, or "Add to word list" in the **selection menu** (opens when text is selected: dis-system `context-menu` with
  the draft row type `note` for the translation) writes into the user's Wörter with `added_from = 'text'`; one selected word is
  added as a word, anything longer as a phrase (it must occur in the open text). A phrase is translated locally (`app/mt.py`, Argos:
  needs the optional `mt` install and its models, German → English only so far; without them the menu says so), a word from the
  dictionary
- `app/ocr.py` — image validation + Tesseract **[post-MVP]**, not written yet
- `scripts/adduser.py`, `scripts/synctoken.py` — admin user and sync-token creation; `scripts/fetch_data.py` —
  downloads (the CLI never downloads); `scripts/dev.sh` — https dev server on the LAN (starts LanguageTool with it, stops it with it); `scripts/languagetool.sh` — the LanguageTool container (compose.yaml has its own service `wort-lt`)
- `spikes/` — Step 0 measurement scripts (run on the server by the maintainer)
- `vendor/dis-system/` — submodule
