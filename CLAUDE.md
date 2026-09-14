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
- `.github/workflows/build.yml` builds and pushes `ghcr.io/thepexcel/aiangelcomfypod` on push to main. No local docker on SiraPC — CI is the only build.
- Public repo: never add keys, our own LoRAs, workflows, prompts, outputs or anything NSFW (`tests/test_template.py` guards tokens and local paths). Owner ruling 2026-09-14: RunPod ToS §7 bans "pornography or graphic adult content … or other adult products" (lifetime ban), so the public template and repo stay neutral — neutral presets plus the paste-a-list **Model list** panel (`nodes/ComfyUI-AiAngel`). The NSFW paste list is distributed OUTSIDE RunPod/GitHub; its source is the private `D:/ClaudeMediaGen/scripts/runpod/private-extra-models.txt` (also `rp_pod.py up --extra-models-file`).
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
