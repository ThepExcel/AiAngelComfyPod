# AI Angel ComfyPod

ComfyUI tuned for **MiniMax H3** video, **SCAIL-2** and **Krea 2**: fast restarts, one-switch model
presets, and a **Model list** panel that downloads a whole list of Civitai / Hugging Face links
with one button.

Step-by-step guide (Thai, with copy-ready MODELS values): https://www.thepexcel.com/aiangel-comfypod/

Full reference and source: https://github.com/ThepExcel/AiAngelComfyPod

## Quick start

1. Pick a GPU with enough VRAM for your model (H3 video: 48 GB or more is comfortable; RTX PRO 6000
   96 GB is the fastest we measured).
2. Keep the default `MODELS=h3`, or change it (see below), and deploy.
3. Open port **8188** (ComfyUI). The first boot downloads the models in the background; when
   `/workspace/aiangel/logs/models.log` says `ALL PRESET MODELS READY`, press **R** in ComfyUI.
4. Open **Templates → ComfyUI-AiAngel → AiAngel H3 - Clip** for a ready H3 workflow.

## Environment variables

| Variable | Example | Meaning |
|---|---|---|
| `MODELS` | `h3` | presets to download on boot, comma list: `h3` (~44 GB), `h3core` (~21 GB, text encoder + VAEs only, for your own H3 model), `h3extra`, `h3upscaler` (~690 MB, H3 latent upscaler), `scail` (~29 GB), `krea2` (~19 GB), `all` |
| `EXTRA_MODELS` | links, one per line | any other Civitai / Hugging Face files to download on boot |
| `CIVITAI_TOKEN` | `{{ RUNPOD_SECRET_civitai }}` | your Civitai API key, needed for Civitai downloads |
| `HF_TOKEN` | `{{ RUNPOD_SECRET_hf }}` | only for gated Hugging Face files |
| `COMFYUI_ARGS` | `--fast-disk` | extra ComfyUI launch flags |

Files already on disk at the right size are skipped, so restarts download nothing.

## Ports

| Port | Service |
|---|---|
| 8188 | ComfyUI |
| 8080 | FileBrowser (user `admin`, password printed in the pod log) |
| 8888 | JupyterLab (password printed in the pod log) |

## In ComfyUI

- **Model list** (cloud-download icon, left sidebar): paste links, press **Download all**.
- **Outputs** (images icon): download new results as one ZIP, or sync everything with `pull.py`.
- **Model Manager** and Civicomfy for one model at a time.

MIT licensed. Models and custom nodes keep their own licenses.
