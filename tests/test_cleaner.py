"""Stage 4b: the three cleanup steps and the guards that keep them conservative."""

import numpy as np
import pytest
from PIL import Image

from src.cleaner import clean, enforce_aspect, meet_resolution, trim_borders

RNG = np.random.default_rng(20240607)


def patterned(h, w, lo=90, hi=150):
    return RNG.integers(lo, hi, (h, w, 3), dtype=np.uint8)


def with_border(h, w, pad, level=250, **kw):
    """A patterned tile surrounded by `pad` px of flat page background."""
    arr = np.full((h, w, 3), level, np.uint8)
    arr[pad:h - pad, pad:w - pad] = patterned(h - 2 * pad, w - 2 * pad, **kw)
    return Image.fromarray(arr)


# --- trim_borders ----------------------------------------------------------

def test_a_flat_border_around_a_pattern_is_removed():
    trimmed, steps = trim_borders(with_border(200, 200, 10), target_ratio=1.0)
    assert trimmed.size == (180, 180)
    assert steps["trim"] == (10, 10, 10, 10)


def test_a_plain_white_tile_is_left_alone():
    """The regression this guard exists for: every row of a plain tile is flat
    and near-white, so without the interior test the trimmer eats the product."""
    arr = np.full((200, 200, 3), 252, np.uint8)
    arr = np.clip(arr.astype(int) + RNG.integers(-2, 3, arr.shape), 0, 255).astype(np.uint8)

    trimmed, steps = trim_borders(Image.fromarray(arr), target_ratio=1.0)

    assert trimmed.size == (200, 200)
    assert steps["trim"] == (0, 0, 0, 0)
    assert steps["trim_choice"] == "none"


def test_a_dark_plain_tile_is_also_left_alone():
    arr = np.full((200, 200, 3), 6, np.uint8)
    trimmed, _ = trim_borders(Image.fromarray(arr), target_ratio=1.0)
    assert trimmed.size == (200, 200)


def test_trimming_never_exceeds_the_per_edge_cap():
    """A 20px border is wider than the 6% cap allows, so the trim stops short
    and says so rather than cutting until it finds pattern."""
    trimmed, steps = trim_borders(with_border(200, 200, 20), target_ratio=1.0)

    assert min(trimmed.size) >= int(200 * (1 - 2 * 0.085))  # background + shadow caps
    assert "background" in steps["trim_capped"]


def test_a_border_wide_enough_to_dominate_the_interior_is_not_trimmed():
    """With a 60px border on a 200px image the middle of the picture is mostly
    border, so the interior test can no longer tell tile from page -- and the
    trimmer's bias is to leave a sliver rather than risk eating the product."""
    trimmed, steps = trim_borders(with_border(200, 200, 60), target_ratio=1.0)

    assert trimmed.size == (200, 200)
    assert steps["trim_choice"] == "none"


def test_a_trim_that_would_worsen_the_proportions_is_discarded():
    """Border on the left/right only of a 2:1 tile: cropping width moves the
    aspect away from 2.0, so the horizontal trim must be rejected."""
    arr = np.full((200, 400, 3), 250, np.uint8)
    arr[:, 20:380] = patterned(200, 360)

    trimmed, steps = trim_borders(Image.fromarray(arr), target_ratio=2.0)

    assert steps["trim_choice"] == "none"
    assert trimmed.size == (400, 200)


def test_a_trim_that_improves_the_proportions_is_kept():
    """Same picture, but the tile is really 2:1 and the border is top/bottom."""
    arr = np.full((240, 400, 3), 250, np.uint8)
    arr[20:220, :] = patterned(200, 400)

    trimmed, steps = trim_borders(Image.fromarray(arr), target_ratio=2.0)

    assert steps["trim_choice"] in ("vertical", "both")
    assert trimmed.height < 240
    assert abs(trimmed.width / trimmed.height - 2.0) < abs(400 / 240 - 2.0)


def test_with_no_target_ratio_trimming_still_removes_a_real_border():
    trimmed, _ = trim_borders(with_border(200, 200, 8), target_ratio=0.0)
    assert trimmed.size == (184, 184)


# --- enforce_aspect --------------------------------------------------------

def test_an_aspect_within_tolerance_is_untouched():
    img = Image.fromarray(patterned(100, 201))  # 2.01 vs a 2.0 target
    out, steps = enforce_aspect(img, 600, 300)
    assert out.size == (201, 100)
    assert steps["aspect"] == "within-tolerance"


def test_a_too_wide_image_is_centre_cropped_on_the_long_axis():
    img = Image.fromarray(patterned(100, 220))
    out, _ = enforce_aspect(img, 600, 300)
    assert out.size == (200, 100)


def test_a_too_tall_image_is_cropped_on_height():
    img = Image.fromarray(patterned(110, 200))  # a 9% crop, inside the cap
    out, _ = enforce_aspect(img, 600, 300)
    assert out.size == (200, 100)


def test_a_portrait_placement_keeps_its_portrait_orientation():
    """A 1200x600 tile printed upright must not be rotated to landscape: the
    target ratio is expressed in the image's own orientation (0.5, not 2.0)."""
    img = Image.fromarray(patterned(400, 220))  # taller than wide
    out, _ = enforce_aspect(img, 1200, 600)
    assert out.height > out.width
    assert out.size == (200, 400)


def test_a_crop_beyond_the_safety_cap_is_refused_rather_than_clipping():
    img = Image.fromarray(patterned(100, 300))  # needs a 33% crop
    out, steps = enforce_aspect(img, 600, 300)
    assert out.size == (300, 100)               # unchanged
    assert steps["aspect"] == "crop-refused"


def test_without_a_size_the_aspect_step_is_skipped():
    img = Image.fromarray(patterned(100, 300))
    out, steps = enforce_aspect(img, 0, 0)
    assert out.size == (300, 100)
    assert steps["aspect"] == "skipped-no-size"


# --- meet_resolution -------------------------------------------------------

def test_an_image_below_one_pixel_per_millimetre_is_upscaled():
    img = Image.fromarray(patterned(150, 300))
    out, steps = meet_resolution(img, 600, 300)
    assert out.size[0] >= 600 and out.size[1] >= 300
    assert steps["scale"] == pytest.approx(2.0)


def test_an_image_already_above_the_floor_is_never_downscaled():
    img = Image.fromarray(patterned(400, 800))
    out, steps = meet_resolution(img, 600, 300)
    assert out.size == (800, 400)
    assert steps["scale"] == 1.0


def test_the_floor_follows_the_images_own_orientation():
    img = Image.fromarray(patterned(300, 150))  # portrait
    out, _ = meet_resolution(img, 600, 300)
    assert out.size[0] >= 300 and out.size[1] >= 600


# --- clean (the three steps together) --------------------------------------

def test_clean_produces_the_declared_size_at_the_declared_ratio():
    out, steps = clean(with_border(150, 300, 6), 600, 300)

    assert out.width >= 600 and out.height >= 300
    assert out.width / out.height == pytest.approx(2.0, abs=0.02)
    assert steps["final"] == out.size


def test_clean_leaves_a_plain_white_tile_square_and_whole():
    arr = np.full((300, 300, 3), 252, np.uint8)
    out, steps = clean(Image.fromarray(arr), 300, 300)

    assert steps["trim"] == (0, 0, 0, 0)
    assert out.size == (300, 300)
