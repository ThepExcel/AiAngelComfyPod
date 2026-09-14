# AI Angel ComfyPod

ComfyUI on RunPod, tuned for **MiniMax H3**, **SCAIL-2** and **Krea 2**: fast restarts,
one-switch model presets, and a **Model list** panel — paste any list of Civitai or Hugging Face
links, press one button, and every checkpoint, LoRA and VAE lands in the right folder.

Image: `ghcr.io/thepexcel/aiangelcomfypod:latest`

## What you get

- **ComfyUI v0.35.0**, CUDA 12.8, PyTorch — works on RTX 5090 (Blackwell) and older cards.
- **Fast boots.** ComfyUI and all Python packages are inside the image, not on your network
  volume, so a restart does not re-install or re-import anything from slow storage. Only your
  models, inputs, outputs, settings and custom nodes live on the volume.
- **Model presets.** Set `MODELS=h3`, `scail`, `krea2` (or a comma list, or `all`) and the first
  boot downloads exactly those files. Files already on the volume at the right size are skipped,
  so later boots download nothing.
- **Model list panel** — paste a whole list of links and download them all; see below.
- ComfyUI-Manager, KJNodes, Civicomfy (Civitai search), FileBrowser and JupyterLab.

## Quick start

1. Create a **network volume** (100 GB is enough for both presets) in the region you want.
2. Deploy a pod with this template (or image) and attach the volume at `/workspace`.
3. Set environment variables as needed:

   | Variable | Example | Meaning |
   |---|---|---|
   | `MODELS` | `h3,scail` | presets to download on boot (`h3` ≈ 44 GB, `scail` ≈ 29 GB, `krea2` ≈ 19 GB) |
   | `EXTRA_MODELS` | *(links, see below)* | any other Civitai / Hugging Face models to download on boot |
   | `CIVITAI_TOKEN` | *(your Civitai API key)* | needed for Civitai downloads; also fills Model Manager's key |
   | `HF_TOKEN` | *(your token)* | only needed for gated Hugging Face files; also fills Model Manager's key |
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

## Download a list of models (Model list panel)

1. In ComfyUI, click the **cloud-download icon** in the left sidebar (**Model list**).
2. Paste your **Civitai API key** once (Civitai → Account settings → API Keys). It is saved on your
   own volume under `/workspace/aiangel/.secrets/` and shown masked. A Hugging Face token is only
   needed for gated repos.
3. Paste your list — one link per line — and press **Download all**. Each file shows its progress.
   When they finish, press **R** in ComfyUI to refresh the model lists.

List format (lines starting with `#` are ignored):

```
# a Civitai model page (civitai.com or civitai.red); the version in the link is used
https://civitai.com/models/12345/some-model?modelVersionId=67890
# folder|link puts the file in a specific models folder
loras|https://civitai.red/models/111/some-lora?modelVersionId=222
# folder|link|text picks the file whose name contains "text" when a version has several
diffusion_models|https://civitai.com/models/333?modelVersionId=444|int8
# Hugging Face or any direct file link
vae|https://huggingface.co/some-org/some-repo/resolve/main/file.safetensors
```

- Without a folder, Civitai's own label decides. Some uploads label a UNet-only file as a
  checkpoint — put `diffusion_models|` in front of those.
- Files already on the volume at the right size are skipped, so pasting the same list again is safe.
- The same list works at boot: put it in the `EXTRA_MODELS` variable, with your key in a RunPod
  secret (`CIVITAI_TOKEN={{ RUNPOD_SECRET_civitai }}`). Progress is in `logs/models.log`.

## Add one model at a time (Model Manager)

The image also includes [ComfyUI-Model-Manager](https://github.com/hayden-cn/ComfyUI-Model-Manager).

1. Click **Model Manager** in the top bar, then the download icon → **Create Download Task**.
2. Paste a model page link from `civitai.com` or `huggingface.co` (or a direct `.safetensors`
   link) and press the search icon. Pick the file, choose **Model Type** (`checkpoints`, `loras`,
   `vae`, …) and click **Download**. The file lands on your volume and shows up in the loaders.
3. For gated Hugging Face repos or Civitai downloads that need login, add your own
   **Civitai API key** / **Hugging Face token** in ComfyUI **Settings → Model Manager**. Tokens are
   stored only on your volume (`custom_nodes/ComfyUI-Model-Manager/private.key`) and shown masked.

Links from both `civitai.com` and `civitai.red` work. Files Civitai marks as *Diffusion Model*
go to `diffusion_models` by default; you can still change the folder before downloading.

Civicomfy is also installed if you prefer searching Civitai from inside ComfyUI.

## Where things are

```
/workspace/aiangel/
  models/          checkpoints, loras, vae, diffusion_models, text_encoders, ...
  input/ output/   ComfyUI inputs and results
  user/            ComfyUI settings and saved workflows
  custom_nodes/    nodes (yours persist; image nodes are refreshed when the image updates)
  logs/            models.log, filebrowser.log, jupyter.log
  .secrets/        your API keys and the generated FileBrowser / Jupyter passwords
```

A volume that already has models under `/workspace/ComfyUI/models` is used as-is.

Custom nodes you install with ComfyUI-Manager are kept on the volume; their Python packages are
re-installed on each new container (cached on the volume, so it is quick).

## Measured on RTX 5090 (Secure Cloud, EU-RO-1, 2026-09-13)

| Step | Time |
|---|---|
| First boot on a new host (includes pulling the image) | 389 s |
| Pod restart until ComfyUI answers | about a minute or less (ComfyUI itself starts in ~8 s) |
| Preset check when the volume already has the models | 0 s download |
| MiniMax H3, reference image, 5 s 512×896, 4 steps — first job after boot | 230 s |
| Same, next job (model warm) | 38 s |

## Tips for H3 and SCAIL-2

- Switching between H3 and SCAIL-2 unloads the other model — batch your jobs by model.
- The first job after a boot spends about 1.5 minutes loading the model; later jobs are fast.
- Don't use `--highvram` / `--gpu-only` with H3: its weights are larger than 32 GB of VRAM.

## Build

GitHub Actions builds and pushes the image on every change to `Dockerfile`, `docker/`, `nodes/`
or `presets/`. Model presets are plain Hugging Face links in `presets/models.tsv`; the Model list
panel is the custom node in `nodes/ComfyUI-AiAngel`.

## License

MIT for this repository (see `LICENSE`). Models and bundled custom nodes keep their own licenses.
