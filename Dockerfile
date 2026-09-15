# AI Angel ComfyPod — ComfyUI for video models (MiniMax H3, SCAIL-2) on RunPod.
#
# Base: RunPod's own ComfyUI image, pinned by digest. It already carries CUDA 12.8,
# PyTorch, ComfyUI v0.35.0, ComfyUI-Manager, KJNodes, Civicomfy, FileBrowser and JupyterLab,
# with every Python package installed system-wide (fast local disk, not the network volume).
#
# What this image changes:
#   - ComfyUI runs from the image (/opt/comfyui), never copied onto the network volume.
#     Only models / input / output / user settings / custom nodes live on /workspace.
#   - ComfyUI-Model-Manager: a Download tab that takes a Hugging Face or Civitai link
#     (checkpoint, LoRA, VAE, ...). Each user enters their own API tokens in its settings.
#   - First boot downloads the model presets named in MODELS (e.g. MODELS=h3,scail),
#     skipping any file already on the volume at the exact byte size.
#   - Baked custom-node packs (rgthree-comfy, ComfyUI-Easy-Use, ComfyUI-VideoHelperSuite,
#     comfyui-obvpm, ComfyUI-SolAttn_triton, on top of the H3 speed/quality kit below) so the
#     community H3 Advanced v20 and SEEDHUNTER v16 workflows load without missing nodes.
ARG BASE_IMAGE=runpod/comfyui:1.3.0-rc.164-comfyuiv0.35.0-cuda12.8@sha256:f070f97750ed4a3abdcad5fa9491eb327addac5226b135d0c76910335e11b364
FROM ${BASE_IMAGE}

ARG MODEL_MANAGER_VERSION=v2.8.4
ARG MODEL_MANAGER_SHA256=7d3b635f415b063fc53c05bd3d30a7dd2714fd9f4dbb19f7bce95d461ffe8e97

RUN apt-get update \
    && apt-get install -y --no-install-recommends aria2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# The baked ComfyUI moves to its runtime home. custom_nodes stays here as the pristine
# copy that start.sh syncs onto the volume.
RUN mv /opt/comfyui-baked /opt/comfyui

# RunPod's Connect links are cross-site: let them open the UI (see the patch's docstring).
COPY docker/patch_comfy_origin.py /opt/aiangel/patch_comfy_origin.py
RUN python3.12 /opt/aiangel/patch_comfy_origin.py /opt/comfyui/server.py

COPY docker/patch_model_manager.py /opt/aiangel/patch_model_manager.py
RUN curl -fSL "https://github.com/hayden-cn/ComfyUI-Model-Manager/releases/download/${MODEL_MANAGER_VERSION}/dist.tar.gz" -o /tmp/mm.tar.gz \
    && echo "${MODEL_MANAGER_SHA256}  /tmp/mm.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes/ComfyUI-Model-Manager \
    && tar xzf /tmp/mm.tar.gz -C /opt/comfyui/custom_nodes/ComfyUI-Model-Manager \
    && rm /tmp/mm.tar.gz \
    && python3.12 /opt/aiangel/patch_model_manager.py /opt/comfyui/custom_nodes/ComfyUI-Model-Manager/py/information.py \
    && echo "MODEL_MANAGER_PATCH=civitai-hosts,diffusion-model-folder" >> /opt/comfyui/.runpod-bundle-version \
    && python3.12 -m pip install --no-cache-dir -c /opt/comfyui-runtime-constraints.txt \
        -r /opt/comfyui/custom_nodes/ComfyUI-Model-Manager/requirements.txt \
    && echo "MODEL_MANAGER_VERSION=${MODEL_MANAGER_VERSION}" >> /opt/comfyui/.runpod-bundle-version \
    && mv /opt/comfyui/custom_nodes /opt/comfyui/custom_nodes.baked

# Krea 2 Identity Edit nodes (Apache-2.0): instruction image edits that keep a person's face.
ARG KREA2EDIT_COMMIT=86f886dac23013d88996e3a2e99093ba44d322fb
ARG KREA2EDIT_SHA256=de43b5529a916a3bdca0bcebe9420a314f2ee0f8c55603a5c419fdd62be57a17
RUN curl -fSL "https://github.com/lbouaraba/comfyui-krea2edit/archive/${KREA2EDIT_COMMIT}.tar.gz" -o /tmp/k2e.tar.gz \
    && echo "${KREA2EDIT_SHA256}  /tmp/k2e.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-krea2edit \
    && tar xzf /tmp/k2e.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-krea2edit \
    && rm /tmp/k2e.tar.gz \
    && echo "KREA2EDIT_COMMIT=${KREA2EDIT_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# MiniMax H3 speed/quality kit, from two community H3 workflows. None of the four packs below
# ships a requirements.txt (pure Python on top of what the base image already provides).

# MAINodes (GPL-3.0): temporal "de-rope" nodes for smoother H3 motion — H3TimeSmear, H3V2VInit,
# H3InjectSchedule, H3JerkOracle, H3ExactRecover.
ARG MAINODES_COMMIT=f4868b4a08e8a504ce86db54a17961d399ffa2bc
ARG MAINODES_SHA256=e7b77ac2d0710e10c48af57cff2aaa36b98c9f57647513038ca124d8660d66fd
RUN curl -fSL "https://github.com/matlowai/ComfyUI-MAINodes/archive/${MAINODES_COMMIT}.tar.gz" -o /tmp/mainodes.tar.gz \
    && echo "${MAINODES_SHA256}  /tmp/mainodes.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-mainodes \
    && tar xzf /tmp/mainodes.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-mainodes \
    && rm /tmp/mainodes.tar.gz \
    && echo "MAINODES_COMMIT=${MAINODES_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# Spectrum (GPL-3.0): SpectrumApplyMiniMaxH3 — spectral feature forecasting that skips selected
# H3 transformer steps for a sampling speedup.
ARG SPECTRUM_COMMIT=120d72e2f48b781235b34149e39bbdf0f1317d82
ARG SPECTRUM_SHA256=78165686ad35154df807c67ecf19fe619fa049bf52e085ff96ead227b757c304
RUN curl -fSL "https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3/archive/${SPECTRUM_COMMIT}.tar.gz" -o /tmp/spectrum.tar.gz \
    && echo "${SPECTRUM_SHA256}  /tmp/spectrum.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-spectrum-minimax-h3 \
    && tar xzf /tmp/spectrum.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-spectrum-minimax-h3 \
    && rm /tmp/spectrum.tar.gz \
    && echo "SPECTRUM_COMMIT=${SPECTRUM_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# WhatDreamsCost-ComfyUI (GPL-3.0): LoadVideoUI / LoadAudioUI — trim video/audio in the node UI
# before it hits the graph.
ARG WDC_COMMIT=a3c809c8b593a74c2ddcd6c1f83ad85ebebe3c64
ARG WDC_SHA256=af4ed17af9b7e8bebbcefb1d70547c8b47299c9796a970466d891f5151a82491
RUN curl -fSL "https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/archive/${WDC_COMMIT}.tar.gz" -o /tmp/wdc.tar.gz \
    && echo "${WDC_SHA256}  /tmp/wdc.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/whatdreamscost-comfyui \
    && tar xzf /tmp/wdc.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/whatdreamscost-comfyui \
    && rm /tmp/wdc.tar.gz \
    && echo "WDC_COMMIT=${WDC_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# H3 Prompt IDE (GPL-3.0): H3PromptIDEExtension — VS Code-style prompt editor and reference
# palette for H3 prompts.
ARG H3PROMPTIDE_COMMIT=401ef31c5d88f16959c180f17f6e5b013f84bb1f
ARG H3PROMPTIDE_SHA256=67c1f34b309267ef03ea39accc29d0ec2ca7095da1eb4c27a982bbcfdb812252
RUN curl -fSL "https://github.com/ethanfel/ComfyUI-H3-Prompt-IDE/archive/${H3PROMPTIDE_COMMIT}.tar.gz" -o /tmp/h3promptide.tar.gz \
    && echo "${H3PROMPTIDE_SHA256}  /tmp/h3promptide.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-h3-prompt-ide \
    && tar xzf /tmp/h3promptide.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-h3-prompt-ide \
    && rm /tmp/h3promptide.tar.gz \
    && echo "H3PROMPTIDE_COMMIT=${H3PROMPTIDE_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# Workflow-utility packs the two community H3 workflows (H3 Advanced v20, SEEDHUNTER v16) need
# and currently show as missing nodes.

# rgthree-comfy (MIT): power/context nodes, reroute+group utilities and an image comparer used
# to wire the H3 workflows above compactly. No requirements.txt (pure Python).
ARG RGTHREE_COMMIT=2c5342a8cb0eaecaabf61435a5f37dd594c510ba
ARG RGTHREE_SHA256=a4daad50745ed96f04eccb6d41b34d2aef4787c47f72234f6bb5df9186f57336
RUN curl -fSL "https://github.com/rgthree/rgthree-comfy/archive/${RGTHREE_COMMIT}.tar.gz" -o /tmp/rgthree.tar.gz \
    && echo "${RGTHREE_SHA256}  /tmp/rgthree.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/rgthree-comfy \
    && tar xzf /tmp/rgthree.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/rgthree-comfy \
    && rm /tmp/rgthree.tar.gz \
    && echo "RGTHREE_COMMIT=${RGTHREE_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# ComfyUI-Easy-Use (GPL-3.0): the "easy ..." pipe/loader/sampler nodes the H3 workflows above
# wire through for compact prompt/sampler setup.
ARG EASYUSE_COMMIT=450b1ce4ce43b2280521c87f5fa388a898fb2ad2
ARG EASYUSE_SHA256=c06a44b7d1e1b581b117caada5d6c57c0c4a864e574e40bec387549d236c87fb
RUN curl -fSL "https://github.com/yolain/ComfyUI-Easy-Use/archive/${EASYUSE_COMMIT}.tar.gz" -o /tmp/easyuse.tar.gz \
    && echo "${EASYUSE_SHA256}  /tmp/easyuse.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-easy-use \
    && tar xzf /tmp/easyuse.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-easy-use \
    && rm /tmp/easyuse.tar.gz \
    && python3.12 -m pip install --no-cache-dir -c /opt/comfyui-runtime-constraints.txt \
        -r /opt/comfyui/custom_nodes.baked/comfyui-easy-use/requirements.txt \
    && echo "EASYUSE_COMMIT=${EASYUSE_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# ComfyUI-VideoHelperSuite (GPL-3.0): VHS_LoadVideo / VHS_VideoCombine and friends, the video
# I/O the H3 workflows above build on.
ARG VHS_COMMIT=4d907bee61e92c2e65af3bd6383a4e4d356126d1
ARG VHS_SHA256=29122f96ac6d43b14b1b15c758e1c4ac292fe226e6c156b71bd17fe272c4cc58
RUN curl -fSL "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite/archive/${VHS_COMMIT}.tar.gz" -o /tmp/vhs.tar.gz \
    && echo "${VHS_SHA256}  /tmp/vhs.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-videohelpersuite \
    && tar xzf /tmp/vhs.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-videohelpersuite \
    && rm /tmp/vhs.tar.gz \
    && python3.12 -m pip install --no-cache-dir -c /opt/comfyui-runtime-constraints.txt \
        -r /opt/comfyui/custom_nodes.baked/comfyui-videohelpersuite/requirements.txt \
    && echo "VHS_COMMIT=${VHS_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# comfyui-obvpm (GPL-3.0): LoadImageCrop plus lazy switches/gates/bundles the H3 workflows above
# use to keep large graphs tidy. No requirements.txt (pure Python).
ARG OBVPM_COMMIT=9c2d1a2d7547e472c24b772125c0da86e4d821bd
ARG OBVPM_SHA256=e9f01a2efb6322fdf49e468efb60b6ddc23a5e5413e66556f36bb7789f0c9ce6
RUN curl -fSL "https://github.com/obvpm/comfyui-obvpm/archive/${OBVPM_COMMIT}.tar.gz" -o /tmp/obvpm.tar.gz \
    && echo "${OBVPM_SHA256}  /tmp/obvpm.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-obvpm \
    && tar xzf /tmp/obvpm.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-obvpm \
    && rm /tmp/obvpm.tar.gz \
    && echo "OBVPM_COMMIT=${OBVPM_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

# ComfyUI-SolAttn_triton (Apache-2.0): a Triton sparse-attention override for MiniMax H3
# sampling speed. No requirements.txt; its kernel import is wrapped in try/except so a missing
# or mismatched triton degrades to a clear error on use, never a crash on load.
ARG SOLATTN_COMMIT=26d816ebd4f1e43a2c6e4d4759be3137f10a7a73
ARG SOLATTN_SHA256=a667ebd1ee749d49395dd149d93c331e6889c807291a6088a4224860729ee2f4
RUN curl -fSL "https://github.com/kijai/ComfyUI-SolAttn_triton/archive/${SOLATTN_COMMIT}.tar.gz" -o /tmp/solattn.tar.gz \
    && echo "${SOLATTN_SHA256}  /tmp/solattn.tar.gz" | sha256sum -c - \
    && mkdir -p /opt/comfyui/custom_nodes.baked/comfyui-solattn_triton \
    && tar xzf /tmp/solattn.tar.gz --strip-components=1 -C /opt/comfyui/custom_nodes.baked/comfyui-solattn_triton \
    && rm /tmp/solattn.tar.gz \
    && echo "SOLATTN_COMMIT=${SOLATTN_COMMIT}" >> /opt/comfyui/.runpod-bundle-version

COPY presets/models.tsv /opt/aiangel/models.tsv
COPY presets/nsfw.txt /opt/aiangel/nsfw.txt
COPY docker/start.sh /opt/aiangel/start.sh
COPY docker/download_models.sh /opt/aiangel/download_models.sh
COPY docker/seed_model_manager_keys.py /opt/aiangel/
# RunPod Serverless mode (AIANGEL_SERVERLESS=1): the runpod SDK goes into its own --target dir,
# put on PYTHONPATH only for the handler process, so it can never move a package ComfyUI
# depends on; the handler only talks HTTP to ComfyUI.
ARG RUNPOD_SDK_VERSION=1.12.0
RUN python3.12 -m pip install --no-cache-dir --target /opt/aiangel/sls "runpod==${RUNPOD_SDK_VERSION}" \
    && PYTHONPATH=/opt/aiangel/sls python3.12 -c "import runpod; print('runpod', runpod.__version__)"
COPY docker/handler.py docker/serverless_models.py /opt/aiangel/
# Our own node: the "Model list" sidebar tab (paste links, download all), the boot downloader, and
# the "Outputs" tab (ZIP download, pull.py sync).
COPY nodes/ComfyUI-AiAngel /opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel
RUN echo "AIANGEL_NODE=$(sha256sum /opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel/*.py /opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel/web/*.js | sha256sum | cut -c1-12)" \
        >> /opt/comfyui/.runpod-bundle-version \
    && chmod +x /opt/aiangel/*.sh \
    && python3.12 -c "import torch, comfy_kitchen; print('torch', torch.__version__)"

# Standalone status/control dashboard, port 8189 (docs/dashboard-api.md). docker/start.sh
# starts it before ComfyUI. docker/dashboard/web/ (front end) is copied in when it exists.
COPY docker/dashboard /opt/aiangel/dashboard
ARG GIT_SHA=unknown
RUN echo "$GIT_SHA" > /opt/aiangel/image-version

ENV DATA_DIR=/workspace/aiangel \
    AIANGEL_SERVERLESS=0 \
    MODELS="" \
    EXTRA_MODELS="" \
    COMFYUI_ARGS=""

WORKDIR /opt/comfyui
EXPOSE 8188 8080 8888 8189 22
ENTRYPOINT ["/opt/aiangel/start.sh"]
