# Tile Catalogue Extractor

Turns a tile-catalogue PDF into a folder of clean tile images plus an Excel sheet
listing every tile's name and millimetre dimensions.

## Install

```bash
pip install -r requirements.txt
```

## Run

One command, one argument:

```bash
python extract_tiles.py "Copy of Odisha Catalogue .pdf" -o output
```

On the reference catalogue (88 PDF pages / 171 catalogue pages) this produces
**1046 tiles** in one to four minutes (machine-dependent) and exits `0` with
`VALIDATION : all checks passed`.

## What you get

| Path | What it is |
|---|---|
| `output/images/` | one PNG per tile, named `<TITLE>_<L>x<W>.png` |
| `output/tiles.xlsx` | the deliverable: `Title`, `Length (mm)`, `Width (mm)`, `Image Name` |
| `output/contact_sheet.html` | every tile as a thumbnail with its name, size and flags — open it to eyeball a whole run in two minutes |
| `output/report.txt` | what the run decided: validation results, skipped pages, flags, tiles per page, rejected images, unused text |

Nothing is hardcoded to a particular catalogue. Pages are found by structure (a
size header in the top band), tiles by geometry (grids of equal-sized images),
and names by position (the text row beneath a tile).

## Options

| Flag | Effect |
|---|---|
| `-o, --output DIR` | output directory (default `output`) |
| `--debug` | also write the raw pre-cleanup bitmaps and per-page geometry to `output/debug/` |
| `--limit-pages N` | process only the first N PDF pages, for a fast iteration loop |

## Tests

```bash
python -m pytest tests -q
```

134 tests. Most run on synthetic geometry and need no PDF. The golden-page tests
in `tests/test_golden_pages.py` check hand-verified pages of the reference
catalogue and skip themselves if it is not present — point `TILE_CATALOGUE_PDF`
at the file to run them from another location.

## How it works

Five stages, one module each under `src/`:

1. **`page_parser.py`** — split each PDF spread into two catalogue pages, read the
   size header, collect text lines and image placements.
2. **`classifier.py`** — decide which placed images are tiles (grids of
   equal-sized images) and which are room scenes, logos or rules.
3. **`binder.py`** — bind each tile to the name printed beneath it and to a
   millimetre size.
4. **`image_extractor.py`** + **`cleaner.py`** — pull each bitmap at full stored
   resolution, then trim borders, enforce the aspect ratio and meet a
   one-pixel-per-millimetre floor.
5. **`outputs.py`** — write the images, workbook, contact sheet and report, and
   validate the result before reporting success.

`APPROACH.md` explains the method, the decisions behind it, and the limitations.
