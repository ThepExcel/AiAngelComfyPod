# AI Angel ComfyPod

ComfyUI tuned for **MiniMax H3** video, **SCAIL-2** and **Krea 2**: fast restarts, one-switch model
presets, and a **Dashboard** (port 8189) to watch the boot, add models, save your API keys and
download your results as ZIP, without digging through logs.

Step-by-step guide (Thai, with copy-ready MODELS values): https://www.thepexcel.com/aiangel-comfypod/

Full reference and source: https://github.com/ThepExcel/AiAngelComfyPod

## Quick start

1. Pick a GPU with enough VRAM for your model (H3 video: 48 GB or more is comfortable; RTX PRO 6000
   96 GB is the fastest we measured). The image runs on **CUDA 13.0** (about 2.4x faster than 12.8
   for H3); if a pod never starts on an older host, edit the image to
   `ghcr.io/thepexcel/aiangelcomfypod:cuda12.8`.
2. Keep the default `MODELS=h3core,h3upscaler,aiangelh3` (~42 GB: H3 text encoder + VAEs, the H3
   latent upscaler and the AiAngelH3 model), or change it with **Set overrides** (see below), and deploy.
3. In **Connect**, open **8189 Dashboard**. It shows the boot and each model's download progress,
   and when ComfyUI is ready press **Open ComfyUI** there (models still downloading appear in
   ComfyUI after you press **R**).
4. Open **Templates → ComfyUI-AiAngel → AiAngelH3 - Clip** for a ready H3 workflow (with
   `MODELS=h3`, use **H3 Hybrid - Clip (MODELS=h3)** instead).

AiAngelH3 (https://huggingface.co/AiAngelGallery/AiAngelH3) is a merge of MiniMax H3 derivatives under
the MiniMax H3 Community License: not licensed in the EU, UK, South Korea or the US; label published
results as AI-generated.

## Environment variables

| Variable | Example | Meaning |
|---|---|---|
| `MODELS` | `h3core,h3upscaler,aiangelh3` | presets to download on boot, comma list: `h3` (~44 GB), `h3core` (~21 GB, text encoder + VAEs only, for your own H3 model), `aiangelh3` (~21 GB, the AiAngelH3 merge; pair with `h3core`), `h3extra`, `h3upscaler` (~690 MB, H3 latent upscaler), `scail` (~29 GB), `krea2` (~19 GB), `all` |
| `EXTRA_MODELS` | links, one per line | any other Civitai / Hugging Face files to download on boot |
| `CIVITAI_TOKEN` | `{{ RUNPOD_SECRET_civitai }}` | your Civitai API key, needed for Civitai downloads |
| `HF_TOKEN` | `{{ RUNPOD_SECRET_hf }}` | only for gated Hugging Face files |
| `COMFYUI_ARGS` | `--fast-disk` | extra ComfyUI launch flags |

Files already on disk at the right size are skipped, so restarts download nothing.

## Ports

| Port | Service |
|---|---|
| 8189 | Dashboard: status, models, outputs ZIP, API keys, logs, passwords for the two below |
| 8188 | ComfyUI |
| 8080 | FileBrowser (user `admin`, password on the Dashboard) |
| 8888 | JupyterLab (token on the Dashboard) |

## Dashboard (8189)

- **Overview**: ComfyUI ready / starting / stopped with Open and Restart, GPU, VRAM, free disk,
  FileBrowser and JupyterLab passwords, latest results.
- **Models**: every preset with per-file progress; add one (e.g. `scail`, `krea2`) without a
  restart; paste Civitai / Hugging Face links.
- **Outputs**: pick results or take them all as ZIP, split into parts (per 1/2/4 GB or per 50/100
  files), or only what is new since your last ZIP.
- **Keys** for Civitai / Hugging Face, and **Logs** (boot, models, ComfyUI).

## In ComfyUI

- **Model list** (cloud-download icon, left sidebar): paste links, press **Download all**.
- **Outputs** (images icon): download new results as one ZIP, or sync everything with `pull.py`.
- **Model Manager** and Civicomfy for one model at a time.

MIT licensed. Models and custom nodes keep their own licenses.
