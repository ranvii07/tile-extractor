"""Stage 1 — turn PDF pages into logical catalogue halves.

A printed spread is one PDF page holding two catalogue pages side by side, so we
split at the vertical midline and assign every word and image placement to a half
by its centre point. A half is a real catalogue page only if it carries a tile-size
header in its top band; that single rule skips the cover, the index and the back
cover without naming a single page number.
"""

from __future__ import annotations

import math
import re
from typing import List, Tuple

import pymupdf

from .models import (Half, ImagePlacement, Rect, SizeSpec, TextLine, rect_area,
                     rect_cx, rect_cy)

# --- Calibration constants -------------------------------------------------
# Each value is traced to a measurement of the reference catalogue, but all are
# expressed as ratios so a similar catalogue at another trim size still works.

# A page is a two-page spread when it is this much wider than tall.
# Measured: content pages are 1191x865pt (ratio 1.377); a single page would be <1.
SPREAD_ASPECT_MIN = 1.15

# The size header lives in the top band of a half.
# Measured: real headers sit at y = 0.05-0.09 x H on every content page, while the
# index's first size line is at y = 0.217 x H. 0.15 separates them with margin.
HEADER_BAND_FRAC = 0.15

# "600x1200mm", "600X1200MM", "300 x 450 mm". The inch half of the header is
# mojibake in this PDF, so only the mm pattern is ever parsed.
SIZE_RE = re.compile(r"(\d{2,4})\s*[xX××]\s*(\d{2,4})\s*mm", re.IGNORECASE)

# Plausibility guard so stray numbers can never become a tile size.
MIN_SIZE_MM = 50
MAX_SIZE_MM = 3000


def parse_size_text(text: str) -> List[SizeSpec]:
    """Extract every `<n>x<n>mm` size in *text*, normalised to Length >= Width."""
    out: List[SizeSpec] = []
    for m in SIZE_RE.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if not (MIN_SIZE_MM <= a <= MAX_SIZE_MM and MIN_SIZE_MM <= b <= MAX_SIZE_MM):
            continue
        spec = SizeSpec(length_mm=max(a, b), width_mm=min(a, b))
        if spec not in out:
            out.append(spec)
    return out


def _placement_rotation(matrix: Tuple[float, ...]) -> Tuple[int, bool]:
    """Recover the image's on-page rotation from its placement matrix.

    The matrix maps the image's unit square onto the page. Its first column is
    where the image's x-axis points in page space (y down), so the angle of that
    vector is exactly how far the image was turned clockwise when placed.
    Orientation therefore comes from placement, never from the stored pixel
    dimensions -- at least one image in this catalogue is stored landscape and
    placed portrait.
    """
    a, b, c, d = matrix[0], matrix[1], matrix[2], matrix[3]
    angle = math.degrees(math.atan2(b, a))
    quadrant = int(round(angle / 90.0)) % 4
    determinant = a * d - b * c
    return quadrant * 90, determinant < 0


def _text_lines(page: pymupdf.Page) -> List[TextLine]:
    lines: List[TextLine] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = text
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            text = " ".join(text.split())  # collapse the double spaces seen in names
            if text:
                lines.append(TextLine(bbox=tuple(line["bbox"]), text=text))
    return lines


def _image_placements(page: pymupdf.Page) -> List[ImagePlacement]:
    placements: List[ImagePlacement] = []
    for info in page.get_image_info(xrefs=True):
        xref = info.get("xref", 0)
        if not xref:
            # Inline images (xref 0) are decorative page furniture and cannot be
            # extracted as objects; they are never tiles in this layout.
            continue
        rotation, flipped = _placement_rotation(info["transform"])
        placements.append(
            ImagePlacement(
                xref=xref,
                bbox=tuple(info["bbox"]),
                stored_w=int(info["width"]),
                stored_h=int(info["height"]),
                rotation=rotation,
                flipped=flipped,
            )
        )
    return placements


# Vector-drawn tiles: plain single-colour products (PLAIN BLACK, WHITE MATT...)
# are not embedded images at all but filled rectangles in the page's vector
# layer. Rectangles smaller than this are decorative rules, not tiles.
VECTOR_MIN_SIDE_PT = 25.0
# A vector rectangle overlapping an image placement by more than this fraction
# of its own area is a frame or backdrop for that image, not a tile...
VECTOR_MAX_IMAGE_OVERLAP = 0.3
# ...but only when the image is of comparable size. A rectangle far smaller
# than the image it overlaps is a swatch drawn on top of a photograph (the
# SUPER WHITE tile on the plain-colour page sits on a room scene), not a frame.
VECTOR_FRAME_MAX_AREA_RATIO = 6.0


def _overlap_area(a: Rect, b: Rect) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0.0) * max(h, 0.0)


def _vector_placements(page: pymupdf.Page,
                       images: List[ImagePlacement]) -> List[ImagePlacement]:
    """Filled or stroked rectangles that could be plain-colour tiles.

    Each gets a negative pseudo-xref and provisional=True, so it survives only
    if the binder finds a product name printed beneath it. A stroke-only
    rectangle is a white tile outlined on white stock, so its fill is None and
    the extractor synthesises white.
    """
    placements: List[ImagePlacement] = []
    seen: set = set()
    pseudo_xref = -1
    for drawing in page.get_drawings():
        if drawing["type"] not in ("f", "fs", "s"):
            continue
        r = drawing["rect"]
        if min(r.width, r.height) < VECTOR_MIN_SIDE_PT:
            continue
        key = (round(r.x0), round(r.y0), round(r.x1), round(r.y1))
        if key in seen:
            continue
        bbox = (r.x0, r.y0, r.x1, r.y1)
        area = max(r.width * r.height, 1e-6)
        if any(_overlap_area(bbox, im.bbox) / area > VECTOR_MAX_IMAGE_OVERLAP
               and rect_area(im.bbox) / area < VECTOR_FRAME_MAX_AREA_RATIO
               for im in images):
            continue
        seen.add(key)
        placements.append(ImagePlacement(
            xref=pseudo_xref, bbox=bbox,
            stored_w=int(r.width), stored_h=int(r.height), rotation=0,
            fill=drawing.get("fill"), provisional=True,
        ))
        pseudo_xref -= 1
    return placements


def _half_rects(page_rect: pymupdf.Rect) -> List[Tuple[str, Rect]]:
    """Split a spread at the midline; treat a portrait-ish page as a single half."""
    x0, y0, x1, y1 = page_rect
    if (x1 - x0) / max(y1 - y0, 1e-6) < SPREAD_ASPECT_MIN:
        return [("S", (x0, y0, x1, y1))]
    mid = (x0 + x1) / 2.0
    return [("L", (x0, y0, mid, y1)), ("R", (mid, y0, x1, y1))]


def find_header_sizes(half_rect: Rect, lines: List[TextLine]) -> List[SizeSpec]:
    """Sizes declared in the top band of a half, in reading order."""
    top, height = half_rect[1], half_rect[3] - half_rect[1]
    cutoff = top + HEADER_BAND_FRAC * height
    sizes: List[SizeSpec] = []
    for line in sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0])):
        if rect_cy(line.bbox) > cutoff:
            continue
        for spec in parse_size_text(line.text):
            if spec not in sizes:
                sizes.append(spec)
    return sizes


def parse_page(page: pymupdf.Page, page_index: int) -> List[Half]:
    """Split one PDF page into halves, each populated and marked skip or keep."""
    lines = _text_lines(page)
    images = _image_placements(page)
    images += _vector_placements(page, images)
    halves: List[Half] = []

    for side, rect in _half_rects(page.rect):
        x0, x1 = rect[0], rect[2]
        in_half = lambda bb: x0 <= rect_cx(bb) < x1 or (side in ("R", "S") and rect_cx(bb) == x1)

        half_lines = [l for l in lines if in_half(l.bbox)]
        half_images = [im for im in images if in_half(im.bbox)]
        sizes = find_header_sizes(rect, half_lines)

        half = Half(
            page_index=page_index,
            side=side,
            rect=rect,
            sizes=sizes,
            lines=half_lines,
            images=half_images,
        )
        if not sizes:
            half.skip_reason = "no tile-size header in top band (cover/index/back page)"
        halves.append(half)

    return halves


def parse_document(doc: pymupdf.Document, on_error=None) -> List[Half]:
    """Parse every page, isolating per-page failures so one bad page cannot end a run."""
    halves: List[Half] = []
    for page_index in range(doc.page_count):
        try:
            halves.extend(parse_page(doc[page_index], page_index))
        except Exception as exc:  # pragma: no cover - defensive
            if on_error:
                on_error(page_index, exc)
    return halves
