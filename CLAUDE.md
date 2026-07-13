# CJK Decompose Tool

Static site (plus `cj.py` CLI) that decomposes CJK characters into component
trees using BabelStone IDS data.

## Build pipeline

1. `python3 cj.py hanzi` — downloads and caches upstream data into `.cache/`
   (BabelStone IDS.TXT, Unihan, radicals, frequency lists).
2. `python3 gen_data.py` — builds `data.json` for the site from the cache +
   `dicts/`.
3. `index.html` is fully static; serve the repo root (`python3 -m http.server`)
   and open it. `?d=北` auto-decomposes a character (handy for testing).
   `about.html` renders `about.md` at runtime — no build step.

## Per-language decomposition selection

BabelStone tags each IDS alternative with the source regions it applies to
(`$(GHTJKPV)`; G=China, H=Hong Kong, T=Taiwan, J=Japan, K=Korea, P=North
Korea, V=Vietnam). `gen_data.py` picks one decomposition per language setting
using `SOURCE_PRIORITY` (j: J→T→G; simp: G→H→T; trad: T→H→J→K→G; among equal
ranks, fully-encoded alternatives beat ones with {NN} tokens). `data.json`
stores the Japanese pick as `ids`, with sparse `ids_simp`/`ids_trad` override
dicts holding only entries that differ; the JS helper `idsOf()` in
`index.html` resolves lookups against the current language setting.

## Unencoded IDS components ({NN} tokens / PUA glyphs)

BabelStone IDS writes components Unicode hasn't encoded as `{NN}` tokens
(e.g. 北 = `⿰{45}匕`). The IDS.TXT header maps each token to a Private Use
Area codepoint in the BabelStone Han PUA font. `gen_data.py`'s
`load_pua_tokens()` parses that table (codepoint + description + the token's
own IDS; `cj.py` keeps a minimal `load_pua_map()` duplicate), and
decompositions get the PUA character substituted in;
`fonts/decomp-bsh-pua.woff2` (a subset of BabelStone Han PUA, `unicode-range:
U+E080-F8DF`, listed first in the font stacks) renders them in the browser.
PUA components are first-class in `data.json`: the header description becomes
their gloss ("top of 合") and the header IDS their `ids` entry, so they are
expandable in the tree and the sort-radical search can see inside them.

- Full regeneration recipe for the font subsets: see `fonts/README.md`.
- **Keep IDS.TXT and the PUA font in version lockstep** — BabelStone deletes
  PUA glyphs once characters get officially encoded, so refreshing one
  without the other breaks rendering.
- Terminal output of `cj.py` shows these components blank/tofu (most terminal
  fonts lack PUA glyphs) — known limitation, web app unaffected.

## Sort-radical marking

Each component box in the tree can carry a clover glyph (an abstract
monochrome quatrefoil SVG) marking it as the parent character's
**sort-radical** (the Kangxi radical a dictionary files it under). The source
is Unihan's `kRSUnicode` (`radical.residual_strokes`): `cj.py` caches it to
`.cache/rs_variants.txt` (radical numbers may carry primes marking simplified
forms — `绞 = 120'.6` — which are stripped; dropping them instead silently
loses every simplified char), `gen_data.py` emits a `"rs"` map in `data.json`
(`char → "num.res"`, restricted to chars reachable in a tree, plus curated
entries for the CJK-stroke glyphs that ARE single-stroke radicals: ㇐=1 ㇑=2
㇔=3 ㇒=4 ㇚=6, since the CJK Strokes block has no `kRSUnicode`), and
`index.html`'s `sortRadicalIndex()` marks, among a parent's direct components,
the one whose `rs` radical number matches the parent's with `res == 0` (i.e.
the component that *is* that radical form: 河 rad 85 → 氵 = `85.0`). If the
radical is buried below the top row (including inside PUA components, whose
`ids` come from the token table), `subtreeHasRadical()` marks the direct
component whose subtree contains it instead. ~92% of the top-10k hanzi
resolve; the rest get no clover — the intended "can't localize" behavior.
`radicalInfo()` also falls back to `rs` residual-0 so radical *forms* with no
gloss of their own (𠆢 = `9.0`) still get a watermark number and the radical's
name instead of "meaningless component". Radicals-Supplement glyphs are
matched to Kangxi numbers by name with enumerators/"simplified" prefixes
stripped ("knife two" → 18), plus a curated `SUPPLEMENT_KANGXI` map in
`cj.py` for the ~12 whose Unicode names are unrelated to their radical
(⺀ "CJK RADICAL REPEAT" is by usage the bottom form of 冫 ice → 15; the
label shows the Kangxi name, not the Unicode one). Every numbered radical
label is backfilled into `rs` as `num.0`, so supplement forms participate
in clover matching (冬 = ⿱夂⺀ → ⺀).

## Data/font caveats

- `data.json` is generated — don't hand-edit; rerun `gen_data.py`.
- The bundled fonts in `fonts/` are subsets; if a character renders as tofu,
  the subset likely needs regenerating with wider coverage (`fonts/README.md`).
- Unihan `kDefinition` glosses can be terse to the point of looking like bugs
  (叚 → "false" is a genuine definition, not a boolean leak).
