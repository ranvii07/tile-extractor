"""Plain data containers passed between pipeline stages. No logic lives here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# (x0, y0, x1, y1) in PDF points, y increasing downwards (PyMuPDF convention).
Rect = Tuple[float, float, float, float]


def rect_w(r: Rect) -> float:
    return r[2] - r[0]


def rect_h(r: Rect) -> float:
    return r[3] - r[1]


def rect_area(r: Rect) -> float:
    return max(rect_w(r), 0.0) * max(rect_h(r), 0.0)


def rect_cx(r: Rect) -> float:
    return (r[0] + r[2]) / 2.0


def rect_cy(r: Rect) -> float:
    return (r[1] + r[3]) / 2.0


@dataclass
class TextLine:
    """One rendered line of text with its bounding box."""

    bbox: Rect
    text: str


@dataclass
class ImagePlacement:
    """An embedded image XObject as it is placed on the page.

    Some products are printed as a contiguous block of the *same* image repeated
    (a 2x2 swatch showing how the tile repeats). Those placements are coalesced
    into one record: `bbox` is then the union of the block, while `unit_bbox` is
    a single cell -- i.e. one tile. Layout questions (labels, reading order, area)
    use `bbox`; questions about the tile's own shape use `unit_bbox`.
    """

    xref: int
    bbox: Rect
    stored_w: int
    stored_h: int
    rotation: int  # 0/90/180/270, derived from the placement matrix
    flipped: bool = False
    unit_bbox: Optional[Rect] = None
    repeat_x: int = 1
    repeat_y: int = 1
    # The distinct tile faces printed inside this block, in reading order. A plain
    # tile and a repeat swatch have exactly one; a bookmatch pair has two; a
    # multi-panel mural has one per panel. All share the block's single name.
    members: List["ImagePlacement"] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.unit_bbox is None:
            self.unit_bbox = self.bbox
        if not self.members:
            self.members = [self]

    @property
    def placed_w(self) -> float:
        return rect_w(self.bbox)

    @property
    def placed_h(self) -> float:
        return rect_h(self.bbox)

    @property
    def unit_w(self) -> float:
        return rect_w(self.unit_bbox)

    @property
    def unit_h(self) -> float:
        return rect_h(self.unit_bbox)

    @property
    def is_repeat_block(self) -> bool:
        return self.repeat_x > 1 or self.repeat_y > 1

    @property
    def placed_ratio(self) -> float:
        """Orientation-agnostic long/short ratio of a single tile as printed."""
        lo = min(self.unit_w, self.unit_h)
        return (max(self.unit_w, self.unit_h) / lo) if lo > 0 else 0.0


@dataclass(frozen=True)
class SizeSpec:
    """A tile size read from a page header. Length is always the larger value."""

    length_mm: int
    width_mm: int

    @property
    def ratio(self) -> float:
        """Long/short ratio, orientation-agnostic."""
        return self.length_mm / self.width_mm if self.width_mm else 0.0

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.length_mm}x{self.width_mm}mm"


@dataclass
class Half:
    """One logical catalogue page: half of a printed two-page spread."""

    page_index: int  # 0-based PDF page index
    side: str  # 'L' or 'R'
    rect: Rect
    sizes: List[SizeSpec] = field(default_factory=list)
    lines: List[TextLine] = field(default_factory=list)
    images: List[ImagePlacement] = field(default_factory=list)
    skip_reason: Optional[str] = None

    @property
    def label(self) -> str:
        return f"p{self.page_index + 1}{self.side}"

    @property
    def area(self) -> float:
        return rect_area(self.rect)


@dataclass
class Tile:
    """A classified tile: placement plus everything bound and produced for it."""

    page_index: int
    side: str
    order: int  # position within the half, reading order
    placement: ImagePlacement
    name: Optional[str] = None
    size: Optional[SizeSpec] = None
    flags: List[str] = field(default_factory=list)
    image_name: Optional[str] = None
    out_w: int = 0
    out_h: int = 0
    steps: Dict[str, object] = field(default_factory=dict)  # cleanup bookkeeping

    @property
    def half_label(self) -> str:
        return f"p{self.page_index + 1}{self.side}"

    def flag(self, code: str) -> None:
        if code not in self.flags:
            self.flags.append(code)


@dataclass
class Rejection:
    """An image the classifier deliberately did not treat as a tile."""

    half_label: str
    xref: int
    bbox: Rect
    reason: str
