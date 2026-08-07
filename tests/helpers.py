"""Builders for synthetic geometry, so stages 1-3 can be tested without a PDF."""

from __future__ import annotations

from src.models import Half, ImagePlacement, SizeSpec, TextLine


def img(x0, y0, x1, y1, xref=1, rotation=0, stored=(100, 100), **kw) -> ImagePlacement:
    return ImagePlacement(xref=xref, bbox=(x0, y0, x1, y1),
                          stored_w=stored[0], stored_h=stored[1],
                          rotation=rotation, **kw)


def line(x0, y0, x1, y1, text) -> TextLine:
    return TextLine(bbox=(x0, y0, x1, y1), text=text)


def half(sizes=(), lines=(), images=(), rect=(0.0, 0.0, 600.0, 800.0),
         page_index=0, side="L", skip_reason=None) -> Half:
    return Half(page_index=page_index, side=side, rect=rect,
                sizes=list(sizes), lines=list(lines), images=list(images),
                skip_reason=skip_reason)


def size(length, width) -> SizeSpec:
    return SizeSpec(length_mm=length, width_mm=width)
