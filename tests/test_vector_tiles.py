"""Vector-drawn tiles: synthesis from fill colour and the provisional gate."""

from src.image_extractor import extract_tile, synthesize_fill
from src.models import ImagePlacement


def vector(x0, y0, x1, y1, fill=None, xref=-1):
    return ImagePlacement(xref=xref, bbox=(x0, y0, x1, y1),
                          stored_w=int(x1 - x0), stored_h=int(y1 - y0),
                          rotation=0, fill=fill, provisional=True)


def test_a_filled_rectangle_becomes_a_flat_bitmap_of_its_colour():
    img = synthesize_fill(vector(0, 0, 123, 82, fill=(0.86, 0.35, 0.15)))
    assert img.size == (123, 82)
    assert img.getpixel((60, 40)) == (219, 89, 38)
    assert len(img.getcolors()) == 1  # flat: exactly one colour


def test_a_stroke_only_rectangle_synthesises_white():
    """A white tile on white stock is drawn as just an outline; fill is None."""
    img = synthesize_fill(vector(0, 0, 100, 100, fill=None))
    assert img.getpixel((50, 50)) == (255, 255, 255)


def test_extract_tile_routes_negative_xrefs_to_synthesis():
    img = extract_tile(source=None, placement=vector(0, 0, 80, 80, fill=(0, 0, 1)))
    assert img.size == (80, 80)
    assert img.getpixel((10, 10)) == (0, 0, 255)
