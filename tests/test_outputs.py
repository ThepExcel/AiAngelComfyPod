"""Outputs tab: listing, ZIP streaming and pull.py, run against the real aiohttp routes.

ComfyUI itself is not installed here, so `folder_paths` and `server.PromptServer` are stubbed with
the two attributes the node uses; the route handlers, the ZIP stream and the sync script are the
shipped code. /view is stood in by aiohttp's FileResponse, which is what ComfyUI's /view returns.
"""

import asyncio
import importlib.util
import io
import json
import socket
import sys
import threading
import types
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NODE = ROOT / "nodes" / "ComfyUI-AiAngel"


def load(name, path, package=None):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


outputs = load("aiangel_outputs", NODE / "outputs.py")
pull = load("aiangel_pull", NODE / "pull.py")


def make_outputs(root: Path) -> dict[str, bytes]:
    data = {
        "ComfyUI_00001_.png": b"\x89PNG" + b"a" * 5000,
        "video/H3_00001.mp4": bytes(range(256)) * 9000,  # ~2.3 MB, several read chunks
        "video/sub dir/ไทย clip.webm": b"w" * 1234,
        "empty.txt": b"",
    }
    for rel, body in data.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    (root / ".cache").mkdir()
    (root / ".cache" / "hidden.png").write_bytes(b"x")
    (root / ".DS_Store").write_bytes(b"x")
    return data


def test_list_outputs_skips_hidden_and_labels_kind(tmp_path):
    make_outputs(tmp_path)
    files = {f["path"]: f for f in outputs.list_outputs(tmp_path)}
    assert set(files) == {
        "ComfyUI_00001_.png",
        "video/H3_00001.mp4",
        "video/sub dir/ไทย clip.webm",
        "empty.txt",
    }
    assert files["video/H3_00001.mp4"]["kind"] == "video"
    assert files["ComfyUI_00001_.png"]["kind"] == "image"
    assert files["empty.txt"]["kind"] == "other"


@pytest.mark.parametrize(
    "bad", ["../secret.txt", "video/../../x", "/etc/passwd", "missing.png", "."]
)
def test_safe_files_refuses_outside_or_missing(tmp_path, bad):
    out = tmp_path / "output"
    out.mkdir()
    make_outputs(out)
    (tmp_path / "secret.txt").write_text("no")
    with pytest.raises(ValueError):
        outputs.safe_files(out, [bad])


def test_zip_chunks_round_trip(tmp_path):
    data = make_outputs(tmp_path)
    files = outputs.safe_files(tmp_path, list(data))
    blob = b"".join(outputs.zip_chunks(files, chunk=4096))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.testzip() is None
        assert {i.filename: zf.read(i) for i in zf.infolist()} == data
        assert all(i.compress_type == zipfile.ZIP_STORED for i in zf.infolist())


@pytest.fixture
def pod(tmp_path, monkeypatch):
    """The node's real routes on a local port, output folder = tmp_path/output."""
    out = tmp_path / "output"
    out.mkdir()
    routes = web.RouteTableDef()
    monkeypatch.setitem(
        sys.modules,
        "folder_paths",
        types.SimpleNamespace(
            base_path=str(tmp_path),
            models_dir=str(tmp_path / "models"),
            get_output_directory=lambda: str(out),
        ),
    )
    server_stub = types.SimpleNamespace(
        PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=routes))
    )
    monkeypatch.setitem(sys.modules, "server", server_stub)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIANGEL_NSFW_KIT", str(ROOT / "presets" / "nsfw.txt"))
    load("ComfyUI_AiAngel", NODE / "__init__.py", package=True)

    @routes.get("/view")
    async def view(request):
        q = request.rel_url.query
        return web.FileResponse(out / q.get("subfolder", "") / q["filename"])

    app = web.Application()
    app.add_routes(routes)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    loop = asyncio.new_event_loop()
    runner = web.AppRunner(app)

    def serve():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
        loop.run_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/aiangel/outputs", timeout=1)
            break
        except OSError:
            threading.Event().wait(0.05)
    yield base, out
    asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)


def post_form(url, files):
    body = urllib.parse.urlencode({"files": json.dumps(files)}).encode()
    return urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=10)


def test_zip_route_streams_selected_and_all(pod):
    base, out = pod
    data = make_outputs(out)
    with post_form(base + "/aiangel/outputs/zip", ["video/H3_00001.mp4"]) as r:
        assert r.headers["Content-Type"] == "application/zip"
        assert "attachment" in r.headers["Content-Disposition"]
        with zipfile.ZipFile(io.BytesIO(r.read())) as zf:
            assert zf.namelist() == ["video/H3_00001.mp4"]
    with post_form(base + "/aiangel/outputs/zip", []) as r:
        with zipfile.ZipFile(io.BytesIO(r.read())) as zf:
            assert {n: zf.read(n) for n in zf.namelist()} == data


def test_zip_route_rejects_traversal(pod):
    base, out = pod
    make_outputs(out)
    with pytest.raises(urllib.error.HTTPError) as e:
        post_form(base + "/aiangel/outputs/zip", ["../secret"])
    assert e.value.code == 400


def test_pull_syncs_skips_and_resumes(pod, tmp_path, capsys):
    base, out = pod
    data = make_outputs(out)
    dest = tmp_path / "pc"
    assert pull.main([base, str(dest), "--jobs", "3"]) == 0
    got = {p.relative_to(dest).as_posix(): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    assert got == data

    # second run: nothing new
    capsys.readouterr()
    assert pull.main([base, str(dest)]) == 0
    assert "done 0, already here 4" in capsys.readouterr().out

    # a cut-off download resumes from its .part file
    vid = dest / "video" / "H3_00001.mp4"
    body = vid.read_bytes()
    vid.unlink()
    vid.with_name(vid.name + ".part").write_bytes(body[:1000])
    entry = next(f for f in pull.list_remote(base) if f["path"] == "video/H3_00001.mp4")
    assert pull.fetch_one(base, entry, dest) == ("done", len(body) - 1000)
    assert vid.read_bytes() == body
    assert not vid.with_name(vid.name + ".part").exists()


def test_nsfw_kit_route_serves_the_list(pod):
    base, _ = pod
    with urllib.request.urlopen(base + "/aiangel/kit/nsfw", timeout=10) as r:
        text = json.load(r)["text"]
    assert text == (ROOT / "presets" / "nsfw.txt").read_text(encoding="utf-8")


def test_pull_refuses_unsafe_server_paths(tmp_path):
    with pytest.raises(ValueError):
        pull.local_path(tmp_path, "../evil.png")
