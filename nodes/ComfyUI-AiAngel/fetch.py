"""Resolve and download a pasted model list (Civitai, Hugging Face or direct links).

Used by the ComfyUI sidebar tab (this package's __init__.py) and at pod boot for EXTRA_MODELS:

    python3.12 fetch.py              # reads EXTRA_MODELS, MODELS_DIR, CIVITAI_TOKEN, HF_TOKEN
    python3.12 fetch.py --dry-run    # resolve only

A list holds entries separated by newlines, spaces or ";". Lines starting with # are comments.

    URL                      folder chosen automatically
    FOLDER|URL               e.g. loras|https://civitai.com/models/123?modelVersionId=456
    FOLDER|URL|FILE_PART     pick the Civitai file whose name contains FILE_PART

Civitai links may use civitai.com or civitai.red; downloads need a Civitai API key. The key
goes into the civitai.com URL as ?token= (an Authorization header would be replayed to the
signed storage URL Civitai redirects to). Hugging Face links use a Bearer token when given.
Tokens are never printed. Files already present at the expected size are skipped.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CIVITAI_HOSTS = {"civitai.com", "www.civitai.com", "civitai.red", "www.civitai.red"}
CIVITAI_API = "https://civitai.com/api/v1"
UA = {"User-Agent": "AiAngelComfyPod/1.0"}
KNOWN_FOLDERS = {
    "checkpoints",
    "clip_vision",
    "controlnet",
    "diffusion_models",
    "embeddings",
    "loras",
    "text_encoders",
    "upscale_models",
    "vae",
}


def parse_entries(raw: str) -> list[tuple[str | None, str, str | None]]:
    entries = []
    text = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#"))
    for token in re.split(r"[\s;]+", text.strip()):
        if not token:
            continue
        parts = token.split("|")
        if len(parts) == 1 and parts[0].startswith("http"):
            entries.append((None, parts[0], None))
        elif len(parts) in (2, 3) and parts[0] in KNOWN_FOLDERS and parts[1].startswith("http"):
            entries.append((parts[0], parts[1], parts[2] if len(parts) == 3 else None))
        else:
            raise ValueError(f"bad entry: {token[:80]}")
    return entries


def civitai_ids(url: str) -> tuple[str | None, str | None]:
    """Return (model_id, version_id) from any Civitai page or download link."""
    parsed = urlparse(url)
    version = parse_qs(parsed.query).get("modelVersionId", [None])[0]
    m = re.match(r"^/api/download/models/(\d+)", parsed.path) or re.match(
        r"^/model-versions/(\d+)", parsed.path
    )
    if m:
        version = m.group(1)
    m = re.match(r"^/models/(\d+)", parsed.path)
    return (m.group(1) if m else None), version


def pick_file(files: list[dict], file_part: str | None) -> dict:
    weights = [f for f in files if f.get("type") in ("Model", "Diffusion Model", "Pruned Model")]
    candidates = weights or files
    if not candidates:
        raise ValueError("this version has no files")
    if file_part:
        matched = [f for f in candidates if file_part in f.get("name", "")]
        if not matched:
            raise ValueError(f"no file containing {file_part!r}")
        return matched[0]
    return next((f for f in candidates if f.get("primary")), candidates[0])


def civitai_folder(model_type: str, file_type: str) -> str:
    if file_type == "Diffusion Model":
        return "diffusion_models"
    return {
        "Checkpoint": "checkpoints",
        "LORA": "loras",
        "LoCon": "loras",
        "DoRA": "loras",
        "VAE": "vae",
        "TextualInversion": "embeddings",
        "Controlnet": "controlnet",
        "Upscaler": "upscale_models",
    }.get(model_type, "checkpoints")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def resolve(
    folder: str | None, url: str, file_part: str | None, tokens: dict | None = None
) -> dict:
    host = urlparse(url).hostname or ""
    if host in CIVITAI_HOSTS:
        model_id, version_id = civitai_ids(url)
        if version_id:
            version = get_json(f"{CIVITAI_API}/model-versions/{version_id}")
            model_type = (version.get("model") or {}).get("type", "")
        elif model_id:
            model = get_json(f"{CIVITAI_API}/models/{model_id}")
            version, model_type = model["modelVersions"][0], model.get("type", "")
        else:
            raise ValueError("Civitai link without a model or version id")
        f = pick_file(version.get("files", []), file_part)
        return {
            "folder": folder or civitai_folder(model_type, f.get("type", "")),
            "name": f["name"],
            "url": f["downloadUrl"],
            "size": int(round(float(f.get("sizeKB") or 0) * 1024)),
            "site": "civitai",
        }
    name = Path(urlparse(url).path).name
    if not name:
        raise ValueError("link has no file name")
    return {
        "folder": folder or "checkpoints",
        "name": name,
        "url": url,
        "size": remote_size(
            url, (tokens or {}).get("huggingface") if host == "huggingface.co" else None
        ),
        "site": "huggingface" if host == "huggingface.co" else "direct",
    }


def remote_size(url: str, token: str | None = None) -> int:
    """Byte size from a HEAD request (0 when the server will not say). Without it a 0-byte file
    left by a failed attempt looked like a finished download (seen on a pod 2026-09-14).
    A private Hugging Face repo answers an anonymous HEAD with 401, so the token goes along."""
    headers = {**UA, **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        req = urllib.request.Request(url, headers=headers, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:  # gated repo without a token, offline, ...: size stays unknown
        return 0


def authed_civitai_url(url: str, token: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}token={token}"


def already_have(path: Path, size: int) -> bool:
    if not path.exists() or path.with_name(path.name + ".aria2").exists():
        return False
    if path.with_name(path.name + ".aria2__temp").exists() or path.stat().st_size == 0:
        return False  # an interrupted aria2c run or an empty leftover is never a finished file
    # Civitai reports size in KB with rounding, so allow a little slack.
    return size == 0 or abs(path.stat().st_size - size) <= 4096


def _python_download(url: str, dest: Path, headers: dict) -> bool:
    """Resumable fallback when aria2c is not installed."""
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={**UA, **headers})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req, timeout=120) as r:
        mode = "ab" if have and r.status == 206 else "wb"
        with open(part, mode) as f:
            shutil.copyfileobj(r, f, 8 * 1024 * 1024)
    part.replace(dest)
    return True


def partial_path(job: dict, models_dir: Path) -> Path:
    """The file that grows while this job downloads (for progress display)."""
    dest = models_dir / job["folder"] / job["name"]
    part = dest.with_name(dest.name + ".part")
    return part if part.exists() else dest


def _aria2_reason(output: str) -> str:
    """The useful part of aria2c's error output, e.g. 'status=403'."""
    m = re.search(r"status=\d{3}", output)
    if m:
        return m.group(0)
    errors = [ln.strip() for ln in output.splitlines() if "ERROR" in ln or "errorCode" in ln]
    return (errors[-1] if errors else "aria2c failed")[:160]


def _aria2_download(url: str, dest: Path, headers: dict) -> tuple[bool, str]:
    cmd = [
        "aria2c",
        "-x",
        "16",
        "-s",
        "16",
        "-c",
        "--file-allocation=none",
        "--console-log-level=error",
    ]
    cmd += ["--summary-interval=0", f"--user-agent={UA['User-Agent']}"]
    cmd += ["--auto-file-renaming=false", "-d", str(dest.parent), "-o", dest.name]
    cmd += [f"--header={k}: {v}" for k, v in headers.items()]
    p = subprocess.run(cmd + [url], capture_output=True, text=True, errors="replace")
    return p.returncode == 0, "" if p.returncode == 0 else _aria2_reason(p.stdout + p.stderr)


def download(job: dict, models_dir: Path, tokens: dict) -> tuple[bool, str]:
    """Download one resolved job. Returns (ok, message) and never raises."""
    dest = models_dir / job["folder"] / job["name"]
    label = f"{job['folder']}/{job['name']}"
    if already_have(dest, job["size"]):
        return True, f"have {label}"
    token = tokens.get(job["site"]) or ""
    if job["site"] == "civitai" and not token:
        return False, f"{label}: Civitai downloads need your Civitai API key"
    url, headers = job["url"], {}
    if token and job["site"] == "civitai":
        url = authed_civitai_url(url, token)
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    reason = ""
    ok = False
    try:
        if shutil.which("aria2c"):
            ok, reason = _aria2_download(url, dest, headers)
        if not ok:
            # Some Civitai files redirect to b2.civitai.com, which answers aria2c with 403 while a
            # plain single-connection GET works (measured on a pod 2026-09-14).
            if reason:
                dest.unlink(missing_ok=True)
                dest.with_name(dest.name + ".aria2").unlink(missing_ok=True)
            ok = _python_download(url, dest, headers)
    except urllib.error.HTTPError as e:
        return False, f"DOWNLOAD FAILED {label}: HTTP {e.code}" + (
            f" (aria2c {reason})" if reason else ""
        )
    except Exception as e:  # a network error must not kill the caller's loop
        return False, f"DOWNLOAD FAILED {label}: {type(e).__name__}" + (
            f" (aria2c {reason})" if reason else ""
        )
    ok = ok and already_have(dest, job["size"])
    if ok:
        return True, f"got {label}"
    size_now = dest.stat().st_size if dest.exists() else 0
    return False, f"DOWNLOAD FAILED {label}: size {size_now} != expected {job['size']}"


def env_tokens() -> dict:
    return {"civitai": os.environ.get("CIVITAI_TOKEN"), "huggingface": os.environ.get("HF_TOKEN")}


def main(argv: list[str], emit: Callable[[str], None] = print) -> int:
    models_dir = Path(os.environ.get("MODELS_DIR", "/opt/comfyui/models"))
    failed = 0
    for folder, url, file_part in parse_entries(os.environ.get("EXTRA_MODELS", "")):
        try:
            job = resolve(folder, url, file_part, env_tokens())
        except Exception as e:  # report and continue with the next entry
            emit(f"[extra] RESOLVE FAILED {url[:80]}: {e}")
            failed += 1
            continue
        emit(f"[extra] {job['folder']}/{job['name']} {job['size'] / 1e9:.2f} GB")
        if "--dry-run" in argv:
            continue
        ok, msg = download(job, models_dir, env_tokens())
        emit(f"[extra] {msg}")
        failed += 0 if ok else 1
    emit(f"[extra] done, {failed} problem(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], lambda s: print(s, flush=True)))
