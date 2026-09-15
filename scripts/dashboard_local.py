"""Run the pod dashboard on this machine against a throwaway data dir (no GPU, no ComfyUI).

Fills the data dir with a few fake outputs and one finished + one partial model file, so every
tab has something real (served by the real server) to render.

usage: uv run --with aiohttp python scripts/dashboard_local.py [PORT] [DATA_DIR]
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
port = sys.argv[1] if len(sys.argv) > 1 else "8190"
data = Path(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="aiangel-dash-"))

(data / "output" / "AiAngel").mkdir(parents=True, exist_ok=True)
(data / "logs").mkdir(exist_ok=True)
(data / ".secrets").mkdir(exist_ok=True)
(data / ".secrets" / "filebrowser_password").write_text("local-fb-pass", encoding="utf-8")
(data / ".secrets" / "jupyter_password").write_text("local-jupyter-token", encoding="utf-8")
for i in range(1, 7):
    (data / "output" / "AiAngel" / f"local_{i:05d}_.png").write_bytes(b"\x89PNG" + b"0" * 2048 * i)
(data / "logs" / "boot.log").write_text(
    "[aiangel] boot start\n  FileBrowser :8080 password local-fb-pass\n"
    "[aiangel] WARNING: sample warning\n[aiangel] ComfyUI READY on :8188\n",
    encoding="utf-8",
)
models = data / "models"
(models / "vae").mkdir(parents=True, exist_ok=True)
with (models / "vae" / "minimax_h3_audio_vae_fp32.safetensors").open("wb") as f:
    f.truncate(605254808)  # full size: shows as "have"
with (models / "vae" / "minimax_h3_video_vae_fp16.safetensors").open("wb") as f:
    f.write(b"0" * (64 << 20))  # partial

os.environ.update(
    DATA_DIR=str(data),
    MODELS_DIR=str(models),
    PRESETS_FILE=str(ROOT / "presets" / "models.tsv"),
    AIANGEL_NSFW_KIT=str(ROOT / "presets" / "nsfw.txt"),
    AIANGEL_NODE_DIR=str(ROOT / "nodes" / "ComfyUI-AiAngel"),
    MODELS="h3core,h3upscaler,aiangelh3",
    DASHBOARD_PORT=port,
)
print("data dir", data, flush=True)
sys.path.insert(0, str(ROOT / "docker" / "dashboard"))
import server  # noqa: E402

server.main()
