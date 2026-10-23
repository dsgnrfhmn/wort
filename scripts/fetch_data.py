"""Fetch the big data files for the CLI. This is the ONLY place that downloads anything.

The `wort` CLI never uses the network except `wort sync`; run this script separately, on a machine/shell
where network access is fine, then hand the files to the CLI:

    python scripts/fetch_data.py dictionary [OUT_DIR]     ~1 GB kaikki.org JSONL (Wiktionary, CC BY-SA)
    python scripts/fetch_data.py uk [OUT_DIR]             ~300 MB German Wiktionary dump, gzipped (Ukrainian translations, CC BY-SA)
    python scripts/fetch_data.py en-uk [OUT_DIR]          English Wiktionary, streamed (3 GB): only entries with Ukrainian translations are kept, gzipped
    python scripts/fetch_data.py models [OUT_DIR]         Argos de->en and en->de models (~100 MB each; needs `uv sync --group mt`)

    wort import --file OUT_DIR/kaikki.org-dictionary-German.jsonl
    wort import-uk --file OUT_DIR/raw-wiktextract-data.jsonl.gz
    wort import-en-uk --file OUT_DIR/kaikki-English-uk.jsonl.gz
    wort install-translation OUT_DIR/*.argosmodel

Downloads are saved under OUT_DIR (default: ./downloads) and are untrusted data: nothing is executed.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

KAIKKI_URL = "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl"
KAIKKI_DE_URL = "https://kaikki.org/dewiktionary/raw-wiktextract-data.jsonl.gz"  # German Wiktionary, all languages
KAIKKI_EN_URL = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl"  # English words, en.wiktionary
UK_MARK = b'"lang_code": "uk"'  # a line without it has no Ukrainian translation; the importer parses the rest
DIRECTIONS = (("de", "en"), ("en", "de"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_dictionary(out: Path, url: str = KAIKKI_URL) -> Path:
    dest = out / Path(url).name
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as fh:
        done = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            print(f"\r{done / 1e6:.0f} MB", end="", flush=True)
    tmp.replace(dest)
    print()
    return dest


def fetch_english_uk(out: Path) -> Path:
    """Stream the English dump and keep only the lines that carry a Ukrainian translation (byte filter, no
    parsing: the file stays untrusted data for the importer). Saves ~3 GB of disk."""
    import gzip
    dest = out / "kaikki-English-uk.jsonl.gz"
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(KAIKKI_EN_URL, timeout=60) as resp, gzip.open(tmp, "wb") as fh:
        done = kept = 0
        for line in resp:
            done += len(line)
            if UK_MARK in line:
                fh.write(line)
                kept += 1
                if kept % 2000 == 0:
                    print(f"\r{done / 1e6:.0f} MB read, {kept} entries kept", end="", flush=True)
    tmp.replace(dest)
    print()
    return dest


def fetch_models(out: Path) -> list[Path]:
    try:
        from argostranslate import package
    except ImportError:
        sys.exit("Needs the 'mt' group: uv sync --group mt")
    package.update_package_index()
    available = package.get_available_packages()
    files = []
    for src, dst in DIRECTIONS:
        wanted = next((p for p in available if p.from_code == src and p.to_code == dst), None)
        if wanted is None:
            sys.exit(f"No {src}->{dst} model in the Argos package index.")
        files.append(Path(shutil.copy(wanted.download(), out / f"translate-{src}_{dst}.argosmodel")))
    return files


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"dictionary", "uk", "en-uk", "models"}:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[2] if len(argv) > 2 else "downloads")
    out.mkdir(parents=True, exist_ok=True)
    if argv[1] == "models":
        paths = fetch_models(out)
    elif argv[1] == "en-uk":
        paths = [fetch_english_uk(out)]
    else:
        paths = [fetch_dictionary(out, KAIKKI_URL if argv[1] == "dictionary" else KAIKKI_DE_URL)]
    for path in paths:
        print(f"{path}  sha256 {sha256(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
