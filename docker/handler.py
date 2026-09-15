"""RunPod Serverless handler: run one ComfyUI API-format graph, return its output files.

Job input:
    {"workflow": {...API graph...},
     "images": {"ref1.jpg": "<base64>", ...},      # written to ComfyUI's input/ first (optional)
     "max_seconds": 1500}                            # give up after this long (optional)
Job output:
    {"prompt_id": "...", "seconds": 97.3,
     "files": [{"name": "h3_00001_.mp4", "bytes": 1234567, "b64": "..."}]}

RunPod caps a /run result at 10 MB, so files over MAX_RESULT_BYTES in total fail the job with a
clear message instead of an opaque platform error. ComfyUI runs in the same container
(started by start.sh); this file only talks to it over HTTP. `run_job` needs no runpod package,
so it is tested against a fake ComfyUI.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
COMFY_DIR = Path(os.environ.get("COMFY_DIR", "/opt/comfyui"))
MAX_RESULT_BYTES = 7 * 1024 * 1024  # base64 grows it by a third; RunPod /run allows 10 MB


def _get(path: str, timeout: float = 30) -> dict:
    with urllib.request.urlopen(COMFY_URL + path, timeout=timeout) as r:
        return json.load(r)


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        COMFY_URL + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # ComfyUI explains a rejected graph in the body
        raise RuntimeError(
            f"ComfyUI rejected the workflow: {e.read().decode(errors='replace')[:2000]}"
        )


def wait_for_comfy(max_seconds: float = 600) -> None:
    t0 = time.time()
    while True:
        try:
            _get("/system_stats", timeout=5)
            return
        except Exception:
            if time.time() - t0 > max_seconds:
                raise RuntimeError(f"ComfyUI did not come up within {max_seconds:.0f} s")
            time.sleep(1)


def _output_files(outputs: dict) -> list[Path]:
    files = []
    for node_out in outputs.values():
        for items in node_out.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("filename") and item.get("type") == "output":
                    files.append(
                        COMFY_DIR / "output" / item.get("subfolder", "") / item["filename"]
                    )
    return files


HF_BASE = os.environ.get("HF_BASE", "https://huggingface.co")
# loader node -> (input holding the file name, models subfolder)
LOADERS = {
    "LoraLoaderModelOnly": ("lora_name", "loras"),
    "LoraLoader": ("lora_name", "loras"),
    "UNETLoader": ("unet_name", "diffusion_models"),
    "VAELoader": ("vae_name", "vae"),
    "CLIPLoader": ("clip_name", "text_encoders"),
}


def fetch_missing_models(workflow: dict) -> list[str]:
    """Download model files the graph names but ComfyUI does not list, from the endpoint's HF repo.

    A cached model is a snapshot taken when the endpoint was set up, so a file added to the repo
    later is missing on the worker. Files go to ComfyUI's own models/<subfolder>, which ComfyUI
    rescans on the next prompt. Needs MODEL_REPO (or RunPod's MODEL_NAME), plus HF_TOKEN for a
    private repo.
    """
    repo = os.environ.get("MODEL_REPO") or os.environ.get("MODEL_NAME")
    token = os.environ.get("HF_TOKEN")
    fetched = []
    listed: dict[str, set] = {}
    for node in workflow.values():
        spec = LOADERS.get(node.get("class_type", ""))
        name = (node.get("inputs") or {}).get(spec[0]) if spec else None
        if not isinstance(name, str):
            continue
        folder = spec[1]
        if folder not in listed:
            listed[folder] = set(_get(f"/models/{folder}"))
        if name in listed[folder] or not repo:
            continue
        dest = COMFY_DIR / "models" / folder / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            f"{HF_BASE}/{repo}/resolve/main/{folder}/{name}",
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )
        part = dest.with_name(dest.name + ".part")
        with urllib.request.urlopen(req, timeout=600) as r, open(part, "wb") as f:
            while chunk := r.read(8 * 1024 * 1024):
                f.write(chunk)
        part.replace(dest)
        listed[folder].add(name)
        fetched.append(f"{folder}/{name}")
    return fetched


def run_job(job_input: dict) -> dict:
    workflow = job_input.get("workflow")
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("input.workflow must be a ComfyUI API-format graph (a JSON object)")
    for name, data in (job_input.get("images") or {}).items():
        dest = COMFY_DIR / "input" / Path(name).name  # never a path outside input/
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(data))
    max_seconds = float(job_input.get("max_seconds", 1500))

    wait_for_comfy()
    fetched = fetch_missing_models(workflow)
    t0 = time.time()
    prompt_id = _post("/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})["prompt_id"]
    while True:
        entry = _get(f"/history/{prompt_id}").get(prompt_id)
        if entry and entry.get("status", {}).get("completed"):
            break
        if entry and entry.get("status", {}).get("status_str") == "error":
            messages = entry["status"].get("messages", [])
            raise RuntimeError(f"ComfyUI error: {json.dumps(messages)[:2000]}")
        if time.time() - t0 > max_seconds:
            _post("/interrupt", {})
            raise RuntimeError(f"workflow still running after {max_seconds:.0f} s, interrupted")
        time.sleep(1)
    seconds = round(time.time() - t0, 1)

    paths = _output_files(entry.get("outputs", {}))
    total = sum(p.stat().st_size for p in paths)
    if total > MAX_RESULT_BYTES:
        raise RuntimeError(
            f"outputs are {total / 1e6:.1f} MB, over the {MAX_RESULT_BYTES / 1e6:.0f} MB a job "
            "result can carry; make the clip shorter or smaller"
        )
    files = []
    for p in paths:
        data = p.read_bytes()
        files.append({"name": p.name, "bytes": len(data), "b64": base64.b64encode(data).decode()})
        p.unlink(missing_ok=True)  # container disk stays clean between jobs
    return {"prompt_id": prompt_id, "seconds": seconds, "fetched": fetched, "files": files}


def handler(job: dict) -> dict:
    return run_job(job.get("input") or {})


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
