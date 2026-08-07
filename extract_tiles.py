#!/usr/bin/env python3
"""Automated tile-catalogue extraction.

One command turns a tile-catalogue PDF into an images folder, an Excel sheet, a
contact sheet and a run report:

    python extract_tiles.py "catalogue.pdf" -o output/

The pipeline is five stages -- parse pages, classify tiles, bind names and sizes,
extract and clean bitmaps, write and validate outputs -- each implemented in its
own module under `src/`. Nothing is hardcoded to a particular catalogue: pages
are found by structure (a size header in the top band), tiles by geometry (grids
of equal-sized images), and names by position (the text row beneath a tile).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import traceback
from pathlib import Path
from typing import List, Tuple

import pymupdf

from src.binder import bind_half
from src.classifier import classify_half
from src.image_extractor import ImageSource, extract_tile
from src.cleaner import clean
from src.models import Rejection, SizeSpec, Tile
from src.outputs import (assign_image_names, validate, write_contact_sheet,
                         write_excel, write_report)
from src.page_parser import parse_document

PNG_SAVE = {"format": "PNG", "optimize": True}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract tile images, names and dimensions from a catalogue PDF.")
    parser.add_argument("pdf", type=str, help="path to the catalogue PDF")
    parser.add_argument("-o", "--output", type=str, default="output",
                        help="output directory (default: output)")
    parser.add_argument("--debug", action="store_true",
                        help="also write raw pre-cleanup images and per-page geometry")
    parser.add_argument("--limit-pages", type=int, default=None,
                        help="process only the first N PDF pages (development aid)")
    return parser.parse_args(argv)


def validate_inputs(pdf_path: Path, out_dir: Path) -> pymupdf.Document:
    """Fail fast, with a clear message, before any work is done."""
    if not pdf_path.is_file():
        raise SystemExit(f"error: no such file: {pdf_path}")
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise SystemExit(f"error: cannot open {pdf_path.name} as a PDF: {exc}")
    if doc.page_count == 0:
        raise SystemExit(f"error: {pdf_path.name} has no pages")
    if doc.needs_pass:
        raise SystemExit(f"error: {pdf_path.name} is password protected")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        raise SystemExit(f"error: output directory {out_dir} is not writable: {exc}")
    return doc


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    pdf_path = Path(args.pdf.strip())  # tolerate the trailing space in the sample filename
    out_dir = Path(args.output)

    doc = validate_inputs(pdf_path, out_dir)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = out_dir / "debug"
    if args.debug:
        debug_dir.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []

    # ---- Stage 1: pages -> halves -------------------------------------------
    halves = parse_document(doc, on_error=lambda i, e: errors.append(f"page {i+1}: {e}"))
    if args.limit_pages:
        halves = [h for h in halves if h.page_index < args.limit_pages]

    skipped = [(h.label, h.skip_reason) for h in halves if h.skip_reason]
    kept = [h for h in halves if not h.skip_reason]

    # The sizes this catalogue actually prints, used to interpret tiles whose
    # shape contradicts their page header.
    vocabulary: List[SizeSpec] = []
    for half in kept:
        for size in half.sizes:
            if size not in vocabulary:
                vocabulary.append(size)

    # ---- Stages 2 & 3: classify and bind ------------------------------------
    tiles: List[Tile] = []
    rejections: List[Rejection] = []
    leftovers: List[Tuple[str, str]] = []

    for half in kept:
        try:
            accepted, rejected = classify_half(half, vocabulary)
            bound, unused = bind_half(half, accepted, vocabulary)
            # A provisional candidate (vector rectangle, or lone image accepted
            # on a vocabulary rather than header match) is a tile only if a
            # printed name bound to it; otherwise it was page furniture.
            for tile in bound:
                if tile.placement.provisional and not tile.name:
                    rejected.append(Rejection(
                        half.label, tile.placement.xref, tile.placement.bbox,
                        "provisional candidate with no printed name beneath"))
                else:
                    tiles.append(tile)
            rejections.extend(rejected)
            leftovers.extend((half.label, line.text) for line in unused)
        except Exception as exc:
            errors.append(f"{half.label}: classification/binding failed: {exc}")

    tiles.sort(key=lambda t: (t.page_index, 0 if t.side in ("L", "S") else 1, t.order))
    assign_image_names(tiles)

    # ---- Stage 4: extract and clean -----------------------------------------
    source = ImageSource(doc)
    trimmed = cropped = upscaled = 0
    scales: List[float] = []
    produced: List[Tile] = []

    for tile in tiles:
        try:
            raw = extract_tile(source, tile.placement)
            if args.debug:
                raw.save(debug_dir / f"raw_{tile.image_name}", **PNG_SAVE)

            length = tile.size.length_mm if tile.size else 0
            width = tile.size.width_mm if tile.size else 0
            image, steps = clean(raw, length, width)

            if steps.get("trim") and any(steps["trim"]):
                trimmed += 1
            if steps.get("trim_capped"):
                tile.flag("trim-capped")
            if str(steps.get("aspect", "")).startswith("cropped"):
                cropped += 1
            if steps.get("aspect") == "crop-refused":
                tile.flag("aspect-crop-refused")
            scale = steps.get("scale")
            if isinstance(scale, float) and scale > 1.0:
                upscaled += 1
                scales.append(scale)

            image.save(images_dir / tile.image_name, **PNG_SAVE)
            tile.out_w, tile.out_h = image.size
            tile.steps.update(steps)
            produced.append(tile)
        except Exception as exc:
            errors.append(f"{tile.half_label} {tile.name!r}: extraction failed: {exc}")
            if args.debug:
                errors.append(traceback.format_exc())

    # ---- Stage 5: outputs and validation ------------------------------------
    write_excel(produced, out_dir / "tiles.xlsx")
    write_contact_sheet(produced, images_dir, out_dir / "contact_sheet.html", pdf_path.name)
    problems = validate(produced, images_dir)

    stats = {
        "pages": doc.page_count,
        "halves_kept": len(kept),
        "decoded": source.decoded,
        "cache_hits": source.cache_hits,
        "trimmed": trimmed,
        "cropped": cropped,
        "upscaled": upscaled,
        "median_scale": round(statistics.median(scales), 3) if scales else 1.0,
    }
    write_report(out_dir / "report.txt", pdf_path, produced, skipped, rejections,
                 leftovers, errors, problems, stats)

    if args.debug:
        with (debug_dir / "geometry.txt").open("w", encoding="utf-8") as handle:
            for half in halves:
                handle.write(f"{half.label} rect={half.rect} sizes={[str(s) for s in half.sizes]} "
                             f"skip={half.skip_reason} images={len(half.images)}\n")

    page_count = doc.page_count
    doc.close()

    print(f"Pages      : {page_count} ({len(kept)} catalogue pages, {len(skipped)} skipped)")
    print(f"Tiles      : {len(produced)}")
    print(f"Images     : {images_dir}")
    print(f"Excel      : {out_dir / 'tiles.xlsx'}")
    print(f"Contact    : {out_dir / 'contact_sheet.html'}")
    print(f"Report     : {out_dir / 'report.txt'}")
    if errors:
        print(f"Recovered  : {len(errors)} error(s) - see report.txt")
    if problems:
        print("VALIDATION : FAILED - see report.txt")
        return 1
    print("VALIDATION : all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
