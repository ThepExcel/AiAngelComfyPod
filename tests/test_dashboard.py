"""Dashboard server (docker/dashboard/server.py): real routes under aiohttp, run against a real
TCP port the way tests/test_outputs.py does it. fetch.resolve / fetch.download are stubbed by
default in `make_dashboard` so no test ever reaches the network.
"""

import asyncio
import importlib.util
import io
import json
import os
import socket
import sys
import threading
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
os.environ["AIANGEL_NODE_DIR"] = str(NODE)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


server = load("aiangel_dashboard_server", ROOT / "docker" / "dashboard" / "server.py")


def _stub_resolve(folder, url, file_part, tokens):
    name = Path(urllib.parse.urlparse(url).path).name or "file.bin"
    return {
        "folder": folder or "checkpoints",
        "name": name,
        "url": url,
        "size": 0,
        "site": "direct",
    }


def _stub_download(job, models_dir, tokens):
    return True, "stub"


@pytest.fixture
def make_dashboard(tmp_path, monkeypatch):
    """Factory fixture: make_dashboard(**overrides) starts a fresh dashboard app on a real port
    and returns (base_url, cfg). Every override is forwarded to server.Config.from_env."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("MODELS_DIR", str(data_dir / "models"))
    presets_file = tmp_path / "models.tsv"
    presets_file.touch()
    monkeypatch.setenv("PRESETS_FILE", str(presets_file))
    monkeypatch.setenv("AIANGEL_DASHBOARD_WEB_DIR", str(tmp_path / "no-such-web-dir"))
    monkeypatch.setenv("AIANGEL_NSFW_KIT", str(ROOT / "presets" / "nsfw.txt"))
    monkeypatch.setenv("MODELS", "")
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    # the host machine may have real tokens in its env; tests must never depend on or leak them
    monkeypatch.delenv("CIVITAI_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    teardown = []

    def make(**overrides):
        overrides.setdefault("gpu_stats_fn", lambda: {})
        overrides.setdefault("comfy_state_fn", lambda: "down")
        overrides.setdefault("tcp_ready_fn", lambda port: False)
        overrides.setdefault("resolve_fn", _stub_resolve)
        overrides.setdefault("download_fn", _stub_download)
        app = server.build_app(**overrides)

        loop = asyncio.new_event_loop()
        runner = web.AppRunner(app)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

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
                urllib.request.urlopen(base + "/api/state", timeout=1)
                break
            except OSError:
                threading.Event().wait(0.05)
        teardown.append((runner, loop))
        return base, app["cfg"]

    yield make
    for runner, loop in teardown:
        asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(5)
        loop.call_soon_threadsafe(loop.stop)


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.load(r)


def post_json(url, body, headers=None):
    data = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.load(r)


def post_json_expect_error(url, body, headers=None):
    data = json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
    raise AssertionError("expected an HTTP error")


# ---------------------------------------------------------------------------
# /api/state
# ---------------------------------------------------------------------------


def test_state_reports_have_missing_and_downloading(make_dashboard, tmp_path, monkeypatch):
    presets = tmp_path / "models.tsv"
    presets.write_text(
        "demo\tcheckpoints\thave.safetensors\t1000\thttps://huggingface.co/x/resolve/main/have.safetensors\n"
        "demo\tcheckpoints\tmissing.safetensors\t2000\thttps://huggingface.co/x/resolve/main/missing.safetensors\n"
        "demo\tcheckpoints\tpartial.safetensors\t3000\thttps://huggingface.co/x/resolve/main/partial.safetensors\n",
        encoding="utf-8",
        newline="\n",
    )
    models_dir = tmp_path / "data" / "models" / "checkpoints"
    models_dir.mkdir(parents=True)
    (models_dir / "have.safetensors").write_bytes(b"a" * 1000)
    (models_dir / "partial.safetensors").write_bytes(b"a" * 1200)
    monkeypatch.setenv("PRESETS_FILE", str(presets))
    monkeypatch.setenv("MODELS", "demo")

    base, _cfg = make_dashboard()
    status, body = get_json(base + "/api/state")
    assert status == 200
    presets_out = {p["name"]: p for p in body["presets"]}
    files = {f["name"]: f for f in presets_out["demo"]["files"]}
    assert presets_out["demo"]["in_env"] is True
    assert files["have.safetensors"]["state"] == "have"
    assert files["have.safetensors"]["have_bytes"] == 1000
    assert files["missing.safetensors"]["state"] == "missing"
    assert files["missing.safetensors"]["have_bytes"] == 0
    assert files["partial.safetensors"]["state"] == "downloading"
    assert files["partial.safetensors"]["have_bytes"] == 1200
    assert body["models_env"] == "demo"
    assert body["outputs"] == {"count": 0, "bytes": 0}
    assert body["pod"]["gpu"] is None
    assert body["services"][0]["key"] == "comfyui" and body["services"][0]["state"] == "down"


def test_partial_download_goes_missing_after_a_stall(make_dashboard, tmp_path, monkeypatch):
    presets = tmp_path / "models.tsv"
    presets.write_text(
        "demo\tcheckpoints\tstall.safetensors\t3000\thttps://huggingface.co/x/resolve/main/stall.safetensors\n",
        encoding="utf-8",
        newline="\n",
    )
    models_dir = tmp_path / "data" / "models" / "checkpoints"
    models_dir.mkdir(parents=True)
    (models_dir / "stall.safetensors").write_bytes(b"a" * 1200)
    monkeypatch.setenv("PRESETS_FILE", str(presets))

    clock = [1000.0]
    base, _cfg = make_dashboard(now_fn=lambda: clock[0])
    _status, first = get_json(base + "/api/state")
    assert first["presets"][0]["files"][0]["state"] == "downloading"

    clock[0] = 1000.0 + 35  # no bytes added, 35s later: no longer "recently growing"
    _status, second = get_json(base + "/api/state")
    assert second["presets"][0]["files"][0]["state"] == "missing"


# ---------------------------------------------------------------------------
# /api/keys
# ---------------------------------------------------------------------------


def test_keys_save_mask_and_clear(make_dashboard):
    base, cfg = make_dashboard()
    status, body = post_json(base + "/api/keys", {"civitai": "abcdefgh12345678"})
    assert status == 200
    assert body["civitai"] == "abcd…5678"
    assert body["huggingface"] is None
    assert (cfg.secrets_dir / "civitai_token").read_text(encoding="utf-8") == "abcdefgh12345678"

    # "" keeps the existing value
    _status, body = post_json(base + "/api/keys", {"civitai": ""})
    assert body["civitai"] == "abcd…5678"

    # "-" clears it
    _status, body = post_json(base + "/api/keys", {"civitai": "-"})
    assert body["civitai"] is None
    assert not (cfg.secrets_dir / "civitai_token").exists()


# ---------------------------------------------------------------------------
# /api/download
# ---------------------------------------------------------------------------


def test_download_400_on_bad_line(make_dashboard):
    base, _cfg = make_dashboard()
    bad = "notaknownfolder|nothttp"
    status, body = post_json_expect_error(base + "/api/download", {"text": bad})
    assert status == 400
    assert bad in body["error"]


def test_download_queues_pasted_links(make_dashboard):
    base, _cfg = make_dashboard()
    status, body = post_json(
        base + "/api/download", {"text": "loras|https://civitai.com/models/1?modelVersionId=2"}
    )
    assert status == 200 and body["queued"] == 1


# ---------------------------------------------------------------------------
# /api/preset
# ---------------------------------------------------------------------------


def test_preset_queues_only_missing_files(make_dashboard, tmp_path, monkeypatch):
    presets = tmp_path / "models.tsv"
    presets.write_text(
        "demo\tcheckpoints\thave.safetensors\t1000\thttps://huggingface.co/x/resolve/main/have.safetensors\n"
        "demo\tcheckpoints\tmissing.safetensors\t2000\thttps://huggingface.co/x/resolve/main/missing.safetensors\n",
        encoding="utf-8",
        newline="\n",
    )
    models_dir = tmp_path / "data" / "models" / "checkpoints"
    models_dir.mkdir(parents=True)
    (models_dir / "have.safetensors").write_bytes(b"a" * 1000)
    monkeypatch.setenv("PRESETS_FILE", str(presets))

    base, _cfg = make_dashboard()
    status, body = post_json(base + "/api/preset", {"name": "demo"})
    assert status == 200 and body["queued"] == 1
    _status, state = get_json(base + "/api/state")
    labels = {j["label"] for j in state["jobs"]}
    assert labels == {"checkpoints/missing.safetensors"}


def test_preset_400_on_unknown_and_nsfw(make_dashboard):
    base, _cfg = make_dashboard()
    status, body = post_json_expect_error(base + "/api/preset", {"name": "not-a-real-preset"})
    assert status == 400 and "not-a-real-preset" in body["error"]
    status, body = post_json_expect_error(base + "/api/preset", {"name": "nsfw"})
    assert status == 400


# ---------------------------------------------------------------------------
# outputs: list, single file (range + traversal), zip
# ---------------------------------------------------------------------------


def make_outputs(root: Path) -> dict[str, bytes]:
    data = {
        "clip_00001_.mp4": bytes(range(256)) * 100,  # 25600 bytes
        "sub/image.png": b"\x89PNG" + b"a" * 500,
    }
    for rel, body in data.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return data


def test_outputs_list_single_file_and_zip(make_dashboard, tmp_path):
    base, cfg = make_dashboard()
    data = make_outputs(cfg.output_dir())

    status, body = get_json(base + "/api/outputs")
    assert status == 200
    assert {f["path"] for f in body["files"]} == set(data)
    assert body["output_dir"] == str(cfg.output_dir())

    with urllib.request.urlopen(base + "/api/outputs/file?path=clip_00001_.mp4", timeout=10) as r:
        assert r.read() == data["clip_00001_.mp4"]

    req = urllib.request.Request(
        base + "/api/outputs/file?path=clip_00001_.mp4", headers={"Range": "bytes=0-9"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 206
        assert r.read() == data["clip_00001_.mp4"][:10]

    try:
        urllib.request.urlopen(base + "/api/outputs/file?path=../evil", timeout=10)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400

    body = urllib.parse.urlencode({"files": json.dumps(["sub/image.png"])}).encode()
    with urllib.request.urlopen(
        urllib.request.Request(base + "/api/outputs/zip", data=body), timeout=10
    ) as r:
        with zipfile.ZipFile(io.BytesIO(r.read())) as zf:
            assert zf.namelist() == ["sub/image.png"]
            assert zf.read("sub/image.png") == data["sub/image.png"]


# ---------------------------------------------------------------------------
# /api/logs
# ---------------------------------------------------------------------------


def test_logs_mask_secret_values(make_dashboard, tmp_path):
    base, cfg = make_dashboard()
    cfg.secrets_dir.mkdir(parents=True, exist_ok=True)
    (cfg.secrets_dir / "civitai_token").write_text("sekrit12345", encoding="utf-8", newline="\n")
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    (cfg.log_dir / "boot.log").write_text(
        "boot start\ntoken in use: sekrit12345 for download\n", encoding="utf-8", newline="\n"
    )
    status, body = get_json(base + "/api/logs?name=boot")
    assert status == 200
    text = "\n".join(body["lines"])
    assert "sekrit12345" not in text
    assert "••••" in text

    try:
        urllib.request.urlopen(base + "/api/logs?name=nope", timeout=10)
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_logs_strip_terminal_colors(make_dashboard):
    """ComfyUI colors its log lines; on a real pod the browser showed '[32m[INFO][0m'."""
    base, cfg = make_dashboard()
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    (cfg.log_dir / "boot.log").write_text(
        "\x1b[32m[INFO]\x1b[0m Starting server\n\x1b[1m\x1b[33m[WARNING]\x1b[0m old api\n",
        encoding="utf-8",
        newline="\n",
    )
    status, body = get_json(base + "/api/logs?name=boot")
    assert status == 200
    assert body["lines"] == ["[INFO] Starting server", "[WARNING] old api"]


def test_elastic_volume_reports_no_fake_free_space(monkeypatch, tmp_path):
    """A RunPod Global volume reports 0 used of 1 PiB; showing '1048576 GB free' is wrong."""
    cfg = server.Config.from_env(data_dir=tmp_path)
    real = server.shutil.disk_usage

    def fake(path):
        if Path(path) == tmp_path:
            return real(path)._replace(total=1 << 50, used=0, free=1 << 50)
        return real(path)

    monkeypatch.setattr(server.shutil, "disk_usage", fake)
    disk = cfg.disk_usage()
    assert disk["workspace"] == {"used": None, "total": None, "elastic": True}
    assert disk["container"]["total"] > 0


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_csrf_cross_site_post_refused_but_page_open_allowed(make_dashboard):
    base, _cfg = make_dashboard()

    req = urllib.request.Request(
        base + "/api/keys",
        data=json.dumps({"civitai": ""}).encode(),
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected 403")
    except urllib.error.HTTPError as e:
        assert e.code == 403

    req = urllib.request.Request(
        base + "/",
        headers={
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
        assert r.read() == b"dashboard front end missing"

    status, body = post_json(base + "/api/keys", {"civitai": ""})
    assert status == 200 and "civitai" in body
