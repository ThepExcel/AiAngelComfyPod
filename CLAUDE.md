---
purpose: |
  Career/income: run ComfyUI video models (SCAIL-2, MiniMax H3) on rented RunPod GPUs fast and cheap, published as a public AI Angel template that earns creator credits
---
> STATUS: active · kind: tool · template: tool@1.0.0 · registry: claude-master/registry/projects.yaml

# AiAngelComfyPod

Career/income: run ComfyUI video models (SCAIL-2, MiniMax H3) on rented RunPod GPUs fast and cheap, published as a public AI Angel template that earns creator credits

## Commands

```bash
scripts/dev     # run the entry point (uv run python -m aiangelcomfypod)
scripts/test    # uv run pytest -q
scripts/lint    # uv run ruff check . && uv run ruff format --check .
```

## Template layout

- `Dockerfile` — FROM `runpod/comfyui` pinned by digest; ComfyUI runs from `/opt/comfyui` in the image, user data under `$DATA_DIR` (`/workspace/aiangel`) via symlinks.
- `docker/start.sh` (entrypoint) · `docker/download_models.sh` (presets by `MODELS=`) · `presets/models.tsv` (preset, subdir, file, bytes, HF URL).
- `.github/workflows/build.yml` builds and pushes `ghcr.io/thepexcel/aiangelcomfypod` on push to main as a matrix: `:cuda12.8` (also `:latest`) and `:cuda13.0`, same RunPod ComfyUI release pinned by digest. `latest` moves to 13.0 only after a pod A/B shows it faster; a CUDA 13 image needs a host driver that supports it (RunPod `allowedCudaVersions` accepts at most `13.0`). No local docker on SiraPC — CI is the only build.
- Custom node packs baked at build (krea2edit, MAINodes, Spectrum, WhatDreamsCost, H3 Prompt IDE, rgthree-comfy, Easy-Use, VideoHelperSuite, obvpm, SolAttn) are pinned by commit + sha256 and listed in `tests/test_template.py BAKED_NODE_PACKS`. The H3 latent upscaler node has no LICENSE file, so it is never baked; `MODELS=...,h3upscaler` fetches its code (pinned commit, in `docker/start.sh`) and its model file (a normal `presets/models.tsv` preset) onto the user's own pod at boot instead.
- `h3` preset = hybrid fl2va+ref2va b25 + int8 and fp16 video VAEs + both turbo LoRAs; `h3extra` = b20, plain ref2va, 8-step fl2v LoRA, taeh3. Measured on a 5090: the int8 video VAE gives no speedup on CUDA 12.8.
- Model list downloads: Civitai files served from b2.civitai.com refuse aria2c (403), so `fetch.download` falls back to a plain GET; a 0-byte or aria2 `__temp` leftover never counts as finished.
- Public repo: never add keys, our own trained LoRAs, private workflows, prompts, outputs or character refs (`tests/test_template.py` guards tokens and local paths). Owner ruling 2026-09-14 (evening, reversing the same morning's "stay neutral"): the public template ships an **NSFW kit** — `presets/nsfw.txt` (third-party Civitai/HF links, pinned versions), opt-in via `MODELS=...,nsfw` or the panel's "Load NSFW kit (18+)" button. The owner was told once that RunPod ToS §7 bans adult products with a lifetime account ban and confirmed anyway; do not re-litigate, but keep the kit opt-in and adults-only. Private-only lists (character kits) stay in `D:/ClaudeMediaGen/scripts/runpod/`.
- `nodes/ComfyUI-AiAngel` also carries the **Outputs** tab (`outputs.py` streams a STORED ZIP; `pull.py` is the stdlib sync script served at `/aiangel/pull.py`). Its routes are tested for real in `tests/test_outputs.py` (`scripts/test` adds aiohttp).
- ComfyUI-Model-Manager is patched at build (`docker/patch_model_manager.py`: civitai.red hosts, Diffusion Model → diffusion_models); a new upstream release must re-pass that patch.
- Paid pod/volume actions (tooling lives in `D:/ClaudeMediaGen/scripts/runpod/rp_pod.py`) need the owner's yes per session.

## Architecture invariants

1. All Thai text crosses subprocess/API boundaries via UTF-8 file, never argv or stdin (cp874 rule).
2. Paid API calls emit an audit sidecar JSON (endpoint, request_id, cost_estimate) before returning.
3. Credentials are read from os.environ — never hardcoded, never printed in full.
4. Entry point uses argparse + `sys.stdout.reconfigure(encoding="utf-8")`.

## Boundaries

**always:** uv for all Python execution; ruff for lint+format; pytest for tests.
**ask-first:** adding a new external dependency; changing the public CLI interface.
**never:** print credential values; commit .env files; use inline Thai in subprocess argv.

## Mistakes log

| Date | Symptom | Root cause | Fix |
|------|---------|-----------|-----|
| — | — | — | — |

## Pointers

- Thai I/O pattern, audit-sidecar contract: see gold example `src/aiangelcomfypod/example.py`
- Visual assets: /visual-assist
- Slide decks: /slide-assist
