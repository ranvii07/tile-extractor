"""Stage 3: the stop-list, label binding by geometry, and size derivation."""

import pytest

from src.binder import (bind_half, bind_names, candidate_labels, choose_size,
                        is_stop_line, measure_size, normalise_name, page_scale)
from tests.helpers import half, img, line, size


# --- normalise_name / stop-list --------------------------------------------

def test_normalise_collapses_whitespace_and_drops_mojibake():
    assert normalise_name("  ROLEX   BEIGE-HL  ") == "ROLEX BEIGE-HL"
    assert normalise_name("EL­-7002�") == "EL-7002"


@pytest.mark.parametrize("text", [
    "",
    "SIZE :",
    "FINISH",
    "F I N I S H",        # letter-spaced heading: the stop key ignores spacing
    "F",                  # ...and the same heading split into one line per letter
    "High Gloss",
    "GLOSS",
    "600x1200mm",         # a size caption is never a name
    "PGVT",
    "STEP RISER",
    "WOODEN SERIES",      # section banner
    "DIGITAL WALL TILES",
])
def test_page_furniture_is_not_a_product_name(text):
    assert is_stop_line(text) is True


@pytest.mark.parametrize("text", [
    "GOLD-02",
    "EL-09 (MATT)",       # substring matching would have eaten this via "MATT"
    "ESTILA CREMA",
    "RS-1004-R",
    "5335",               # bare numbers are genuine names in this catalogue
    "10122",
])
def test_genuine_product_names_survive(text):
    assert is_stop_line(text) is False


def test_a_bare_number_is_a_folio_only_in_the_margin():
    assert is_stop_line("37", in_margin=True) is True
    assert is_stop_line("37", in_margin=False) is False


def test_candidate_labels_treats_the_bottom_band_as_margin():
    rect = (0.0, 0.0, 600.0, 800.0)          # margin starts at y = 752
    folio = line(300, 770, 320, 782, "37")
    name = line(40, 700, 120, 712, "88")     # a genuine name well above the margin
    kept = candidate_labels([folio, name], rect)
    assert [l.text for l in kept] == ["88"]


# --- bind_names ------------------------------------------------------------

def test_labels_bind_to_the_image_directly_above_them():
    images = [img(50, 100, 150, 200, xref=1), img(200, 100, 300, 200, xref=2)]
    lines = [line(50, 205, 90, 215, "GOLD-02"), line(200, 205, 240, 215, "GOLD-03")]

    names, leftovers = bind_names(images, lines)

    assert names == {0: "GOLD-02", 1: "GOLD-03"}
    assert leftovers == []


def test_binding_is_per_row_so_rows_do_not_steal_each_others_labels():
    images = [img(50, 100, 150, 200, xref=1), img(50, 300, 150, 400, xref=2)]
    lines = [line(50, 205, 90, 215, "TOP"), line(50, 405, 90, 415, "BOTTOM")]

    names, _ = bind_names(images, lines)

    assert names == {0: "TOP", 1: "BOTTOM"}


def test_a_row_with_one_missing_label_still_binds_the_rest():
    images = [img(50, 100, 150, 200, xref=1), img(200, 100, 300, 200, xref=2),
              img(350, 100, 450, 200, xref=3)]
    lines = [line(50, 205, 90, 215, "FIRST"), line(350, 205, 400, 215, "THIRD")]

    names, leftovers = bind_names(images, lines)

    assert names == {0: "FIRST", 2: "THIRD"}
    assert leftovers == []


def test_a_label_too_far_from_any_image_is_left_over():
    images = [img(50, 100, 150, 200, xref=1)]
    lines = [line(400, 205, 460, 215, "ELSEWHERE")]

    names, leftovers = bind_names(images, lines)

    assert names == {}
    assert [l.text for l in leftovers] == ["ELSEWHERE"]


def test_a_label_far_below_the_image_does_not_bind():
    """Beyond MAX_LABEL_GAP_PT it belongs to something else, not this row."""
    images = [img(50, 100, 150, 200, xref=1)]
    lines = [line(50, 260, 90, 270, "TOO FAR")]

    names, leftovers = bind_names(images, lines)

    assert names == {}
    assert len(leftovers) == 1


def test_stop_lines_are_never_bound_as_names():
    images = [img(50, 100, 150, 200, xref=1)]
    lines = [line(50, 205, 90, 215, "High Gloss")]

    names, leftovers = bind_names(images, lines)

    assert names == {}
    assert leftovers == []  # filtered out before binding, not reported as unused


# --- choose_size -----------------------------------------------------------

def test_a_single_header_applies_to_every_tile():
    chosen, flags = choose_size(img(0, 0, 100, 50), [size(600, 300)])
    assert chosen == size(600, 300)
    assert flags == []


def test_step_and_riser_each_take_the_header_matching_their_shape():
    headers = [size(1000, 300), size(1000, 200)]

    step, step_flags = choose_size(img(0, 0, 300, 90), headers)    # ratio 3.33
    riser, riser_flags = choose_size(img(0, 0, 300, 60), headers)  # ratio 5.0

    assert step == size(1000, 300) and step_flags == []
    assert riser == size(1000, 200) and riser_flags == []


def test_a_shape_that_contradicts_the_header_is_flagged():
    """A square tile on a 600x300 wall page: 100% off, far beyond tolerance."""
    _, flags = choose_size(img(0, 0, 100, 100), [size(600, 300)])
    assert "size-aspect-mismatch" in flags


def test_no_header_means_no_size():
    chosen, flags = choose_size(img(0, 0, 100, 50), [])
    assert chosen is None
    assert flags == ["no-size-header"]


# --- page_scale / measure_size ---------------------------------------------

def test_page_scale_is_points_per_millimetre_from_matching_tiles():
    pairs = [(img(0, 0, 300, 150), size(600, 300)),
             (img(0, 0, 300, 150), size(600, 300))]
    assert page_scale(pairs) == pytest.approx(0.5)


def test_page_scale_is_a_median_so_one_outlier_cannot_skew_it():
    pairs = [(img(0, 0, 300, 150), size(600, 300)),
             (img(0, 0, 300, 150), size(600, 300)),
             (img(0, 0, 900, 450), size(600, 300))]  # outlier at 1.5 pt/mm
    assert page_scale(pairs) == pytest.approx(0.5)


def test_page_scale_is_undefined_without_any_matching_tile():
    assert page_scale([]) is None


def test_a_measured_size_snaps_to_a_size_the_catalogue_prints():
    """150pt at 0.5 pt/mm is 300mm -- snap to the listed 300x300, not 301x300."""
    measured, note = measure_size(img(0, 0, 150.5, 150), 0.5,
                                  [size(600, 300), size(300, 300)])
    assert measured == size(300, 300)
    assert note == "size-measured"


def test_a_measured_size_with_no_match_is_rounded_and_marked_unlisted():
    measured, note = measure_size(img(0, 0, 111, 111), 0.5, [size(600, 300)])
    assert measured == size(220, 220)
    assert note == "size-measured-unlisted"


def test_measuring_is_refused_without_a_page_scale():
    measured, note = measure_size(img(0, 0, 150, 150), 0.0, [size(300, 300)])
    assert measured is None
    assert note == "no-page-scale"


# --- bind_half (integration over the stage) --------------------------------

def test_square_companion_tile_is_measured_from_the_page_scale():
    """The p51 case: 450x300 wall tiles plus a square 300x300 companion."""
    header = size(450, 300)
    wall_a = img(50, 100, 200, 200, xref=1)   # 150x100pt -> ratio 1.5, matches
    wall_b = img(250, 100, 400, 200, xref=2)
    square = img(450, 100, 550, 200, xref=3)  # 100x100pt -> contradicts header
    lines = [line(50, 205, 90, 215, "915-L"),
             line(250, 205, 290, 215, "915-HL"),
             line(450, 205, 490, 215, "915-F")]

    tiles, leftovers = bind_half(
        half(sizes=[header], lines=lines, images=[wall_a, wall_b, square]),
        [wall_a, wall_b, square],
        vocabulary=[size(450, 300), size(300, 300)],
    )

    assert [t.name for t in tiles] == ["915-L", "915-HL", "915-F"]
    assert [t.size for t in tiles] == [header, header, size(300, 300)]
    assert "size-measured" in tiles[2].flags
    assert "size-aspect-mismatch" not in tiles[2].flags
    assert leftovers == []


def test_one_block_with_several_faces_shares_a_single_name():
    left = img(50, 100, 150, 300, xref=11)
    right = img(150, 100, 250, 300, xref=12)
    block = img(50, 100, 250, 300, xref=11, unit_bbox=(50, 100, 150, 300),
                repeat_x=2, repeat_y=1, members=[left, right])
    lines = [line(50, 305, 110, 315, "BM-9018")]

    tiles, _ = bind_half(half(sizes=[size(600, 300)], lines=lines, images=[block]),
                         [block])

    assert len(tiles) == 2
    assert {t.name for t in tiles} == {"BM-9018"}
    assert all("shared-name" in t.flags for t in tiles)


def test_a_tile_with_no_bindable_label_is_flagged_not_dropped():
    tile = img(50, 100, 150, 200, xref=1)
    tiles, _ = bind_half(half(sizes=[size(600, 300)], lines=[], images=[tile]), [tile])

    assert len(tiles) == 1
    assert tiles[0].name is None
    assert "missing-label" in tiles[0].flags
