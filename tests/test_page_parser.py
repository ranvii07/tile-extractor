"""Stage 1: size-header parsing, spread splitting and placement rotation."""

import pytest

from src.models import SizeSpec
from src.page_parser import (HEADER_BAND_FRAC, _half_rects, _placement_rotation,
                             find_header_sizes, parse_size_text)
from tests.helpers import line


class FakeRect:
    """Duck-types the (x0, y0, x1, y1) unpacking that _half_rects does."""

    def __init__(self, x0, y0, x1, y1):
        self._v = (x0, y0, x1, y1)

    def __iter__(self):
        return iter(self._v)


# --- parse_size_text -------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("600x1200mm", [SizeSpec(1200, 600)]),
    ("600X1200MM", [SizeSpec(1200, 600)]),
    ("300 x 450 mm", [SizeSpec(450, 300)]),
    ("300×450mm", [SizeSpec(450, 300)]),          # unicode multiplication sign
    ("SIZE : 1000x300mm", [SizeSpec(1000, 300)]),
])
def test_reads_the_size_forms_the_catalogue_prints(text, expected):
    assert parse_size_text(text) == expected


def test_length_is_always_the_larger_value():
    """The core normalisation: orientation on the page never changes L vs W."""
    assert parse_size_text("600x1200mm") == parse_size_text("1200x600mm")
    spec = parse_size_text("300x600mm")[0]
    assert (spec.length_mm, spec.width_mm) == (600, 300)


def test_collects_several_sizes_in_order_without_duplicates():
    text = "STEP 1000x300mm  RISER 1000x200mm  STEP 1000x300mm"
    assert parse_size_text(text) == [SizeSpec(1000, 300), SizeSpec(1000, 200)]


@pytest.mark.parametrize("text", [
    "",
    "GOLD-02",                # a product name
    "1200x600",               # no mm unit -> not a size header
    "12x24 inch",             # the inch half of the header
    "10x20mm",                # below MIN_SIZE_MM: a stray number
    "4000x5000mm",            # above MAX_SIZE_MM
    "Page 37",
])
def test_rejects_text_that_is_not_a_tile_size(text):
    assert parse_size_text(text) == []


# --- find_header_sizes -----------------------------------------------------

def test_header_is_read_from_the_top_band_only():
    """The index page lists sizes too -- but far below the header band."""
    rect = (0.0, 0.0, 600.0, 800.0)
    cutoff = HEADER_BAND_FRAC * 800.0  # 120pt

    in_band = line(40, 50, 200, 62, "600x1200mm")
    below_band = line(40, 300, 200, 312, "300x450mm")
    assert cutoff < 300

    assert find_header_sizes(rect, [in_band, below_band]) == [SizeSpec(1200, 600)]


def test_a_half_with_no_header_yields_no_sizes():
    rect = (0.0, 0.0, 600.0, 800.0)
    assert find_header_sizes(rect, [line(40, 40, 200, 52, "INDEX")]) == []


def test_dual_header_keeps_reading_order():
    """Step/riser pages declare two sizes; order matters for the report."""
    rect = (0.0, 0.0, 600.0, 800.0)
    lines = [line(40, 50, 200, 62, "STEP 1000x300mm"),
             line(40, 70, 200, 82, "RISER 1000x200mm")]
    assert find_header_sizes(rect, lines) == [SizeSpec(1000, 300), SizeSpec(1000, 200)]


# --- _half_rects -----------------------------------------------------------

def test_a_wide_page_splits_into_two_halves_at_the_midline():
    halves = _half_rects(FakeRect(0, 0, 1191, 865))  # measured spread size
    assert [side for side, _ in halves] == ["L", "R"]
    (_, left), (_, right) = halves
    assert left[2] == right[0] == pytest.approx(595.5)


def test_a_portrait_page_is_treated_as_one_half():
    halves = _half_rects(FakeRect(0, 0, 595, 842))
    assert [side for side, _ in halves] == ["S"]


# --- _placement_rotation ---------------------------------------------------

@pytest.mark.parametrize("matrix, expected", [
    ((100, 0, 0, 100, 0, 0), 0),        # placed upright
    ((0, 100, -100, 0, 0, 0), 90),      # turned a quarter clockwise
    ((-100, 0, 0, -100, 0, 0), 180),
    ((0, -100, 100, 0, 0, 0), 270),
])
def test_rotation_comes_from_the_placement_matrix(matrix, expected):
    angle, _ = _placement_rotation(matrix)
    assert angle == expected


def test_a_mirrored_placement_is_reported_as_flipped():
    _, flipped = _placement_rotation((100, 0, 0, -100, 0, 0))
    assert flipped is True
    _, upright = _placement_rotation((100, 0, 0, 100, 0, 0))
    assert upright is False
