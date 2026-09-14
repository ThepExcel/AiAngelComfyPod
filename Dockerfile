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

COPY presets/models.tsv /opt/aiangel/models.tsv
COPY docker/start.sh /opt/aiangel/start.sh
COPY docker/download_models.sh /opt/aiangel/download_models.sh
COPY docker/seed_model_manager_keys.py /opt/aiangel/
# Our own node: the "Model list" sidebar tab (paste links, download all) and the boot downloader.
COPY nodes/ComfyUI-AiAngel /opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel
RUN echo "AIANGEL_NODE=$(sha256sum /opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel/*.py /opt/comfyui/custom_nodes.baked/ComfyUI-AiAngel/web/*.js | sha256sum | cut -c1-12)" \
        >> /opt/comfyui/.runpod-bundle-version \
    && chmod +x /opt/aiangel/*.sh \
    && python3.12 -c "import torch, comfy_kitchen; print('torch', torch.__version__)"

ENV DATA_DIR=/workspace/aiangel \
    MODELS="" \
    EXTRA_MODELS="" \
    COMFYUI_ARGS=""

WORKDIR /opt/comfyui
EXPOSE 8188 8080 8888 22
ENTRYPOINT ["/opt/aiangel/start.sh"]
