# Handoff — where we stopped (2026-10-31)

Read this first next time. It says what exists, what is verified, what is not, and what to do next.
Standing rules are in `CLAUDE.md`, decisions in `DECISIONS.md`, the ordered plan in `PLAN.md`, the page-by-page UI
review in `GUI-REFRESH.org`.

## State in one paragraph

The web app (`app/`) works locally: login, per-user word list with scores, word detail with marked mistakes, lookup,
hover translations for any German word, practice in three tabs (Sätze bilden, Abfrage, Grammatik; one task at a time,
retries, topic questions), history/import, **Texte** (reading texts with word and selection menus; photo → Tesseract →
offline translation preview → saved texts with notes), and an English interface with a German switch. LanguageTool
starts with the dev server and is a service in the compose stack. The AI layer is complete and **off until a key is
installed**. The CLI is offline except `wort sync`. The code is committed and pushed on `wip/development`
(`0ef26c6`, 2026-10-31); this handoff is a later edit. **Nothing has run against the live Anthropic API, the OS-level CLI network rule, nginx or
compose (including `wort-lt`), and OCR has only seen generated pages, not real photos.**

- Branch `wip/development` (new 2026-10-31): `wip/cli-development` + `wip/web-view` (incl. the 2026-10-23 state that was
  PR #5) + `gui-improvements`, fast-forwarded; no merge conflicts. Local `wip/dev-testing` and `gui-improvements` sit at
  `c2de5ae`, one commit before it, and are not pushed.
- Tests: `PYTHONPATH=.:src uv run pytest` → **577 passed, 1 skipped** (2026-10-31, dev venv; web deps `--group web`,
  photo tests `--group ocr`, AI tests `--group ai`, they skip otherwise). dis-system `python -m pytest tests`: 74 passed.
- DB: schema v9 (`app/db.py`; was v3 on 2026-10-23).
- dis-system: the submodule is `c0ce165` on **`dsgnrfhmn/uiux-dev`** (pushed 2026-10-31). A fresh
  `git clone --recurse-submodules -b wip/development` fetched the earlier pin `bc62167`; repeat it once the commit with
  the new pin is pushed. That branch is deliberately **not** merged into dis-system `main` (`2db2701`): it changes 52
  existing files and adds 3 (D00b). Its exception to dis-system's branch rules is in dis-system's own `CLAUDE.md`.
- Rollback tags (pushed 2026-10-31): `gui/before-words-texts` (`f806b7c`), `gui/words-texts-refresh` (`985691d`).

## Done since 2026-10-23

- 10-28 `ebc7f23` Üben as a chat: topic questions, local feedback, explanations, Grammatik tab.
- 10-28/29 `f2c83cf` word detail marks, Abfrage page, access-log redaction fix, local look trial (`trial.css`, D00h),
  dev-only "Gesuchte laden" from the CLI's `user.db` (D00g).
- 10-29 `81c1c18` English interface with a German switch (D00j), practice as one task at a time with retries (D00i),
  `scripts/languagetool.sh`.
- 10-30 pinned composer and original/corrected toggle (`5989c2a`); Texte reading texts (`a389a01`); Practice GUI
  refresh (`c6e3df7`); LanguageTool starts with `scripts/dev.sh`, `compose.yaml` service `wort-lt` (`00cc087`); dis-system
  draft props committed (`de28078`); Texte photo → text → preview, saved texts, notes, delete (`f806b7c`); Words and
  Texte refresh (`985691d`).
- 10-31 History, Login and one tooltip on texts (`c2de5ae`); `.gitmodules` follows `dsgnrfhmn/uiux-dev` (`0ef26c6`).

## What is built

| Area | Where | Notes |
|---|---|---|
| Accounts | `app/auth.py`, `scripts/adduser.py` | argon2, hashed session tokens, CSRF, login throttle; no signup |
| Word list + detail + lookup | `app/words.py`, `app/lookup.py`, `app/templates/words.html`, `_word_detail.html` | sort, search, presets, selection, own translation, word opens beside the table, `/api/gloss` |
| Practice | `app/practice.py`, `app/scoring.py`, `app/questions.py`, `app/grammar.py`, `app/checking.py`, `app/hints.py` | three tabs, one open session per tab, only the first answer counts; Grammatik B1/B2 graded locally; sentence check = required form + LanguageTool |
| Texte | `app/texts.py`, `app/uploads.py`, `app/ocr.py`, `app/mt.py`, `app/templates/texts.html` | Pillow decode, then Tesseract (`deu`), offline translation; install `--group ocr` and `tesseract-ocr-deu` |
| Interface language | `app/i18n.py`, `app/ui_terms.py` | English source text → German; stored in the profile (`users.ui_lang`) |
| UI | `app/static/ui.css`, `app/templates/_ui.html`, `layout.css`, `trial.css`, dis-system tokens | wort's own small kit on `--ds-*` tokens (GUI-REFRESH decision) next to dis-system components via `app/ds.py` |
| DB | `app/db.py` | schema v9, WAL, migrations from older versions |
| AI layer | `app/ai/` | six blocks (check, explain, tasks, recheck, rule, answer), `WORT_AI_FEATURES`, daily cap, fake + Anthropic provider (Haiku 5.5, SDK `messages.parse`) |
| Sanitizing | `src/wort/sanitize.py` | applied at every input/output boundary; `tests/test_boundaries.py` (mutation-checked) |
| CLI sync | `src/wort/syncing.py`, `app/sync_app.py`, `scripts/synctoken.py` | `wort sync` -> `POST :8456/sync`, write-only token, pinned cert |
| CLI offline | `src/wort/netguard.py`, `scripts/wort-offline`, `scripts/fetch_data.py` | CLI never downloads; fetching is a separate script |
| LanguageTool | `scripts/languagetool.sh`, `scripts/dev.sh`, `compose.yaml` (`wort-lt`) | loopback only; image `erikvl87/languagetool:6.5` pinned by digest (6.6 does not start) |
| Deploy | `compose.yaml`, `nginx.conf`, `DEPLOY.md`, `deploy/` | `wort-web`, `wort-sync`, `wort-lt`, TLS front; AI is DEPLOY §6, CLI network §7 |
| Tracking | `GUI-REFRESH.org`, `UX-Decisions.md`, `BACKLOG.md` | page-by-page review; UI rules without wort context; feature ideas |

## Decisions since 2026-10-23 (all in `DECISIONS.md` unless noted)

- **D00g** dev-only import from the CLI's `user.db` (needs `WORT_CLI_DB`; the server never sets it).
- **D00h** trial look in `app/static/trial.css`; whether any of it goes into dis-system is open.
- **D00i** one task at a time, "Nochmal antworten" (first answer counts), one open session per Üben tab.
- **D00j** interface English by default, switchable to German; German content stays German.
- **dis-system integration branch (2026-10-31):** wort follows `dsgnrfhmn/uiux-dev` until the redesign is finished (D00b).
- **GUI refresh (garv, 2026-10-30, `GUI-REFRESH.org`):** dis-system is a visual reference, not a guideline; the refreshed
  pages use wort's own kit. **`CLAUDE.md` "Design-system rules (hard)" still says the opposite** and has not been changed.

## Not verified (do not assume these work)

1. Any real Anthropic call. Run `PYTHONPATH=.:src python scripts/ai_smoke.py` on the server (needs key); expect `ALL PASS`.
2. `scripts/wort-offline --check` on the real CLI machine (Linux user systemd / macOS sandbox).
3. `nginx.conf` (8456 listener) and `compose.yaml` (`wort-sync`, `wort-lt`): never started through `podman-compose up`.
   The Containerfile with Tesseract was not rebuilt (as of 2026-10-30, `GUI-REFRESH.org`).
4. Quality of AI verdicts on real mistakes: `spikes/ai_eval.md` is a spec, not run.
5. OCR (D3): generated pages only; the table for book page, sign, screenshot, menu and low light is empty; threshold and
   deskew are open. LanguageTool server numbers (D4) are empty too (dev machine only).
6. UI: Practice, Words, Texte, History and Login were checked in a browser with demo data (1440 and 390 px, both themes,
   `GUI-REFRESH.org`). Left: keyboard and phone walkthroughs by a person, real photos (T-5), a screen-reader pass.
   `/favorites` and `/exercise/{lemma}` are untouched.
7. GitHub state of `wip/web-view` and of wort PR #5: not checked from here (no network); `origin/wip/web-view` was
   `f8d2fd4` when last fetched.

## Next steps (suggested order)

**Yours:**
1. **Design-system rule.** Either update `CLAUDE.md` (own kit allowed, `ui.css` / `_ui.html` in the module list) or fold the
   kit back into dis-system component by component. The same section of `GUI-REFRESH.org` lists three smaller decisions
   (one explanation surface, `/favorites` + `/exercise` delete or restyle, global colour overrides in `ui.css`).
2. **`origin/wip/dev-testing` (`19fc3da`).** It pins `6d58745`, which is on no dis-system branch, and has no `.gitmodules`
   file at all, so a recursive clone fails. It is an ancestor of `wip/development`: fast-forward it there, or delete it.
   `PLAN.md` still says "PRs into `wip/dev-testing`".
3. **dis-system.** Keep working on `dsgnrfhmn/uiux-dev`. Before any PR into `main`: tests, existing demos with default props,
   both themes; merge commit, not squash; then re-pin wort and move the other services (D00b).
4. On the server: key in `~/.config/wort/ai.env`, egress to `api.anthropic.com:443` only (DEPLOY §6), smoke test, then
   `spikes/ai_eval.md`; start the compose stack including `wort-lt`.
5. Step 0 spikes on the server (dictionary coverage, lemmatizer) → D1/D2; OCR on real photos → D3; LanguageTool numbers → D4.

**Mine, one piece at a time:**
1. What is left in `GUI-REFRESH.org` (Global shell, Practice, Texte 4/9, cross-cutting contrast).
2. Sentence mistakes do not count toward a topic's progress yet (D00i, open).
3. **Step 1 evidence:** sandbox proofs (D6) for the podman compose deploy (D00f).
4. **Step 7:** nightly `.backup` of the SQLite DB, structured logs, admin usage view (AI calls per user per day).
5. Mobile layouts on the design canvas, then touch for word tooltips.

## How to run locally

Same as `README.md` ("Run it locally"):

    git clone --recurse-submodules <repo> && cd wort
    uv sync --group web --group ocr                     # + `sudo apt install tesseract-ocr tesseract-ocr-deu` for Texte
    uv run wort import --file tests/fixtures/german_sample.jsonl   # or the full dictionary: python scripts/fetch_data.py dictionary downloads/
    PYTHONPATH=.:src uv run python scripts/adduser.py anna
    WORT_INSECURE_COOKIES=1 PYTHONPATH=.:src uv run uvicorn app.main:create_app --factory --port 8000   # 127.0.0.1 only
    scripts/dev.sh                                      # LAN https + LanguageTool container (WORT_DEV_LT=0 skips it)

## Gotchas learned

- Git identity (written in a cloud session, not re-checked): `GIT_AUTHOR_*`/`GIT_COMMITTER_*` override `git config`, and
  the stop hook wanted `noreply@anthropic.com` in wort commits. On the dev machine on 2026-10-31 `0ef26c6`
  carries `dsgnrfhmn`'s GitHub noreply address. dis-system wants that address and no mention of consuming apps or of real people (a personal handle counts) in anything pushed.
- dis-system rules: work on `dsgnrfhmn/<topic>` from `main`, PR only, `python -m pytest tests` before pushing;
  in a single-branch clone create the remote-tracking ref with `git fetch origin +refs/heads/<b>:refs/remotes/origin/<b>` or the stop hook complains.
- **A submodule pin must be on GitHub before the wort commit that uses it is pushed**; otherwise `git submodule update`
  fails for everyone else (happened to `origin/wip/dev-testing`, pin `6d58745`).
- From the Claude sandbox `github.com` is unreachable: pushes are run by garv in the session with `!`. On 2026-10-31 the
  first push to each of dis-system and wort returned 403 and went through on retry; the cause was not found.
- SDK facts checked, not assumed: Haiku 5.5 rejects `temperature`/`top_p`/prefill; SDK 2.x sends the key in the `Authorization` header.
- A leftover implicit SQLite transaction once locked the DB for the admin script; `tests/test_web_store.py` guards it.
- `cli.main()` installs the network guard process-wide; `tests/conftest.py` uninstalls it after each test.
- A macro imported at the top of a template is visible to every included component (a macro named `mark` printed as
  `<Macro 'mark'>` in the history table); a test guards every page (`GUI-REFRESH.org`, log).
