"""Builds app/static/favicon.ico (16/32/48 px) from the ZOZ INNOVATIONS - FZCO icon (app/static/zoz-icon-512.png).

The other brand files are the originals from the ZOZ website: zoz-logo.svg (header and SVG favicon),
zoz-icon-512.png and apple-touch-icon.png.

Usage:  python scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"

if __name__ == "__main__":
    icon = Image.open(STATIC / "zoz-icon-512.png").convert("RGBA")
    icon.save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("wrote", STATIC / "favicon.ico")
