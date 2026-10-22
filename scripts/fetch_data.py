"""Fetch the big data files for the CLI. This is the ONLY place that downloads anything.

The `wort` CLI never uses the network except `wort sync`; run this script separately, on a machine/shell
where network access is fine, then hand the files to the CLI:

    python scripts/fetch_data.py dictionary [OUT_DIR]     ~1 GB kaikki.org JSONL (Wiktionary, CC BY-SA)
    python scripts/fetch_data.py models [OUT_DIR]         Argos de->en and en->de models (~100 MB each; needs `uv sync --group mt`)

    wort import --file OUT_DIR/kaikki.org-dictionary-German.jsonl
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
DIRECTIONS = (("de", "en"), ("en", "de"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_dictionary(out: Path) -> Path:
    dest = out / Path(KAIKKI_URL).name
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(KAIKKI_URL, timeout=60) as resp, open(tmp, "wb") as fh:
        done = 0
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            print(f"\r{done / 1e6:.0f} MB", end="", flush=True)
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
    if len(argv) < 2 or argv[1] not in {"dictionary", "models"}:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(argv[2] if len(argv) > 2 else "downloads")
    out.mkdir(parents=True, exist_ok=True)
    for path in ([fetch_dictionary(out)] if argv[1] == "dictionary" else fetch_models(out)):
        print(f"{path}  sha256 {sha256(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
