"""End-to-end checks against hand-verified pages of the reference catalogue.

Each page here was read by eye and the expected output written down before the
code was pointed at it, so these are the tests that would catch a regression the
unit tests cannot see -- a layout rule that stops matching the real document.

Skipped automatically when the catalogue PDF is not present. Point the
TILE_CATALOGUE_PDF environment variable at it to run them elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from src.binder import bind_half
from src.classifier import classify_half
from src.models import SizeSpec
from src.page_parser import parse_document

DEFAULT_PDF = Path.home() / "Downloads" / "Copy of Odisha Catalogue .pdf"
PDF_PATH = Path(os.environ.get("TILE_CATALOGUE_PDF", DEFAULT_PDF))

pytestmark = pytest.mark.skipif(
    not PDF_PATH.is_file(), reason=f"reference catalogue not found at {PDF_PATH}")


@pytest.fixture(scope="module")
def catalogue():
    """Every tile in the catalogue, keyed by half label (e.g. 'p51L')."""
    doc = pymupdf.open(PDF_PATH)
    try:
        halves = parse_document(doc)
        kept = [h for h in halves if not h.skip_reason]

        vocabulary: list[SizeSpec] = []
        for h in kept:
            for s in h.sizes:
                if s not in vocabulary:
                    vocabulary.append(s)

        by_half: dict[str, list] = {}
        for h in kept:
            accepted, _ = classify_half(h)
            tiles, _ = bind_half(h, accepted, vocabulary)
            by_half[h.label] = tiles
        return {"halves": halves, "kept": kept, "tiles": by_half}
    finally:
        doc.close()


def tiles_on(catalogue, label):
    return catalogue["tiles"].get(label, [])


# --- whole-document shape --------------------------------------------------

def test_the_expected_number_of_tiles_is_found(catalogue):
    total = sum(len(v) for v in catalogue["tiles"].values())
    assert total == 1019


def test_only_the_cover_index_and_back_pages_are_skipped(catalogue):
    skipped = sorted(h.label for h in catalogue["halves"] if h.skip_reason)
    assert skipped == ["p1L", "p1R", "p2L", "p2R", "p88R"]


def test_every_tile_has_a_name_and_a_size(catalogue):
    unnamed = [t for v in catalogue["tiles"].values() for t in v if not t.name]
    unsized = [t for v in catalogue["tiles"].values() for t in v if not t.size]
    assert unnamed == []
    assert unsized == []


def test_length_is_never_smaller_than_width(catalogue):
    for tiles in catalogue["tiles"].values():
        for t in tiles:
            assert t.size.length_mm >= t.size.width_mm


# --- p3: the simplest page, three tiles under one header -------------------

def test_page_3_left_reads_three_named_tiles(catalogue):
    tiles = tiles_on(catalogue, "p3L")
    assert [t.name for t in tiles] == ["GOLD-02", "GOLD-03", "GOLD-09"]
    assert all(t.size == SizeSpec(1200, 600) for t in tiles)
    assert all(t.flags == [] for t in tiles)


# --- p4: a tile stored landscape but placed portrait -----------------------

def test_page_4_left_handles_the_rotated_tile(catalogue):
    """GOLD-28's bitmap is stored 756x382 but placed upright by a 90 degree
    matrix. Orientation must come from the placement, not the stored pixels."""
    tiles = tiles_on(catalogue, "p4L")
    gold_28 = next(t for t in tiles if t.name == "GOLD-28")

    assert gold_28.placement.stored_w > gold_28.placement.stored_h  # stored landscape
    assert gold_28.placement.rotation == 90
    assert gold_28.placement.placed_h > gold_28.placement.placed_w  # placed portrait
    assert gold_28.size == SizeSpec(1200, 600)


def test_page_4_left_reads_six_tiles_in_printed_order(catalogue):
    assert [t.name for t in tiles_on(catalogue, "p4L")] == [
        "GOLD-28", "EL-7002", "EL-7007", "EL-7012", "EL-7016", "EL-7020"]


# --- p51: square companion tiles measured off the page scale ---------------

def test_page_51_left_measures_the_square_companion_tiles(catalogue):
    """The -F tiles are square on a 450x300 page; their size is derived from the
    page scale and snapped to the 300x300 the catalogue prints elsewhere."""
    tiles = tiles_on(catalogue, "p51L")
    by_name = {t.name: t for t in tiles}

    assert by_name["915-F"].size == SizeSpec(300, 300)
    assert by_name["911-F"].size == SizeSpec(300, 300)
    assert "size-measured" in by_name["915-F"].flags
    assert "size-aspect-mismatch" not in by_name["915-F"].flags

    wall_tiles = [t for n, t in by_name.items() if not n.endswith("-F")]
    assert all(t.size == SizeSpec(450, 300) for t in wall_tiles)


def test_page_51_left_finds_all_ten_tiles(catalogue):
    assert len(tiles_on(catalogue, "p51L")) == 10


# --- p87 / p88: dual-size step-and-riser pages -----------------------------

def test_page_87_pairs_each_step_and_riser_with_its_own_size(catalogue):
    tiles = tiles_on(catalogue, "p87L")
    assert [(t.name, t.size.length_mm, t.size.width_mm) for t in tiles] == [
        ("RS-1003-S", 1000, 300),
        ("RS-1003-R", 1000, 200),
        ("RS-1004-S", 1000, 300),
        ("RS-1004-R", 1000, 200),
        ("RS-1060 -S", 1000, 300),
        ("RS-1060-R", 1000, 200),
    ]


def test_page_88_uses_the_900mm_step_and_riser_sizes(catalogue):
    tiles = tiles_on(catalogue, "p88L")
    assert [(t.name, t.size.length_mm, t.size.width_mm) for t in tiles] == [
        ("RS-07-S", 900, 300),
        ("RS-07-R", 900, 200),
        ("RS-13-S", 900, 300),
        ("RS-13-R", 900, 200),
        ("WOODEN TEAK-S", 900, 300),
        ("WOODEN TEAK-R", 900, 200),
    ]


def test_the_step_riser_headers_declare_two_sizes(catalogue):
    """The dual-size case the binder's per-tile header choice exists for."""
    half_87 = next(h for h in catalogue["kept"] if h.label == "p87L")
    assert half_87.sizes == [SizeSpec(1000, 300), SizeSpec(1000, 200)]


# --- multi-face products ---------------------------------------------------

def test_a_bookmatch_pair_shares_one_printed_name(catalogue):
    faces = [t for v in catalogue["tiles"].values() for t in v if t.name == "BM-9018"]
    assert len(faces) == 2
    assert all("shared-name" in t.flags for t in faces)


def test_a_three_panel_mural_yields_one_tile_per_panel(catalogue):
    faces = [t for v in catalogue["tiles"].values()
             if v for t in v if t.name == "3416-HL-1-P1-P2-P3"]
    assert len(faces) == 3
    assert all("shared-name" in t.flags for t in faces)
