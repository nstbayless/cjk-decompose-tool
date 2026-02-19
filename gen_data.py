#!/usr/bin/env python3
"""Generate data.json for the static site from cached cj.py data + ids.txt."""

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / ".cache"
IDS_DEFAULT = Path("/home/n/git/clong-radical/ids.txt")

BAD_CHARS = set("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑲")


def load_freq_file(path):
    chars = []
    glosses = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            ch = parts[0]
            chars.append(ch)
            if len(parts) > 1 and parts[1]:
                glosses[ch] = parts[1]
    return chars, glosses


def load_radicals(path):
    radicals = {}
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2:
                radicals[parts[0]] = parts[1]
    return radicals


def load_ids(ids_path):
    """Load raw preferred IDS decomposition strings."""
    ids = {}
    with open(ids_path) as f:
        for line in f:
            if not line.startswith("U"):
                continue
            line = line.strip()
            m = re.match(r"^U\+\w+\s+(\S)\s+(.+)$", line)
            if not m:
                continue
            char = m.group(1)
            decomps = m.group(2).split()
            decomp = decomps[0]
            for d in decomps:
                if not any(c in d for c in BAD_CHARS):
                    decomp = d
                    break
            decomp = re.sub(r"\[.*?]$", "", decomp)
            if len(decomp) <= 1:
                continue
            ids[char] = decomp
    return ids


def main():
    ids_path = Path(sys.argv[1]) if len(sys.argv) > 1 else IDS_DEFAULT

    # Check prerequisites
    for p in [CACHE_DIR / "hanzi_freq.txt", CACHE_DIR / "kanji_freq.txt",
              CACHE_DIR / "radicals.txt", CACHE_DIR / "canonical_radicals.txt",
              CACHE_DIR / "definitions.txt"]:
        if not p.exists():
            print(f"Missing {p}. Run `python3 cj.py hanzi` first to cache data.",
                  file=sys.stderr)
            sys.exit(1)

    hanzi, _ = load_freq_file(CACHE_DIR / "hanzi_freq.txt")
    kanji, _ = load_freq_file(CACHE_DIR / "kanji_freq.txt")
    radicals = load_radicals(CACHE_DIR / "radicals.txt")
    canonical = set()
    with open(CACHE_DIR / "canonical_radicals.txt") as f:
        for line in f:
            canonical.add(line.strip())
    ids = load_ids(ids_path)

    # Base layer: all Unihan kDefinition entries
    glosses = {}
    with open(CACHE_DIR / "definitions.txt") as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            if len(parts) == 2 and parts[1]:
                glosses[parts[0]] = parts[1]

    # Radical glosses override, prepended to definition
    for ch, label in radicals.items():
        if ch in glosses:
            glosses[ch] = f"{label} — {glosses[ch]}"
        else:
            glosses[ch] = label

    data = {
        "hanzi": hanzi,
        "kanji": kanji,
        "glosses": glosses,
        "ids": ids,
        "allRadicals": list(radicals.keys()),
        "canonical": list(canonical),
    }

    out = SCRIPT_DIR / "data.json"
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"Wrote {out} ({size_mb:.1f} MB, "
          f"{len(hanzi)} hanzi, {len(kanji)} kanji, "
          f"{len(ids)} IDS entries, {len(glosses)} glosses)")


if __name__ == "__main__":
    main()
