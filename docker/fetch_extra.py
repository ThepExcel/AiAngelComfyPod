"""Download extra models named in EXTRA_MODELS (Civitai, Hugging Face or direct links).

EXTRA_MODELS holds entries separated by newlines, spaces or ";". Each entry is

    URL                      folder chosen automatically
    FOLDER|URL               e.g. loras|https://civitai.com/models/123?modelVersionId=456
    FOLDER|URL|FILE_PART     pick the Civitai file whose name contains FILE_PART

Civitai links may use civitai.com or civitai.red; a download needs CIVITAI_TOKEN (your own
Civitai API key). Hugging Face links use HF_TOKEN when set. Tokens are sent only to their own
site and never printed. Files already present at the expected size are skipped.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
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
    for token in re.split(r"[\s;]+", raw.strip()):
        if not token:
            continue
        parts = token.split("|")
        if len(parts) == 1:
            entries.append((None, parts[0], None))
        elif len(parts) in (2, 3) and parts[0] in KNOWN_FOLDERS:
            entries.append((parts[0], parts[1], parts[2] if len(parts) == 3 else None))
        else:
            raise ValueError(f"bad EXTRA_MODELS entry: {token[:80]}")
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


def resolve(folder: str | None, url: str, file_part: str | None) -> dict:
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
            "token_env": "CIVITAI_TOKEN",
        }
    name = Path(urlparse(url).path).name
    if not name:
        raise ValueError("link has no file name")
    return {
        "folder": folder or "checkpoints",
        "name": name,
        "url": url,
        "size": 0,
        "token_env": "HF_TOKEN" if host == "huggingface.co" else None,
    }


def authed_civitai_url(url: str, token: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}token={token}"


def already_have(path: Path, size: int) -> bool:
    if not path.exists() or path.with_name(path.name + ".aria2").exists():
        return False
    # Civitai reports size in KB with rounding, so allow a little slack.
    return size == 0 or abs(path.stat().st_size - size) <= 4096


def main() -> int:
    raw = os.environ.get("EXTRA_MODELS", "")
    models_dir = Path(os.environ.get("MODELS_DIR", "/opt/comfyui/models"))
    dry = "--dry-run" in sys.argv
    failed = 0
    for folder, url, file_part in parse_entries(raw):
        try:
            job = resolve(folder, url, file_part)
        except Exception as e:  # report and continue with the next entry
            print(f"[extra] RESOLVE FAILED {url[:80]}: {e}", flush=True)
            failed += 1
            continue
        dest = models_dir / job["folder"] / job["name"]
        gb = job["size"] / 1e9
        if dry:
            print(f"[extra] {job['folder']}/{job['name']} {gb:.2f} GB", flush=True)
            continue
        if already_have(dest, job["size"]):
            print(f"[extra] have {job['folder']}/{job['name']}", flush=True)
            continue
        label = f"{job['folder']}/{job['name']}"
        token = os.environ.get(job["token_env"] or "", "")
        if job["token_env"] == "CIVITAI_TOKEN" and not token:
            print(f"[extra] SKIPPED {label}: Civitai downloads need CIVITAI_TOKEN", flush=True)
            failed += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "aria2c",
            "-q",
            "-x",
            "16",
            "-s",
            "16",
            "-c",
            "--auto-file-renaming=false",
            "-d",
            str(dest.parent),
            "-o",
            dest.name,
        ]
        url = job["url"]
        if token and job["token_env"] == "CIVITAI_TOKEN":
            # A query token stays on civitai.com; an Authorization header would be replayed to the
            # signed storage URL Civitai redirects to, which rejects a second auth mechanism.
            url = authed_civitai_url(url, token)
        elif token:
            cmd.append(f"--header=Authorization: Bearer {token}")
        print(f"[extra] downloading {label} ({gb:.2f} GB)", flush=True)
        ok = subprocess.run(cmd + [url]).returncode == 0 and already_have(dest, job["size"])
        print(f"[extra] {'got' if ok else 'DOWNLOAD FAILED'} {label}", flush=True)
        failed += 0 if ok else 1
    print(f"[extra] done, {failed} problem(s)", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
