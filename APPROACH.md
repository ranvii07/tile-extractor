# Approach

## The problem

A tile catalogue is a design document, not a database. The same PDF contains
product tiles, room-scene photographs, logos, decorative rules and section
banners, with no tagging to tell them apart. The task is to recover, for every
product tile: its printed name, its size in millimetres, and a clean image of the
tile itself.

The whole method rests on one observation: **a tile catalogue's layout is
regular, and that regularity is machine-readable.** Every rule below is derived
from page structure, never from a page number or a product name.

## Reproducing the result

```bash
pip install -r requirements.txt
python extract_tiles.py "Copy of Odisha Catalogue .pdf" -o output
python -m pytest tests -q
```

Reference run: 88 PDF pages → 171 catalogue pages (5 skipped) → **1019 tiles**,
0 rows missing a title or a size, all validation checks passing, 126 tests green.

## Method

### 1. Pages

A printed spread is one PDF page holding two catalogue pages side by side, so
each page wider than it is tall is split at the vertical midline; text and images
are assigned to a half by their centre point.

A half is a real catalogue page **if and only if it carries a tile-size header in
its top 15%**. That single structural rule skips the cover, the index and the
back cover without naming a single page number — and it is why the code is not
tied to this catalogue. Measured: real headers sit at 5–9% of page height, while
the index's first size line is at 21.7%.

Sizes are read with one regex over `<n>x<n>mm`, guarded by a plausibility range
(50–3000 mm) so a stray number can never become a tile size.

### 2. Tiles

Tiles are printed as grids of identically sized images; nothing else on the page
is. Classification is therefore pure geometry — the module takes rectangles, not
a PDF, which is what makes it unit-testable.

Two passes:

- **Hard filters.** Room scenes cover 22–70% of a half while the largest genuine
  tile covers 7.3%, so 18% separates them with room to spare. Logos are
  104×24 pt against a 67 pt shortest genuine tile side.
- **Repetition.** Survivors are grouped by printed size. A group of two or more
  is a grid and is accepted. A lone image is accepted only if its shape matches a
  header size (a featured hero tile); otherwise it is an unexplained one-off and
  is rejected with a reason.

On the reference catalogue this rejects 130 images — 116 room scenes and 14
unexplained singletons — every one recorded in the report.

### 3. Names and sizes

Names sit in a text row 4.6–5.1 pt below their image row, left-aligned with the
image. Binding buckets images into rows, then pairs each row's images with the
labels beneath it one-to-one, nearest-alignment first — so a row with one missing
label still binds the rest correctly.

Page furniture is removed first by a stop-list matched against the **whole line**,
never as a substring (substring matching would eat `EL-09 (MATT)`). Bare numbers
are treated as folios only in the bottom 6% of the page, because plenty of
genuine product names in this catalogue are bare numbers (`5335`, `10122`).

Sizes come from the half's header. Where a half declares two sizes — the step and
riser pages — each tile takes the header whose shape best matches its own.

## Key decisions

Six calls shaped the output. Each is listed with the alternative rejected.

### Length is always the larger millimetre value

Headers print sizes in both orders (`600x1200mm` and `1200x600mm` both appear).
Normalising `Length = max, Width = min` makes the column mean the same thing on
every row. **Rejected:** preserving the printed order, which would have made the
two columns incomparable across pages.

### Orientation comes from the placement matrix, never from stored pixels

At least one tile in this catalogue (GOLD-28, p4) is stored landscape 756×382 and
placed upright by a 90° matrix. Reading orientation from the stored bitmap would
have saved it on its side. The placement matrix's first column is where the
image's x-axis points in page space, which is exactly the clockwise rotation
applied when placing it — so the same rotation reproduces the printed tile.
**Rejected:** inferring orientation from stored width vs height.

### Touching equal-sized images coalesce into one product

The catalogue prints several products as a grid of abutting cells sharing a
single printed name: a 2×2 repeat swatch of one image, a bookmatch pair of two
mirrored faces (`BM-9018`), a stacked three-panel mural (`3416-HL-1-P1-P2-P3`).
Cells of such a grid abut to within 0.2 pt whereas two separately named tiles are
never closer than 11 pt, so **abutment alone identifies a block.**

A block keeps one entry per *distinct* face: a repeat swatch is one tile shown
four times (one row), a bookmatch pair is two faces under one name (two rows,
both flagged `shared-name`). **Rejected:** one row per cell, which would have
reported the same tile four times; and one row per block, which would have lost a
bookmatch pair's second face.

This also fixes classification: a 2×2 swatch covers 23% of a half and would trip
the room-scene filter, so area is judged on one cell, not the whole grid.

### Tiles that contradict their header get measured, not guessed

Wall-tile pages print 450×300 tiles alongside a square companion tile (`915-F`).
The square's shape contradicts the page header by 33%, far outside the 20%
tolerance that genuine tiles land inside.

Rather than guess, the page is used as a ruler. Every tile on a half is
reproduced at one scale, so the tiles that *do* match their header calibrate a
points-per-millimetre figure (a median, so one outlier cannot skew it). The
contradicting tile is measured against that scale and **snapped to the nearest
size the catalogue actually prints anywhere** — a vocabulary collected from every
header in the document. A measurement of 301×300 becomes the listed 300×300.

103 tiles are sized this way, each flagged `size-measured`. If no catalogue size
fits within 8%, the measurement is rounded to 10 mm and flagged
`size-measured-unlisted` instead — visible, not silent. **Rejected:** assigning
the header size anyway (wrong data), or dropping the tile (lost product).

### Bitmaps are extracted natively, never rasterised

Every tile comes from the embedded image object's own compressed bytes, decoded
once and cached by xref. That is the highest quality the document contains and it
is resolution-independent. Soft-masked images are composited onto white because
the catalogue prints on white stock. **Rejected:** rendering pages at a chosen
DPI, which caps quality at the DPI guess and resamples every tile twice.

### Cleanup is biased towards leaving a sliver rather than clipping a tile

A leftover border is a cosmetic flaw; a clipped tile design misrepresents the
product. So each cleanup step stops early and flags rather than cutting deeper:

- **Trim** flat near-white/near-black edges, capped at 6% per edge.
- **Enforce aspect** by centre-cropping the long axis — never stretching, never
  padding — and refuse any crop beyond 12%, flagging `aspect-crop-refused`.
- **Meet resolution** by Lanczos upscaling until pixels ≥ millimetres on both
  axes. Never downscale.

Two guards on the trimmer earn their place, both from measured failures:

- An **interior-brightness test**: a flat near-white edge is only background if it
  also differs from the middle of the picture. Without it, every row of a PLAIN
  WHITE or SUPER WHITE tile reads as border and 14% of the product is eaten.
- An **aspect-improvement test**: the vertical and horizontal trims are evaluated
  as four candidates (none / vertical / horizontal / both) and any trim that
  moves the image *away* from the tile's true proportions is discarded — that is
  the signature of having cut into the tile rather than off it.

On the reference catalogue the trimmer now fires zero times, which is the correct
answer: the embedded bitmaps carry no page background, and every trim before
these guards existed was a false positive.

## Verification

The run does not report success on its own say-so. `validate()` re-checks the
finished artefacts and any failure makes the process exit non-zero:

- every row has a title and positive dimensions;
- every row's image file exists;
- every image meets the 1 px/mm floor and sits within 2% of its millimetre
  aspect ratio;
- no two rows share an image filename.

Alongside that, `report.txt` records every decision — pages skipped, images
rejected and why, tiles per page, every flag raised, and text near tiles that was
not used as a name — so the run can be audited rather than trusted.
`contact_sheet.html` shows all 1019 tiles as thumbnails for a two-minute visual
pass.

The test suite is 126 tests. Stages 1–3 are tested on synthetic geometry with no
PDF involved; the cleaner is tested on generated bitmaps with known borders; and
`tests/test_golden_pages.py` asserts hand-verified expectations against the real
catalogue — p3 (the simple case), p4 (the rotated tile), p51 (measured square
companions), p87/p88 (dual-size step and riser pages), plus the bookmatch pair
and the three-panel mural.

## Assumptions

1. **"Suitable as a repeatable texture" is read as: a clean, tile-only crop at the
   tile's exact aspect ratio and full embedded resolution** — the tile surface with
   every border, margin, shadow and label removed, and nothing else. No synthetic
   seamless tiling (edge mirroring, offset blending, frequency-domain seam repair)
   is applied. A printed catalogue tile is already a repeating unit; inventing
   pixels to force a seam match would alter the product's appearance, which the
   brief's "preserve the entire tile design" requirement rules out.
2. The PDF has a real text layer. There is no OCR fallback; a scanned catalogue
   would yield images with no names.
3. Product names are printed below their tile, left-aligned with it. A catalogue
   labelling tiles above or beside them would need a different binding rule.
4. Every catalogue page declares its tile size in a header near the top.
5. Tiles are printed at one scale per page — this is what makes the page usable
   as a ruler for measuring contradicting tiles.
6. Tile bitmaps are embedded as image XObjects, not drawn as vectors.
7. Sizes are printed in millimetres. The inch half of this catalogue's header is
   mojibake in the PDF and is never parsed.
8. Non-catalogue pages are excluded deliberately, not accidentally: a half with no
   size header is skipped **and logged by name** in the report. Nothing the
   pipeline cannot bind confidently is ever guessed — it is flagged and surfaced.

## Limitations

- **Constants are calibrated, not universal.** Every threshold is expressed as a
  ratio of the page rather than an absolute measurement, so a similar catalogue
  at another trim size should work — but a catalogue with a genuinely different
  layout grammar (tiles at several scales on one page, labels beside images)
  would need recalibration. The report is designed to make that visible quickly.
- **`shared-name` rows are intentional duplicates.** A bookmatch pair produces two
  rows with the same title and different images. Anyone consuming the sheet as a
  product list should collapse on title; anyone consuming it as a face list
  should not.
- **Names are taken as printed**, including their inconsistencies — `RS-1060 -S`
  keeps its stray space because that is what the catalogue prints. No spelling
  correction is attempted.
- **`size-measured` sizes are derived, not read.** They are correct to within the
  8% snap tolerance and matched against sizes the catalogue prints, but they were
  never printed next to those tiles.
- **The 1 px/mm floor is met by upscaling** where the embedded bitmap is smaller
  (median factor 1.32). Upscaling adds no detail; it guarantees the stated
  resolution, not new information.
- **152 text lines near tiles remain unbound** — finish and series descriptors
  like `Double Charge`, `Carvin Matt`, `PORCELAIN`. All are page furniture and
  none is a product name, but they are listed in the report rather than silently
  dropped, so the assumption stays checkable.
