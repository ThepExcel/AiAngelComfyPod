# AI Angel ComfyPod

ComfyUI on RunPod, tuned for **MiniMax H3**, **SCAIL-2** and **Krea 2**: fast restarts,
one-switch model presets, and a **Model list** panel — paste any list of Civitai or Hugging Face
links, press one button, and every checkpoint, LoRA and VAE lands in the right folder.

Image: `ghcr.io/thepexcel/aiangelcomfypod:latest`

New to RunPod? Sign up through [runpod.io?ref=fbrjus7u](https://runpod.io?ref=fbrjus7u) — it
supports this template.

## What you get

- **ComfyUI v0.35.0**, PyTorch — works on RTX 5090 (Blackwell) and older cards. Two images:
  `:cuda12.8` (= `:latest`, runs on any current host) and `:cuda13.0` (needs a host driver with
  CUDA 13 — pick the CUDA 13.0 filter when you deploy).
- **Fast boots.** ComfyUI and all Python packages are inside the image, not on your network
  volume, so a restart does not re-install or re-import anything from slow storage. Only your
  models, inputs, outputs, settings and custom nodes live on the volume.
- **Model presets.** Set `MODELS=h3`, `scail`, `krea2` (or a comma list, or `all`) and the first
  boot downloads exactly those files. Files already on the volume at the right size are skipped,
  so later boots download nothing.
- **Model list panel** — paste a whole list of links and download them all; see below.
- **Outputs panel** — download new results as one ZIP in a click, or sync them all to your
  computer with `pull.py`.
- ComfyUI-Manager, KJNodes, Civicomfy (Civitai search), FileBrowser and JupyterLab.

## Quick start

1. Create a **network volume** (100 GB is enough for both presets) in the region you want.
2. Deploy a pod with this template (or image) and attach the volume at `/workspace`.
3. Set environment variables as needed:

   | Variable | Example | Meaning |
   |---|---|---|
   | `MODELS` | `h3,scail` | presets to download on boot (`h3` ≈ 44 GB, `h3core` ≈ 21 GB = only the H3 text encoder + VAEs, for your own H3 model, `h3extra` ≈ 49 GB more, `scail` ≈ 29 GB, `krea2` ≈ 19 GB, `h3upscaler` ≈ 690 MB, `nsfw` = adult kit, see below) |
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

## NSFW kit (adults 18+)

`MODELS=h3,krea2,nsfw` (with `CIVITAI_TOKEN` set) also downloads a curated adult kit on boot, or
press **Load NSFW kit (18+)** in the Model list panel and then **Download all**. The list is
`presets/nsfw.txt`:

- **MiniMax H3 video:** Mystic XXX LoRA (our default: strength 0.8 on the normal H3 model with the
  4-step turbo LoRA), 10Eros Max beta5 TURBO-hybrid int8 (full model with turbo merged in: leave
  the turbo LoRA out, concept LoRAs at 0.2-0.6, euler/simple 6 steps), HMCumshot (author's R2V
  setting: turbo 0.85, strength 0.9, euler/beta, trigger `hmcumshot3`), Motion Booster, H3 Turbo v4
  and VBVR Pro reasoning LoRAs.
- **Krea 2 images:** PornMaster Krea2 (uncensored UNet), Krea 2 Identity Edit LoRA (edit a photo
  and keep the person's face; the `comfyui-krea2edit` nodes are in the image), POV Blowjob,
  Mystic XXX and SNOFS LoRAs.

Only generate adults, and only people who agreed to it. You are responsible for following
RunPod's and Civitai's terms.

## Get your results out (Outputs panel)

Click the **images icon** in the left sidebar (**Outputs**). Every result on the pod shows as a
thumbnail, newest first, with a **NEW** tag on anything you have not downloaded yet from this
browser.

- **Download N new** — one ZIP of everything made since your last download. Press it after each
  batch; the button remembers where you stopped.
- **Click thumbnails** to pick some, then **Selected** — one ZIP of just those. **All** takes the
  whole filtered list (All / Images / Videos). The **↓** on a thumbnail saves that one file.
- ZIPs are not re-compressed (images and videos already are), so the download starts at once and
  the pod spends no time packing.

**Sync everything to your computer** (at the bottom of the panel) is for big batches, such as a
night of video jobs. Get `pull.py` from the panel, copy the command, and run it on your computer
(Python 3.9+, nothing to install):

```
python pull.py https://<pod-id>-8188.proxy.runpod.net ./aiangel-outputs
```

It downloads several files at a time (`--jobs 4` by default), skips files you already have, and
resumes a file that was cut off — run it again whenever you like and only new results come down.
`--only video` and `--since-hours 6` narrow what it takes.

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

Second test (RTX 5090, pod disk without a network volume, 2026-09-14):

| Step | Time |
|---|---|
| First boot on a new host (includes pulling the image) | 810 s — image pull time varies a lot by host |
| `MODELS=krea2` from Hugging Face (19 GB) | 561 s |
| A 14 GB Krea 2 finetune from Civitai via the Model list panel | a few minutes |
| Krea 2 image 768×1344, 8 steps — first / next | 20 s / 12 s |

## Tips for H3 and SCAIL-2

- Switching between H3 and SCAIL-2 unloads the other model — batch your jobs by model.
- The first job after a boot spends about 1.5 minutes loading the model; later jobs are fast.
- Don't use `--highvram` / `--gpu-only` with H3: its weights are larger than 32 GB of VRAM.

## AiAngel H3 workflows

Open ComfyUI's **Templates** browser → *ComfyUI-AiAngel*:

- **AiAngel H3 - Clip** — reference-to-video from `<Picture 1>` and a structured prompt, 2-15 s.
- **AiAngel H3 - Extend** — continues a previous H3 clip without a cut: its last 22 frames and
  their sound anchor the new part, the overlap is cross-faded, and the saved video is previous +
  new. Feed the result back in to keep going past 15 s.

Both use only ComfyUI core nodes, the `h3` preset, the 4-step turbo LoRA and Comfy Kitchen
attention. On an RTX PRO 6000 a 5 s 576×1024 clip takes about 42 s (46 s without Kitchen
attention), a 15 s clip about 141 s, and extending a 5 s clip by 5 s about 62 s.

## H3 speed & quality kit

Nodes from two community MiniMax H3 workflows (H3 Advanced v20, SEEDHUNTER v16), baked into the
image (`custom_nodes.baked`):

- **`comfyui-mainodes`** — temporal "de-rope" nodes for smoother H3 motion: `H3TimeSmear`,
  `H3V2VInit`, `H3InjectSchedule`, `H3JerkOracle`, `H3ExactRecover`.
- **`comfyui-spectrum-minimax-h3`** — `SpectrumApplyMiniMaxH3`, a spectral feature forecaster
  that skips selected H3 transformer steps for a sampling speedup.
- **`whatdreamscost-comfyui`** — `LoadVideoUI` / `LoadAudioUI`, trim video or audio clips right
  in the node instead of pre-cutting them.
- **`comfyui-h3-prompt-ide`** — a VS Code-style prompt editor and reference palette for H3
  prompts.
- **`rgthree-comfy`** — power/context nodes, reroute and group utilities, an image comparer;
  general workflow wiring both H3 workflows above lean on.
- **`comfyui-easy-use`** — the "easy ..." pipe/loader/sampler nodes for compact prompt and
  sampler setup.
- **`comfyui-videohelpersuite`** — `VHS_LoadVideo`, `VHS_VideoCombine` and the rest of the video
  I/O both workflows build on.
- **`comfyui-obvpm`** — `Load Image & Crop`, plus lazy switches, gates and bundles that keep the
  large H3 graphs tidy.
- **`comfyui-solattn_triton`** — a Triton sparse-attention override for faster H3 sampling; if
  the image's triton build does not match, the node reports it clearly on use rather than
  failing to load.

`MODELS=h3` now downloads a **hybrid fl2va+ref2va model** (`smhfacct/Minimax-H3-fl2va-ref2va-hybrid-models`,
the *b25-49* variant) instead of the plain `ref2va` checkpoint: it keeps `fl2va`'s higher output
quality while adding `ref2va`'s reference-conditioning pathway, so one model does both
first/last-frame and reference-video generation. It comes with the H3 text encoder, the fp16
video VAE that ComfyUI's built-in H3 templates ask for, the audio VAE and the ref2v 4-step turbo
LoRA — exactly what the AiAngel workflows load. In ComfyUI's own H3 templates, pick the hybrid
file in the diffusion model loader. Bringing your own H3 model (a Civitai merge, a turbo-merged
checkpoint)? `MODELS=h3core` downloads only the text encoder and the two VAEs it needs.
`MODELS=h3extra` adds the *b20-49* variant (closer to `ref2va`, for stronger reference
adherence), the original plain `ref2va` checkpoint, the fl2v 4-step and 8-step turbo LoRAs, the
int8 video VAE (slower than fp16 on CUDA 12.8 in our tests — community workflows say it pays off
on CUDA 13) and the `taeh3` preview VAE, for comparing.

Left out of the image: a neural latent-upscaler node (`Comfyui_Minimax_h3_latent_Upscaler`) from
the same workflows — its GitHub repo ships no LICENSE file, so it can't be redistributed here.
It is fetched on your own pod instead: `MODELS=h3,h3upscaler` (the RunPod template's default; or add
`h3upscaler` to your MODELS list) fetches the node's code straight from GitHub at a pinned commit
onto your own pod's volume before ComfyUI starts, so it loads on the first boot, and its model file
(`minimax_h3_latent_upscaler_3d_bf16.safetensors`, ≈ 690 MB, from
`LBH-123-AI/Minimax_h3_latent_Upscaler` on Hugging Face) the same way any other preset downloads.

## Serverless worker (advanced)

The same image runs as a RunPod **Serverless** worker when the template sets
`AIANGEL_SERVERLESS=1`: no web UI and no boot downloads, just ComfyUI plus a job handler.

- **Models** come from the endpoint's **cached model** — a Hugging Face repo laid out like
  ComfyUI's `models/` folder (`diffusion_models/`, `loras/`, `text_encoders/`, `vae/`, ...;
  private repos work with your HF token) — and/or a network volume that a pod of this template
  filled (`/runpod-volume/aiangel/models`). Set `MODEL_REPO=owner/name` to pick one cached repo.
- **Job input:** `{"workflow": <ComfyUI API graph>, "images": {"ref1.jpg": "<base64>"}}`.
  **Output:** `{"seconds": ..., "files": [{"name", "bytes", "b64"}]}`. RunPod caps a `/run`
  result at 10 MB, so keep outputs under 7 MB (a 15 s 576×1024 H3 clip is about 2.5 MB).

## Build

GitHub Actions builds and pushes the image on every change to `Dockerfile`, `docker/`, `nodes/`
or `presets/`. Model presets are plain Hugging Face links in `presets/models.tsv`; the Model list
panel is the custom node in `nodes/ComfyUI-AiAngel`.

## License

MIT for this repository (see `LICENSE`). Models and bundled custom nodes keep their own licenses.
