# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Crop the AI Angel mark (white line art on transparent) to its visible pixels for the dashboard.

usage: uv run scripts/make_dashboard_logo.py SRC.png docker/dashboard/web/logo.png [--height 96]
"""

import argparse

from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--height", type=int, default=96)
ap.add_argument("--max-y", type=int, help="ignore rows below this (the mark without its wordmark)")
a = ap.parse_args()

img = Image.open(a.src).convert("RGBA")
if a.max_y:
    img = img.crop((0, 0, img.width, a.max_y))
alpha = img.getchannel("A").point(lambda v: 255 if v > 24 else 0)
box = alpha.getbbox()
print("source", img.size, "visible bbox", box)
mark = img.crop(box)
w = round(mark.width * a.height / mark.height)
mark.resize((w, a.height), Image.LANCZOS).save(a.dst, optimize=True)
print("saved", a.dst, (w, a.height))
