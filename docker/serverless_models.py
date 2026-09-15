"""Point ComfyUI at the models a RunPod Serverless worker can see, via extra_model_paths.yaml.

Two sources, both optional:
  - the endpoint's cached model: a Hugging Face repo laid out like ComfyUI's models/ folder
    (diffusion_models/, loras/, vae/, ...), mounted under /runpod-volume/huggingface-cache/hub
  - a network volume that a pod of this template filled: /runpod-volume/aiangel/models

    python3.12 serverless_models.py OUT_YAML [--hf-cache DIR] [--volume-models DIR]
                                    [--repo OWNER/NAME]

Prints one line per source it found. Stdlib only.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

HF_CACHE = "/runpod-volume/huggingface-cache/hub"
VOLUME_MODELS = "/runpod-volume/aiangel/models"
FOLDERS = (
    "checkpoints",
    "clip_vision",
    "controlnet",
    "diffusion_models",
    "embeddings",
    "latent_upscale_models",
    "loras",
    "text_encoders",
    "upscale_models",
    "vae",
    "vae_approx",
)


def snapshot(repo_dir: Path) -> Path | None:
    """The snapshot folder refs/main points at, else the newest one (HF cache layout)."""
    snaps = repo_dir / "snapshots"
    ref = repo_dir / "refs" / "main"
    if ref.is_file():
        candidate = snaps / ref.read_text(encoding="utf-8").strip()
        if candidate.is_dir():
            return candidate
    if snaps.is_dir():
        found = sorted((p for p in snaps.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        if found:
            return found[-1]
    return None


def model_roots(hf_cache: Path, volume_models: Path, repo: str | None) -> list[Path]:
    roots = []
    if hf_cache.is_dir():
        if repo:
            repo_dirs = [hf_cache / ("models--" + repo.replace("/", "--"))]
        else:
            repo_dirs = sorted(hf_cache.glob("models--*"))
        for repo_dir in repo_dirs:
            snap = snapshot(repo_dir)
            if snap:
                roots.append(snap)
    if volume_models.is_dir():
        roots.append(volume_models)
    return roots


def render(roots: list[Path]) -> str:
    lines = []
    for i, root in enumerate(roots):
        present = [f for f in FOLDERS if (root / f).is_dir()]
        if not present:
            continue
        lines.append(f"aiangel_source_{i}:")
        lines.append(f"    base_path: {root.as_posix()}")
        lines.extend(f"    {f}: {f}" for f in present)
    return "\n".join(lines) + "\n" if lines else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--hf-cache", default=HF_CACHE)
    ap.add_argument("--volume-models", default=VOLUME_MODELS)
    ap.add_argument("--repo", default=os.environ.get("MODEL_REPO") or None)
    a = ap.parse_args()
    roots = model_roots(Path(a.hf_cache), Path(a.volume_models), a.repo)
    Path(a.out).write_text(render(roots), encoding="utf-8")
    for root in roots:
        print(f"models from {root}")
    if not roots:
        print("WARNING: no cached model and no network volume models found")


if __name__ == "__main__":
    main()
