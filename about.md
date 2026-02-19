## CJK Decomposition

Vibecoded with Claude Opus 4.6.

### Data sources

- **IDS decomposition data** — [CJKVI IDS Database](https://github.com/cjkvi/cjkvi-ids), based on the [CHISE IDS Database](http://www.chise.org/ids/). Provides Ideographic Description Sequences mapping CJK characters to their structural components.

- **Character readings, frequency, stroke counts, and English definitions** — [Unicode Han Database (Unihan)](https://www.unicode.org/charts/unihan.html), downloaded from [unicode.org](https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip). Fields used: `kMandarin`, `kJapaneseOn`, `kJapaneseKun`, `kFrequency`, `kTotalStrokes`, `kJoyoKanji`, `kDefinition`.

- **Kangxi radical mappings** — [CJKRadicals.txt](https://www.unicode.org/Public/UCD/latest/ucd/CJKRadicals.txt) from the Unicode Character Database, combined with `unicodedata` module names from the Kangxi Radicals block (U+2F00–U+2FD5) and CJK Radicals Supplement block (U+2E80–U+2EFF).
