"""Generates the PaperOps icons from the logo (paper slip with an orange band and two printed lines):
app/static/favicon.ico (16/32/48 px) and app/static/apple-touch-icon.png (180 px, dark background).

Usage:  python scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PAPER, ORANGE, INK, BG = (247, 244, 236), (240, 140, 46), (29, 29, 27), (18, 20, 23)


def logo(size, background=None):
    """The 32x32 favicon design, drawn at 8x and scaled down for clean edges."""
    big = size * 8
    img = Image.new("RGBA", (big, big), background + (255,) if background else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = big / 32  # design units -> pixels
    inset = 0 if not background else 4 * s  # padding on the solid touch icon
    k = (big - 2 * inset) / big

    def box(x0, y0, x1, y1):
        return [inset + x0 * s * k, inset + y0 * s * k, inset + x1 * s * k, inset + y1 * s * k]

    d.rounded_rectangle(box(6, 3, 26, 29), radius=2 * s * k, fill=PAPER)
    d.rectangle(box(6, 7, 26, 12), fill=ORANGE)
    d.rectangle(box(9, 15, 23, 17), fill=INK)
    d.rectangle(box(9, 19, 19, 21), fill=INK)
    d.rectangle(box(9, 23, 21, 25), fill=INK)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    logo(48).save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    logo(180, background=BG).save(STATIC / "apple-touch-icon.png")
    print("wrote", STATIC / "favicon.ico", "and", STATIC / "apple-touch-icon.png")
