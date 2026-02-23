#!/usr/bin/env python3
"""Generate data.json for the static site from cached cj.py data + ids.txt."""

import csv
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / ".cache"
DICTS_DIR = SCRIPT_DIR / "dicts"
IDS_DEFAULT = Path("/home/n/git/clong-radical/ids.txt")

BAD_CHARS = set("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑲")


# ── Helpers ──

def extract_cjk(s):
    """Return list of CJK ideograph codepoints found in s."""
    out = []
    for c in s:
        cp = ord(c)
        if (0x4E00 <= cp <= 0x9FFF    # CJK Unified Ideographs
                or 0x3400 <= cp <= 0x4DBF   # Extension A
                or 0x20000 <= cp <= 0x2A6DF  # Extension B
                or 0x2A700 <= cp <= 0x2CEAF  # Extensions C–F
                or 0xF900 <= cp <= 0xFAFF):  # Compatibility Ideographs
            out.append(c)
    return out


def cumulative(lists):
    """Given ordered list of char lists, return cumulative union lists preserving order."""
    result = []
    seen = set()
    accum = []
    for lst in lists:
        for ch in lst:
            if ch not in seen:
                seen.add(ch)
                accum.append(ch)
        result.append(list(accum))
    return result


# ── Loaders ──

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


def load_joyo_levels(path):
    """Load JLPT and Joyo grade character sets from joyo.csv (NHV33 compilation).

    Returns:
      jlpt: dict mapping 'n5'..'n1' -> cumulative list of kanji
      joyo: dict mapping '1'..'6','s' -> cumulative list of kanji
    """
    by_jlpt = {str(l): [] for l in range(1, 6)}   # keys '1'..'5'
    by_grade = {str(g): [] for g in list(range(1, 7)) + ['S']}

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ch = row["kanji"]
            grade = row["grade"]
            jlpt_val = row["jlpt"]
            if grade in by_grade:
                by_grade[grade].append(ch)
            if jlpt_val in by_jlpt:
                by_jlpt[jlpt_val].append(ch)

    # Cumulative JLPT: N5 (jlpt=5) is easiest, N1 (jlpt=1) hardest
    jlpt = {}
    accum = []
    for lvl in ["5", "4", "3", "2", "1"]:
        accum = accum + by_jlpt[lvl]
        key = "n" + lvl  # n5, n4, n3, n2, n1
        jlpt[key] = list(accum)

    # Cumulative Joyo grades: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> S
    joyo = {}
    accum = []
    for g in ["1", "2", "3", "4", "5", "6", "S"]:
        accum = accum + by_grade[g]
        key = g.lower()  # '1'..'6', 's'
        joyo[key] = list(accum)

    return jlpt, joyo


def load_hsk_old(dicts_dir):
    """Load old HSK 2012 (Hanban) word lists from glxxyz/hskhsk.com.

    Each file is one word per line (UTF-8 BOM). We extract all CJK characters
    from each word and build cumulative sets across levels.

    Returns dict: hsk_1..hsk_6 -> cumulative char list
    """
    per_level = []
    for lvl in range(1, 7):
        path = dicts_dir / f"hsk2012_l{lvl}.txt"
        chars_this_level = []
        seen = set()
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                word = line.strip()
                if not word:
                    continue
                for ch in extract_cjk(word):
                    if ch not in seen:
                        seen.add(ch)
                        chars_this_level.append(ch)
        per_level.append(chars_this_level)

    cumul = cumulative(per_level)
    return {f"hsk_{i+1}": cumul[i] for i in range(6)}


def load_nhsk(dicts_dir):
    """Load New HSK 2021 hanzi lists from krmanik/HSK-3.0.

    Files contain one character per line, already extracted. Levels 7–9 share
    a single combined file (the official standard groups them together).

    Returns dict: nhsk_1..nhsk_9 -> cumulative char list
      nhsk_7, nhsk_8, nhsk_9 are identical (all include levels 1–9 combined).
    """
    per_level = []
    for lvl in range(1, 7):
        path = dicts_dir / f"nhsk_hanzi_{lvl}.txt"
        chars = []
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                ch = line.strip()
                if ch and extract_cjk(ch):
                    chars.append(ch)
        per_level.append(chars)

    # Levels 7-9 combined
    path_79 = dicts_dir / "nhsk_hanzi_7-9.txt"
    chars_79 = []
    with open(path_79, encoding="utf-8-sig") as f:
        for line in f:
            ch = line.strip()
            if ch and extract_cjk(ch):
                chars_79.append(ch)
    per_level.append(chars_79)  # index 6 = 7-9 block

    cumul = cumulative(per_level)   # 7 cumulative lists

    result = {f"nhsk_{i+1}": cumul[i] for i in range(6)}  # nhsk_1..nhsk_6
    # nhsk_7, nhsk_8, nhsk_9 all = cumulative through 7-9 block
    for lvl in (7, 8, 9):
        result[f"nhsk_{lvl}"] = cumul[6]
    return result


def load_tocfl(dicts_dir):
    """Load TOCFL vocabulary from ivankra/tocfl (tocfl-202307.csv).

    Level mapping (ID prefix):
      L0 = Novice (excluded — pre-Band A)
      L1 + L2 = Band A
      L1 + L2 + L3 + L4 = Band B (cumulative)
      L1 + L2 + L3 + L4 + L5 = Band C (cumulative)

    Characters are extracted from the Traditional column. Entries may contain
    slash-separated variants (e.g. 你/妳) and parenthetical optionals
    (e.g. 手指(頭)); all CJK characters in the cell are included.

    Returns dict: tocfl_a, tocfl_b, tocfl_c -> cumulative char list
    """
    # Collect per-sub-level character sets
    by_sublevel = {str(i): [] for i in range(1, 6)}  # L1..L5
    seen_by_sublevel = {str(i): set() for i in range(1, 6)}

    with open(dicts_dir / "tocfl.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_field = row["ID"]            # e.g. 'L1-0042'
            m = re.match(r"L(\d+)-", id_field)
            if not m:
                continue
            sublevel = m.group(1)
            if sublevel not in by_sublevel:
                continue  # L0 = Novice, skip

            trad = row["Traditional"]
            for ch in extract_cjk(trad):
                if ch not in seen_by_sublevel[sublevel]:
                    seen_by_sublevel[sublevel].add(ch)
                    by_sublevel[sublevel].append(ch)

    # Band A = L1+L2, Band B = L1..L4, Band C = L1..L5
    band_sublevel_groups = {
        "a": ["1", "2"],
        "b": ["1", "2", "3", "4"],
        "c": ["1", "2", "3", "4", "5"],
    }

    result = {}
    for band, sublevels in band_sublevel_groups.items():
        seen = set()
        chars = []
        for sl in sublevels:
            for ch in by_sublevel[sl]:
                if ch not in seen:
                    seen.add(ch)
                    chars.append(ch)
        result[f"tocfl_{band}"] = chars

    return result


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

    for fname in ["joyo.csv", "hsk2012_l1.txt", "nhsk_hanzi_1.txt", "tocfl.csv"]:
        if not (DICTS_DIR / fname).exists():
            print(f"Missing {DICTS_DIR}/{fname}.", file=sys.stderr)
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

    jlpt, joyo = load_joyo_levels(DICTS_DIR / "joyo.csv")
    hsk_old = load_hsk_old(DICTS_DIR)
    nhsk = load_nhsk(DICTS_DIR)
    tocfl = load_tocfl(DICTS_DIR)

    data = {
        "hanzi": hanzi,
        "kanji": kanji,
        "glosses": glosses,
        "ids": ids,
        "allRadicals": list(radicals.keys()),
        "canonical": list(canonical),
        # JLPT cumulative (n5 = N5 only; n1 = all Joyo)
        "jlpt_n5": jlpt["n5"],
        "jlpt_n4": jlpt["n4"],
        "jlpt_n3": jlpt["n3"],
        "jlpt_n2": jlpt["n2"],
        "jlpt_n1": jlpt["n1"],
        # Joyo cumulative (joyo_1 = grade 1; joyo_s = all 2136)
        "joyo_1": joyo["1"],
        "joyo_2": joyo["2"],
        "joyo_3": joyo["3"],
        "joyo_4": joyo["4"],
        "joyo_5": joyo["5"],
        "joyo_6": joyo["6"],
        "joyo_s": joyo["s"],
        # Old HSK (Hanban 2012) cumulative
        **hsk_old,
        # New HSK 2021 cumulative (nhsk_7/8/9 share the same 7-9 combined set)
        **nhsk,
        # TOCFL cumulative (Bands A/B/C; L0 Novice excluded)
        **tocfl,
    }

    out = SCRIPT_DIR / "data.json"
    with open(out, "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"Wrote {out} ({size_mb:.1f} MB, "
          f"{len(hanzi)} hanzi, {len(kanji)} kanji, "
          f"{len(ids)} IDS entries, {len(glosses)} glosses)")
    print(f"  JLPT: N5={len(jlpt['n5'])} N4={len(jlpt['n4'])} "
          f"N3={len(jlpt['n3'])} N2={len(jlpt['n2'])} N1={len(jlpt['n1'])}")
    print(f"  Joyo: 1={len(joyo['1'])} 2={len(joyo['2'])} 3={len(joyo['3'])} "
          f"4={len(joyo['4'])} 5={len(joyo['5'])} 6={len(joyo['6'])} S={len(joyo['s'])}")
    print(f"  HSK (old): " + " ".join(f"L{i+1}={len(hsk_old[f'hsk_{i+1}'])}" for i in range(6)))
    print(f"  New HSK:   " + " ".join(f"L{i+1}={len(nhsk[f'nhsk_{i+1}'])}" for i in range(9)))
    print(f"  TOCFL: A={len(tocfl['tocfl_a'])} B={len(tocfl['tocfl_b'])} C={len(tocfl['tocfl_c'])}")


if __name__ == "__main__":
    main()
