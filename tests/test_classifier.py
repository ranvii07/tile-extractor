"""Stage 2: block coalescing and the tile / non-tile decision, on synthetic coords."""

from src.classifier import classify_half, coalesce_blocks, reading_order
from tests.helpers import half, img, size


# --- coalesce_blocks -------------------------------------------------------

def test_separately_named_tiles_are_not_merged():
    """Distinct products sit >= 11pt apart; only abutting cells form a block."""
    tiles = [img(0, 0, 100, 50, xref=1), img(140, 0, 240, 50, xref=2)]
    blocks = coalesce_blocks(tiles)
    assert len(blocks) == 2
    assert all(not b.is_repeat_block for b in blocks)


def test_a_repeat_swatch_becomes_one_product_with_one_face():
    """A 2x2 grid of the SAME image is one tile shown four times."""
    cells = [img(0, 0, 100, 100, xref=7), img(100, 0, 200, 100, xref=7),
             img(0, 100, 100, 200, xref=7), img(100, 100, 200, 200, xref=7)]
    blocks = coalesce_blocks(cells)

    assert len(blocks) == 1
    block = blocks[0]
    assert (block.repeat_x, block.repeat_y) == (2, 2)
    assert len(block.members) == 1              # one distinct face
    assert block.bbox == (0, 0, 200, 200)       # union, for label binding
    assert block.unit_bbox == (0, 0, 100, 100)  # one tile, for shape questions


def test_a_bookmatch_pair_keeps_both_faces_under_one_name():
    cells = [img(0, 0, 100, 200, xref=11), img(100, 0, 200, 200, xref=12)]
    blocks = coalesce_blocks(cells)

    assert len(blocks) == 1
    assert len(blocks[0].members) == 2
    assert [m.xref for m in blocks[0].members] == [11, 12]


def test_a_three_panel_mural_keeps_all_panels_in_reading_order():
    cells = [img(0, 200, 100, 300, xref=3), img(0, 0, 100, 100, xref=1),
             img(0, 100, 100, 200, xref=2)]
    blocks = coalesce_blocks(cells)

    assert len(blocks) == 1
    assert [m.xref for m in blocks[0].members] == [1, 2, 3]


def test_touching_cells_of_different_sizes_stay_separate():
    """Abutment alone is not enough -- the cells must also be the same size."""
    cells = [img(0, 0, 100, 100, xref=1), img(100, 0, 300, 100, xref=2)]
    assert len(coalesce_blocks(cells)) == 2


# --- classify_half ---------------------------------------------------------

HEADER = size(600, 300)  # ratio 2.0


def test_a_grid_of_equal_tiles_is_accepted():
    tiles = [img(0, 0, 100, 50, xref=1), img(140, 0, 240, 50, xref=2),
             img(280, 0, 380, 50, xref=3)]
    accepted, rejected = classify_half(half(sizes=[HEADER], images=tiles))

    assert len(accepted) == 3
    assert rejected == []


def test_a_room_scene_is_rejected_as_too_large():
    tiles = [img(0, 0, 100, 50, xref=1), img(140, 0, 240, 50, xref=2),
             img(0, 300, 400, 600, xref=9)]  # 25% of the half
    accepted, rejected = classify_half(half(sizes=[HEADER], images=tiles))

    assert [p.xref for p in accepted] == [1, 2]
    assert len(rejected) == 1
    assert "too large" in rejected[0].reason


def test_a_logo_is_rejected_as_too_small():
    tiles = [img(0, 0, 100, 50, xref=1), img(140, 0, 240, 50, xref=2),
             img(0, 700, 104, 724, xref=9)]  # 104x24pt: the measured logo
    accepted, rejected = classify_half(half(sizes=[HEADER], images=tiles))

    assert [p.xref for p in accepted] == [1, 2]
    assert "too small" in rejected[0].reason


def test_a_lone_image_is_kept_only_when_its_shape_matches_the_header():
    hero = img(0, 0, 200, 100, xref=1)      # ratio 2.0, matches 600x300
    oddity = img(0, 300, 150, 450, xref=2)  # ratio 1.0, matches nothing
    accepted, rejected = classify_half(half(sizes=[HEADER], images=[hero, oddity]))

    assert [p.xref for p in accepted] == [1]
    assert "matches no header size" in rejected[0].reason


def test_a_skipped_half_produces_nothing():
    tiles = [img(0, 0, 100, 50, xref=1), img(140, 0, 240, 50, xref=2)]
    accepted, rejected = classify_half(
        half(sizes=[HEADER], images=tiles, skip_reason="cover page"))

    assert accepted == [] and rejected == []


def test_a_repeat_block_is_judged_on_one_cell_not_the_whole_grid():
    """A 2x2 swatch covers 23% of a half but each tile in it is a normal size."""
    cells = [img(0, 0, 240, 240, xref=7), img(240, 0, 480, 240, xref=7),
             img(0, 240, 240, 480, xref=7), img(240, 240, 480, 480, xref=7)]
    # Union is 480x480 = 48% of the 600x800 half; one cell is 240x240 = 12%.
    accepted, rejected = classify_half(half(sizes=[size(600, 600)], images=cells))

    assert len(accepted) == 1
    assert rejected == []


# --- reading_order ---------------------------------------------------------

def test_reading_order_is_left_to_right_then_top_to_bottom():
    a = img(200, 0, 300, 50, xref=2)
    b = img(0, 0, 100, 50, xref=1)
    c = img(0, 300, 100, 350, xref=3)
    assert [p.xref for p in reading_order([c, a, b])] == [1, 2, 3]
