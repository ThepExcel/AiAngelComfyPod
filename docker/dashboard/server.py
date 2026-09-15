"""AI Angel Dashboard — standalone status/control server for the pod, port 8189.

Run with `python3.12 /opt/aiangel/dashboard/server.py`. Started by docker/start.sh BEFORE
ComfyUI, so it answers while ComfyUI is booting, crashed or restarting. HTTP contract:
docs/dashboard-api.md.

Reuses fetch.py / outputs.py from the ComfyUI-AiAngel node (loaded from AIANGEL_NODE_DIR)
instead of duplicating the download resolver, the output lister and the ZIP streamer. Those
two modules have no ComfyUI imports, so they load standalone here and in the tests.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue

from aiohttp import ClientSession, ClientTimeout, web

SITES = ("civitai", "huggingface")
ENV_TOKEN_NAMES = {"civitai": "CIVITAI_TOKEN", "huggingface": "HF_TOKEN"}
ELASTIC_DISK_BYTES = 1 << 50  # 1 PiB: what an elastic (Global) volume reports as its size


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _node_dir() -> Path:
    default = "/opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel"
    return Path(os.environ.get("AIANGEL_NODE_DIR", default))


_NODE = _node_dir()
fetch = _load_module("aiangel_dashboard_fetch", _NODE / "fetch.py")
outputs = _load_module("aiangel_dashboard_outputs", _NODE / "outputs.py")


# ---------------------------------------------------------------------------
# small helpers shared by several routes
# ---------------------------------------------------------------------------


def _written_bytes(path: Path) -> int:
    """Bytes actually on disk (allocated blocks), not the file's apparent length while a
    multi-connection downloader has pre-allocated the tail. Same idea as the node's
    _written_bytes."""
    if not path.exists():
        return 0
    st = path.stat()
    blocks = getattr(st, "st_blocks", None)
    return min(st.st_size, blocks * 512) if blocks else st.st_size


def _mask(value: str | None) -> str | None:
    return None if not value else f"{value[:4]}…{value[-4:]}"


def _read_secret(path: Path) -> str | None:
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    return None


class SizeTracker:
    """Tells a file that is actively growing apart from a stalled partial one, without waiting
    30 real seconds inside a request: it remembers, per file, the last observed byte count and
    the instant it last grew, so 'downloading' can be read from two polls instead of a sleep."""

    def __init__(self) -> None:
        self._seen: dict[str, tuple[int, float]] = {}

    def note(self, path: Path, size: int, now: float) -> float:
        key = str(path)
        last_size, last_growth = self._seen.get(key, (size, now))
        if size > last_size:
            last_growth = now
        self._seen[key] = (size, last_growth)
        return last_growth


class Cached:
    """Wraps a slow probe (nvidia-smi) so repeated /api/state polls do not each pay its cost."""

    def __init__(self, fn: Callable[[], dict], ttl: float = 2.0) -> None:
        self._fn = fn
        self._ttl = ttl
        self._at = 0.0
        self._val: dict = {}

    def __call__(self) -> dict:
        now = time.time()
        if now - self._at > self._ttl:
            self._val = self._fn()
            self._at = now
        return self._val


# ---------------------------------------------------------------------------
# process / hardware probes (each overridable in tests so nothing real is touched there)
# ---------------------------------------------------------------------------


def _nvidia_smi_stats() -> dict:
    try:
        p = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if p.returncode != 0 or not p.stdout.strip():
            return {}
        name, used, total, util = (part.strip() for part in p.stdout.splitlines()[0].split(","))
        return {"name": name, "used_mb": int(used), "total_mb": int(total), "util": int(util)}
    except Exception:
        return {}


def _find_comfy_pids(proc_root: Path = Path("/proc")) -> list[int]:
    pids = []
    if not proc_root.is_dir():
        return pids
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        parts = [p.decode(errors="replace") for p in raw.split(b"\x00") if p]
        if any("main.py" in p for p in parts) and any("8188" in p for p in parts):
            pids.append(int(entry.name))
    return pids


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _comfy_state() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=0.5) as r:
            if r.status == 200:
                return "ready"
    except Exception:
        pass
    return "starting" if _find_comfy_pids() else "down"


def _tcp_ready(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# config: every path and every swappable probe, built fresh per app instance
# ---------------------------------------------------------------------------


@dataclass
class Config:
    data_dir: Path
    models_dir: Path
    presets_file: Path
    nsfw_file: Path
    web_dir: Path
    comfy_dir: Path
    image_version_file: Path
    models_env: str
    start_time: float
    gpu_stats_fn: Callable[[], dict]
    comfy_state_fn: Callable[[], str]
    tcp_ready_fn: Callable[[int], bool]
    resolve_fn: Callable
    download_fn: Callable
    now_fn: Callable[[], float]
    jobs: list = field(default_factory=list)
    jobs_lock: threading.Lock = field(default_factory=threading.Lock)
    download_queue: Queue = field(default_factory=Queue)
    size_tracker: SizeTracker = field(default_factory=SizeTracker)

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / ".secrets"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def output_dir(self) -> Path:
        return self.data_dir / "output"

    def cuda_version(self) -> str | None:
        v = os.environ.get("CUDA_VERSION")
        if v:
            return v
        try:
            import torch  # optional: not installed in the dev/test environment

            return torch.version.cuda
        except Exception:
            return None

    def image_version(self) -> str | None:
        try:
            return self.image_version_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def disk_usage(self) -> dict:
        def one(path) -> dict:
            try:
                u = shutil.disk_usage(path)
            except OSError:
                return {"used": None, "total": None}
            # A RunPod Global volume (object storage) reports 0 used of 1 PiB: it has no fixed
            # size, so "free space" would be a made-up number.
            if u.total >= ELASTIC_DISK_BYTES:
                return {"used": None, "total": None, "elastic": True}
            return {"used": u.used, "total": u.total}

        return {"workspace": one(self.data_dir), "container": one("/")}

    @classmethod
    def from_env(cls, **overrides) -> Config:
        data_dir = Path(os.environ.get("DATA_DIR", "/workspace/aiangel"))
        default_web_dir = Path(__file__).resolve().parent / "web"
        cfg = cls(
            data_dir=data_dir,
            models_dir=Path(os.environ.get("MODELS_DIR", str(data_dir / "models"))),
            presets_file=Path(os.environ.get("PRESETS_FILE", "/opt/aiangel/models.tsv")),
            nsfw_file=Path(os.environ.get("AIANGEL_NSFW_KIT", "/opt/aiangel/nsfw.txt")),
            web_dir=Path(os.environ.get("AIANGEL_DASHBOARD_WEB_DIR", str(default_web_dir))),
            comfy_dir=Path(os.environ.get("AIANGEL_COMFY_DIR", "/opt/comfyui")),
            image_version_file=Path(
                os.environ.get("AIANGEL_IMAGE_VERSION_FILE", "/opt/aiangel/image-version")
            ),
            models_env=os.environ.get("MODELS", ""),
            start_time=time.time(),
            gpu_stats_fn=Cached(_nvidia_smi_stats),
            comfy_state_fn=_comfy_state,
            tcp_ready_fn=_tcp_ready,
            resolve_fn=fetch.resolve,
            download_fn=fetch.download,
            now_fn=time.time,
        )
        for key, value in overrides.items():
            setattr(cfg, key, value)
        worker = threading.Thread(
            target=_worker, name="aiangel-dashboard-downloads", args=(cfg,), daemon=True
        )
        worker.start()
        return cfg


def _token(cfg: Config, site: str) -> str | None:
    f = cfg.secrets_dir / f"{site}_token"
    if f.is_file():
        value = f.read_text(encoding="utf-8").strip()
        if value:
            return value
    return os.environ.get(ENV_TOKEN_NAMES[site]) or None


def _worker(cfg: Config) -> None:
    while True:
        job = cfg.download_queue.get()
        try:
            if not job.get("name"):
                job["state"] = "resolving"
                tokens = {site: _token(cfg, site) for site in SITES}
                resolved = cfg.resolve_fn(
                    job.get("folder_hint"), job["url"], job.get("file_part"), tokens
                )
                job.update(resolved)
            job["state"] = "downloading"
            tokens = {site: _token(cfg, site) for site in SITES}
            ok, msg = cfg.download_fn(job, cfg.models_dir, tokens)
            job["state"] = "done" if ok else "failed"
            job["message"] = msg
        except Exception as e:  # keep the worker alive, show the reason in the panel
            job["state"] = "failed"
            job["message"] = str(e)[:300]
        finally:
            cfg.download_queue.task_done()


# ---------------------------------------------------------------------------
# preset / file-state computation (pure, so it is testable without real downloads or sleeps)
# ---------------------------------------------------------------------------


def _preset_rows(presets_file: Path) -> list[tuple[list[str], str, str, int, str]]:
    rows = []
    if not presets_file.is_file():
        return rows
    for line in presets_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        preset, sub, name, size, url = line.split("\t")
        rows.append((preset.split(","), sub, name, int(size), url))
    return rows


def _in_env(name: str, models_env: str) -> bool:
    wanted = {p for p in models_env.replace(" ", "").split(",") if p}
    return name in wanted or "all" in wanted


def compute_file_state(
    path: Path, expected_size: int, tracker: SizeTracker, now: float, job_state: str | None
) -> tuple[str, int]:
    have = _written_bytes(path)
    if have >= expected_size > 0:
        return "have", have
    if job_state == "queued":
        return "queued", have
    if job_state in ("resolving", "downloading"):
        return "downloading", have
    if have > 0:
        last_growth = tracker.note(path, have, now)
        if now - last_growth <= 30:
            return "downloading", have
        return ("failed" if job_state == "failed" else "missing"), have
    return ("failed" if job_state == "failed" else "missing"), 0


def _preset_summaries(cfg: Config, jobs: list[dict], now: float) -> list[dict]:
    order: list[str] = []
    files_by_preset: dict[str, list[tuple[str, str, int, str]]] = {}
    for presets, sub, name, size, url in _preset_rows(cfg.presets_file):
        for p in presets:
            if p not in files_by_preset:
                files_by_preset[p] = []
                order.append(p)
            files_by_preset[p].append((sub, name, size, url))
    job_state_by_target = {
        (job["folder"], job["name"]): job["state"]
        for job in jobs
        if job.get("folder") and job.get("name")
    }
    summaries = []
    for name in order:
        files = []
        for sub, fname, size, _url in files_by_preset[name]:
            path = cfg.models_dir / sub / fname
            state, have = compute_file_state(
                path, size, cfg.size_tracker, now, job_state_by_target.get((sub, fname))
            )
            files.append(
                {"folder": sub, "name": fname, "size": size, "have_bytes": have, "state": state}
            )
        summaries.append({"name": name, "in_env": _in_env(name, cfg.models_env), "files": files})
    return summaries


def _outputs_summary(output_dir: Path) -> dict:
    files = outputs.list_outputs(output_dir)
    return {"count": len(files), "bytes": sum(f["size"] for f in files)}


def _job_view(job: dict, cfg: Config) -> dict:
    view = {
        "id": job["id"],
        "label": f"{job['folder']}/{job['name']}" if job.get("name") else job["url"],
        "url": job["url"],
        "state": job["state"],
        "size": job.get("size"),
        "message": job.get("message"),
        "done_bytes": 0,
    }
    if job.get("state") == "downloading" and job.get("name"):
        part = fetch.partial_path(job, cfg.models_dir)
        view["done_bytes"] = _written_bytes(part)
    elif job.get("state") == "done":
        view["done_bytes"] = job.get("size") or 0
    return view


def _service_url(request: web.Request, port: int) -> str:
    pod_id = os.environ.get("RUNPOD_POD_ID")
    if pod_id:
        return f"https://{pod_id}-{port}.proxy.runpod.net/"
    return f"http://{request.url.host}:{port}/"


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


async def get_state(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    now = cfg.now_fn()
    with cfg.jobs_lock:
        jobs = [dict(j) for j in cfg.jobs]
    gpu = cfg.gpu_stats_fn()
    pod = {
        "id": os.environ.get("RUNPOD_POD_ID") or None,
        "gpu": gpu.get("name"),
        "vram_used_mb": gpu.get("used_mb"),
        "vram_total_mb": gpu.get("total_mb"),
        "gpu_util": gpu.get("util"),
        "cuda": cfg.cuda_version(),
        "image": cfg.image_version(),
        "uptime_s": int(now - cfg.start_time),
        "disk": cfg.disk_usage(),
    }
    services = [
        {
            "key": "comfyui",
            "name": "ComfyUI",
            "port": 8188,
            "url": _service_url(request, 8188),
            "state": cfg.comfy_state_fn(),
        },
        {
            "key": "filebrowser",
            "name": "FileBrowser",
            "port": 8080,
            "url": _service_url(request, 8080),
            "state": "ready" if cfg.tcp_ready_fn(8080) else "down",
            "user": "admin",
            "secret": _read_secret(cfg.secrets_dir / "filebrowser_password"),
        },
        {
            "key": "jupyter",
            "name": "JupyterLab",
            "port": 8888,
            "url": _service_url(request, 8888),
            "state": "ready" if cfg.tcp_ready_fn(8888) else "down",
            "secret": _read_secret(cfg.secrets_dir / "jupyter_password"),
        },
    ]
    body = {
        "pod": pod,
        "services": services,
        "models_env": cfg.models_env,
        "presets": _preset_summaries(cfg, jobs, now),
        "jobs": [_job_view(j, cfg) for j in jobs],
        "keys": {site: _mask(_token(cfg, site)) for site in SITES},
        "outputs": _outputs_summary(cfg.output_dir()),
    }
    return web.json_response(body)


async def post_keys(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    body = await request.json()
    cfg.secrets_dir.mkdir(parents=True, exist_ok=True)
    for site in SITES:
        value = str(body.get(site) or "").strip()
        f = cfg.secrets_dir / f"{site}_token"
        if value == "-":
            f.unlink(missing_ok=True)
        elif value:
            f.write_text(value, encoding="utf-8", newline="\n")
            try:
                f.chmod(0o600)
            except OSError:  # RunPod Global volumes refuse chmod; the key is saved anyway
                pass
    return web.json_response({site: _mask(_token(cfg, site)) for site in SITES})


async def post_download(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    body = await request.json()
    try:
        entries = fetch.parse_entries(str(body.get("text") or ""))
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    queued = []
    with cfg.jobs_lock:
        for folder, url, file_part in entries:
            job = {
                "id": len(cfg.jobs) + 1,
                "url": url,
                "folder_hint": folder,
                "file_part": file_part,
                "state": "queued",
                "folder": None,
                "name": None,
                "size": None,
                "message": None,
            }
            cfg.jobs.append(job)
            queued.append(job)
    for job in queued:
        cfg.download_queue.put(job)
    return web.json_response({"queued": len(queued)})


async def post_preset(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    body = await request.json()
    name = str(body.get("name") or "")
    if name == "nsfw":
        return web.json_response(
            {"error": "nsfw needs the kit text: GET /api/kit/nsfw, then POST /api/download"},
            status=400,
        )
    rows = _preset_rows(cfg.presets_file)
    known = {p for presets, *_ in rows for p in presets}
    if name not in known:
        return web.json_response({"error": f"unknown preset: {name}"}, status=400)
    queued = []
    with cfg.jobs_lock:
        for presets, sub, fname, size, url in rows:
            if name not in presets:
                continue
            path = cfg.models_dir / sub / fname
            if _written_bytes(path) >= size:
                continue
            job = {
                "id": len(cfg.jobs) + 1,
                "url": url,
                "folder": sub,
                "name": fname,
                "size": size,
                "site": "huggingface",
                "state": "queued",
                "message": None,
            }
            cfg.jobs.append(job)
            queued.append(job)
    for job in queued:
        cfg.download_queue.put(job)
    return web.json_response({"queued": len(queued)})


async def get_nsfw_kit(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    if not cfg.nsfw_file.is_file():
        return web.json_response({"error": "no NSFW kit in this image"}, status=404)
    return web.json_response({"text": cfg.nsfw_file.read_text(encoding="utf-8")})


async def get_outputs(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    files = await asyncio.to_thread(outputs.list_outputs, cfg.output_dir())
    return web.json_response({"files": files, "output_dir": str(cfg.output_dir())})


async def get_outputs_file(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    rel = request.rel_url.query.get("path", "")
    try:
        files = outputs.safe_files(cfg.output_dir(), [rel])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    path, arc = files[0]
    headers = {}
    if request.rel_url.query.get("download") == "1":
        headers["Content-Disposition"] = f'attachment; filename="{Path(arc).name}"'
    return web.FileResponse(path, headers=headers)


async def post_outputs_zip(request: web.Request) -> web.StreamResponse:
    cfg: Config = request.app["cfg"]
    if request.content_type == "application/json":
        raw = (await request.json()).get("files")
    else:
        raw = (await request.post()).get("files")
    root = cfg.output_dir()
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


def _restart_comfyui(cfg: Config) -> None:
    pids = _find_comfy_pids()
    marker = cfg.data_dir / ".dashboard-restarted-at"
    try:
        marker.write_text(str(int(time.time())), encoding="utf-8", newline="\n")
    except OSError:
        pass
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 20
    while time.time() < deadline and any(_pid_alive(p) for p in pids):
        time.sleep(0.5)
    for pid in pids:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    args = os.environ.get("COMFYUI_ARGS", "").split()
    cmd = ["python3.12", "main.py", "--listen", "0.0.0.0", "--port", "8188", *args]
    with open(cfg.log_dir / "comfyui.log", "ab") as f:
        subprocess.Popen(cmd, cwd=str(cfg.comfy_dir), stdout=f, stderr=f, start_new_session=True)


async def post_comfy_restart(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    threading.Thread(target=_restart_comfyui, args=(cfg,), daemon=True).start()
    return web.json_response({"ok": True})


def _tail(path: Path, n: int, max_bytes: int = 2 << 20) -> list[str]:
    """Last n lines, reading at most the last max_bytes (a log polled every 2 s can be large)."""
    if not path.is_file():
        return []
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - max_bytes))
        text = f.read().decode("utf-8", errors="replace")
    # progress bars redraw with \r: keep only the last state of each line
    # (str.splitlines would split on \r too, so split on \n only)
    lines = [ln.rstrip("\r").rsplit("\r", 1)[-1] for ln in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    return lines[-n:]


def _secret_values(secrets_dir: Path) -> list[str]:
    values = []
    if secrets_dir.is_dir():
        for f in secrets_dir.iterdir():
            if f.is_file():
                v = f.read_text(encoding="utf-8", errors="replace").strip()
                if v:
                    values.append(v)
    return values


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _mask_line(line: str, secrets: list[str]) -> str:
    # ComfyUI and its nodes color their log lines; a browser would show the codes as "[32m"
    line = ANSI_ESCAPE.sub("", line)
    for v in secrets:
        line = line.replace(v, "••••")
    return line


async def _comfyui_live_logs(lines: int) -> list[str] | None:
    """Best effort: ComfyUI's own /internal/logs shape is not something this repo has seen (it
    lives in the base image, not here), so this parses defensively and falls back to the log
    file on anything unexpected."""
    try:
        async with (
            ClientSession(timeout=ClientTimeout(total=1.5)) as s,
            s.get("http://127.0.0.1:8188/internal/logs") as r,
        ):
            if r.status != 200:
                return None
            data = await r.json(content_type=None)
    except Exception:
        return None
    if isinstance(data, str):  # ComfyUI's /internal/logs joins every entry into one string
        return data.splitlines()[-lines:]
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("entries") or data.get("logs") or []
    else:
        return None
    out = []
    for e in entries:
        if isinstance(e, str):
            out.append(e)
        elif isinstance(e, dict):
            out.append(str(e.get("m") or e.get("message") or e))
    return out[-lines:]


async def get_logs(request: web.Request) -> web.Response:
    cfg: Config = request.app["cfg"]
    name = request.rel_url.query.get("name", "")
    try:
        n = int(request.rel_url.query.get("lines", "200"))
    except ValueError:
        n = 200
    if name == "boot":
        lines = _tail(cfg.log_dir / "boot.log", n)
    elif name == "models":
        lines = _tail(cfg.log_dir / "models.log", n)
    elif name == "comfyui":
        lines = None
        if cfg.comfy_state_fn() == "ready":
            lines = await _comfyui_live_logs(n)
        if lines is None:
            # after a dashboard restart ComfyUI writes comfyui.log; before that its output is
            # part of the boot log (start.sh tees everything it runs)
            log = cfg.log_dir / "comfyui.log"
            lines = _tail(log if log.is_file() else cfg.log_dir / "boot.log", n)
    else:
        return web.json_response({"error": f"unknown log name: {name}"}, status=400)
    secrets = _secret_values(cfg.secrets_dir)
    lines = [_mask_line(ln, secrets) for ln in lines]
    return web.json_response({"name": name, "lines": lines})


# ---------------------------------------------------------------------------
# CSRF: same rule as the patched ComfyUI server (docker/patch_comfy_origin.py)
# ---------------------------------------------------------------------------


@web.middleware
async def csrf_middleware(request: web.Request, handler):
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        is_page_open = (
            request.method == "GET"
            and request.headers.get("Sec-Fetch-Mode") == "navigate"
            and request.headers.get("Sec-Fetch-Dest") == "document"
        )
        if not is_page_open:
            return web.json_response({"error": "cross-site request refused"}, status=403)
    return await handler(request)


# ---------------------------------------------------------------------------
# static front end (owned by another lane, docker/dashboard/web/)
# ---------------------------------------------------------------------------


def _add_static_routes(app: web.Application, web_dir: Path) -> None:
    async def missing(request: web.Request) -> web.Response:
        return web.Response(text="dashboard front end missing", status=200)

    if not web_dir.is_dir():
        app.router.add_get("/", missing)
        return

    async def index(request: web.Request) -> web.Response:
        idx = web_dir / "index.html"
        if idx.is_file():
            return web.FileResponse(idx)
        return web.Response(text="dashboard front end missing", status=200)

    async def by_name(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        path = (web_dir / name).resolve()
        try:
            path.relative_to(web_dir.resolve())
        except ValueError:
            raise web.HTTPNotFound() from None
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    app.router.add_static("/static/", web_dir, show_index=False)
    app.router.add_get("/", index)
    app.router.add_get("/{name}", by_name)


def build_app(**overrides) -> web.Application:
    cfg = Config.from_env(**overrides)
    app = web.Application(middlewares=[csrf_middleware])
    app["cfg"] = cfg
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/keys", post_keys)
    app.router.add_post("/api/download", post_download)
    app.router.add_post("/api/preset", post_preset)
    app.router.add_get("/api/kit/nsfw", get_nsfw_kit)
    app.router.add_get("/api/outputs", get_outputs)
    app.router.add_get("/api/outputs/file", get_outputs_file)
    app.router.add_post("/api/outputs/zip", post_outputs_zip)
    app.router.add_post("/api/comfy/restart", post_comfy_restart)
    app.router.add_get("/api/logs", get_logs)
    _add_static_routes(app, cfg.web_dir)
    return app


def main() -> None:
    port = int(os.environ.get("DASHBOARD_PORT", "8189"))
    web.run_app(build_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
