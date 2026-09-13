# AI Angel ComfyPod

ComfyUI on RunPod, tuned for the heavy video models **MiniMax H3** and **SCAIL-2**:
fast restarts, one-switch model download, and a built-in downloader for any checkpoint or
LoRA from Hugging Face or Civitai.

Image: `ghcr.io/thepexcel/aiangelcomfypod:latest`

## What you get

- **ComfyUI v0.35.0**, CUDA 12.8, PyTorch — works on RTX 5090 (Blackwell) and older cards.
- **Fast boots.** ComfyUI and all Python packages are inside the image, not on your network
  volume, so a restart does not re-install or re-import anything from slow storage. Only your
  models, inputs, outputs, settings and custom nodes live on the volume.
- **Model presets.** Set `MODELS=h3`, `MODELS=scail`, `MODELS=h3,scail` or `MODELS=all` and the
  first boot downloads exactly those files. Files already on the volume at the right size are
  skipped, so later boots download nothing.
- **Add any checkpoint / LoRA from Hugging Face or Civitai** — see below.
- ComfyUI-Manager, KJNodes, Civicomfy (Civitai search), FileBrowser and JupyterLab.

## Quick start

1. Create a **network volume** (100 GB is enough for both presets) in the region you want.
2. Deploy a pod with this template (or image) and attach the volume at `/workspace`.
3. Set environment variables as needed:

   | Variable | Example | Meaning |
   |---|---|---|
   | `MODELS` | `h3,scail` | presets to download on boot (`h3` ≈ 44 GB, `scail` ≈ 29 GB) |
   | `HF_TOKEN` | *(your token)* | only needed for gated Hugging Face files |
   | `COMFYUI_ARGS` | `--fast-disk` | extra ComfyUI launch flags |
   | `FILEBROWSER_PASSWORD` | *(12+ chars)* | otherwise one is generated and printed in the pod log |
   | `JUPYTER_PASSWORD` | | otherwise one is generated and printed in the pod log |
   | `PUBLIC_KEY` | `ssh-ed25519 ...` | enables SSH with your key |

4. Open port **8188** for ComfyUI. Model downloads run in the background; the log is at
   `/workspace/aiangel/logs/models.log`. When it says `ALL PRESET MODELS READY`, press **R** in
   ComfyUI to refresh the model lists.

| Port | Service |
|---|---|
| 8188 | ComfyUI |
| 8080 | FileBrowser (user `admin`) |
| 8888 | JupyterLab |

## Add a checkpoint or LoRA from Hugging Face / Civitai

The image includes [ComfyUI-Model-Manager](https://github.com/hayden-cn/ComfyUI-Model-Manager).

1. In ComfyUI, open **Settings → Model Manager** and paste your own **Civitai API key** and/or
   **Hugging Face token**. Tokens are stored only on your volume
   (`custom_nodes/ComfyUI-Model-Manager/private.key`) and shown masked.
2. Open the **Model Manager** button in the side bar → **Download** tab.
3. Paste a model page link from `civitai.com` or `huggingface.co`, choose the folder
   (`checkpoints`, `loras`, `vae`, …), and download.

Civicomfy is also installed if you prefer searching Civitai from inside ComfyUI.

## Where things are

```
/workspace/aiangel/
  models/          checkpoints, loras, vae, diffusion_models, text_encoders, ...
  input/ output/   ComfyUI inputs and results
  user/            ComfyUI settings and saved workflows
  custom_nodes/    nodes (yours persist; image nodes are refreshed when the image updates)
  logs/            models.log, filebrowser.log, jupyter.log
  .secrets/        generated FileBrowser / Jupyter passwords
```

A volume that already has models under `/workspace/ComfyUI/models` is used as-is.

Custom nodes you install with ComfyUI-Manager are kept on the volume; their Python packages are
re-installed on each new container (cached on the volume, so it is quick).

## Tips for H3 and SCAIL-2

- Switching between H3 and SCAIL-2 unloads the other model — batch your jobs by model.
- The first job after a boot spends about 1.5 minutes loading the model; later jobs are fast.
- Don't use `--highvram` / `--gpu-only` with H3: its weights are larger than 32 GB of VRAM.

## Build

GitHub Actions builds and pushes the image on every change to `Dockerfile`, `docker/` or
`presets/`. Model presets are plain Hugging Face links in `presets/models.tsv`.

Models and bundled custom nodes keep their own licenses.
