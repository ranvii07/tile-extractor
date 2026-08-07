"""Stage 4b — turn an extracted bitmap into a clean, correctly proportioned tile.

Three steps, in order, each conservative by design:

1. **Trim** uniform near-white / near-black border rows and columns, plus soft
   drop-shadow ramps, with a hard per-edge cap so a pattern can never be eaten.
2. **Enforce aspect** by centre-cropping the long axis to the tile's mm ratio.
   Never stretch, never pad -- a squashed tile fails the brief outright.
3. **Meet the resolution floor** with Lanczos upscaling so pixels >= millimetres
   on both axes. Never downscale.

The bias throughout is that a sliver of leftover border is a much smaller error
than a clipped tile design, so every step stops early and flags rather than
cutting deeper.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

# --- Calibration constants -------------------------------------------------

# Hard cap on how much of an edge trimming may remove. The catalogue's borders
# are a few pixels at most; anything beyond this is pattern, not border.
TRIM_MAX_FRAC = 0.06

# A row/column counts as flat when its 2nd-98th percentile spread is this small
# in every channel (percentiles, so one stray pixel cannot block a trim).
UNIFORM_SPREAD = 6

# Flat lines this bright or this dark are page background, not tile.
NEAR_WHITE = 244
NEAR_BLACK = 12

# ...but only if they also differ from the tile's own interior by this much.
# Without it, a plain white tile reads as border on every edge (measured: the
# trimmer removed 14% of PLAIN WHITE and SUPER WHITE before this guard existed).
INTERIOR_DELTA = 18

# Second pass: soft drop shadows sit on the right and bottom edges as flat grey
# ramps. Trimmed under a tighter cap because mid-greys can also be tile design.
SHADOW_MAX_FRAC = 0.025
SHADOW_SPREAD = 8
SHADOW_MIN_MEAN = 200

# Aspect within this of the target is left untouched (measured: most tiles are
# within 1.5%). Beyond it, the long axis is centre-cropped.
ASPECT_TOL = 0.02

# Refuse to crop more than this off the long axis; flag instead of clipping.
MAX_CROP_FRAC = 0.12


def _flat(line: np.ndarray, spread: int) -> bool:
    hi = np.percentile(line, 98, axis=0)
    lo = np.percentile(line, 2, axis=0)
    return bool(np.all((hi - lo) <= spread))


def _interior_level(arr: np.ndarray) -> float:
    """Median brightness of the middle of the image -- i.e. of the tile itself."""
    h, w = arr.shape[:2]
    y0, y1 = int(h * 0.2), max(int(h * 0.8), int(h * 0.2) + 1)
    x0, x1 = int(w * 0.2), max(int(w * 0.8), int(w * 0.2) + 1)
    return float(np.median(arr[y0:y1, x0:x1]))


def _is_background(line: np.ndarray, interior: float) -> bool:
    """A flat page-coloured line that is clearly not the tile's own surface.

    The distance-from-interior test is what protects plain tiles: on a PLAIN
    WHITE tile every row is flat and near-white, so without it the trimmer would
    happily eat the product.
    """
    if not _flat(line, UNIFORM_SPREAD):
        return False
    mean = float(line.mean())
    if abs(mean - interior) < INTERIOR_DELTA:
        return False
    return mean >= NEAR_WHITE or mean <= NEAR_BLACK


def _is_shadow(line: np.ndarray, interior: float) -> bool:
    if not _flat(line, SHADOW_SPREAD):
        return False
    mean = float(line.mean())
    return mean >= SHADOW_MIN_MEAN and abs(mean - interior) >= INTERIOR_DELTA


def _aspect_error(w: int, h: int, target: float) -> float:
    if not target or w <= 0 or h <= 0:
        return 0.0
    return abs((w / h) - target) / target


def trim_borders(img: Image.Image, target_ratio: float = 0.0) -> Tuple[Image.Image, Dict[str, object]]:
    """Peel flat background and soft shadow edges, within hard caps.

    Three guards keep this conservative, in increasing order of subtlety:
    a per-edge cap, so a pattern can never be eaten wholesale; a
    distance-from-interior test, so a uniformly pale tile is not mistaken for
    page background; and an aspect check, which discards any trim that moves the
    image *away* from the tile's true proportions -- the signature of having cut
    into the tile rather than off it.
    """
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    h, w = arr.shape[:2]
    interior = _interior_level(arr)
    max_v, max_h = int(h * TRIM_MAX_FRAC), int(w * TRIM_MAX_FRAC)
    capped: List[str] = []

    top, bottom, left, right = 0, h, 0, w
    while top < bottom - 1 and top < max_v and _is_background(arr[top, left:right], interior):
        top += 1
    while bottom > top + 1 and (h - bottom) < max_v and _is_background(arr[bottom - 1, left:right], interior):
        bottom -= 1
    while left < right - 1 and left < max_h and _is_background(arr[top:bottom, left], interior):
        left += 1
    while right > left + 1 and (w - right) < max_h and _is_background(arr[top:bottom, right - 1], interior):
        right -= 1
    if top >= max_v or (h - bottom) >= max_v or left >= max_h or (w - right) >= max_h:
        capped.append("background")

    # Soft drop shadows sit on the right and bottom; tighter cap, same guards.
    shadow_v, shadow_h = int(h * SHADOW_MAX_FRAC), int(w * SHADOW_MAX_FRAC)
    peeled_v = peeled_h = 0
    while bottom > top + 1 and peeled_v < shadow_v and _is_shadow(arr[bottom - 1, left:right], interior):
        bottom -= 1
        peeled_v += 1
    while right > left + 1 and peeled_h < shadow_h and _is_shadow(arr[top:bottom, right - 1], interior):
        right -= 1
        peeled_h += 1
    if peeled_v >= shadow_v or peeled_h >= shadow_h:
        capped.append("shadow")

    # Accept the vertical and horizontal trims only if they do not make the
    # proportions worse. Evaluated as a set of four candidates so the axes cannot
    # mask each other.
    candidates = {
        "none": (0, h, 0, w),
        "vertical": (top, bottom, 0, w),
        "horizontal": (0, h, left, right),
        "both": (top, bottom, left, right),
    }
    base_error = _aspect_error(w, h, target_ratio)
    best_key, best = "none", candidates["none"]
    best_error = base_error
    best_trim = 0
    for key, (t, b, l, r) in candidates.items():
        error = _aspect_error(r - l, b - t, target_ratio)
        amount = t + (h - b) + l + (w - r)
        # Strictly better proportions, or equal proportions with more border gone.
        if error < best_error - 1e-9 or (error <= best_error + 1e-9 and amount > best_trim):
            best_key, best, best_error, best_trim = key, (t, b, l, r), error, amount

    t, b, l, r = best
    steps: Dict[str, object] = {
        "trim": (t, h - b, l, w - r),
        "trim_capped": capped if best_key != "none" else [],
        "trim_choice": best_key,
    }
    if (t, b, l, r) == (0, h, 0, w):
        return img, steps
    return img.crop((l, t, r, b)), steps


def enforce_aspect(img: Image.Image, length_mm: int, width_mm: int) -> Tuple[Image.Image, Dict[str, object]]:
    """Centre-crop the long axis so the image matches the tile's mm ratio.

    The target is expressed in the image's own orientation, so a tile printed
    landscape stays landscape -- rotating it would misrepresent the product.
    """
    w, h = img.size
    if not length_mm or not width_mm:
        return img, {"aspect": "skipped-no-size"}

    if w >= h:
        target = max(length_mm, width_mm) / min(length_mm, width_mm)
        actual = w / h
    else:
        target = min(length_mm, width_mm) / max(length_mm, width_mm)
        actual = w / h

    deviation = abs(actual - target) / target
    if deviation <= ASPECT_TOL:
        return img, {"aspect": "within-tolerance", "aspect_dev": round(deviation, 4)}

    if actual > target:  # too wide -> crop width
        new_w = int(round(h * target))
        crop_frac = (w - new_w) / w
        if crop_frac > MAX_CROP_FRAC:
            return img, {"aspect": "crop-refused", "aspect_dev": round(deviation, 4)}
        x0 = (w - new_w) // 2
        return img.crop((x0, 0, x0 + new_w, h)), {"aspect": f"cropped-w {w}->{new_w}"}

    new_h = int(round(w / target))  # too tall -> crop height
    crop_frac = (h - new_h) / h
    if crop_frac > MAX_CROP_FRAC:
        return img, {"aspect": "crop-refused", "aspect_dev": round(deviation, 4)}
    y0 = (h - new_h) // 2
    return img.crop((0, y0, w, y0 + new_h)), {"aspect": f"cropped-h {h}->{new_h}"}


def meet_resolution(img: Image.Image, length_mm: int, width_mm: int) -> Tuple[Image.Image, Dict[str, object]]:
    """Upscale with Lanczos until pixels >= millimetres on both axes."""
    w, h = img.size
    if not length_mm or not width_mm:
        return img, {"scale": "skipped-no-size"}

    need_w, need_h = (max(length_mm, width_mm), min(length_mm, width_mm)) if w >= h \
        else (min(length_mm, width_mm), max(length_mm, width_mm))

    factor = max(need_w / w, need_h / h, 1.0)
    if factor <= 1.0:
        return img, {"scale": 1.0}
    out = img.resize((max(int(round(w * factor)), need_w), max(int(round(h * factor)), need_h)),
                     Image.LANCZOS)
    return out, {"scale": round(factor, 3)}


def clean(img: Image.Image, length_mm: int, width_mm: int) -> Tuple[Image.Image, Dict[str, object]]:
    """Run the full cleanup and report what each step did."""
    steps: Dict[str, object] = {}
    # Target proportions in the image's own orientation, so trimming knows which
    # way "better" is before any cropping happens.
    target_ratio = 0.0
    if length_mm and width_mm:
        w0, h0 = img.size
        target_ratio = (max(length_mm, width_mm) / min(length_mm, width_mm)) if w0 >= h0 \
            else (min(length_mm, width_mm) / max(length_mm, width_mm))

    out, s = trim_borders(img, target_ratio)
    steps.update(s)
    steps["after_trim"] = out.size
    out, s = enforce_aspect(out, length_mm, width_mm)
    steps.update(s)
    out, s = meet_resolution(out, length_mm, width_mm)
    steps.update(s)
    steps["final"] = out.size
    return out, steps
