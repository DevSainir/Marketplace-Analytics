"""Placeholder card photos for the demo's A/B tests.

A drawn garment on a flat colour, labelled «DEMO» and the variant's letter:
obviously not a product photo, which is the point — the demo ships no image of
anything real. Generated rather than committed, so the repository holds no
binary that a reader cannot review.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

#: WB card photos are 3:4.
_SIZE = (600, 800)


def placeholder_photo(letter: str, background: str, garment: str) -> bytes:
    """A JPEG of a plain garment silhouette, captioned ``DEMO`` and ``letter``.

    Args:
        letter: The variant's label, drawn large.
        background: The backdrop colour, ``#rrggbb``.
        garment: The silhouette's colour, ``#rrggbb``.

    Returns:
        The encoded JPEG.
    """
    image = Image.new("RGB", _SIZE, background)
    draw = ImageDraw.Draw(image)
    # A sweatshirt in three shapes: body, two sleeves.
    draw.rounded_rectangle((170, 200, 430, 610), radius=36, fill=garment)
    draw.polygon([(175, 215), (80, 470), (140, 495), (215, 300)], fill=garment)
    draw.polygon([(425, 215), (520, 470), (460, 495), (385, 300)], fill=garment)
    draw.ellipse((255, 175, 345, 235), fill=background)
    caption = ImageFont.load_default(size=44)
    label = ImageFont.load_default(size=150)
    draw.text((300, 90), "DEMO", font=caption, fill=garment, anchor="mm")
    draw.text((300, 700), letter, font=label, fill=garment, anchor="mm")
    out = BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()
