"""AI Angel model list: paste a list of Civitai / Hugging Face links, press one button, and every
file downloads into the right models folder. Adds a sidebar tab; no graph nodes.

API (same origin as ComfyUI):
  GET  /aiangel/status      jobs with progress, which API keys are saved (masked)
  POST /aiangel/keys        {"civitai": "...", "huggingface": "..."}; "" keeps, "-" clears
  POST /aiangel/download    {"text": "<pasted list>"} -> queued entries, or 400 with the bad line
"""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

from . import fetch

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

SECRETS = Path(os.environ.get("DATA_DIR", folder_paths.base_path)) / ".secrets"
SITES = ("civitai", "huggingface")
ENV_NAMES = {"civitai": "CIVITAI_TOKEN", "huggingface": "HF_TOKEN"}

_jobs: list[dict] = []
_lock = threading.Lock()
_queue: queue.Queue[dict] = queue.Queue()


def _models_dir() -> Path:
    return Path(folder_paths.models_dir)


def _token(site: str) -> str | None:
    f = SECRETS / f"{site}_token"
    if f.exists():
        value = f.read_text(encoding="utf-8").strip()
        if value:
            return value
    return os.environ.get(ENV_NAMES[site]) or None


def _mask(value: str | None) -> str | None:
    return None if not value else f"{value[:4]}…{value[-4:]}"


def _worker() -> None:
    while True:
        job = _queue.get()
        try:
            job["state"] = "resolving"
            job.update(fetch.resolve(job["folder_hint"], job["url"], job["file_part"]))
            job["state"] = "downloading"
            job["started"] = time.time()
            tokens = {site: _token(site) for site in SITES}
            ok, msg = fetch.download(job, _models_dir(), tokens)
            job["state"] = "done" if ok else "failed"
            job["message"] = msg
        except Exception as e:  # show the reason in the panel, keep the worker alive
            job["state"] = "failed"
            job["message"] = str(e)[:300]
        finally:
            _queue.task_done()


threading.Thread(target=_worker, name="aiangel-downloads", daemon=True).start()


def _job_view(job: dict) -> dict:
    view = {k: job.get(k) for k in ("id", "url", "state", "folder", "name", "size", "message")}
    if job.get("state") == "downloading" and job.get("name"):
        part = fetch.partial_path(job, _models_dir())
        view["done_bytes"] = part.stat().st_size if part.exists() else 0
    elif job.get("state") == "done":
        view["done_bytes"] = job.get("size") or 0
    return view


routes = PromptServer.instance.routes


@routes.get("/aiangel/status")
async def status(request: web.Request) -> web.Response:
    with _lock:
        jobs = [_job_view(j) for j in _jobs]
    keys = {site: _mask(_token(site)) for site in SITES}
    return web.json_response({"jobs": jobs, "keys": keys, "models_dir": str(_models_dir())})


@routes.post("/aiangel/keys")
async def save_keys(request: web.Request) -> web.Response:
    body = await request.json()
    SECRETS.mkdir(parents=True, exist_ok=True)
    for site in SITES:
        value = str(body.get(site) or "").strip()
        f = SECRETS / f"{site}_token"
        if value == "-":
            f.unlink(missing_ok=True)
        elif value:
            f.write_text(value, encoding="utf-8")
            f.chmod(0o600)
    return web.json_response({site: _mask(_token(site)) for site in SITES})


@routes.post("/aiangel/download")
async def start_download(request: web.Request) -> web.Response:
    body = await request.json()
    try:
        entries = fetch.parse_entries(str(body.get("text") or ""))
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    queued = []
    with _lock:
        for folder, url, file_part in entries:
            job = {
                "id": len(_jobs) + 1,
                "url": url,
                "folder_hint": folder,
                "file_part": file_part,
                "state": "queued",
            }
            _jobs.append(job)
            queued.append(job)
    for job in queued:
        _queue.put(job)
    return web.json_response({"queued": len(queued)})
