"""Stage 3 — bind each tile to its printed name and its millimetre size.

Names sit in a text row immediately below their image row, left-aligned with the
image they belong to, so binding is done by x-alignment inside a vertical band.
Sizes come from the half's header; where a half declares more than one size
(the step-and-riser pages do), each tile takes the header whose shape best
matches its own. Anything that cannot be matched confidently is flagged rather
than guessed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Sequence, Tuple

from .models import Half, ImagePlacement, SizeSpec, TextLine, Tile
from .page_parser import SIZE_RE

# --- Calibration constants -------------------------------------------------

# A name's top edge sits 4.6-5.1pt below its image's bottom edge (measured on
# pp. 3, 5, 51, 87). 25pt absorbs variation while staying well inside the
# smallest gap to the next image row (22pt on the densest page).
MAX_LABEL_GAP_PT = 25.0

# A label may start slightly before its image's left edge (measured: 0.6pt).
LABEL_ABOVE_SLACK_PT = 3.0

# The label must lie mostly within its image's horizontal span.
MIN_LABEL_OVERLAP = 0.5

# Labels are left-aligned to their image within ~1pt; 40pt is a generous cap
# that still cannot reach the next column (tightest column pitch is 145pt).
MAX_LABEL_DX_PT = 40.0

# Rows are bucketed for pairing; tightest measured row pitch is 103pt.
ROW_TOL_PT = 20.0

# How far a tile's placed shape may differ from its header size before the
# binding is called into question. Genuine tiles land within 13% (measured: 1.5%
# on p3, 6% on p87, 12.4% on p88 where the embedded image carries a shadow
# margin). A genuinely wrong size is off by far more -- the square tiles printed
# on the 300x450 wall pages miss by 33%.
ASPECT_MATCH_TOL = 0.20

# Whole-line labels that are page furniture, never product names. Matched against
# the whole line only -- substring matching would eat names like "EL-09 (MATT)".
STOP_LINES = {
    "size", "size :", "size:", "finish", "glossy", "gloss", "highgloss",
    "matt", "matte", "pgvt", "gvt", "index", "innovative", "chicembodied",
    "vitrifiedtiles", "pgvtvitrifiedtiles", "digitalwalltiles",
    "heavydutyparkingtiles", "steprisertiles", "stepriser", "step", "reser",
    "adhesivesgrout",
}

_NON_PRINTABLE = re.compile(r"[^\x20-\x7E]")


def normalise_name(text: str) -> str:
    """Collapse whitespace and drop non-printable/mojibake characters."""
    text = unicodedata.normalize("NFKC", text)
    text = _NON_PRINTABLE.sub("", text)
    return " ".join(text.split()).strip()


def _stop_key(text: str) -> str:
    """Letters and digits only, lowercased -- collapses 'F i n i s h' to 'finish'."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def is_stop_line(text: str, in_margin: bool = False) -> bool:
    """True when a text line is page furniture rather than a product name.

    `in_margin` marks lines in the extreme top/bottom band of the half. Only there
    is a digits-only line treated as a folio -- plenty of genuine product names in
    this catalogue are bare numbers ("5335", "10122", "1532").
    """
    clean = normalise_name(text)
    if not clean:
        return True
    if in_margin and clean.isdigit():  # folio / page number
        return True
    # A lone letter is never a product name. The "FINISH" heading is set as
    # letter-spaced vertical type, which the text extractor returns as six
    # single-character lines rather than one; without this they all survive as
    # unbound labels and bury the genuinely unexplained text in the report.
    if len(clean) == 1 and clean.isalpha():
        return True
    if SIZE_RE.search(clean):  # a size caption, not a name
        return True
    key = _stop_key(clean)
    if key in STOP_LINES:
        return True
    # Section banners: multi-word, digit-free, ending in SERIES or TILES.
    upper = clean.upper()
    if (upper.endswith(" SERIES") or upper.endswith(" TILES")) and not any(c.isdigit() for c in clean):
        return True
    return False


def _overlap_fraction(label_bbox, img_bbox) -> float:
    lo = max(label_bbox[0], img_bbox[0])
    hi = min(label_bbox[2], img_bbox[2])
    label_w = max(label_bbox[2] - label_bbox[0], 1e-6)
    return max(hi - lo, 0.0) / label_w


# Folios sit at 95% of the half's height; the lowest genuine name is at 90%.
MARGIN_BAND_FRAC = 0.94


def candidate_labels(lines: Sequence[TextLine], half_rect=None) -> List[TextLine]:
    """Text lines that could be product names, with page furniture removed."""
    out = []
    for l in lines:
        in_margin = False
        if half_rect is not None:
            top, height = half_rect[1], half_rect[3] - half_rect[1]
            in_margin = (l.bbox[1] - top) / max(height, 1e-6) > MARGIN_BAND_FRAC
        if not is_stop_line(l.text, in_margin=in_margin):
            out.append(l)
    return out


def bind_names(
    placements: Sequence[ImagePlacement],
    lines: Sequence[TextLine],
    half_rect=None,
) -> Tuple[dict, List[TextLine]]:
    """Map placement index -> name. Returns the mapping and any unused labels.

    Images are bucketed into rows; for each row the labels sitting just beneath it
    are paired to images one-to-one by left-edge alignment, nearest first.
    """
    labels = candidate_labels(lines, half_rect)
    used = set()
    names: dict = {}

    rows: dict = {}
    for idx, p in enumerate(placements):
        rows.setdefault(round(p.bbox[3] / ROW_TOL_PT), []).append(idx)

    for _, idxs in sorted(rows.items()):
        row_imgs = sorted(idxs, key=lambda i: placements[i].bbox[0])
        row_bottom = max(placements[i].bbox[3] for i in row_imgs)

        band = [
            l for j, l in enumerate(labels)
            if j not in used
            and (row_bottom - LABEL_ABOVE_SLACK_PT) <= l.bbox[1] <= (row_bottom + MAX_LABEL_GAP_PT)
        ]

        # Score every (image, label) pair, then take them greedily nearest-first
        # so a row with a missing label still binds the rest correctly.
        pairs = []
        for i in row_imgs:
            img = placements[i]
            for l in band:
                dx = abs(l.bbox[0] - img.bbox[0])
                if dx > MAX_LABEL_DX_PT:
                    continue
                if _overlap_fraction(l.bbox, img.bbox) < MIN_LABEL_OVERLAP:
                    continue
                pairs.append((dx, i, l))

        pairs.sort(key=lambda t: t[0])
        taken_imgs, taken_labels = set(), set()
        for dx, i, l in pairs:
            if i in taken_imgs or id(l) in taken_labels:
                continue
            names[i] = normalise_name(l.text)
            taken_imgs.add(i)
            taken_labels.add(id(l))
            used.add(labels.index(l))

    leftovers = [l for j, l in enumerate(labels) if j not in used]
    return names, leftovers


def choose_size(placement: ImagePlacement, sizes: Sequence[SizeSpec]) -> Tuple[Optional[SizeSpec], List[str]]:
    """Pick the header size that best explains this tile's shape."""
    flags: List[str] = []
    if not sizes:
        return None, ["no-size-header"]
    if len(sizes) == 1:
        best = sizes[0]
    else:
        ranked = sorted(sizes, key=lambda s: abs(placement.placed_ratio - s.ratio) / s.ratio)
        best = ranked[0]
        err_best = abs(placement.placed_ratio - best.ratio) / best.ratio
        err_next = abs(placement.placed_ratio - ranked[1].ratio) / ranked[1].ratio
        if err_next - err_best < 0.05:  # two headers explain the shape equally well
            flags.append("ambiguous-size-header")

    if abs(placement.placed_ratio - best.ratio) > ASPECT_MATCH_TOL * best.ratio:
        flags.append("size-aspect-mismatch")
    return best, flags


# A derived size must land this close to a size the catalogue actually prints
# before it is trusted. Measured: derived 301x300 against a listed 300x300.
SNAP_TOL = 0.08

# Derived sizes are rounded to this grid when nothing in the vocabulary fits.
SIZE_ROUND_MM = 10


def page_scale(pairs: Sequence[Tuple[ImagePlacement, SizeSpec]]) -> Optional[float]:
    """Points-per-millimetre for a half, from tiles that match their header size.

    Every tile on a half is reproduced at one scale, so tiles whose shape agrees
    with the header calibrate a ruler for the ones whose shape does not.
    """
    scales = []
    for placement, size in pairs:
        long_pt = max(placement.unit_w, placement.unit_h)
        if size.length_mm:
            scales.append(long_pt / size.length_mm)
    if not scales:
        return None
    scales.sort()
    return scales[len(scales) // 2]  # median


def measure_size(
    placement: ImagePlacement,
    scale: float,
    vocabulary: Sequence[SizeSpec],
) -> Tuple[Optional[SizeSpec], str]:
    """Measure a tile in mm using the page scale, then snap to a known size."""
    if scale <= 0:
        return None, "no-page-scale"
    long_mm = max(placement.unit_w, placement.unit_h) / scale
    short_mm = min(placement.unit_w, placement.unit_h) / scale

    best, best_err = None, None
    for spec in vocabulary:
        err = max(abs(long_mm - spec.length_mm) / spec.length_mm,
                  abs(short_mm - spec.width_mm) / spec.width_mm)
        if best_err is None or err < best_err:
            best, best_err = spec, err
    if best is not None and best_err <= SNAP_TOL:
        return best, "size-measured"

    rounded = SizeSpec(
        length_mm=int(round(long_mm / SIZE_ROUND_MM) * SIZE_ROUND_MM),
        width_mm=int(round(short_mm / SIZE_ROUND_MM) * SIZE_ROUND_MM),
    )
    if rounded.width_mm <= 0 or rounded.length_mm <= 0:
        return None, "size-unmeasurable"
    return rounded, "size-measured-unlisted"


def bind_half(
    half: Half,
    placements: Sequence[ImagePlacement],
    vocabulary: Optional[Sequence[SizeSpec]] = None,
) -> Tuple[List[Tile], List[TextLine]]:
    """Produce fully bound Tile records for one half.

    Sizes are taken from the half's header. Tiles whose shape contradicts the
    header -- the square companion tiles printed on wall-tile pages -- are instead
    measured against the page scale and snapped to a size the catalogue prints.
    """
    names, leftovers = bind_names(placements, half.lines, half.rect)
    vocabulary = list(vocabulary) if vocabulary else list(half.sizes)
    tiles: List[Tile] = []

    order = 0
    for block_index, block in enumerate(placements):
        size, size_flags = choose_size(block, half.sizes)
        name = names.get(block_index)
        # A block contributes one tile per distinct face it prints. Most blocks
        # have exactly one; bookmatch pairs and murals have several, all sharing
        # the single name printed beneath the block.
        for face in block.members:
            tile = Tile(page_index=half.page_index, side=half.side, order=order,
                        placement=face, name=name, size=size)
            for f in size_flags:
                tile.flag(f)
            if not name:
                tile.flag("missing-label")
            if len(block.members) > 1:
                tile.flag("shared-name")
                tile.steps["block_faces"] = len(block.members)
            if block.is_repeat_block:
                tile.steps["repeat"] = f"{block.repeat_x}x{block.repeat_y}"
            tiles.append(tile)
            order += 1

    # Calibrate on the tiles the header explains, then measure the ones it does not.
    scale = page_scale([(t.placement, t.size) for t in tiles
                        if t.size and "size-aspect-mismatch" not in t.flags])
    if scale:
        for tile in tiles:
            if "size-aspect-mismatch" not in tile.flags:
                continue
            measured, note = measure_size(tile.placement, scale, vocabulary)
            if measured is not None:
                tile.size = measured
                tile.flags.remove("size-aspect-mismatch")
                tile.flag(note)
                tile.steps["measured_mm"] = (round(max(tile.placement.unit_w, tile.placement.unit_h) / scale, 1),
                                             round(min(tile.placement.unit_w, tile.placement.unit_h) / scale, 1))

    return tiles, leftovers
