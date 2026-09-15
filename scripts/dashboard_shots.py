# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Screenshot every dashboard tab at 2x (for review and for the guide page).

usage: uv run scripts/dashboard_shots.py URL OUT_DIR [--width 1440] [--height 900]
       URL e.g. http://localhost:8765/?demo  or  https://<pod>-8189.proxy.runpod.net/
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

TABS = ["overview", "models", "outputs", "keys", "logs"]

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("out")
ap.add_argument("--width", type=int, default=1440)
ap.add_argument("--height", type=int, default=900)
a = ap.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": a.width, "height": a.height}, device_scale_factor=2)
    page.goto(a.url, wait_until="networkidle", timeout=120000)
    page.wait_for_timeout(2500)
    for i, tab in enumerate(TABS, start=1):
        page.keyboard.press(str(i))
        page.wait_for_timeout(1500)
        path = out / f"{a.width}-{i}-{tab}.png"
        page.screenshot(path=str(path), full_page=True)
        print(path)
    b.close()
