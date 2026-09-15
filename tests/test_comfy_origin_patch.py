"""patch_comfy_origin: a cross-site page open reaches ComfyUI; a cross-site POST still gets 403.

The middleware below is ComfyUI 0.35.0 server.py's create_origin_only_middleware head, verbatim up
to the cross-site check (the Host/Origin check after it only matters for loopback hosts and is not
touched by the patch). The patch file is applied to it exactly as the Docker build applies it.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

COMFY_0_35_0_MIDDLEWARE = """from aiohttp import web


def create_origin_only_middleware():
    @web.middleware
    async def origin_only_middleware(request: web.Request, handler):
        if 'Sec-Fetch-Site' in request.headers:
            sec_fetch_site = request.headers['Sec-Fetch-Site']
            if sec_fetch_site == 'cross-site':
                return web.Response(status=403)
        return await handler(request)

    return origin_only_middleware
"""

PAGE_OPEN = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}


def patched_middleware(tmp_path):
    spec = importlib.util.spec_from_file_location("pco", ROOT / "docker" / "patch_comfy_origin.py")
    pco = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pco)
    server = tmp_path / "server.py"
    server.write_text(COMFY_0_35_0_MIDDLEWARE, encoding="utf-8")
    pco.patch(server)
    ns: dict = {}
    exec(server.read_text(encoding="utf-8"), ns)
    return ns["create_origin_only_middleware"]()


def statuses(middleware, cases):
    async def ok(request):
        return web.Response(text="ok")

    async def run():
        app = web.Application(middlewares=[middleware])
        app.router.add_get("/", ok)
        app.router.add_post("/prompt", ok)
        async with TestClient(TestServer(app)) as client:
            out = []
            for method, path, headers in cases:
                resp = await client.request(method, path, headers=headers)
                out.append(resp.status)
            return out

    return asyncio.run(run())


def test_cross_site_page_open_is_allowed(tmp_path):
    mw = patched_middleware(tmp_path)
    assert statuses(mw, [("GET", "/", PAGE_OPEN)]) == [200]


def test_other_cross_site_requests_are_still_refused(tmp_path):
    mw = patched_middleware(tmp_path)
    cases = [
        ("POST", "/prompt", PAGE_OPEN),  # a form POST navigation from another site
        ("POST", "/prompt", {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"}),
        (
            "GET",
            "/",
            {
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Dest": "image",
            },
        ),
        (
            "GET",
            "/",
            {
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "iframe",
            },
        ),
    ]
    assert statuses(mw, cases) == [403, 403, 403, 403]


def test_same_origin_and_plain_requests_unchanged(tmp_path):
    mw = patched_middleware(tmp_path)
    cases = [
        ("POST", "/prompt", {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"}),
        ("GET", "/", {}),
    ]
    assert statuses(mw, cases) == [200, 200]


def test_patch_matches_real_comfyui_server_text():
    """The OLD block is ComfyUI's own indentation and quoting, so the build-time count is 1."""
    spec = importlib.util.spec_from_file_location("pco2", ROOT / "docker" / "patch_comfy_origin.py")
    pco = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pco)
    assert COMFY_0_35_0_MIDDLEWARE.count(pco.OLD) == 1
