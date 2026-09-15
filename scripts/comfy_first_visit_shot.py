# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Open a pod's ComfyUI in a fresh browser (a first visit) and screenshot what loads, once from the
plain URL (RunPod Connect) and once from the dashboard's ?template= link. Also screenshots the
Templates browser filtered to ComfyUI-AiAngel.

  uv run scripts/comfy_first_visit_shot.py <pod-id> OUT_DIR
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

pod, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
base = f"https://{pod}-8188.proxy.runpod.net/"

JS_STATE = """() => {
  const wf = window.app?.extensionManager?.workflow?.activeWorkflow;
  return {name: wf?.filename || wf?.path || null, nodes: window.app?.graph?._nodes?.length ?? null};
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    for tag, url in (
        ("connect", base),
        ("dashboard-link", base + "?template=AiAngelH3-Clip&source=ComfyUI-AiAngel"),
    ):
        ctx = b.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=120000)
        pg.wait_for_timeout(30000)
        print(tag, pg.evaluate(JS_STATE), flush=True)
        pg.screenshot(path=str(out / f"comfy-{tag}.png"))
        if tag == "connect":
            pg.keyboard.press("Escape")
            try:
                pg.get_by_role("button", name="Templates").first.click(timeout=5000)
                pg.wait_for_timeout(4000)
                pg.get_by_text("ComfyUI-AiAngel").first.click(timeout=5000)
                pg.wait_for_timeout(3000)
                pg.screenshot(path=str(out / "comfy-templates.png"))
                print("templates shot ok", flush=True)
            except Exception as e:  # noqa: BLE001
                print("templates shot failed:", e, flush=True)
        ctx.close()
    b.close()
