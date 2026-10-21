# Handoff — where we stopped (2026-10-21)

Read this first next time. It says what exists, what is verified, what is not, and what to do next.
Standing rules are in `CLAUDE.md`, decisions in `DECISIONS.md`, the ordered plan in `PLAN.md`.

## State in one paragraph

The web app (`app/`) from the design canvas exists and works locally: login, per-user word list with
scores, word detail, practice (Sätze bilden, Abfrage), Texte placeholder. The AI layer is complete and
**off by default**. The CLI is offline except `wort sync`. Everything is committed and pushed. **Nothing has
run against the live Anthropic API, the OS-level CLI network rule, nginx or compose** (no key / no such
tools in the dev container).

- Branch `wip/web-view` @ `805b518`, PR **#5** into `wip/dev-testing` (no `main` branch exists in the repo).
- 394 tests pass: `PYTHONPATH=.:src uv run pytest` (web deps: `uv sync --group web`; AI tests need `--group ai`, they skip otherwise).
- dis-system submodule is on branch `dsgnrfhmn/form-props` @ `d8811df`, **not merged to dis-system `main`**.

## What is built

| Area | Where | Notes |
|---|---|---|
| Accounts | `app/auth.py`, `scripts/adduser.py` | argon2, hashed session tokens, CSRF, login throttle; no signup |
| Word list + detail | `app/words.py`, `app/templates/words.html`, `word.html` | sort, search, presets, selection, own translation |
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
- Design gaps are **not** patched locally (rule in `CLAUDE.md`); listed in `PLAN.md` "Web UI status".

## Not verified (do not assume these work)

1. Any real Anthropic call. Run `PYTHONPATH=.:src python scripts/ai_smoke.py` on the server (needs key); expect `ALL PASS`.
2. `scripts/wort-offline --check` on the real CLI machine (Linux user systemd / macOS sandbox).
3. `nginx.conf` (8456 listener) and `compose.yaml` (`wort-sync`): never started.
4. Quality of AI verdicts on real mistakes: `spikes/ai_eval.md` is a spec, not run.
5. Both-theme check was done on Wörter/Üben screenshots only, not on every state.

## Next steps (suggested order)

**Yours (blockers for merging / enabling):**
1. Open the dis-system PR for `dsgnrfhmn/form-props` and merge it; then switch the submodule to `main`
   (record the hash in `DECISIONS.md` D00b). Merge PR #5 afterwards.
2. On the server: key in `~/.config/wort/ai.env`, egress to `api.anthropic.com:443` only (DEPLOY §6), smoke test, then `spikes/ai_eval.md`.
3. Verify items 2-3 of "Not verified" above.
4. Step 0 spikes (dictionary coverage, lemmatizer) on the server; numbers into `DECISIONS.md` D1/D2.

**Mine, one piece at a time:**
1. **Lookup page in the web (PLAN Step 2)** — missing today; words only arrive via CLI import. Search, forms, own translation on a miss, "Learn this word".
2. **dis-system components for the design gaps** (on a dis-system branch, never `main`): article colors, score chip, task/answer bubbles, inline correction marks, word tooltip.
3. **Step 1 evidence:** systemd unit with the sandbox, D6 proofs (other services' files unreadable, no outbound).
4. **Step 7:** nightly `.backup` of the SQLite DB, structured logs, admin usage view (AI calls per user per day).
5. **Texte (post-MVP):** Tesseract spike (D3) first, then uploads with the CLAUDE.md rules, spaCy tooltips.
6. `scripts/demo.sh` (one-step local run) if useful.

## How to run locally

    uv sync --group web
    uv run wort import --file <kaikki.jsonl>          # from: python scripts/fetch_data.py dictionary downloads/
    PYTHONPATH=.:src uv run python scripts/adduser.py anna
    WORT_INSECURE_COOKIES=1 PYTHONPATH=.:src uv run uvicorn app.main:create_app --factory --port 8000   # 127.0.0.1 only

## Gotchas learned

- Git identity: this environment sets `GIT_AUTHOR_*`/`GIT_COMMITTER_*`, which override `git config`. The stop hook wants
  `noreply@anthropic.com` in wort commits; set the env vars for the commit. dis-system wants the GitHub noreply address
  (`255602589+dsgnrfhmn@users.noreply.github.com`) and no mention of consuming apps.
- dis-system rules: work on `dsgnrfhmn/<topic>` from `main`, PR only, `python -m pytest tests` before pushing;
  in a single-branch clone create the remote-tracking ref with `git fetch origin +refs/heads/<b>:refs/remotes/origin/<b>` or the stop hook complains.
- SDK facts checked, not assumed: Haiku 5.5 rejects `temperature`/`top_p`/prefill; SDK 2.x sends the key in the `Authorization` header.
- A leftover implicit SQLite transaction once locked the DB for the admin script; `tests/test_web_store.py` guards it.
- `cli.main()` installs the network guard process-wide; `tests/conftest.py` uninstalls it after each test.
