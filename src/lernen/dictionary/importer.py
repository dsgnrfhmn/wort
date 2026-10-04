"""Import a kaikki.org (English Wiktionary) German JSONL dump into dictionary.db.

Only the fields the app needs are kept: lemma, part of speech, gender, IPA,
auxiliary verb, separability, weak/strong, English glosses, examples and the
inflected forms with their grammatical tags.

Wiktionary also has separate "form of X" entries (e.g. the plural `zigtausende`
of `zigtausend`). They are not stored as entries, but each one becomes a
pointer form -> lemma in the form index, so inflected forms the lemma's own
table does not list can still be found.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from lernen.text import normalize

MAX_EXAMPLES = 10  # example sentences kept per entry
KAIKKI_URL = "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl"

POS_KEPT = {"noun", "verb", "adj", "adv", "prep", "conj", "pron", "num", "intj", "phrase", "particle"}

# Forms that are table metadata rather than real word forms.
_META_TAGS = {"table-tags", "inflection-template", "class"}
_GENDER_TAGS = {"masculine": "m", "feminine": "f", "neuter": "n"}
_PRONOUNS = {"ich", "du", "er", "sie", "es", "wir", "ihr", "er/sie/es", "sie/Sie", "Sie"}
_ARTICLES = {"der", "die", "das", "des", "dem", "den", "ein", "eine", "eines", "einem", "einen", "einer"}

SCHEMA = """
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    lemma TEXT NOT NULL,
    lemma_norm TEXT NOT NULL,
    pos TEXT NOT NULL,
    gender TEXT,
    ipa TEXT,
    aux TEXT,
    separable INTEGER NOT NULL DEFAULT 0,
    conj TEXT,
    glosses TEXT NOT NULL,
    examples TEXT NOT NULL,
    forms TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE form_index (form_norm TEXT NOT NULL, entry_id INTEGER NOT NULL);
CREATE TABLE en_index (en_word TEXT NOT NULL, entry_id INTEGER NOT NULL, score INTEGER NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE form_ptr (form_norm TEXT NOT NULL, target_norm TEXT NOT NULL, pos TEXT NOT NULL);
"""

INDEXES = """
CREATE INDEX idx_entries_lemma ON entries(lemma_norm);
CREATE INDEX idx_form_index ON form_index(form_norm);
CREATE INDEX idx_en_index ON en_index(en_word);
"""


def clean_form(form: str) -> str:
    """Drop leading articles/pronouns that some inflection tables include."""
    words = form.split()
    while len(words) > 1 and (words[0] in _ARTICLES or words[0] in _PRONOUNS):
        words = words[1:]
    return " ".join(words)


def _gender(raw: dict) -> str | None:
    for tag in raw.get("tags", []):
        if tag in _GENDER_TAGS:
            return _GENDER_TAGS[tag]
    for head in raw.get("head_templates", []):
        args = head.get("args", {})
        for key in ("g", "1"):
            first = str(args.get(key, "")).split(",")[0].split("-")[0]
            if first in ("m", "f", "n"):
                return first
        expansion = head.get("expansion", "")
        rest = expansion[len(raw["word"]):].split()
        if rest and rest[0].rstrip(",") in ("m", "f", "n"):
            return rest[0].rstrip(",")
    for sense in raw.get("senses", []):
        for tag in sense.get("tags", []):
            if tag in _GENDER_TAGS:
                return _GENDER_TAGS[tag]
    return None


def _head_expansion(raw: dict) -> str:
    return " ".join(h.get("expansion", "") for h in raw.get("head_templates", []))


def _ipa(raw: dict) -> str | None:
    for sound in raw.get("sounds", []):
        if ipa := sound.get("ipa"):
            return ipa
    return None


def _forms(raw: dict) -> list[tuple[str, list[str]]]:
    forms: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in raw.get("forms", []):
        tags = item.get("tags", [])
        form = item.get("form", "").strip()
        if not form or form == "-" or _META_TAGS & set(tags):
            continue
        form = clean_form(form)
        key = (form, tuple(sorted(tags)))
        if key not in seen:
            seen.add(key)
            forms.append((form, sorted(tags)))
    return forms


def _aux(raw: dict, forms: list[tuple[str, list[str]]]) -> str | None:
    auxes = [f for f, tags in forms if "auxiliary" in tags]
    if auxes:
        return " / ".join(dict.fromkeys(auxes))
    match = re.search(r"auxiliary (haben|sein)(?: or (haben|sein))?", _head_expansion(raw))
    if match:
        return " / ".join(a for a in match.groups() if a)
    return None


def _conj(raw: dict) -> str | None:
    expansion = _head_expansion(raw)
    tags = {t for item in raw.get("forms", []) for t in item.get("tags", [])}
    table = [i.get("form") for i in raw.get("forms", []) if "table-tags" in i.get("tags", [])]
    for kind in ("irregular", "strong", "weak"):
        if kind in tags or kind in table or re.search(rf"\b{kind}\b", expansion):
            return kind
    return None


def _separable(raw: dict, forms: list[tuple[str, list[str]]]) -> bool:
    if re.search(r"\bseparable\b", _head_expansion(raw)):
        return True
    for form, tags in forms:
        if {"present", "third-person", "singular"} <= set(tags) and "subjunctive-i" not in tags and " " in form:
            return True
    return False


def _glosses_and_examples(raw: dict) -> tuple[list[str], list[tuple[str, str]], bool]:
    glosses: list[str] = []
    examples: list[tuple[str, str]] = []
    only_form_of = True
    for sense in raw.get("senses", []):
        if not (sense.get("form_of") or "form-of" in sense.get("tags", [])):
            only_form_of = False
        for gloss in sense.get("glosses", [])[:1]:
            if gloss not in glosses:
                glosses.append(gloss)
        for example in sense.get("examples", []):
            text = example.get("text", "").strip()
            english = (example.get("english") or example.get("translation") or "").strip()
            if text and len(text) < 120 and len(examples) < MAX_EXAMPLES:
                examples.append((text, english))
    return glosses, examples, only_form_of


def gloss_keys(gloss: str) -> Iterator[str]:
    """English lookup keys for one gloss: "to intend, to plan (something)" -> intend, plan."""
    gloss = re.sub(r"\([^)]*\)", "", gloss)
    for part in re.split(r"[,;]", gloss):
        part = part.strip().lower()
        part = re.sub(r"^(to|a|an|the) ", "", part).strip(" .!?")
        if part and len(part.split()) <= 3:
            yield part


def parse_entry(raw: dict) -> dict | None:
    if raw.get("lang_code", "de") != "de" or raw.get("pos") not in POS_KEPT:
        return None
    glosses, examples, only_form_of = _glosses_and_examples(raw)
    if not glosses or only_form_of:
        return None
    forms = _forms(raw)
    pos = raw["pos"]
    return {
        "lemma": raw["word"],
        "pos": pos,
        "gender": _gender(raw) if pos == "noun" else None,
        "ipa": _ipa(raw),
        "aux": _aux(raw, forms) if pos == "verb" else None,
        "separable": _separable(raw, forms) if pos == "verb" else False,
        "conj": _conj(raw) if pos == "verb" else None,
        "glosses": glosses,
        "examples": examples,
        "forms": forms,
        "weight": len(raw.get("senses", [])) + len(raw.get("translations", [])),
    }


def form_pointers(raw: dict) -> list[tuple[str, str, str]]:
    """(form, lemma it is a form of, pos) for a "form of X" entry that is not stored itself."""
    if raw.get("lang_code", "de") != "de" or raw.get("pos") not in POS_KEPT or not raw.get("word"):
        return []
    form = normalize(raw["word"])
    pointers = []
    for sense in raw.get("senses", []):
        for target in sense.get("form_of") or []:
            word = target.get("word") if isinstance(target, dict) else None
            if word and normalize(word) != form:
                pointers.append((form, normalize(word), raw["pos"]))
    return pointers


def iter_jsonl(lines: Iterable[str]) -> Iterator[dict]:
    for line in lines:
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


_POINTER_SQL = """
INSERT INTO form_index
SELECT DISTINCT p.form_norm, e.id FROM form_ptr p JOIN entries e ON e.lemma_norm = p.target_norm
WHERE {where} AND p.form_norm != e.lemma_norm
  AND NOT EXISTS (SELECT 1 FROM form_index f WHERE f.form_norm = p.form_norm AND f.entry_id = e.id)
"""


def _resolve_form_pointers(conn: sqlite3.Connection) -> int:
    """Turn form -> lemma pointers into form_index rows. Same part of speech wins; if the
    lemma exists only with another part of speech (zigtausende is tagged noun, zigtausend is
    a numeral) the pointer still goes to it."""
    before = conn.execute("SELECT count(*) FROM form_index").fetchone()[0]
    conn.execute(_POINTER_SQL.format(where="e.pos = p.pos"))
    conn.execute(_POINTER_SQL.format(
        where="NOT EXISTS (SELECT 1 FROM entries e2 WHERE e2.lemma_norm = p.target_norm AND e2.pos = p.pos)"
    ))
    return conn.execute("SELECT count(*) FROM form_index").fetchone()[0] - before


def import_entries(raws: Iterable[dict], db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    """Build a fresh dictionary.db from raw kaikki entries. Returns entries written."""
    tmp_path = db_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_path)
    conn.executescript(SCHEMA)
    count = 0
    for raw in raws:
        entry = parse_entry(raw)
        if entry is None:
            conn.executemany("INSERT INTO form_ptr VALUES (?, ?, ?)", form_pointers(raw))
            continue
        cur = conn.execute(
            "INSERT INTO entries (lemma, lemma_norm, pos, gender, ipa, aux, separable, conj, glosses, examples, forms, weight)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry["lemma"], normalize(entry["lemma"]), entry["pos"], entry["gender"], entry["ipa"],
                entry["aux"], int(entry["separable"]), entry["conj"],
                json.dumps(entry["glosses"], ensure_ascii=False),
                json.dumps(entry["examples"], ensure_ascii=False),
                json.dumps(entry["forms"], ensure_ascii=False),
                entry["weight"],
            ),
        )
        entry_id = cur.lastrowid
        norms = {normalize(f) for f, _ in entry["forms"]} - {normalize(entry["lemma"])}
        conn.executemany("INSERT INTO form_index VALUES (?, ?)", [(n, entry_id) for n in norms if n])
        en_rows: dict[str, int] = {}
        for rank, gloss in enumerate(entry["glosses"]):
            for key in gloss_keys(gloss):
                en_rows.setdefault(key, rank)
        conn.executemany("INSERT INTO en_index VALUES (?, ?, ?)", [(k, entry_id, r) for k, r in en_rows.items()])
        count += 1
        if progress and count % 10000 == 0:
            progress(count)
    conn.executescript(INDEXES)
    added = _resolve_form_pointers(conn)
    conn.execute("DROP TABLE form_ptr")
    conn.execute("INSERT INTO meta VALUES ('entries', ?)", (str(count),))
    conn.execute("INSERT INTO meta VALUES ('form_pointers', ?)", (str(added),))
    conn.commit()
    conn.close()
    tmp_path.replace(db_path)
    return count


def import_file(jsonl_path: Path, db_path: Path, progress: Callable[[int], None] | None = None) -> int:
    with open(jsonl_path, encoding="utf-8") as fh:
        return import_entries(iter_jsonl(fh), db_path, progress)


def download(dest: Path, url: str = KAIKKI_URL, progress: Callable[[int], None] | None = None) -> Path:
    """Stream the kaikki dump to disk (one-time, ~1 GB)."""
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done)
    tmp.replace(dest)
    return dest
