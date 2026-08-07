"""Stage 2 — decide which placed images on a half are tiles.

The layout gives this away geometrically: tiles are printed as grids of
identically sized images, and nothing else on the page is. Room-scene renders are
far too large, logos far too small, and both appear alone rather than in a
repeated size. This module is pure geometry -- it takes rectangles, not a PDF --
so it is unit-testable without opening a document.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .models import Half, ImagePlacement, Rejection, SizeSpec, rect_area

# --- Calibration constants -------------------------------------------------
# Measured on the reference catalogue, expressed as fractions of the half so the
# same numbers hold for a catalogue printed at a different trim size.

# Room scenes cover 22-70% of a half (measured: 22% p51, 37% p3, 70% p87);
# the largest genuine tile covers 7.3%. 0.18 sits in the empty band between.
# Applied to a single tile, not to a repeat block: a 2x2 swatch legitimately
# covers 23% of a half while each tile in it covers 5.9%.
MAX_AREA_FRAC = 0.18

# Logos are 104x24pt; the shortest genuine tile side is 67pt.
MIN_SIDE_PT = 30.0

# Belt-and-braces lower bound on area (smallest genuine tile is 2.0% of a half).
MIN_AREA_FRAC = 0.004

# Two placements count as "the same size" within this relative tolerance.
# Measured: repeats of one tile size vary by <1%; distinct sizes differ by >30%.
SIZE_TOL = 0.06

# A lone image is accepted only if its shape matches a header size this closely.
SINGLETON_RATIO_TOL = 0.10

# Row bucketing for reading order; the tightest row pitch measured is 103pt.
ROW_TOL_PT = 20.0

# Two placements of the same image count as adjacent within this gap. Measured:
# cells of a repeat block abut to within 0.2pt; distinct tiles are >=38pt apart.
ADJACENCY_EPS_PT = 1.5


def _touching(a, b, eps: float = ADJACENCY_EPS_PT) -> bool:
    """True when two rectangles overlap or share an edge on both axes."""
    return (a[0] - eps <= b[2] and b[0] - eps <= a[2]
            and a[1] - eps <= b[3] and b[1] - eps <= a[3])


def _same_cell_size(a: ImagePlacement, b: ImagePlacement) -> bool:
    return (abs(a.placed_w - b.placed_w) <= SIZE_TOL * max(a.placed_w, b.placed_w)
            and abs(a.placed_h - b.placed_h) <= SIZE_TOL * max(a.placed_h, b.placed_h))


def coalesce_blocks(placements: Sequence[ImagePlacement]) -> List[ImagePlacement]:
    """Merge abutting equal-sized placements into one logical product block.

    The catalogue prints several products as a grid of touching cells sharing a
    single name: a 2x2 repeat swatch of one image (parking pages), a bookmatch
    pair of two mirrored faces ("BM-9018"), or a stacked mural of three panels
    ("3416-HL-1-P1-P2-P3"). Cells of such a grid abut to within 0.2pt, whereas
    two separately named tiles are never closer than 11pt -- so abutment alone
    identifies a block, and the block keeps one entry per distinct face.
    """
    merged: List[ImagePlacement] = []
    unseen = list(placements)

    while unseen:
        component = [unseen.pop(0)]
        changed = True
        while changed:
            changed = False
            for cand in list(unseen):
                if any(_touching(cand.bbox, m.bbox) and _same_cell_size(cand, m) for m in component):
                    component.append(cand)
                    unseen.remove(cand)
                    changed = True

        if len(component) == 1:
            merged.append(component[0])
            continue

        cells = sorted(component, key=lambda c: (round(c.bbox[1] / ROW_TOL_PT), c.bbox[0]))
        faces: Dict[int, ImagePlacement] = {}
        for cell in cells:
            faces.setdefault(cell.xref, cell)  # first occurrence wins, reading order

        head = cells[0]
        union = (min(c.bbox[0] for c in component), min(c.bbox[1] for c in component),
                 max(c.bbox[2] for c in component), max(c.bbox[3] for c in component))
        merged.append(ImagePlacement(
            xref=head.xref, bbox=union, stored_w=head.stored_w, stored_h=head.stored_h,
            rotation=head.rotation, flipped=head.flipped, unit_bbox=head.bbox,
            repeat_x=len({round(c.bbox[0], 1) for c in component}),
            repeat_y=len({round(c.bbox[1], 1) for c in component}),
            members=list(faces.values()),
        ))

    return merged


def _size_key(placement: ImagePlacement, buckets: List[Tuple[float, float]]) -> int:
    """Index of the size bucket this placement belongs to, creating one if needed.

    Bucketing uses the size of a single tile as printed, so a product shown as a
    2x2 repeat groups with the same product shown once.
    """
    w, h = placement.unit_w, placement.unit_h
    for i, (bw, bh) in enumerate(buckets):
        if abs(w - bw) <= SIZE_TOL * max(bw, w) and abs(h - bh) <= SIZE_TOL * max(bh, h):
            return i
    buckets.append((w, h))
    return len(buckets) - 1


def _matches_any_header(placement: ImagePlacement, sizes: Sequence[SizeSpec]) -> bool:
    ratio = placement.placed_ratio
    return any(abs(ratio - s.ratio) <= SINGLETON_RATIO_TOL * s.ratio for s in sizes)


def reading_order(placements: Sequence[ImagePlacement]) -> List[ImagePlacement]:
    """Left-to-right within a row, top-to-bottom across rows."""
    return sorted(placements, key=lambda p: (round(p.bbox[1] / ROW_TOL_PT), p.bbox[0]))


def classify_half(
    half: Half,
    vocabulary: Sequence[SizeSpec] = (),
) -> Tuple[List[ImagePlacement], List[Rejection]]:
    """Split a half's placements into tile candidates and explained rejections.

    *vocabulary* is every size the catalogue prints anywhere. A lone image whose
    shape matches no header size may still be a companion product (the single
    square -F tile on a rectangular-tile page), so it is accepted provisionally
    when its shape matches a vocabulary size -- the binder then keeps it only if
    a printed name sits beneath it.
    """
    accepted: List[ImagePlacement] = []
    rejections: List[Rejection] = []

    if half.skip_reason:
        return accepted, rejections

    half_area = half.area or 1.0

    # Grids of touching cells become one logical product before anything else.
    placements = coalesce_blocks(half.images)

    # Pass 1: hard geometric filters that never depend on neighbours.
    survivors: List[ImagePlacement] = []
    for p in placements:
        area_frac = rect_area(p.bbox) / half_area
        if min(p.unit_w, p.unit_h) < MIN_SIDE_PT:
            rejections.append(Rejection(half.label, p.xref, p.bbox,
                                        f"too small ({p.unit_w:.0f}x{p.unit_h:.0f}pt) - logo or rule"))
        elif rect_area(p.unit_bbox) / half_area > MAX_AREA_FRAC:
            rejections.append(Rejection(half.label, p.xref, p.bbox,
                                        f"too large ({area_frac:.0%} of half) - room scene"))
        elif area_frac < MIN_AREA_FRAC:
            rejections.append(Rejection(half.label, p.xref, p.bbox,
                                        f"below minimum area ({area_frac:.1%} of half)"))
        else:
            survivors.append(p)

    # Pass 2: tiles repeat. Group survivors by placed size; a group of 2+ is a
    # grid. A singleton is accepted only when its shape matches a header size
    # (a featured hero tile), otherwise it is an unexplained one-off.
    buckets: List[Tuple[float, float]] = []
    groups: Dict[int, List[ImagePlacement]] = {}
    for p in survivors:
        groups.setdefault(_size_key(p, buckets), []).append(p)

    for key, members in groups.items():
        if len(members) >= 2:
            accepted.extend(members)
            continue
        lone = members[0]
        if _matches_any_header(lone, half.sizes):
            accepted.append(lone)
        elif _matches_any_header(lone, vocabulary):
            lone.provisional = True  # kept only if a name binds to it
            accepted.append(lone)
        else:
            rejections.append(Rejection(half.label, lone.xref, lone.bbox,
                                        "lone image whose shape matches no header size"))

    return reading_order(accepted), rejections
