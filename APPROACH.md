# Approach — Automated Tile Catalogue Extraction

## Summary

A tile catalogue is a design document, not a database: the same PDF holds product
tiles, room-scene photographs, logos and section banners with nothing tagging them
apart. This pipeline recovers, for every product tile, its printed name, its size
in millimetres, and a clean image of the tile face.

The method rests on one observation: **a catalogue's layout is regular, and that
regularity is machine-readable.** Every rule below keys off page structure — a
size header in the top band, grids of equal-sized images, a text row beneath a
tile — never off a page number or a product name. That is what makes it run on a
different catalogue without edits.

**Result on the supplied catalogue:** 88 PDF pages → 171 catalogue pages
(5 non-catalogue pages skipped) → **1046 tiles**, every one with a title, a size
and an image — 1031 decoded from embedded images and 15 plain-colour tiles the
catalogue draws as vector rectangles rather than images. Runtime one to four
minutes depending on the machine.

| Deliverable | Contents |
|---|---|
| `images/` | 1046 PNGs, named `<TITLE>_<Length>x<Width>.png` |
| `tiles.xlsx` | `Title \| Length (mm) \| Width (mm) \| Image Name`, one row per tile |

## Tools

Python 3.13 and four libraries. No GPU, no network, no external binaries, no paid
API — the whole pipeline runs offline on a bare machine.

| Tool | Version | Used for |
|---|---|---|
| PyMuPDF | 1.28.2 | page text with coordinates, image placement matrices, native XObject decoding |
| Pillow | 12.2.0 | crop, rotate, Lanczos resample, PNG encoding |
| NumPy | 2.3.0 | border detection on the bitmap as an array |
| openpyxl | 3.1.5 | the Excel deliverable |

PyMuPDF covers both halves of the problem — the text layer *and* the image objects
with their placement transforms — so there are no two coordinate systems to
reconcile.

**No machine learning is used.** Every decision is a geometric rule with a
threshold traceable to a measurement of the document, so each one can be
explained, unit-tested and retuned against a different catalogue. None of that is
true of a black-box detector.

## Workflow

The deliverables are produced by a Python project (`extract_tiles.py` plus seven
modules under `src/`, with a 134-test suite) — this repository. The command
below is what generated the outputs and what I will run live at the demo.

One command, no interaction:

```bash
pip install -r requirements.txt
python extract_tiles.py "Copy of Odisha Catalogue .pdf" -o output
```

```
PDF ─▶ page_parser ─▶ classifier ─▶ binder ─▶ image_extractor ─▶ cleaner ─▶ outputs
       split spread    tile vs      name +    native XObject     trim ▸      images/
       find header     room scene   size mm   decode, rotate     aspect ▸    tiles.xlsx
       skip non-pages  vs logo      bind      per placement      upscale     validate
```

1. **Pages.** Each printed spread is one PDF page holding two catalogue pages, so
   any page wider than tall is split at the midline; text and images join a half by
   centre point. A half is a catalogue page **if and only if it carries a tile-size
   header in its top 15%** — one structural rule that skips cover, index and back
   cover without naming a page number.
2. **Tiles.** Tiles are printed as grids of identically sized images; nothing else
   is. Room scenes are rejected on area (they cover 22–70% of a half against 7.3%
   for the largest genuine tile), logos on size. Survivors are grouped by printed
   size: a group of two or more is a grid; a lone image is accepted if its shape
   matches a header size, or *provisionally* if it matches any size the catalogue
   prints (the single square `-F` companion on a rectangular-tile page) — a
   provisional candidate is kept only when a printed name binds to it. Plain
   single-colour tiles (`PLAIN BLACK`, `WHITE MATT`…) are not images at all but
   vector rectangles; those enter the same funnel, always provisionally, and
   their bitmap is synthesised from the rectangle's fill colour. 272 candidates
   were rejected, each with a logged reason.
3. **Names and sizes.** A tile's name is the text line directly beneath it,
   left-aligned. Each row's images and labels are paired one-to-one, so one missing
   label does not shift the rest. Page furniture is filtered by a whole-line
   stop-list — never substring matching, which would eat names like `EL-09 (MATT)`.

## How each assignment requirement is met

| Requirement | How | Evidence |
|---|---|---|
| Extract the **highest-quality** image | Each tile is decoded from the embedded image object's own compressed bytes; the 15 vector-drawn plain tiles are synthesised losslessly from their fill colour | 1026 unique XObjects decoded |
| Prefer **embedded images over screenshots** | Pages are never rasterised; extraction is resolution-independent | no render path exists in the code |
| **Only the tile surface** — no borders, labels, shadows, frames, background | Tiles are taken as whole image objects, so labels and frames are never inside the crop; a guarded trimmer removes any flat background edge | verified on all 1046 |
| **Preserve the entire design**, no clipping | Every cleanup step is capped and flags rather than cutting deeper | 0 crops refused, 0 caps hit; 12 step/riser tiles centre-cropped ≤11% where the printed bitmap contradicts the printed size — see Key design decisions |
| **Correct aspect ratio**, not stretched or squashed | Fixed by centre-cropping the long axis only — never resampling to fit, never padding | all 1046 within 2% of their mm ratio |
| **Resolution ≥ dimensions in pixels** | Lanczos upscaling until pixels ≥ millimetres on both axes; never downscaled | all 1046 pass on both axes |
| **Avoid compression loss** | Lossless PNG, RGB, no JPEG round-trip | — |
| **Name exactly as shown** | Names are taken verbatim, including their inconsistencies | 0 tiles missing a name |
| **Dimensions in mm** | Read from the page header; derived from page scale where a tile contradicts it | 0 rows missing a size |
| **Consistent image naming** | `<TITLE>_<Length>x<Width>.png`, deterministic, numeric suffix on collision | 0 duplicates, 0 orphans |
| **Excel with the four columns** | Exactly `Title \| Length (mm) \| Width (mm) \| Image Name`, one row per tile | 1046 rows ↔ 1046 images |
| **Works on similar catalogues** | All logic is structural; no page numbers, names or paths hardcoded | thresholds are page ratios |

### On "suitable as a repeatable texture"

Delivered as a clean tile-only crop at the tile's exact aspect ratio and full
embedded resolution — the tile surface with every border, margin, shadow and label
removed, and nothing else. **No synthetic seam repair** (edge mirroring, offset
blending) is applied: a printed catalogue tile is already the repeating unit, and
inventing pixels to force a seam match would alter the product's appearance, which
the brief's "preserve the entire tile design" requirement rules out.

## Key design decisions

**Length is always the larger millimetre value.** Headers print sizes in both
orders (`600x1200mm` and `1200x600mm` both appear), so normalising makes the
column mean the same thing on every row. *Rejected:* preserving printed order,
which leaves the two columns incomparable across pages.

**Orientation comes from the placement matrix, never from stored pixels.** At
least one tile (GOLD-28, p4) is stored landscape 756×382 and placed upright by a
90° matrix; reading the stored bitmap would have saved it on its side.
*Rejected:* inferring orientation from stored width vs height.

**Touching equal-sized images coalesce into one product.** The catalogue prints
repeat swatches, bookmatch pairs and multi-panel murals as grids of abutting cells
sharing one printed name. Cells abut to within 0.2 pt whereas separately named
tiles are never closer than 11 pt, so abutment alone identifies a block. A block
keeps one row per *distinct face*: a 2×2 repeat swatch is one row; a bookmatch
pair is two rows under one name, flagged `shared-name` (14 rows).
*Rejected:* one row per cell (reports the same tile four times) or one row per
block (loses a bookmatch pair's second face).

**Tiles that contradict their header are measured, not guessed.** Wall-tile pages
print square companion tiles alongside 450×300 ones. Since every tile on a half is
reproduced at one scale, the tiles that *do* match their header calibrate a
points-per-millimetre figure, and the contradicting tile is measured against it and
snapped to the nearest size the catalogue actually prints anywhere. 117 tiles are
sized this way, each flagged. *Rejected:* assigning the header size anyway (wrong
data) or dropping the tile (lost product).

**A provisional candidate lives or dies by its printed name.** Two kinds of
genuine product would otherwise be lost: the *single* square `-F` companion on a
page of rectangular tiles (a lone image matching no header size), and plain
single-colour tiles drawn as vector rectangles instead of images. Both are
accepted provisionally — the `-F` singleton because its shape matches a size the
catalogue prints elsewhere, a vector rectangle never on shape alone — and kept
only if the binder finds a product name printed beneath. Unlike an embedded
product photograph, a bare rectangle or an unexplained one-off could be any
piece of page furniture; requiring a name is what lets the net widen without
letting decoration through. On this catalogue the rule adds 27 tiles — 15 named
vector tiles, 11 lone `-F` companions, and one further `-F` that is no longer
alone once its vector companion of the same size joins the page — and rejects
2 nameless survivors. *Rejected:* accepting singletons
or rectangles unconditionally (admits banners and backdrops) or keeping the old
strict rule (loses ~20 real products).

**Step and riser bitmaps are cropped to the printed size, and that is a real
trade-off.** On the two step/riser pages the embedded bitmaps are 5–12% wider
than the printed millimetre size allows (a 942×279 px bitmap labelled
900×300 mm). The two requirements — exact aspect ratio and zero clipping —
cannot both hold there, so the pipeline centre-crops the long axis (≤11%,
12 tiles, all on p87–88) rather than ship a distorted or mislabelled texture.
The cap (12%) still guards against runaway cropping, and every crop is recorded
in the run report. *Rejected:* padding (invents pixels), stretching (distorts
the design), or keeping the raw ratio (contradicts the stated dimensions).

**Cleanup leaves a sliver rather than clipping a tile.** A leftover border is
cosmetic; a clipped design misrepresents the product. Trim is capped at 6% per
edge, aspect crop refuses beyond 12% and flags instead, upscaling never downscales.

Two trimmer guards earn their place, both from measured failures. An
**interior-brightness test**: a flat near-white edge counts as background only if
it also differs from the middle of the picture — without it, every row of a PLAIN
WHITE tile reads as border and 14% of the product is eaten. An
**aspect-improvement test**: any trim moving the image *away* from the tile's true
proportions is discarded, the signature of cutting into the tile rather than off it.

On this catalogue the trimmer correctly fires zero times: the embedded bitmaps are
pre-cropped product shots carrying no page background, so there is nothing to
remove. The trimmer is retained and unit-tested against generated bitmaps with
known borders, for catalogues whose images do include them.

## Verification

The run does not report success on its own say-so. A validation pass re-checks the
finished artefacts and any failure exits non-zero: every row has a title and
positive dimensions, every row's image exists, every image meets the 1 px/mm floor
and sits within 2% of its millimetre aspect ratio, and no two rows share a
filename.

Alongside that, a run report records every decision — pages skipped, images
rejected and why, tiles per page, every flag raised, and text near tiles not used
as a name — so the run can be audited rather than trusted. A contact sheet renders
all 1046 tiles as thumbnails for a two-minute visual pass. Errors are isolated per
page and per image, so one unreadable page logs a flag instead of ending the run.

134 tests cover the pure logic on synthetic geometry, the cleaner on generated
bitmaps with known borders, vector-tile synthesis, and hand-verified expectations
for golden pages — including the rotated tile, the measured square companions,
the recovered lone `-F` companion, the vector-drawn plain-colour range, the
dual-size step and riser pages, the bookmatch pair and the three-panel mural.

## Assumptions

1. The PDF has a real text layer. There is no OCR fallback; a scanned catalogue
   would yield images with no names.
2. Product names are printed below their tile, left-aligned with it.
3. Every catalogue page declares its tile size in a header near the top.
4. Tiles are printed at one scale per page — what makes the page usable as a ruler.
5. Tile bitmaps are embedded as image XObjects — except plain single-colour
   tiles, which this catalogue draws as filled vector rectangles and the
   pipeline synthesises from the fill colour. A patterned tile drawn purely as
   vector art (rather than flat colour) would still be missed.
6. Sizes are printed in millimetres. This catalogue's inch text is mojibake in the
   PDF and is never parsed.
7. Non-catalogue pages are excluded deliberately and logged by name. Nothing the
   pipeline cannot bind confidently is guessed — it is flagged and surfaced.

## Limitations

- **Constants are calibrated, not universal.** Thresholds are ratios of the page
  rather than absolute measurements, so a similar catalogue at another trim size
  should work — but a genuinely different layout grammar (several tile scales on
  one page, labels beside images) would need retuning. The label stop-list is
  likewise seeded with this catalogue's page furniture; unknown furniture in a
  new catalogue would surface in the report's unbound-text section rather than
  corrupt names silently. The report makes both visible quickly.
- **`shared-name` rows are intentional duplicates.** A bookmatch pair is two rows,
  same title, different images. Consumers wanting a product list should collapse
  on title; consumers wanting a face list should not. Separately, the catalogue
  itself prints some products on two different pages (POLO WOOD-L appears on
  PDF pages 45 and 48); each printing is one row, so those titles repeat with a
  numbered image suffix (`_2`). One row per printed tile keeps the sheet a
  faithful index of the catalogue; deduplicating would be a one-line
  post-processing step for consumers who want one row per product.
- **Names are taken as printed**, including inconsistencies — `RS-1060 -S` keeps
  its stray space. No spelling correction is attempted.
- **`size-measured` sizes are derived, not read.** Correct to within the 8% snap
  tolerance and matched to sizes the catalogue prints, but never printed beside
  those tiles.
- **The 1 px/mm floor is met by upscaling** where the embedded bitmap is smaller
  (1034 tiles, median factor 1.32). Upscaling guarantees the stated resolution, not
  new detail — the embedded image is the maximum quality the PDF contains.
- **125 text lines near tiles remain unbound** — finish and series descriptors such
  as `Double Charge`, `PORCELAIN` and letter-spaced section banners. Each was
  checked against its page after the provisional-recovery rule landed; none names
  a product the pipeline missed. They are listed in the report rather than
  silently dropped so that claim stays checkable on a new catalogue.
