"""Serverless worker: model path discovery and the job handler against a fake ComfyUI."""

from __future__ import annotations

import base64
import http.server
import importlib.util
import json
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "docker" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = load("serverless_models")


def fake_hf_repo(cache: Path, repo: str, snap: str, folders: list[str]) -> Path:
    repo_dir = cache / ("models--" + repo.replace("/", "--"))
    (repo_dir / "refs").mkdir(parents=True)
    (repo_dir / "refs" / "main").write_text(snap, encoding="utf-8")
    root = repo_dir / "snapshots" / snap
    for f in folders:
        (root / f).mkdir(parents=True)
        (root / f / "x.safetensors").write_bytes(b"0")
    return root


def test_cached_repo_and_volume_become_extra_model_paths(tmp_path):
    cache = tmp_path / "hub"
    snap = fake_hf_repo(
        cache, "AiAngelGallery/claire-h3", "abc123", ["diffusion_models", "loras", "vae"]
    )
    (cache / "models--AiAngelGallery--claire-h3" / "snapshots" / "old999" / "vae").mkdir(
        parents=True
    )
    volume = tmp_path / "volume-models"
    (volume / "text_encoders").mkdir(parents=True)

    roots = sm.model_roots(cache, volume, None)
    assert roots == [snap, volume]
    yaml = sm.render(roots)
    assert f"base_path: {snap.as_posix()}" in yaml
    assert "    diffusion_models: diffusion_models" in yaml and "    loras: loras" in yaml
    assert "text_encoders: text_encoders" in yaml
    assert "checkpoints" not in yaml  # only folders that exist


def test_named_repo_only_and_nothing_found(tmp_path):
    cache = tmp_path / "hub"
    fake_hf_repo(cache, "a/one", "s1", ["loras"])
    two = fake_hf_repo(cache, "b/two", "s2", ["vae"])
    assert sm.model_roots(cache, tmp_path / "none", "b/two") == [two]
    assert sm.model_roots(tmp_path / "missing", tmp_path / "none", None) == []
    assert sm.render([]) == ""


class FakeComfy(http.server.BaseHTTPRequestHandler):
    history: dict = {}
    output_dir: Path
    fail = False

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/system_stats":
            return self._json(200, {"system": {}})
        if self.path.startswith("/models/"):
            return self._json(200, ["MysticXXX_MMH3-V4.safetensors"])
        if self.path.startswith(
            "/AiAngelGallery/claire-h3/resolve/main/"
        ):  # doubles as the HF host
            if self.headers.get("Authorization") != "Bearer hf-test":
                return self._json(401, {})
            data = b"lora-bytes"
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        pid = self.path.rsplit("/", 1)[-1]
        return self._json(200, {pid: self.history[pid]} if pid in self.history else {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/interrupt":
            return self._json(200, {})
        if "bad" in json.dumps(body["prompt"]):
            return self._json(400, {"error": {"message": "Prompt outputs failed validation"}})
        pid = "p1"
        if FakeComfy.fail:
            FakeComfy.history[pid] = {
                "status": {
                    "status_str": "error",
                    "completed": False,
                    "messages": [["execution_error", {"exception_message": "OOM"}]],
                }
            }
        else:
            sub = FakeComfy.output_dir / "AiAngel"
            sub.mkdir(parents=True, exist_ok=True)
            (sub / "h3_00001_.mp4").write_bytes(b"video-bytes")
            FakeComfy.history[pid] = {
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "h3_00001_.mp4", "subfolder": "AiAngel", "type": "output"}
                        ],
                        "animated": [True],
                    }
                },
            }
        return self._json(200, {"prompt_id": pid})

    def log_message(self, *args):
        pass


@pytest.fixture
def comfy(tmp_path, monkeypatch):
    hd = load("handler")
    FakeComfy.history, FakeComfy.output_dir, FakeComfy.fail = {}, tmp_path / "output", False
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeComfy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(hd, "COMFY_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(hd, "HF_BASE", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(hd, "COMFY_DIR", tmp_path)
    yield hd, tmp_path
    srv.shutdown()


def test_job_returns_the_video_and_writes_input_images(comfy):
    hd, comfy_dir = comfy
    out = hd.handler(
        {
            "input": {
                "workflow": {"1": {"class_type": "SaveVideo"}},
                "images": {"../../evil/ref1.jpg": base64.b64encode(b"jpg").decode()},
            }
        }
    )
    assert (comfy_dir / "input" / "ref1.jpg").read_bytes() == b"jpg"
    assert not (comfy_dir.parent / "evil").exists()
    assert [f["name"] for f in out["files"]] == ["h3_00001_.mp4"]
    assert base64.b64decode(out["files"][0]["b64"]) == b"video-bytes"
    assert not (comfy_dir / "output" / "AiAngel" / "h3_00001_.mp4").exists()


def test_rejected_graph_and_execution_error_fail_the_job(comfy):
    hd, _ = comfy
    with pytest.raises(RuntimeError, match="failed validation"):
        hd.run_job({"workflow": {"1": {"class_type": "bad"}}})
    FakeComfy.fail = True
    with pytest.raises(RuntimeError, match="OOM"):
        hd.run_job({"workflow": {"1": {"class_type": "SaveVideo"}}})
    with pytest.raises(ValueError):
        hd.run_job({})


def test_missing_lora_is_fetched_from_the_endpoint_repo(comfy, monkeypatch):
    hd, comfy_dir = comfy
    monkeypatch.setenv("MODEL_NAME", "AiAngelGallery/claire-h3")
    monkeypatch.setenv("HF_TOKEN", "hf-test")
    graph = {
        "1": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "H3_Motion_BoosterV2.safetensors"},
        },
        "2": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "MysticXXX_MMH3-V4.safetensors"},
        },
        "3": {"class_type": "SaveVideo", "inputs": {}},
    }
    out = hd.run_job({"workflow": graph})
    assert out["fetched"] == [
        "loras/H3_Motion_BoosterV2.safetensors"
    ]  # the listed one is not re-fetched
    assert (
        comfy_dir / "models" / "loras" / "H3_Motion_BoosterV2.safetensors"
    ).read_bytes() == b"lora-bytes"


def test_oversized_output_fails_clearly(comfy, monkeypatch):
    hd, _ = comfy
    monkeypatch.setattr(hd, "MAX_RESULT_BYTES", 5)
    with pytest.raises(RuntimeError, match="over the"):
        hd.run_job({"workflow": {"1": {"class_type": "SaveVideo"}}})


def test_image_wires_serverless_mode():
    start = (ROOT / "docker" / "start.sh").read_text(encoding="utf-8")
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'AIANGEL_SERVERLESS:-0}" = 1' in start and "/opt/aiangel/handler.py" in start
    assert "--target /opt/aiangel/sls" in docker and "docker/handler.py" in docker
