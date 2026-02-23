## CJK Decomposition

Vibecoded with Claude Opus 4.6.

### Data sources

- **IDS decomposition data** — [CJKVI IDS Database](https://github.com/cjkvi/cjkvi-ids), based on the [CHISE IDS Database](http://www.chise.org/ids/). Provides Ideographic Description Sequences mapping CJK characters to their structural components.

- **Character readings, frequency, stroke counts, and English definitions** — [Unicode Han Database (Unihan)](https://www.unicode.org/charts/unihan.html), downloaded from [unicode.org](https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip). Fields used: `kMandarin`, `kJapaneseOn`, `kJapaneseKun`, `kFrequency`, `kTotalStrokes`, `kJoyoKanji`, `kDefinition`.

- **Kangxi radical mappings** — [CJKRadicals.txt](https://www.unicode.org/Public/UCD/latest/ucd/CJKRadicals.txt) from the Unicode Character Database, combined with `unicodedata` module names from the Kangxi Radicals block (U+2F00–U+2FD5) and CJK Radicals Supplement block (U+2E80–U+2EFF).

- **Jōyō kanji list with grades and JLPT levels** — [joyo-kanji-compilation](https://github.com/NHV33/joyo-kanji-compilation) by NHV33 (GitHub). Provides the full 2136-kanji Jōyō table with elementary school grades (1–6), secondary grade (S), and JLPT levels (N1–N5). Used for both the Jōyō grade and JLPT random sets.

- **JLPT kanji lists** — [Jonathan Waller's JLPT resources](http://www.tanos.co.uk/jlpt/) (tanos.co.uk). Community-compiled kanji lists for JLPT N1–N5, widely used as the de facto reference for the post-2010 five-level system.

- **HSK vocabulary lists (2012 standard, levels 1–6)** — [glxxyz/hskhsk.com](https://github.com/glxxyz/hskhsk.com), `HSK Official 2012 L1.txt`–`L6.txt`. Based on the Hanban 2012 publication. CJK characters are extracted from each level's word list to form the per-level character sets (cumulative: L2 includes all L1 characters, etc.).

- **New HSK hanzi lists (2021 standard, levels 1–9)** — [krmanik/HSK-3.0](https://github.com/krmanik/HSK-3.0), `New HSK (2021)/HSK Hanzi/` files. Pre-extracted character lists, 300 characters per level for levels 1–6, and 1200 characters for the combined levels 7–9 block (the official standard groups 7–9 together; nhsk_7/8/9 therefore share the same cumulative set).

- **TOCFL vocabulary list** — [ivankra/tocfl](https://github.com/ivankra/tocfl), `tocfl-202307.csv` (July 2023). Vocabulary for Taiwan's Test of Chinese as a Foreign Language, in Traditional Chinese. Level mapping: L0 = Novice (excluded); L1+L2 = Band A; L1–L4 = Band B (cumulative); L1–L5 = Band C (cumulative). CJK characters are extracted from each entry's Traditional form.
