"""AI Angel sidebar tabs, no graph nodes.

Model list: paste a list of Civitai / Hugging Face links, press one button, and every file
downloads into the right models folder. Outputs: see every result, download many as one ZIP, or
copy the pull script that syncs all new results to your computer.

API (same origin as ComfyUI):
  GET  /aiangel/status        jobs with progress, which API keys are saved (masked)
  GET  /aiangel/access        FileBrowser / JupyterLab passwords generated at boot (start.sh)
  POST /aiangel/keys          {"civitai": "...", "huggingface": "..."}; "" keeps, "-" clears
  POST /aiangel/download      {"text": "<pasted list>"} -> queued entries, or 400 with the bad line
  GET  /aiangel/outputs       output files, newest first: path, size, mtime, kind
  POST /aiangel/outputs/zip   form or JSON field "files" (JSON list of paths; empty = all) -> ZIP
  GET  /aiangel/pull.py       the standalone sync script (pull.py)
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

from . import fetch, outputs

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
            tokens = {site: _token(site) for site in SITES}
            job.update(fetch.resolve(job["folder_hint"], job["url"], job["file_part"], tokens))
            job["state"] = "downloading"
            job["started"] = time.time()
            ok, msg = fetch.download(job, _models_dir(), tokens)
            job["state"] = "done" if ok else "failed"
            job["message"] = msg
        except Exception as e:  # show the reason in the panel, keep the worker alive
            job["state"] = "failed"
            job["message"] = str(e)[:300]
        finally:
            _queue.task_done()


threading.Thread(target=_worker, name="aiangel-downloads", daemon=True).start()


def _written_bytes(path: Path) -> int:
    """Bytes actually on disk. aria2c writes 16 segments at their own offsets, so the file length
    jumps near the end early (measured on a pod: 13.8 of 14.1 GB shown minutes before it finished);
    allocated blocks track what has really been written."""
    if not path.exists():
        return 0
    st = path.stat()
    blocks = getattr(st, "st_blocks", None)
    return min(st.st_size, blocks * 512) if blocks else st.st_size


def _job_view(job: dict) -> dict:
    view = {k: job.get(k) for k in ("id", "url", "state", "folder", "name", "size", "message")}
    if job.get("state") == "downloading" and job.get("name"):
        part = fetch.partial_path(job, _models_dir())
        view["done_bytes"] = _written_bytes(part)
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


@routes.get("/aiangel/access")
async def access(request: web.Request) -> web.Response:
    """FileBrowser / JupyterLab passwords, shown in the panel so nobody has to dig through the pod
    log (RunPod keeps only its tail). Anyone who can reach this ComfyUI can already run code on the
    pod, so this exposes nothing new."""

    def read(name: str) -> str | None:
        f = SECRETS / name
        return f.read_text(encoding="utf-8").strip() or None if f.exists() else None

    return web.json_response(
        {
            "filebrowser": {
                "port": 8080,
                "user": "admin",
                "password": read("filebrowser_password"),
            },
            "jupyter": {"port": 8888, "token": read("jupyter_password")},
        }
    )


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
            try:
                f.chmod(0o600)
            except OSError:  # RunPod Global volumes refuse chmod; the key is saved anyway
                pass
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


NSFW_KIT = Path(os.environ.get("AIANGEL_NSFW_KIT", "/opt/aiangel/nsfw.txt"))


@routes.get("/aiangel/kit/nsfw")
async def nsfw_kit(request: web.Request) -> web.Response:
    if not NSFW_KIT.is_file():
        return web.json_response({"error": "no NSFW kit in this image"}, status=404)
    return web.json_response({"text": NSFW_KIT.read_text(encoding="utf-8")})


def _output_dir() -> Path:
    return Path(folder_paths.get_output_directory())


@routes.get("/aiangel/outputs")
async def list_outputs(request: web.Request) -> web.Response:
    files = await asyncio.to_thread(outputs.list_outputs, _output_dir())
    return web.json_response({"files": files, "output_dir": str(_output_dir())})


@routes.post("/aiangel/outputs/zip")
async def zip_outputs(request: web.Request) -> web.StreamResponse:
    if request.content_type == "application/json":
        raw = (await request.json()).get("files")
    else:
        raw = (await request.post()).get("files")
    root = _output_dir()
    try:
        rels = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
        if not rels:
            rels = [f["path"] for f in await asyncio.to_thread(outputs.list_outputs, root)]
        files = outputs.safe_files(root, [str(r) for r in rels])
    except ValueError as e:  # json.JSONDecodeError is a ValueError too
        return web.json_response({"error": str(e)}, status=400)
    if not files:
        return web.json_response({"error": "no output files yet"}, status=404)

    resp = web.StreamResponse(
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="{outputs.zip_name()}"',
            "Cache-Control": "no-store",
        }
    )
    await resp.prepare(request)
    chunks = outputs.zip_chunks(files)
    while (chunk := await asyncio.to_thread(next, chunks, None)) is not None:
        if chunk:
            await resp.write(chunk)
    await resp.write_eof()
    return resp


@routes.get("/aiangel/pull.py")
async def pull_script(request: web.Request) -> web.FileResponse:
    return web.FileResponse(
        Path(__file__).with_name("pull.py"),
        headers={
            "Content-Type": "text/x-python; charset=utf-8",
            "Content-Disposition": 'attachment; filename="pull.py"',
        },
    )
