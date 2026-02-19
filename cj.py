#!/usr/bin/env python3
"""cj.py - Random CJK character decomposition tree viewer."""

import argparse
import io
import os
import random
import re
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR / ".cache"
IDS_DEFAULT = Path("/home/n/git/clong-radical/ids.txt")

UNIHAN_URL = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"
RADICALS_URL = "https://www.unicode.org/Public/UCD/latest/ucd/CJKRadicals.txt"

BINARY_IDS = set("⿰⿱⿴⿵⿶⿷⿸⿹⿺⿻")
TRINARY_IDS = set("⿲⿳")
BAD_CHARS = set("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑲")


# --- Kangxi radical lookup ---

def load_radicals():
    """Build {char: gloss_label} and a set of canonical radical chars.

    Downloads CJKRadicals.txt (maps radical numbers to codepoints), then
    uses unicodedata to extract English names from the Kangxi Radical block.
    Also covers CJK Radicals Supplement forms and kRSUnicode variants.

    Returns (radicals_dict, canonical_set).
    """
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / "radicals.txt"
    canon_cache = CACHE_DIR / "canonical_radicals.txt"

    if cache.exists() and canon_cache.exists():
        radicals = {}
        with open(cache) as f:
            for line in f:
                parts = line.strip().split("\t", 1)
                if len(parts) == 2:
                    radicals[parts[0]] = parts[1]
        canonical = set()
        with open(canon_cache) as f:
            for line in f:
                canonical.add(line.strip())
        return radicals, canonical

    print("Downloading CJKRadicals.txt...", file=sys.stderr)
    resp = urllib.request.urlopen(RADICALS_URL)
    raw = resp.read().decode("utf-8")

    # Parse CJKRadicals.txt:
    #   radical_number; kangxi_radical_codepoint; cjk_unified_ideograph_codepoint
    # radical_number may have a trailing ' for simplified variant forms
    radicals = {}  # char -> label
    canonical = set()  # chars that are canonical radical forms

    # First pass: collect radical number -> kangxi block char -> english name
    # so we can reuse the name for all variants of the same radical number.
    radical_names = {}  # base radical number (int) -> english gloss

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) != 3:
            continue
        rad_str, kangxi_cp, cjk_cp = parts
        base_num = int(rad_str.rstrip("'"))

        cjk_char = chr(int(cjk_cp, 16))
        kangxi_char = chr(int(kangxi_cp, 16)) if kangxi_cp else None

        # Get English name from the Kangxi Radical block character
        if base_num not in radical_names:
            kangxi_block_char = chr(0x2F00 + base_num - 1)
            try:
                name = unicodedata.name(kangxi_block_char, "")
                gloss = name.replace("KANGXI RADICAL ", "").lower()
            except ValueError:
                gloss = ""
            if gloss:
                radical_names[base_num] = gloss

        gloss = radical_names.get(base_num, "")
        if not gloss:
            continue
        label = f"{base_num}: {gloss}"
        if kangxi_char:
            radicals[kangxi_char] = label
            canonical.add(kangxi_char)
        radicals[cjk_char] = label
        canonical.add(cjk_char)

    # Also map CJK Radicals Supplement block (U+2E80-U+2EFF) by their
    # unicodedata names, e.g. "CJK RADICAL REPEAT" → find matching Kangxi
    for cp in range(0x2E80, 0x2F00):
        ch = chr(cp)
        if ch in radicals:
            continue
        try:
            name = unicodedata.name(ch, "")
        except ValueError:
            continue
        if not name.startswith("CJK RADICAL "):
            continue
        gloss = name.replace("CJK RADICAL ", "").lower()
        # Try to find the matching Kangxi radical number
        for num, kg in radical_names.items():
            if kg == gloss:
                radicals[ch] = f"{num}: {gloss}"
                canonical.add(ch)
                break
        else:
            # No exact match; still label it as a radical variant
            radicals[ch] = f"CJK radical: {gloss}"
            canonical.add(ch)

    # Merge radical variants from kRSUnicode (often in CJK Extension B,
    # e.g. 𠃌 = 5.0, 𠂊 = 4.1).
    rs_file = CACHE_DIR / "rs_variants.txt"
    if rs_file.exists():
        for line in open(rs_file):
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            ch = parts[0]
            if ch in radicals:
                continue  # already have a label from CJKRadicals.txt
            rad = int(parts[1])
            residual = int(parts[2])
            defn = parts[3] if len(parts) > 3 else ""
            if defn:
                continue  # has a definition → real character, not a component
            if residual > 2:
                continue  # too far from the radical form
            gloss = radical_names.get(rad, "")
            if not gloss:
                continue
            if residual == 0:
                label = f"{rad}.0 (variant): {gloss}"
            else:
                label = f"{rad}.{residual} (variant): {gloss}"
            if defn:
                label += f" — {defn}"
            radicals[ch] = label

    with open(cache, "w") as f:
        for ch, label in sorted(radicals.items(), key=lambda x: ord(x[0])):
            f.write(f"{ch}\t{label}\n")

    with open(canon_cache, "w") as f:
        for ch in sorted(canonical, key=ord):
            f.write(f"{ch}\n")

    print(f"Cached {len(radicals)} radical forms ({len(canonical)} canonical).",
          file=sys.stderr)
    return radicals, canonical


# --- Unihan download & caching ---

def ensure_unihan():
    """Download Unihan data and build frequency-sorted character lists."""
    CACHE_DIR.mkdir(exist_ok=True)
    hanzi_file = CACHE_DIR / "hanzi_freq.txt"
    kanji_file = CACHE_DIR / "kanji_freq.txt"

    if hanzi_file.exists() and kanji_file.exists():
        return

    print("Downloading Unihan data (one-time)...", file=sys.stderr)
    resp = urllib.request.urlopen(UNIHAN_URL)
    zip_data = io.BytesIO(resp.read())

    mandarin = {}
    japanese_on = {}
    japanese_kun = {}
    frequency = {}
    strokes = {}
    joyo = set()
    definition = {}
    rs_unicode = {}  # char -> "radical.residual_strokes" e.g. "5.0"

    with zipfile.ZipFile(zip_data) as zf:
        for name in zf.namelist():
            if not name.endswith(".txt"):
                continue
            with zf.open(name) as f:
                for raw in f:
                    line = raw.decode("utf-8").strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) != 3:
                        continue
                    cp, field, value = parts
                    try:
                        ch = chr(int(cp[2:], 16))
                    except Exception:
                        continue
                    if field == "kMandarin":
                        mandarin[ch] = value
                    elif field == "kJapaneseOn":
                        japanese_on[ch] = value
                    elif field == "kJapaneseKun":
                        japanese_kun[ch] = value
                    elif field == "kFrequency":
                        frequency[ch] = int(value)
                    elif field == "kTotalStrokes":
                        strokes[ch] = int(value.split()[0])
                    elif field == "kJoyoKanji":
                        joyo.add(ch)
                    elif field == "kDefinition":
                        definition[ch] = value
                    elif field == "kRSUnicode":
                        rs_unicode[ch] = value

    # Hanzi: characters with Mandarin readings, sorted by frequency heuristic
    hanzi_sorted = sorted(
        mandarin,
        key=lambda c: (frequency.get(c, 6), strokes.get(c, 99), ord(c)),
    )[:10000]

    with open(hanzi_file, "w") as f:
        for c in hanzi_sorted:
            f.write(f"{c}\t{definition.get(c, '')}\n")

    # Kanji: characters with Japanese readings, jōyō first
    kanji_chars = set(japanese_on) | set(japanese_kun)
    kanji_sorted = sorted(
        kanji_chars,
        key=lambda c: (0 if c in joyo else 1, frequency.get(c, 6),
                        strokes.get(c, 99), ord(c)),
    )[:2000]

    with open(kanji_file, "w") as f:
        for c in kanji_sorted:
            f.write(f"{c}\t{definition.get(c, '')}\n")

    # Save radical-stroke data from kRSUnicode. Characters with 0 residual
    # strokes are the radical itself; others are radical-derived variants
    # (often in Extension B, e.g. 𠂊 = 4.1).
    rs_file = CACHE_DIR / "rs_variants.txt"
    count = 0
    with open(rs_file, "w") as f:
        for ch, val in rs_unicode.items():
            # val can be e.g. "5.0" or "61.0 61.0" (multiple entries)
            for entry in val.split():
                entry = entry.rstrip("'")
                try:
                    rad_s, res_s = entry.split(".")
                    rad = int(rad_s)
                    residual = int(res_s)
                except ValueError:
                    continue
                defn = definition.get(ch, "")
                f.write(f"{ch}\t{rad}\t{residual}\t{defn}\n")
                count += 1
                break  # first entry is enough

    # Save all kDefinition entries so any character reached during
    # decomposition can have a gloss, not just the frequency-list chars.
    defn_file = CACHE_DIR / "definitions.txt"
    with open(defn_file, "w") as f:
        for ch, defn in definition.items():
            f.write(f"{ch}\t{defn}\n")

    print(f"Cached {len(hanzi_sorted)} hanzi, {len(kanji_sorted)} kanji, "
          f"{count} rs entries, {len(definition)} definitions.",
          file=sys.stderr)


def load_char_list(mode):
    """Return (list_of_chars, {char: gloss}, all_radicals, canonical) for the given mode.

    Radical glosses take priority over Unihan kDefinition so that
    components like 彳 show "60: step" instead of nothing.
    """
    ensure_unihan()
    radicals, canonical = load_radicals()

    # Load all Unihan kDefinition entries as the base layer
    glosses = {}
    defn_file = CACHE_DIR / "definitions.txt"
    if defn_file.exists():
        with open(defn_file) as f:
            for line in f:
                parts = line.strip().split("\t", 1)
                if len(parts) == 2 and parts[1]:
                    glosses[parts[0]] = parts[1]

    # Radical glosses override plain definitions
    for ch, label in radicals.items():
        if ch in glosses:
            glosses[ch] = f"{label} — {glosses[ch]}"
        else:
            glosses[ch] = label

    # Freq-file definitions override for non-radical chars (they're the same
    # data, but this keeps the merge order explicit)
    path = CACHE_DIR / ("hanzi_freq.txt" if mode == "hanzi" else "kanji_freq.txt")
    chars = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split("\t", 1)
            ch = parts[0]
            chars.append(ch)

    return chars, glosses, set(radicals), canonical


# --- IDS decomposition ---

def parse_ids(s):
    """Parse an IDS string into a nested list/str tree."""
    assert s
    c, s = s[0], s[1:]
    if c in BINARY_IDS:
        a, n = parse_ids(s)
        b, m = parse_ids(s[n:])
        return [c, a, b], n + m + 1
    if c in TRINARY_IDS:
        a, n = parse_ids(s)
        b, m = parse_ids(s[n:])
        d, k = parse_ids(s[n + m:])
        return [c, a, b, d], n + m + k + 1
    return c, 1


def load_ids(ids_path):
    """Load IDS decompositions from ids.txt into {char: parsed_tree}."""
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
            # prefer decomposition without placeholder chars
            decomp = decomps[0]
            for d in decomps:
                if not any(c in d for c in BAD_CHARS):
                    decomp = d
                    break
            decomp = re.sub(r"\[.*?]$", "", decomp)
            if len(decomp) <= 1:
                continue  # trivial / self-referencing
            try:
                parsed, _ = parse_ids(decomp)
                ids[char] = parsed
            except Exception:
                pass
    return ids


# --- Tree printing ---

def _leaves(node):
    """Yield the leaf characters of a parsed IDS node."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for child in node[1:]:
            yield from _leaves(child)


def _should_decompose(char, ids, all_radicals, canonical):
    """Return True if we should show this character's decomposition.

    If the character is a radical (canonical or variant), only decompose
    it when ALL its leaf components are canonical radicals.
    Non-radical characters are always decomposed.
    """
    if char not in ids:
        return False
    if char not in all_radicals:
        return True  # not a radical, always decompose
    decomp = ids[char]
    if not isinstance(decomp, list):
        return False
    children = list(_leaves(decomp))
    return all(c in canonical for c in children)


def print_tree(char, ids, glosses, all_radicals, canonical,
               prefix="", is_last=True, seen=None):
    """Recursively print a character's decomposition tree."""
    if seen is None:
        seen = set()

    connector = "└── " if is_last else "├── "
    extension = "    " if is_last else "│   "

    gloss = glosses.get(char, "")
    gloss_str = f"  ({gloss})" if gloss else ""
    print(f"{prefix}{connector}{char}{gloss_str}")

    if char in seen:
        return
    seen = seen | {char}

    if not _should_decompose(char, ids, all_radicals, canonical):
        return

    decomp = ids[char]
    if not isinstance(decomp, list):
        return

    children = list(_leaves(decomp))
    for i, child in enumerate(children):
        child_last = i == len(children) - 1
        print_tree(child, ids, glosses, all_radicals, canonical,
                   prefix + extension, child_last, seen)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="Random CJK character decomposition tree viewer")
    parser.add_argument("mode", choices=["hanzi", "kanji"],
                        help="character set to use")
    parser.add_argument("--ids", default=str(IDS_DEFAULT),
                        help="path to ids.txt")
    parser.add_argument("-c", "--char", default=None,
                        help="specific character instead of random")
    args = parser.parse_args()

    chars, glosses, all_radicals, canonical = load_char_list(args.mode)
    ids = load_ids(args.ids)

    char = args.char if args.char else random.choice(chars)

    gloss = glosses.get(char, "")
    gloss_str = f"  ({gloss})" if gloss else ""
    print(f"{char}{gloss_str}")

    if _should_decompose(char, ids, all_radicals, canonical):
        children = list(_leaves(ids[char]))
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            print_tree(child, ids, glosses, all_radicals, canonical,
                       "", is_last)
    elif char not in ids:
        print("  (no decomposition available)")


if __name__ == "__main__":
    main()
