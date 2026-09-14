"""Offline tests for docker/fetch_extra.py and docker/patch_model_manager.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fx = load("aiangel_fetch", ROOT / "nodes" / "ComfyUI-AiAngel" / "fetch.py")
pm = load("patch_model_manager", ROOT / "docker" / "patch_model_manager.py")


def test_parse_entries_forms():
    raw = "https://civitai.red/models/1?modelVersionId=2 ; loras|https://x.test/a.safetensors\n"
    raw += "diffusion_models|https://civitai.com/models/3?modelVersionId=4|int8"
    assert fx.parse_entries(raw) == [
        (None, "https://civitai.red/models/1?modelVersionId=2", None),
        ("loras", "https://x.test/a.safetensors", None),
        ("diffusion_models", "https://civitai.com/models/3?modelVersionId=4", "int8"),
    ]


def test_parse_entries_rejects_unknown_folder():
    with pytest.raises(ValueError):
        fx.parse_entries("weights|https://x.test/a.safetensors")


def test_parse_entries_skips_comment_lines_and_rejects_non_links():
    raw = "# my list\nhttps://x.test/a.safetensors\n"
    assert fx.parse_entries(raw) == [(None, "https://x.test/a.safetensors", None)]
    with pytest.raises(ValueError):
        fx.parse_entries("not-a-link")


def test_download_without_civitai_key_reports_instead_of_raising(tmp_path):
    job = {
        "folder": "loras",
        "name": "x.safetensors",
        "url": "https://civitai.com/api/download/models/1",
        "size": 10,
        "site": "civitai",
    }
    ok, msg = fx.download(job, tmp_path, {"civitai": None})
    assert not ok and "Civitai API key" in msg


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://civitai.red/models/111/some-name?modelVersionId=222", ("111", "222")),
        ("https://www.civitai.com/models/111", ("111", None)),
        ("https://civitai.com/api/download/models/333", (None, "333")),
        ("https://civitai.com/model-versions/444", (None, "444")),
    ],
)
def test_civitai_ids(url, expected):
    assert fx.civitai_ids(url) == expected


FILES = [
    {"name": "demo_fp8.safetensors", "type": "Diffusion Model", "primary": True},
    {"name": "demo_int8.safetensors", "type": "Diffusion Model"},
    {"name": "demo.json", "type": "Workflow"},
]


def test_pick_file_primary_and_part():
    assert fx.pick_file(FILES, None)["name"] == "demo_fp8.safetensors"
    assert fx.pick_file(FILES, "int8")["name"] == "demo_int8.safetensors"
    with pytest.raises(ValueError):
        fx.pick_file(FILES, "nvfp4")


def test_pick_file_never_returns_a_workflow_when_weights_exist():
    files = [{"name": "w.json", "type": "Workflow", "primary": True}, *FILES[1:2]]
    assert fx.pick_file(files, None)["name"] == "demo_int8.safetensors"


def test_civitai_folder():
    assert fx.civitai_folder("Checkpoint", "Diffusion Model") == "diffusion_models"
    assert fx.civitai_folder("Checkpoint", "Model") == "checkpoints"
    assert fx.civitai_folder("LORA", "Model") == "loras"


def test_authed_civitai_url():
    base = "https://civitai.com/api/download/models/1"
    assert fx.authed_civitai_url(base, "k") == base + "?token=k"
    assert fx.authed_civitai_url(base + "?type=Model", "k") == base + "?type=Model&token=k"


def test_already_have_tolerates_kb_rounding(tmp_path):
    f = tmp_path / "m.safetensors"
    f.write_bytes(b"x" * 10_000)
    assert fx.already_have(f, 10_000 + 1000)
    assert not fx.already_have(f, 50_000)
    (tmp_path / "m.safetensors.aria2").write_bytes(b"")
    assert not fx.already_have(f, 10_000)


def test_already_have_rejects_empty_leftovers_when_size_unknown(tmp_path):
    """A failed Hugging Face download left a 0-byte file that was skipped as 'have' on a pod."""
    f = tmp_path / "lora.safetensors"
    f.write_bytes(b"")
    assert not fx.already_have(f, 0)
    f.write_bytes(b"x" * 100)
    assert fx.already_have(f, 0)
    (tmp_path / "lora.safetensors.aria2__temp").write_bytes(b"")
    assert not fx.already_have(f, 0)


def test_remote_size_reads_content_length_and_survives_errors(tmp_path):
    import functools
    import http.server
    import threading

    (tmp_path / "w.safetensors").write_bytes(b"z" * 1234)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        assert fx.remote_size(f"http://127.0.0.1:{port}/w.safetensors") == 1234
    finally:
        srv.shutdown()
    assert fx.remote_size("http://127.0.0.1:9/nothing-listens-here") == 0


ARIA2_403 = """09/14 08:57:42 [ERROR] CUID#7 - Download aborted. URI=https://civitai.com/api/download/models/1
Exception: [AbstractCommand.cc:351] errorCode=22 URI=https://b2.civitai.com/file/x.safetensors
  -> [HttpSkipResponseCommand.cc:239] errorCode=22 The response status is not successful. status=403
"""


def test_aria2_reason_names_the_http_status():
    assert fx._aria2_reason(ARIA2_403) == "status=403"
    assert "errorCode=1" in fx._aria2_reason("[ERROR] errorCode=1 network")


def test_download_falls_back_when_aria2_is_refused(tmp_path, monkeypatch):
    """b2.civitai.com answered aria2c with 403 on a real pod while a plain GET worked."""
    body = b"w" * 5000
    served = tmp_path / "srv" / "lora.safetensors"
    served.parent.mkdir()
    served.write_bytes(body)
    models = tmp_path / "models"
    monkeypatch.setattr(fx.shutil, "which", lambda name: "/usr/bin/aria2c")

    def refused(url, dest, headers):
        dest.write_bytes(b"")  # aria2c leaves an empty file and a control file behind
        dest.with_name(dest.name + ".aria2").write_bytes(b"")
        return False, "status=403"

    monkeypatch.setattr(fx, "_aria2_download", refused)
    job = {
        "folder": "loras",
        "name": "lora.safetensors",
        "size": len(body),
        "site": "other",
        "url": served.as_uri(),
    }
    ok, msg = fx.download(job, models, {})
    assert ok, msg
    assert (models / "loras" / "lora.safetensors").read_bytes() == body
    assert not (models / "loras" / "lora.safetensors.aria2").exists()


def test_download_failure_message_carries_the_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(fx.shutil, "which", lambda name: "/usr/bin/aria2c")
    monkeypatch.setattr(fx, "_aria2_download", lambda url, dest, headers: (False, "status=403"))
    job = {
        "folder": "loras",
        "name": "gone.safetensors",
        "size": 10,
        "site": "other",
        "url": (tmp_path / "missing.safetensors").as_uri(),
    }
    ok, msg = fx.download(job, tmp_path / "models", {})
    assert not ok and "status=403" in msg and "DOWNLOAD FAILED" in msg


def test_patch_model_manager_applies_once_and_fails_on_drift(tmp_path):
    src = tmp_path / "information.py"
    src.write_text(
        "\n".join(
            [
                "raise RuntimeError(f'Unknown Website, "
                "please input a URL from huggingface.co or civitai.com.')",
                '"type": self._resolve_model_type(res_data.get("type", "")),',
                'if host_name == "civitai.com":',
            ]
        ),
        encoding="utf-8",
    )
    pm.patch(src)
    out = src.read_text(encoding="utf-8")
    assert '"civitai.red"' in out and '"Diffusion Model"' in out
    with pytest.raises(SystemExit):
        pm.patch(src)  # already patched: the originals no longer match
