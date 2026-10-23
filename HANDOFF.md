# Handoff — where we stopped (2026-10-23)

Read this first next time. It says what exists, what is verified, what is not, and what to do next.
Standing rules are in `CLAUDE.md`, decisions in `DECISIONS.md`, the ordered plan in `PLAN.md`.

## State in one paragraph

The web app (`app/`) works locally: login, per-user word list with scores, word detail, lookup on the Wörter page,
practice (Sätze bilden, Abfrage, Regel üben), history, hover translations for any German word, Texte placeholder.
The AI layer is complete and **off by default**. The CLI is offline except `wort sync`. Everything is committed on
`wip/web-view` (2026-10-23). **Nothing has run against the live Anthropic API, the OS-level CLI network rule, nginx or
compose.**

- Branch `wip/web-view`, PR **#5** into `wip/dev-testing`.
- 419 tests pass: `PYTHONPATH=.:src uv run pytest` (web deps: `uv sync --group web`; AI tests need `--group ai`, they skip otherwise).
- dis-system: the submodule points at `cb13772` on branch `dsgnrfhmn/reading-upload-components` (pushed, PR to its
  `main` pending). Bump it to the merge commit after the merge, and do not delete that branch before (D00b).

## Done 2026-10-22/23

- dis-system (`cb13772`): new word-token, dropzone, stepper, progress-bar, correction-row, image-regions, note-item;
  table-cell `plain`/`mark`/`highlight`, table-row `href` (cancelable `ds-table-row-open`) and keyboard selection,
  nav-bar `right_actions` and centred links, wrapping bars, tooltip layer mode + `window.dsTooltip`, pane `body_html` and
  `data-motion`, inline-mark `uncertain`, hero-block `data-fit`.
- wort: `overrides.css` and `_nav.html` deleted (D00e closed); theme applied in `<head>` (no light flash); the word pane
  opens and closes in place without reloads, scroll kept, 0 dropped frames (measured); `GET /api/gloss` + hover
  translations for any German word; plain-http mode answers loopback clients only; README (two parts, roadmap),
  PLAN.md brought up to date.

## What is built

| Area | Where | Notes |
|---|---|---|
| Accounts | `app/auth.py`, `scripts/adduser.py` | argon2, hashed session tokens, CSRF, login throttle; no signup |
| Word list + detail + lookup | `app/words.py`, `app/lookup.py`, `app/templates/words.html`, `_word_detail.html` | sort, search, presets, selection, own translation, word opens beside the table, `/api/gloss` |
| Practice | `app/practice.py`, `app/scoring.py` | sessions stored per user; local grading; sentence without grammar check = no score |
| DB | `app/db.py` | schema v3 (users, sessions, user_words, attempts, practice_sessions, sync_tokens, ai_usage); WAL; migrations from v0/v1/v2 |
| AI layer | `app/ai/` | six blocks (check, explain, tasks, recheck, rule, answer), `WORT_AI_FEATURES`, daily cap, fake + Anthropic provider (Haiku 5.5, SDK `messages.parse`) |
| Sanitizing | `src/wort/sanitize.py` | applied at every input/output boundary; `tests/test_boundaries.py` (mutation-checked) |
| CLI sync | `src/wort/syncing.py`, `app/sync_app.py`, `scripts/synctoken.py` | `wort sync` -> `POST :8456/sync`, write-only token, pinned cert |
| CLI offline | `src/wort/netguard.py`, `scripts/wort-offline`, `scripts/fetch_data.py` | CLI never downloads; fetching is a separate script |
| Deploy | `compose.yaml`, `nginx.conf`, `DEPLOY.md` | `wort-web`, `wort-sync`, TLS front; AI is DEPLOY §6, CLI network §7 |

## Decisions made this session (all in `DECISIONS.md`)

- **D0r confirmed (2026-10-21):** the web backend may call the Anthropic API (Haiku). Still open under it:
  host egress rule, separate spend-limited key, Haiku-vs-Sonnet test.
- **D00d:** CLI has no network except loopback and one write-only sync port; web is the only side with outbound.
- Language: English primary, Ukrainian as the learner's own translation / AI task translations (design shows DE→UK).
- Design gaps are **not** patched locally (rule in `CLAUDE.md`); the temporary D00e overrides are gone (2026-10-23).

## Not verified (do not assume these work)

1. Any real Anthropic call. Run `PYTHONPATH=.:src python scripts/ai_smoke.py` on the server (needs key); expect `ALL PASS`.
2. `scripts/wort-offline --check` on the real CLI machine (Linux user systemd / macOS sandbox).
3. `nginx.conf` (8456 listener) and `compose.yaml` (`wort-sync`): never started.
4. Quality of AI verdicts on real mistakes: `spikes/ai_eval.md` is a spec, not run.
5. Both-theme check (2026-10-23): Wörter, word detail, Üben start and Verlauf at 1440 and 390 px; not every practice state.
6. The access log: `sanitize.install_log_redaction` empties `record.args`, so uvicorn's access formatter fails and those
   lines are lost (no leak). Not fixed yet (`src/wort/sanitize.py:144`).

## Design audit (2026-10-22): what changed

Done with the new dis-system components (PR #3 and the follow-up): Wörter has `page-head` with the stats text, word colors by
article and a score chip (tag cell by `scoring.level`); Üben start has tabs as links (`?modus=`); the task and the
answer are `message` blocks and a corrected sentence shows `inline-mark` runs (built from the checker's remarks by
`practice.correction_segments`, plain text when the fragments are ambiguous); "falsch/richtig" are tags; Beispiele and
Deine Fehler are `disclosure` sections.
Still different from the canvas: no word tooltips with translations in the feedback, no "saved" icon column, row checkboxes
are hover-only (dis-system design), Texte is a placeholder (post-MVP). The dark theme greys row links until hover in
dis-system; article links are exempt from that rule.
Update 2026-10-23: hover translations now exist for every German word (not the canvas's click-to-note token yet), and
row checkboxes are keyboard-operable in the dis-system branch.

## Next steps (suggested order)

**Yours (blockers for merging / enabling):**
1. Open and merge the dis-system PR `dsgnrfhmn/reading-upload-components` → `main`; then the submodule pointer is bumped
   to the merge commit.
2. Merge PR #5 (`wip/web-view` into `wip/dev-testing`).
3. On the server: key in `~/.config/wort/ai.env`, egress to `api.anthropic.com:443` only (DEPLOY §6), smoke test, then `spikes/ai_eval.md`.
4. Step 0 spikes (dictionary coverage, lemmatizer) on the server; numbers into `DECISIONS.md` D1/D2.

**Mine, one piece at a time:**
1. Bump the dis-system submodule after the merge, record the hash (D00b).
2. Fix the access-log redaction (item 6 above).
3. Word detail from the canvas: mistakes marked in the declension table (table-cell `mark`), "Fehler erklärt" as a side
   pane with the rule table.
4. **Step 1 evidence:** sandbox proofs (D6) for the podman compose deploy (D00f, decided 2026-10-23).
5. **Step 7:** nightly `.backup` of the SQLite DB, structured logs, admin usage view (AI calls per user per day).
6. **Texte (post-MVP):** Tesseract spike (D3) first, then uploads with the CLAUDE.md rules, built from the new components.
7. Mobile layouts on the design canvas, then touch for word tooltips.

## How to run locally

    uv sync --group web
    uv run wort import --file <kaikki.jsonl>          # from: python scripts/fetch_data.py dictionary downloads/
    PYTHONPATH=.:src uv run python scripts/adduser.py anna
    WORT_INSECURE_COOKIES=1 PYTHONPATH=.:src uv run uvicorn app.main:create_app --factory --port 8000   # 127.0.0.1 only (the app refuses non-loopback clients in this mode)

## Gotchas learned

- Git identity: this environment sets `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, which override `git config`. The stop hook wants
  `noreply@anthropic.com` in wort commits; set the env vars for the commit. dis-system wants the GitHub noreply address
  (`255602589+dsgnrfhmn@users.noreply.github.com`) and no mention of consuming apps.
- dis-system rules: work on `dsgnrfhmn/<topic>` from `main`, PR only, `python -m pytest tests` before pushing;
  in a single-branch clone create the remote-tracking ref with `git fetch origin +refs/heads/<b>:refs/remotes/origin/<b>` or the stop hook complains.
- SDK facts checked, not assumed: Haiku 5.5 rejects `temperature`/`top_p`/prefill; SDK 2.x sends the key in the `Authorization` header.
- A leftover implicit SQLite transaction once locked the DB for the admin script; `tests/test_web_store.py` guards it.
- `cli.main()` installs the network guard process-wide; `tests/conftest.py` uninstalls it after each test.
