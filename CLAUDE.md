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
- RunPod **Global volumes** (BETA, object storage, mounted at `/workspace`) refuse temp-file creation (`mkstemp: Operation not permitted`): plain `rsync -a` left every baked node an empty folder while model downloads worked. `start.sh` syncs nodes with `--inplace`, re-checks each node's `__init__.py` every boot, and falls back to a symlink into the image.
- `docker/start.sh` (entrypoint) · `docker/download_models.sh` (presets by `MODELS=`) · `presets/models.tsv` (preset, subdir, file, bytes, HF URL).
- `.github/workflows/build.yml` builds and pushes `ghcr.io/thepexcel/aiangelcomfypod` on push to main as a matrix: `:cuda13.0` (also `:latest`) and `:cuda12.8`, same RunPod ComfyUI release pinned by digest. `latest` = 13.0 since the 2026-09-15 pod A/B (AiAngelH3 5 s clip, RTX PRO 6000: 31 s warm vs 75 s on 12.8; owner: "ต้องบังคับเอา cuda 13.0"); a CUDA 13 image needs a host driver that supports it (RunPod `allowedCudaVersions` accepts only 11.8 to 13.0, so the filter is `13.0`, though hosts report drivers up to 13.2). No local docker on SiraPC — CI is the only build.
- Custom node packs baked at build (krea2edit, MAINodes, Spectrum, WhatDreamsCost, H3 Prompt IDE, rgthree-comfy, Easy-Use, VideoHelperSuite, obvpm, SolAttn) are pinned by commit + sha256 and listed in `tests/test_template.py BAKED_NODE_PACKS`. The H3 latent upscaler node has no LICENSE file, so it is never baked; `MODELS=...,h3upscaler` fetches its code (pinned commit, in `docker/start.sh`) and its model file (a normal `presets/models.tsv` preset) onto the user's own pod at boot instead.
- A `presets/models.tsv` row may belong to several presets (`h3core,h3`). `h3core` = H3 text encoder + fp16 video VAE + audio VAE (for any own H3 model, e.g. the private Claire merge); `h3` = h3core + hybrid fl2va+ref2va b25 + ref2v 4-step turbo LoRA, exactly what `scripts/h3_workflows.py` loads (a test holds that); `h3extra` = b20, plain ref2va, fl2v 4/8-step LoRAs, int8 video VAE (no speedup on CUDA 12.8, measured on a 5090), taeh3.
- Model list downloads: Civitai files served from b2.civitai.com refuse aria2c (403), so `fetch.download` falls back to a plain GET; a 0-byte or aria2 `__temp` leftover never counts as finished.
- Public repo: never add keys, our own trained LoRAs, private workflows, prompts, outputs or character refs (`tests/test_template.py` guards tokens and local paths). Owner ruling 2026-09-14 (evening, reversing the same morning's "stay neutral"): the public template ships an **NSFW kit** — `presets/nsfw.txt` (third-party Civitai/HF links, pinned versions), opt-in via `MODELS=...,nsfw` or the panel's "Load NSFW kit (18+)" button. The owner was told once that RunPod ToS §7 bans adult products with a lifetime account ban and confirmed anyway; do not re-litigate, but keep the kit opt-in and adults-only. Private-only lists (character kits) stay in `D:/ClaudeMediaGen/scripts/runpod/`.
- **Dashboard** (port 8189, `docker/dashboard/`): standalone aiohttp server started by `start.sh` before ComfyUI, front end in `web/` (no build step, `?demo` renders sample data). Contract `docs/dashboard-api.md`; reuses the node's `fetch.py` / `outputs.py` via `AIANGEL_NODE_DIR`. Local run: `.claude/launch.json` `dashboard-local`; screenshots: `scripts/dashboard_shots.py`. Its port must also be listed in the RunPod template (console only). Opening ComfyUI from it is same-site, so it never hits ComfyUI's cross-site 403 (`docker/patch_comfy_origin.py` fixes the direct Connect link too).
- `nodes/ComfyUI-AiAngel` also carries the **Outputs** tab (`outputs.py` streams a STORED ZIP; `pull.py` is the stdlib sync script served at `/aiangel/pull.py`). Its routes are tested for real in `tests/test_outputs.py` (`scripts/test` adds aiohttp).
- **Serverless mode** (`AIANGEL_SERVERLESS=1`, `docker/handler.py` + `docker/serverless_models.py`, runpod SDK in `--target /opt/aiangel/sls` so it never touches ComfyUI's packages): models from the endpoint's cached HF repo (one repo per endpoint; RunPod's REST API has no field for it, set it in the console; the cache is a snapshot from setup time, so the handler downloads any loader file ComfyUI does not list from `MODEL_REPO`/`MODEL_NAME` with `HF_TOKEN` before queueing) or `/runpod-volume/aiangel/models`. The public template is used as pods, and our own gens now also run on a long-running pod: serverless is parked (endpoint `aiangel-h3` at workersMax 0); its cached model is private `AiAngelGallery/claire-h3` (the Claire recipe files + the H3 latent upscaler model), client `D:/ClaudeMediaGen/scripts/runpod/rp_sls.py`. A template env change reaches only workers started after it; an already-warm worker keeps the old env.
- `scripts/h3_workflows.py clip(upscale=True, upscale_scale=…)` adds the H3 latent upscaler + a 3-step refine after sampling (the node author's r2v example); it needs `MODELS=...,h3upscaler` on the pod. At `upscale_scale=1.25` it reproduces the seed's 576p clip shot for shot at 704x1280 (owner's chosen 720p route); 1.875 (1080p) runs out of memory on a 96 GB card for a 10 s clip. 2x of a 10 s 576p clip overflows the serverless 7 MB result. That repo stays private: it re-hosts Civitai authors' LoRAs and a merge of third-party checkpoints.
- ComfyUI-Model-Manager is patched at build (`docker/patch_model_manager.py`: civitai.red hosts, Diffusion Model → diffusion_models); a new upstream release must re-pass that patch.
- Pod tests (tooling in `D:/ClaudeMediaGen/scripts/runpod/`) have no budget cap: keep a test pod up until the test plan is done and the owner has seen the results, arm the deadman, report the running cost. **Always launch two pods at once and keep whichever boots first** (owner 2026-09-14: image pulls take 10 to 60+ min per host; `rp_state.py park` between the two `up`s, terminate the loser as soon as the winner has ComfyUI up), and filter for fast hosts with `rp_pod.py up --min-download` (RunPod `minDownloadMbps`). A batch of several clips keeps two pods running in parallel with one runner script per pod, because one GPU renders one clip at a time and a single queue makes the owner wait for every job ahead. Live iterating runs on an RTX PRO 6000 (about 2.5x a 5090 per clip); recipes and timings live in that folder's README.
- `nodes/ComfyUI-AiAngel/example_workflows/` = the template's own H3 workflows, shown in ComfyUI's Templates browser under their file names: `AiAngelH3-Clip` / `AiAngelH3-Extend` (the default merge) and `H3-Hybrid-Clip` / `H3-Hybrid-Extend` (need MODELS=h3). Names carry no spaces or brackets (owner 2026-09-16) because ComfyUI's `?template=<name>&source=ComfyUI-AiAngel` link accepts only `[a-zA-Z0-9_.-]`; the dashboard's Open ComfyUI uses that link, and `web/aiangel.js` opens AiAngelH3-Clip once per browser over an untouched blank canvas for users who come in from RunPod Connect. The AiAngelH3 pair is derived from the Hybrid pair by `scripts/make_aiangelh3_workflows.py` and stored with `scripts/save_example_workflow.py`. They are saved from the real UI after `scripts/h3_workflows.py` builds the API graph (`app.loadApiJson`, arrange, run, save), so a change to the builder means re-saving them on a pod.

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
