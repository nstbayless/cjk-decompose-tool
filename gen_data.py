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
IDS_DEFAULT = SCRIPT_DIR / ".cache" / "babelstone_ids.txt"

BAD_CHARS = set("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑲")

# Glyph-source priority per language setting. BabelStone tags each IDS
# alternative with the regions it applies to ($(GHTJKPV...)); when a character
# has different decompositions per region, pick by these priorities.
# Letters: G=China H=HongKong T=Taiwan J=Japan K=Korea P=NorthKorea V=Vietnam.
SOURCE_PRIORITY = {
    "j":    "JTG",
    "simp": "GHT",
    "trad": "THJKG",
}


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


def load_rs(path):
    """Load kRSUnicode radical-stroke data: char -> (radical_num, residual).

    From cj.py's rs_variants.txt (char \\t radical \\t residual \\t defn). This
    is Unihan's authoritative sort-radical assignment: `residual == 0` means the
    character IS a radical form (氵 = 85.0), otherwise it's filed under that
    radical (河 = 85.5, "river" under radical 85 水).
    """
    rs = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                try:
                    rs[parts[0]] = (int(parts[1]), int(parts[2]))
                except ValueError:
                    continue
    return rs


def _clean_ids(raw):
    """Strip BabelStone/cjkvi-ids annotations from a raw IDS field.

    The leading 〾 (Ideographic Variation Indicator) is dropped — the rest is
    a valid IDS. The ㇯ subtraction operator is deliberately NOT stripped:
    it makes the field an "A minus B" expression the component tree cannot
    represent, and _pick_decomp filters such fields out entirely.
    """
    raw = re.sub(r"\^\s*", "", raw)
    raw = re.sub(r"[$][(][^)]*[)]\s*$", "", raw)
    raw = raw.lstrip("〾")
    raw = re.sub(r"\[.*?]$", "", raw)
    return raw


def load_pua_tokens(ids_path):
    """Parse the {NN} token table from the BabelStone IDS header.

    Header lines look like:
      #\t{45}\tleft of 北 [G source glyph] (F5FB )\t？
    where the parenthesized field gives the codepoint of the component's
    glyph in the BabelStone Han PUA font, the text before it is a human
    description, and the final field is the component's own IDS (？ = unknown
    form; many entries carry one, e.g. {88} "top of 合" = ⿵𠆢一).

    Returns {token: (pua_char, description, ids_or_None)}.
    """
    tokens = {}
    with open(ids_path, encoding="utf-8-sig") as f:
        for line in f:
            if line.startswith("U"):
                break  # token table lives entirely in the header
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or parts[0] != "#":
                continue
            m = re.match(r"^\{(\d+)\}$", parts[1])
            if not m:
                continue
            cp = re.search(r"\(([0-9A-F]{4,5}) ", parts[2])
            if not cp:
                continue
            desc = re.sub(r"\s*\[[^\]]*\]", "", parts[2][:cp.start()]).strip()
            decomp = _clean_ids(parts[3]) if len(parts) > 3 else ""
            if len(decomp) <= 1 or "？" in decomp or "㇯" in decomp:
                decomp = None
            tokens[m.group(1)] = (chr(int(cp.group(1), 16)), desc, decomp)
    return tokens


def load_pua_map(ids_path):
    """{NN} token -> PUA char (see load_pua_tokens)."""
    return {num: pua for num, (pua, _, _) in load_pua_tokens(ids_path).items()}


def _parse_sources(raw):
    """Extract the source-region letter set from a raw IDS field's $(...) tag.

    Tags mix region letters with annotations: 'G[B]' carries a bracketed
    standard reference, 'UCS2003' is a pseudo-source. Returns a set of
    single letters (empty if the field is untagged).
    """
    m = re.search(r"[$][(]([^)]*)[)]\s*$", raw)
    if not m:
        return set()
    tag = m.group(1).replace("UCS2003", "")
    tag = re.sub(r"\[[^\]]*\]", "", tag)
    return set(re.findall(r"[A-Z]", tag))


def _pick_decomp(alts, priority, char):
    """Pick the best (decomp, sources) alternative for one source priority.

    Rank by the best-matching priority letter (unlisted sources and untagged
    fields rank after all listed letters); among equal ranks prefer fully
    encoded alternatives (no {NN} tokens / numbered components), then the
    first listed.

    Fields the component tree cannot represent are skipped: unknown-form ？
    entries and ㇯ subtractions ("A minus B"). A character with no usable
    field is left undecomposed rather than shown with a wrong breakdown.
    """
    best = None
    best_key = None
    for idx, (d, srcs) in enumerate(alts):
        if len(d) <= 1 or d == char or "？" in d or "㇯" in d:
            continue
        rank = min((priority.index(s) for s in srcs if s in priority),
                   default=len(priority))
        messy = 1 if ("{" in d or any(c in d for c in BAD_CHARS)) else 0
        key = (rank, messy, idx)
        if best_key is None or key < best_key:
            best, best_key = d, key
    return best


def load_ids(ids_path):
    """Load IDS decomposition strings, selected per language setting.

    Returns {"j": {...}, "simp": {...}, "trad": {...}}: for each language,
    the decomposition whose source tag best matches SOURCE_PRIORITY.
    {NN} tokens (unencoded components) are replaced with their glyph in the
    BabelStone Han PUA font (see fonts/decomp-bsh-pua.woff2).
    """
    pua = load_pua_map(ids_path)
    ids = {lang: {} for lang in SOURCE_PRIORITY}
    with open(ids_path, encoding="utf-8-sig") as f:
        for line in f:
            if not line.startswith("U"):
                continue
            line = line.strip()
            m = re.match(r"^U\+\w+\s+(\S)\s+(.+)$", line)
            if not m:
                continue
            char = m.group(1)
            alts = [(_clean_ids(f), _parse_sources(f))
                    for f in m.group(2).split("\t")
                    if not f.startswith("*")]  # '*...' fields are comments
            for lang, priority in SOURCE_PRIORITY.items():
                decomp = _pick_decomp(alts, priority, char)
                if decomp is None:
                    continue
                decomp = re.sub(r"\{([0-9]+)\}",
                                lambda m: pua.get(m.group(1), "〇"), decomp)
                ids[lang][char] = decomp

    # The tokens themselves are components with known decompositions ({88}
    # "top of 合" = ⿵𠆢一): give each PUA char its IDS so trees can expand
    # through unencoded components (and the sort-radical search can look
    # inside them).
    for pua_char, _desc, decomp in load_pua_tokens(ids_path).values():
        if not decomp:
            continue
        decomp = re.sub(r"\{([0-9]+)\}",
                        lambda m: pua.get(m.group(1), "〇"), decomp)
        for lang in ids:
            ids[lang].setdefault(pua_char, decomp)
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
              CACHE_DIR / "definitions.txt", CACHE_DIR / "readings.txt",
              CACHE_DIR / "rs_variants.txt"]:
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
    ids_by_lang = load_ids(ids_path)
    # Base = Japanese (the site's default language); other languages ship as
    # sparse override dicts holding only the entries that differ.
    ids = ids_by_lang["j"]
    ids_simp = {ch: d for ch, d in ids_by_lang["simp"].items()
                if ids.get(ch) != d}
    ids_trad = {ch: d for ch, d in ids_by_lang["trad"].items()
                if ids.get(ch) != d}

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

    # Unencoded {NN} components: use the BabelStone header description as
    # the gloss ("top of 合") so PUA boxes aren't unlabeled.
    for pua_char, desc, _decomp in load_pua_tokens(ids_path).values():
        if desc:
            glosses.setdefault(pua_char, desc)

    readings_zh = {}
    readings_ja = {}
    with open(CACHE_DIR / "readings.txt") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            ch, py, ja = parts
            if py:
                readings_zh[ch] = py
            if ja:
                readings_ja[ch] = ja

    jlpt, joyo = load_joyo_levels(DICTS_DIR / "joyo.csv")
    hsk_old = load_hsk_old(DICTS_DIR)
    nhsk = load_nhsk(DICTS_DIR)
    tocfl = load_tocfl(DICTS_DIR)

    # Restrict readings to characters that can actually be displayed: the
    # decomposition graph plus the frequency and level lists.
    displayable = set(hanzi) | set(kanji) | set(ids)
    for decomp in ids.values():
        displayable.update(c for c in decomp if ord(c) > 0x2FFF)
    for lists in (jlpt, joyo, hsk_old, nhsk, tocfl):
        for lst in lists.values():
            displayable.update(lst)
    readings_zh = {ch: v for ch, v in readings_zh.items() if ch in displayable}
    readings_ja = {ch: v for ch, v in readings_ja.items() if ch in displayable}

    # kRSUnicode radical-stroke data, used by the site to flag which component
    # is the sort-radical. Cover every char that can appear in a tree: the
    # displayable set plus components from all three language decompositions
    # (simp/trad overrides may introduce forms the base 'ids' lacks).
    rs_all = load_rs(CACHE_DIR / "rs_variants.txt")
    # CJK-stroke glyphs that ARE single-stroke Kangxi radical forms. The CJK
    # Strokes block has no kRSUnicode (Unihan covers unified ideographs
    # only), so decompositions like 乏 = ⿱㇒之 could never match radical 4 丿.
    for ch, rs_val in {"㇐": (1, 0), "㇑": (2, 0), "㇔": (3, 0),
                       "㇒": (4, 0), "㇚": (6, 0)}.items():
        rs_all.setdefault(ch, rs_val)
    # Any char the radicals table labels "NN: ..." is a form of radical NN;
    # backfill rs entries (residual 0) for forms Unihan doesn't cover — the
    # Radicals Supplement and Kangxi blocks aren't unified ideographs and so
    # have no kRSUnicode (⺀ = 15, the bottom form of 冫 in 冬/寒).
    for ch, label in radicals.items():
        m = re.match(r"^(\d+):", label)
        if m:
            rs_all.setdefault(ch, (int(m.group(1)), 0))
    rs_chars = set(displayable)
    for dct in (ids, ids_simp, ids_trad):
        for decomp in dct.values():
            # Skip only the IDC operators (⿰⿱… U+2FF0-2FFF) — the Radicals
            # Supplement block (U+2E80-2EFF, e.g. ⺀ in 冬) is a component.
            rs_chars.update(c for c in decomp
                            if not (0x2FF0 <= ord(c) <= 0x2FFF))
    rs = {ch: f"{rad}.{res}" for ch, (rad, res) in rs_all.items()
          if ch in rs_chars}

    data = {
        "hanzi": hanzi,
        "kanji": kanji,
        "glosses": glosses,
        "ids": ids,
        "ids_simp": ids_simp,
        "ids_trad": ids_trad,
        "readingsZh": readings_zh,
        "readingsJa": readings_ja,
        "allRadicals": list(radicals.keys()),
        "canonical": list(canonical),
        # kRSUnicode "radical.residual" per char; residual 0 = a radical form.
        "rs": rs,
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
          f"{len(ids)} IDS entries "
          f"(+{len(ids_simp)} simp / +{len(ids_trad)} trad overrides), "
          f"{len(glosses)} glosses, "
          f"{len(readings_zh)} zh / {len(readings_ja)} ja readings, "
          f"{len(rs)} rs entries)")
    print(f"  JLPT: N5={len(jlpt['n5'])} N4={len(jlpt['n4'])} "
          f"N3={len(jlpt['n3'])} N2={len(jlpt['n2'])} N1={len(jlpt['n1'])}")
    print(f"  Joyo: 1={len(joyo['1'])} 2={len(joyo['2'])} 3={len(joyo['3'])} "
          f"4={len(joyo['4'])} 5={len(joyo['5'])} 6={len(joyo['6'])} S={len(joyo['s'])}")
    print(f"  HSK (old): " + " ".join(f"L{i+1}={len(hsk_old[f'hsk_{i+1}'])}" for i in range(6)))
    print(f"  New HSK:   " + " ".join(f"L{i+1}={len(nhsk[f'nhsk_{i+1}'])}" for i in range(9)))
    print(f"  TOCFL: A={len(tocfl['tocfl_a'])} B={len(tocfl['tocfl_b'])} C={len(tocfl['tocfl_c'])}")


if __name__ == "__main__":
    main()
