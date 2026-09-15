"""Build-time patch for ComfyUI's server.py: let a cross-site link OPEN the UI.

RunPod's Connect menu links from console.runpod.io to <pod>-8188.proxy.runpod.net, which browsers
send as `Sec-Fetch-Site: cross-site`. ComfyUI answers every such request with 403, so each user's
first click on "ComfyUI" showed "Access denied" until they reloaded the page.

Only a top-level page navigation (GET, Sec-Fetch-Mode: navigate, Sec-Fetch-Dest: document) is let
through. Every other cross-site request, including a POST that would queue a workflow, is still
refused, and the Host/Origin check below it is untouched.

The replacement must match exactly once, so a changed upstream release fails the build instead of
shipping a silently unpatched server.
"""

import sys
from pathlib import Path

OLD = """            if sec_fetch_site == 'cross-site':
                return web.Response(status=403)"""
NEW = """            is_page_open = (
                request.method == 'GET'
                and request.headers.get('Sec-Fetch-Mode') == 'navigate'
                and request.headers.get('Sec-Fetch-Dest') == 'document'
            )
            if sec_fetch_site == 'cross-site' and not is_page_open:
                return web.Response(status=403)"""


def patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        sys.exit(f"patch_comfy_origin: expected 1 match, found {count} in {path}")
    path.write_text(text.replace(OLD, NEW), encoding="utf-8", newline="\n")
    print(f"patch_comfy_origin: patched {path}")


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
