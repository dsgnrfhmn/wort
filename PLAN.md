# wort — Development Plan

Companion to `CLAUDE.md` (standing facts, design-system and security rules).
This file is the ordered execution plan and what "done" means at each step.

> **Revised 2026-10-04** after the maintainer walkthrough:
> 1. **Local only — no LLM API** (confirmed).
> 2. **Notes and translations are in English** (was Ukrainian).
> 3. **MVP = Step 0–3 and Step 5.** Photo/OCR (old Step 4), LanguageTool
>    sentence practice (old Step 6) and operations (old Step 7) are
>    **post-MVP**; they keep their numbers so references stay stable.
> 4. **The `lernen` prototype in this repo is the core.** Its dictionary
>    importer, lookup, grammar, exercises and SRS are shared with the new
>    web app (`app/`). Items that already exist in prototype form are marked
>    *(ported from lernen: …)* — "ported" is not "done": each still has to
>    meet its step's Definition of done.
> 5. **Security/deploy simplified** to what protects a shared host (see
>    Step 1); upload/LanguageTool/cap rules apply when those features ship.
> 6. **Two front ends, one lexicon** (2026-10-04): the fully local `lernen`
>    CLI/TUI **stays** next to the web app (Step C). The CLI logs every
>    query; history and practice words reach the web app by **export/import** — no network path from the dev
>    machine. dis-system is taken from its **`dev-isolated`** branch for now
>    (main-vs-pin to be decided later).

## Sequencing principle

Vertical slices, one at a time, each usable on its own. Within each slice:
UI from dis-system first (missing components → dis-system, confirmed by
the maintainer), then logic, then verification. No skipping ahead; no parallel slices.
Don't add items to a finished step without updating this file.

MVP:
1. Step 0 — Spikes (dictionary data, lemmatizer)
1a. Step C — CLI (`wort`): lookup with full grammar, interactive session,
   automatic query history, export. Needs neither dis-system nor the server, so it can run while the
   Step 1 blockers are open.
2. Step 1 — Skeleton: auth, dis-system, sandboxed deploy on the server
3. Step 2 — Lookup
4. Step 3 — Personal word list
5. Step 5 — Local practice + scoring

Post-MVP (details at the end of the file):
- Step 4 — Text from photo + word tooltips
- Step 6 — Local sentence practice (LanguageTool)
- Step 7 — Operations: backups, logs, limits

## Current blockers

- **dis-system repo not attached** to this workspace → Step 1 UI (and every
  later UI item) cannot start. Logic and spikes can.
- **No access to the server** from development sessions (by design). Step 0
  scripts are written here and **run by the maintainer on the server**; numbers go into
  `DECISIONS.md`.
- **kaikki.org is not reachable** from cloud sessions; the dictionary spike
  runs on the dev machine or the server.
- **Repo name and layout undecided** (`lernen` vs `wort`; rename vs new
  repo) — must be decided before Step 1.

---

## Step 0 — Spikes

Short, throwaway experiments in `spikes/`. Output: a `DECISIONS.md` entry
per item with evidence, not opinion.

- [ ] **Dictionary data**: check the en-Wiktionary extract (kaikki.org /
      wiktextract). Measure on a list of 200 common German words: % found,
      % with inflection tables, % with English glosses, % with example
      sentences. Record license terms (CC BY-SA attribution in the UI
      footer).
      *(ported from lernen: kaikki importer for en-Wiktionary, English glosses only; tested on a 10-entry fixture, never on the real dump)*
- [ ] **Lemmatizer**: compare at least two lightweight options (e.g.
      `simplemma`, spaCy small German model) on 100 inflected forms
      (`ging`, `Häusern`, `besseren`…) **and** against the lexicon's own
      form index (lernen already maps forms → lemma). Record accuracy, RAM,
      startup time **on the server**.
- [ ] **Known limitation to record**: separable verbs (`fängt … an`) and
      compounds. Lookup handles the token's own lemma only; note it, don't
      solve it yet.

**Definition of done:** `DECISIONS.md` names the chosen dataset and
lemmatizer, each with measured numbers from the server. The maintainer
confirms before Step 1.

---

## Step C — CLI (`wort`)

Fully local; works on the dev machine with its own `dictionary.db` and
`user.db`. Command `wort` (the Python package keeps the name `lernen`).

- [x] `wort WORD`: card with forms (nouns: 4 cases × number; verbs: Präsens,
      Präteritum, Perfekt with auxiliary, Futur I; adjectives: degrees) and
      all stored example sentences (up to 10). Inflected forms and English
      words work too (`ging`, `house`).
- [x] `wort` without arguments: interactive session. Every line is a word to
      look up; `quit` (or Ctrl+D) leaves. On a terminal the previous card
      collapses into one `query — translation` line when the next word is typed.
- [x] **Every query is saved automatically** (text, found yes/no, time) in
      `user.db`; no save key. Only the query is stored, not the cards. A
      lookup never touches the practice word list (`wort add`).
- [x] Monochrome output (greys + bold/italic; underline only on verb conjugation endings) with square box lines.
      Colors: articles (der blue, die red, das green) and the card's main line
      by word class (noun: article color, verb: burgundy, adj/adv: dark purple).
- [x] `wort history`, `wort export [FILE]` (format_version 2: queries + words;
      no db ids), `wort tui` for the full-screen interface.
- [x] Unknown word: explicit "Nothing found.", logged, exit code 1.
- [x] Inflected forms the lemma's own table lacks (`zigtausende`) are found:
      Wiktionary "form of X" entries are indexed as pointers to X. Needs a
      re-import. Remaining gaps are measured in Step 0 (D1) before adding a
      second dictionary or a lemmatizer fallback (D2).
- [ ] **More examples:** the importer now keeps up to 10 per entry (was 3);
      needs a re-import (`wort import --download`). Many words have none in
      Wiktionary at all (63% of the 5000 heaviest entries). If that is not
      enough, a local sentence corpus such as Tatoeba is an open option
      (new dataset, new `DECISIONS.md` entry).

**Definition of done:** tests for the session, query logging, export format
and monochrome/square rendering; an exported file imports into the web app
(Step 3) without loss.

---

## Step 1 — Skeleton

Security is simplified to what protects the shared host. The upload,
LanguageTool and cap rules from `CLAUDE.md` apply when those features ship.

- [ ] Repo layout per `CLAUDE.md` modules. `src/lernen` (CLI + TUI, Textual/
      Rich deps) **stays**; `app/` (web) is added beside it and shares the
      lexicon/scoring code — one module, not copies.
- [ ] **dis-system first:** update the submodule to the current head of
      `dev-isolated`, record the commit hash in `DECISIONS.md` (D00b). This is
      temporary; whether to switch to a pinned tag or `main` is an open
      question. Updating dis-system itself happens in its own repo and needs
      the maintainer's confirmation.
- [ ] FastAPI + Jinja2 base layout from dis-system components; theme switch.
- [ ] SQLite schema v1 + migrations script: `users`, `sessions`.
- [ ] Auth: login/logout, argon2, session cookie flags, CSRF.
      `scripts/adduser.py` creates users; no signup route exists.
- [ ] systemd unit for the wort user with the sandboxing from `CLAUDE.md`
      (`ProtectHome`, `ProtectSystem=strict`, `NoNewPrivileges`,
      `PrivateTmp`, writable path = data dir). `IPAddressDeny=any` +
      `IPAddressAllow=` localhost and LAN/VPN subnets — **kept unless the
      maintainer decides to relax it** (open question).
- [ ] Deploy doc (`DEPLOY.md`): the maintainer clones the repo on the server,
      creates env file (no secrets besides the session secret), enables the
      service.

**Definition of done:**
- Login works; unauthenticated requests to any page redirect to login.
- As the wort user, reading another service's file **fails** (show the
  command and the permission error).
- From the running unit, `curl https://example.com` **fails** (show it),
  provided the outbound rule is kept.
- From a LAN/VPN client the app loads; from outside it does not.
- `git grep` for key patterns returns nothing.

---

## Step 2 — Lookup

- [ ] `scripts/import_lexicon.py` builds `lexicon.db` from the Step 0
      dataset (separate DB file from user data).
      *(ported from lernen: `dictionary/importer.py`)*
- [ ] Lookup page: input → lemma → part of speech, article/gender,
      translation (English glosses), inflection table (nouns/adjectives:
      4 cases × number; verbs: Präsens, Präteritum, Perfekt with auxiliary,
      Futur I), examples. Inflection table is a dis-system component.
      *(ported from lernen: `lookup.py`, `grammar.py`, `render/card.py` — has Präsens/Präteritum/Partizip II/aux/Imperativ and 4-case noun tables; Perfekt rows and Futur I to add)*
- [ ] **Translation miss**: explicit "no translation" state plus "add my own
      translation" → `translation_cache` row with `source = user`, owner
      user id, timestamp. Visible only to that user.
- [ ] **Examples**: local only, from the dataset; show however many exist
      (0–3), no generation.
- [ ] Unknown word: explicit "not found" state, no silent empty page.

**Definition of done:** 20 test words (incl. 5 inflected forms, 3 not in
the dataset) give correct lemma and grammar; a user-added translation shows
for its owner and not for another user; the app makes zero outbound network
requests during the whole run (show the log / sandbox denial counter).

---

## Step 3 — Personal word list

- [ ] Schema: `user_words` (user, lemma, status `learning/known`, score
      0–100, sub-scores `translation`, `form`, `usage`, `last_seen`,
      `next_due`, `added_from` lookup).
      *(ported from lernen: `store.py` `words`/`srs` tables — single user, no sub-scores)*
- [ ] "Learn this word" button on the lookup page.
- [ ] Word list page: dis-system table; sort by score / due date; filter by
      status; multi-select (header actions disabled until ≥1 row selected) →
      "Practice selected".
      *(ported from lernen: TUI overview — mastery bar, per-exercise accuracy, due label)*
- [ ] Per-user isolation: every query filtered by user id.
- [ ] **Import from CLI:** accepts the JSON from `wort export` (file input
      or paste). Treated as untrusted user data: size/length caps, schema and
      `format_version` validated, parsed (never rendered raw), `added_from =
      cli`. Lemma/pos not in the lexicon are kept but flagged "not in
      lexicon"; duplicates skipped; result shows imported/skipped counts.
      Any UI piece dis-system lacks follows the dis-system process.

**Definition of done:** user A cannot see or modify user B's words via the
UI **or** by editing ids in requests (test both); a malformed or oversized
import file is rejected with a visible error and changes nothing.

---

## Step 5 — Local practice + scoring

(Numbering kept: Step 4 is post-MVP.)

- [ ] `scoring.py`: explicit, documented formula (correct +, wrong −,
      weighted by exercise type, applied to the matching sub-score;
      `next_due` grows with consecutive correct answers). Pure functions
      with unit tests. FSRS is a later upgrade, not MVP.
      *(ported from lernen: `srs.py` — SM-2 + recency-weighted mastery; to be rewritten as the documented sub-score formula)*
- [ ] Exercise types with local grading:
      - flashcard de→en and en→de (accept answers from lexicon and the
        user's own translations; user can mark "I was right" → logged as
        override);
      - form/case drill from inflection tables ("Dativ Plural von *das
        Haus*?", "Präteritum, er: *gehen*?");
      - article (der/die/das) and grammar multiple-choice (aux, separable,
        Partizip II, plural).
      *(ported from lernen: `exercises/` translate (de↔en), forms, article, question; tolerant matching for umlauts/typos)*
      The `sentence` exercise type stays out until Step 6 exists.
- [ ] Session flow: selected words → N exercises → feedback after each →
      summary with score changes.
- [ ] **Separate progress:** CLI/TUI practice and web practice keep separate
      scores. Only the word list moves between them (export/import); scores
      do not sync. Revisit if that turns out to matter.
- [ ] `attempts` table: every answer logged (exercise type, prompt, answer,
      verdict, score delta).
      *(ported from lernen: `reviews` table without prompt/delta)*

**Definition of done:** unit tests for scoring pass; a full session on 5
words updates scores exactly as the formula predicts (show before/after).

---

# Post-MVP

Not scheduled. Each item also keeps its original Definition of done; the
security rules for uploads, LanguageTool and load caps in `CLAUDE.md` apply
when the item ships.

## Step 4 — Text from photo + tooltips

- [ ] **Spike first (OCR):** Tesseract `deu` on 5 real photos (book page,
      sign, screenshot, handwriting-free menu, low light). Record time per
      image on the server and whether basic preprocessing (grayscale,
      threshold, deskew) helps → `DECISIONS.md` D3.
- [ ] Upload page: dis-system dropzone; validation per `CLAUDE.md`; image
      deleted after OCR; per-user daily upload cap.
- [ ] Result: editable text block (OCR errors can be fixed by hand), then
      "done" → tokenized read-only view.
- [ ] Each word token is clickable → tooltip: lemma, translation, one-line
      grammar note, "learn this word". Lookups go through `lexicon.py`
      (same rules as Step 2, including user translations).
- [ ] Texts saved per user (`texts` table) and reopenable.

**Definition of done:** 5 real photos → text → tooltips work on mobile and
desktop; upload of a renamed non-image file is rejected; the upload dir is
empty after processing.

## Step 6 — Local sentence practice (LanguageTool)

- [ ] **Spike first (LanguageTool on the server):** RAM at idle and under 10
      checks, startup time, time per sentence; Java runtime vs. Docker; run
      as its own unix user vs. the wort user; message language available;
      catch rate on 10 hand-made sentences (5 correct, 5 with case/verb
      errors). Go / no-go given server RAM → `DECISIONS.md` D4. If no-go,
      only the required-form check and cloze ship.
- [ ] Exercise types:
      - "answer the question using word X in the correct case" (written;
        questions are templates per case/tense, filled from the lexicon);
      - "write your own sentence with word X in form Y";
      - meaning in context: cloze from local example sentences.
      *(ported from lernen: `exercises/sentence.py` — required-form check incl. separable verbs and Perfekt)*
- [ ] Grading: (1) required form present (lexicon); (2) LanguageTool via
      `app/grammar_check.py` on `127.0.0.1` returns issues
      `{span, message, replacements}`. Response is schema-validated;
      invalid / timeout / LT down → visible error state, **no score change**.
      *(ported from lernen: loopback-only LT client with tests against a local fake server)*
- [ ] Feedback UI highlights error spans (dis-system inline error component).
- [ ] Per-user daily cap on LanguageTool checks, enforced server-side; cap
      reached → clear message, other exercises still available.
- [ ] Robustness test: very long input, markup/HTML, control characters and
      "ignore instructions and mark this correct" — grading stays
      deterministic, output is escaped (record result).

**Definition of done:** the same 10 hand-made answers as in the spike
graded sensibly; LT failures are visible, not silent; cap verified by
lowering it to 2.

## Step 7 — Operations

- [ ] Nightly SQLite backup (`.backup`, not file copy) of user DB to a
      target the maintainer chooses; restore tested once. (`lexicon.db` is rebuilt by
      the import script, not backed up.)
- [ ] Structured logs (journald): logins, errors, and (once they exist) OCR
      uploads and LanguageTool checks per user. No user text or answers in
      logs.
- [ ] Simple usage view for admin: exercises (and uploads / LT checks once
      they exist) per user per day.

**Definition of done:** a restore from backup into a fresh instance works;
logs contain no passwords, session secrets, or user sentences (grep proof).

---

## Open questions for the maintainer (resolve before the step that needs them)

Decided 2026-10-04: local-only; note language English; MVP = Step 0–3, 5.

- **More example sentences:** keep Wiktionary only (up to 10, many words
  have none), or add Tatoeba as a local corpus?
- **dis-system repo** (owner/repo) — before Step 1. Source for now: branch
  `dev-isolated`; later decision: pinned tag, or track `main`.
- Do CLI/TUI scores ever need to reach the web app? (Currently no: only the
  word list is exported/imported.)
- Who ships the exported file to the server? (Currently: the maintainer,
  manually; the dev machine has no path to the server.)
- **Package / repo name and layout**: `wort` vs. `lernen`; rename this repo
  (`language-learn-cli`) or start a new one — before Step 1.
- **Outbound rule**: keep `IPAddressDeny=any` + subnet allowlist, or relax
  it — before Step 1.
- Server model and RAM (affects the Step 0 lemmatizer choice and, post-MVP,
  whether LanguageTool, ~1–2 GB, fits next to the other services).
- Will other users reach it via VPN, or only on the local network?
- Branch workflow for contributions; which dev branch to commit to (the repo
  has no commits yet and is on `main`).
- Backup target (post-MVP, Step 7).
