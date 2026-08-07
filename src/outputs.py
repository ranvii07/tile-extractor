"""Stage 5 — write the deliverables and check them before the run reports success.

Produces the two required artefacts (an images folder and an Excel file with
exactly the four required columns) plus two self-verification artefacts: a
contact sheet for a two-minute visual pass over the whole catalogue, and a run
report recording every decision the pipeline made.
"""

from __future__ import annotations

import base64
import html
import io
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from PIL import Image

from .models import Rejection, Tile

# Excel columns are fixed by the assignment: nothing extra belongs in this file.
EXCEL_COLUMNS = ["Title", "Length (mm)", "Width (mm)", "Image Name"]

# Windows forbids <>:"/\|?* in filenames; we also fold spaces to hyphens.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COLLAPSE = re.compile(r"[\s_]+")

CONTACT_THUMB_PX = 190

# Validation tolerances.
ASPECT_CHECK_TOL = 0.02  # saved aspect vs mm ratio


def slugify(name: str) -> str:
    """A deterministic, Windows-safe filename stem that stays readable."""
    cleaned = _UNSAFE.sub("", name or "UNNAMED")
    cleaned = _COLLAPSE.sub("-", cleaned.strip())
    cleaned = cleaned.strip(". -")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return (cleaned or "UNNAMED").upper()[:80]


def assign_image_names(tiles: Sequence[Tile]) -> None:
    """Give every tile a unique `<NAME>_<L>x<W>.png`, numbering any collisions."""
    used: Dict[str, int] = {}
    for tile in tiles:
        length = tile.size.length_mm if tile.size else 0
        width = tile.size.width_mm if tile.size else 0
        stem = f"{slugify(tile.name)}_{length}x{width}"
        count = used.get(stem, 0)
        used[stem] = count + 1
        tile.image_name = f"{stem}.png" if count == 0 else f"{stem}_{count + 1}.png"


def write_excel(tiles: Sequence[Tile], path: Path) -> None:
    """The required workbook: one row per tile, in catalogue order, four columns."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Tiles"
    sheet.append(EXCEL_COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for tile in tiles:
        sheet.append([
            tile.name or "",
            tile.size.length_mm if tile.size else None,
            tile.size.width_mm if tile.size else None,
            tile.image_name or "",
        ])

    for column, width in zip("ABCD", (34, 14, 14, 46)):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    book.save(path)


def _thumb_data_uri(image_path: Path) -> str:
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.thumbnail((CONTACT_THUMB_PX, CONTACT_THUMB_PX), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def write_contact_sheet(tiles: Sequence[Tile], images_dir: Path, path: Path, pdf_name: str) -> None:
    """One self-contained page showing every tile with its name, size and flags."""
    cards = []
    for tile in tiles:
        image_path = images_dir / (tile.image_name or "")
        try:
            uri = _thumb_data_uri(image_path)
        except Exception:
            uri = ""
        flags = "".join(
            f'<span class="flag">{html.escape(f)}</span>' for f in tile.flags
        )
        size = f"{tile.size.length_mm} x {tile.size.width_mm} mm" if tile.size else "unknown"
        cards.append(
            '<figure class="card">'
            f'<div class="thumb"><img loading="lazy" src="{uri}" alt=""></div>'
            f'<figcaption><b>{html.escape(tile.name or "(unnamed)")}</b>'
            f'<span class="meta">{size}</span>'
            f'<span class="meta">{tile.out_w}x{tile.out_h}px &middot; {tile.half_label}</span>'
            f'{flags}</figcaption></figure>'
        )

    flagged = sum(1 for t in tiles if t.flags)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tile contact sheet - {html.escape(pdf_name)}</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font: 14px/1.45 system-ui, sans-serif; margin: 0; padding: 24px;
        background: Canvas; color: CanvasText; }}
 h1 {{ font-size: 20px; margin: 0 0 4px; }}
 .sub {{ opacity: .7; margin-bottom: 20px; }}
 .grid {{ display: grid; gap: 14px;
          grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }}
 .card {{ margin: 0; border: 1px solid rgba(128,128,128,.35); border-radius: 8px;
          padding: 10px; display: flex; flex-direction: column; gap: 8px; }}
 .thumb {{ display: grid; place-items: center; height: {CONTACT_THUMB_PX}px;
           background: repeating-conic-gradient(rgba(128,128,128,.16) 0% 25%,
                       transparent 0% 50%) 50%/16px 16px; border-radius: 4px; }}
 .thumb img {{ max-width: 100%; max-height: {CONTACT_THUMB_PX}px; display: block; }}
 figcaption {{ display: flex; flex-direction: column; gap: 3px; font-size: 12px;
               word-break: break-word; }}
 .meta {{ opacity: .72; }}
 .flag {{ display: inline-block; margin-top: 4px; padding: 1px 7px; border-radius: 999px;
          background: rgba(220,140,0,.22); font-size: 11px; width: fit-content; }}
</style></head><body>
<h1>Tile contact sheet</h1>
<div class="sub">{html.escape(pdf_name)} &middot; {len(tiles)} tiles &middot; {flagged} carrying a flag</div>
<div class="grid">{''.join(cards)}</div>
</body></html>"""
    path.write_text(document, encoding="utf-8")


def validate(tiles: Sequence[Tile], images_dir: Path) -> List[str]:
    """End-of-run checks. Every failure is reported; none are silently tolerated."""
    problems: List[str] = []

    missing_names = [t for t in tiles if not (t.name or "").strip()]
    if missing_names:
        problems.append(f"{len(missing_names)} row(s) have no title")

    bad_dims = [t for t in tiles
                if not t.size or t.size.length_mm <= 0 or t.size.width_mm <= 0]
    if bad_dims:
        problems.append(f"{len(bad_dims)} row(s) have non-positive dimensions")

    duplicates = [n for n, c in Counter(t.image_name for t in tiles).items() if c > 1]
    if duplicates:
        problems.append(f"{len(duplicates)} duplicate image filename(s): {duplicates[:3]}")

    absent, under_res, wrong_aspect = [], [], []
    for tile in tiles:
        path = images_dir / (tile.image_name or "")
        if not path.is_file():
            absent.append(tile.image_name)
            continue
        if not tile.size:
            continue
        need_long, need_short = tile.size.length_mm, tile.size.width_mm
        long_px, short_px = max(tile.out_w, tile.out_h), min(tile.out_w, tile.out_h)
        if long_px < need_long or short_px < need_short:
            under_res.append(f"{tile.image_name} ({tile.out_w}x{tile.out_h})")
        target = need_long / need_short
        actual = long_px / max(short_px, 1)
        if abs(actual - target) / target > ASPECT_CHECK_TOL:
            wrong_aspect.append(f"{tile.image_name} ({actual:.3f} vs {target:.3f})")

    if absent:
        problems.append(f"{len(absent)} row(s) reference a missing image file: {absent[:3]}")
    if under_res:
        problems.append(f"{len(under_res)} image(s) below the 1px/mm floor: {under_res[:3]}")
    if wrong_aspect:
        problems.append(f"{len(wrong_aspect)} image(s) off their mm aspect ratio: {wrong_aspect[:3]}")

    return problems


def write_report(
    path: Path,
    pdf_path: Path,
    tiles: Sequence[Tile],
    skipped: Sequence[Tuple[str, str]],
    rejections: Sequence[Rejection],
    leftovers: Sequence[Tuple[str, str]],
    errors: Sequence[str],
    problems: Sequence[str],
    stats: Dict[str, object],
) -> None:
    """A plain-text account of everything the run decided, for review and demo Q&A."""
    lines: List[str] = []
    add = lines.append

    add("=" * 72)
    add("TILE CATALOGUE EXTRACTION - RUN REPORT")
    add("=" * 72)
    add(f"Source PDF     : {pdf_path.name}")
    add(f"Pages in PDF   : {stats.get('pages')}")
    add(f"Catalogue pages: {stats.get('halves_kept')} kept, {len(skipped)} skipped")
    add(f"Tiles extracted: {len(tiles)}")
    add(f"Images decoded : {stats.get('decoded')} unique objects "
        f"({stats.get('cache_hits')} reuses avoided a re-decode)")
    add("")

    add("-" * 72)
    add("VALIDATION")
    add("-" * 72)
    if problems:
        for problem in problems:
            add(f"  FAIL  {problem}")
    else:
        add("  PASS  every row has a title, positive dimensions and an existing image")
        add("  PASS  every image meets the 1px/mm floor and its mm aspect ratio")
        add("  PASS  no duplicate image filenames")
    add("")

    add("-" * 72)
    add("PAGES SKIPPED (no tile-size header in the top band)")
    add("-" * 72)
    for label, reason in skipped:
        add(f"  {label:8s} {reason}")
    add("")

    flag_counts = Counter(f for t in tiles for f in t.flags)
    add("-" * 72)
    add("FLAGS")
    add("-" * 72)
    if flag_counts:
        for flag, count in flag_counts.most_common():
            add(f"  {count:5d}  {flag}")
        add("")
        add("  Flag meanings:")
        add("    size-measured        size derived from the page scale and matched to a")
        add("                         size the catalogue prints (square companion tiles)")
        add("    size-measured-unlisted  measured, but no catalogue size matched; rounded")
        add("    shared-name          one printed name covers several tile faces")
        add("                         (bookmatch pairs, multi-panel murals)")
        add("    vector-drawn         plain-colour tile drawn as a vector rectangle,")
        add("                         not an embedded image; bitmap synthesised from its fill")
        add("    missing-label        no name could be bound; needs review")
        add("    ambiguous-size-header  two headers explain the shape equally well")
        add("    size-aspect-mismatch shape contradicts the header and could not be measured")
        add("    trim-capped          border trimming stopped at its safety cap")
        add("    aspect-crop-refused  required crop exceeded the safety cap; left uncropped")
    else:
        add("  none")
    add("")

    add("-" * 72)
    add("TILES PER CATALOGUE PAGE")
    add("-" * 72)
    per_half = Counter(t.half_label for t in tiles)
    row: List[str] = []
    for label, count in sorted(per_half.items(), key=lambda kv: (int(kv[0][1:-1]), kv[0][-1])):
        row.append(f"{label:>7s}:{count:<3d}")
        if len(row) == 8:
            add("  " + " ".join(row))
            row = []
    if row:
        add("  " + " ".join(row))
    add("")

    add("-" * 72)
    add("IMAGES REJECTED AS NON-TILES")
    add("-" * 72)
    reason_counts = Counter(r.reason.split(" (")[0] for r in rejections)
    for reason, count in reason_counts.most_common():
        add(f"  {count:5d}  {reason}")
    add(f"  {'-' * 40}")
    add(f"  {len(rejections):5d}  total")
    add("")

    if leftovers:
        add("-" * 72)
        add("TEXT LINES NEAR TILES THAT WERE NOT USED AS NAMES")
        add("-" * 72)
        for label, text in leftovers[:40]:
            add(f"  {label:8s} {text!r}")
        if len(leftovers) > 40:
            add(f"  ... and {len(leftovers) - 40} more")
        add("")

    add("-" * 72)
    add("CLEANUP")
    add("-" * 72)
    add(f"  tiles trimmed          : {stats.get('trimmed')}")
    add(f"  tiles aspect-cropped   : {stats.get('cropped')}")
    add(f"  tiles upscaled         : {stats.get('upscaled')}")
    add(f"  median upscale factor  : {stats.get('median_scale')}")
    add("")

    if errors:
        add("-" * 72)
        add("RECOVERED ERRORS (run continued)")
        add("-" * 72)
        for error in errors:
            add(f"  {error}")
        add("")

    add("=" * 72)
    add("RESULT: " + ("FAILED VALIDATION" if problems else "OK"))
    add("=" * 72)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
