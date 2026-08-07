"""Stage 4a — pull each tile's bitmap out of the PDF natively.

Nothing here rasterises a page. Every tile comes from the embedded image object's
own compressed bytes, decoded once and reused, which is the highest quality the
document contains. Orientation is then applied from the placement matrix so the
saved image matches what the catalogue actually prints.
"""

from __future__ import annotations

import io
from typing import Dict, Optional

import pymupdf
from PIL import Image

from .models import ImagePlacement

# Soft-masked images are composited onto white: the catalogue prints on white
# stock, so this reproduces the printed appearance rather than inventing a colour.
MATTE = (255, 255, 255)


class ImageSource:
    """Decodes embedded images on demand and caches them by xref."""

    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self._cache: Dict[int, Image.Image] = {}
        self.decoded = 0
        self.cache_hits = 0

    def _decode(self, xref: int) -> Image.Image:
        info = self.doc.extract_image(xref)
        img: Optional[Image.Image] = None

        try:
            candidate = Image.open(io.BytesIO(info["image"]))
            candidate.load()
            # CMYK JPEGs in PDFs are frequently Adobe-inverted; let PyMuPDF's
            # colour management handle those rather than guessing.
            if candidate.mode not in ("CMYK", "P"):
                img = candidate.convert("RGB")
        except Exception:
            img = None

        if img is None:
            pix = pymupdf.Pixmap(self.doc, xref)
            if pix.colorspace is None or pix.colorspace.n == 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
            mode = "RGB" if pix.n >= 3 else "L"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")

        smask = info.get("smask", 0)
        if smask:
            try:
                mask_info = self.doc.extract_image(smask)
                mask = Image.open(io.BytesIO(mask_info["image"])).convert("L")
                if mask.size != img.size:
                    mask = mask.resize(img.size, Image.LANCZOS)
                backdrop = Image.new("RGB", img.size, MATTE)
                backdrop.paste(img, mask=mask)
                img = backdrop
            except Exception:
                pass  # an unreadable mask is not a reason to lose the tile

        return img

    def get(self, xref: int) -> Image.Image:
        if xref in self._cache:
            self.cache_hits += 1
            return self._cache[xref]
        img = self._decode(xref)
        self._cache[xref] = img
        self.decoded += 1
        return img


def oriented(img: Image.Image, placement: ImagePlacement) -> Image.Image:
    """Turn a decoded bitmap to the orientation it is printed in.

    The placement matrix says how far the image was rotated clockwise onto the
    page, so the same clockwise rotation reproduces the printed tile. This is why
    orientation never depends on the stored pixel dimensions.
    """
    out = img
    if placement.flipped:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    rotation = placement.rotation % 360
    if rotation == 90:
        out = out.transpose(Image.ROTATE_270)  # PIL rotates counter-clockwise
    elif rotation == 180:
        out = out.transpose(Image.ROTATE_180)
    elif rotation == 270:
        out = out.transpose(Image.ROTATE_90)
    return out


def extract_tile(source: ImageSource, placement: ImagePlacement) -> Image.Image:
    """The tile's embedded bitmap, oriented as printed."""
    return oriented(source.get(placement.xref), placement)
