#!/bin/bash
# Container entrypoint. ComfyUI code and Python packages come from the image (local disk);
# everything a user creates or downloads lives under DATA_DIR on /workspace so it survives
# pod restarts when a network volume is attached.
set -uo pipefail

BOOT_T0=$(date +%s)
COMFY=/opt/comfyui
BAKED_NODES="$COMFY/custom_nodes.baked"
DATA_DIR="${DATA_DIR:-/workspace/aiangel}"
CONSTRAINTS=/opt/comfyui-runtime-constraints.txt
LOG_DIR="$DATA_DIR/logs"
SECRETS="$DATA_DIR/.secrets"

stamp() { echo "[aiangel $(date -u +%FT%TZ) +$(( $(date +%s) - BOOT_T0 ))s] $*"; }

mkdir -p "$DATA_DIR" "$LOG_DIR" "$SECRETS" "$DATA_DIR/input" "$DATA_DIR/output" "$DATA_DIR/user" \
    "$DATA_DIR/custom_nodes" "$DATA_DIR/.cache/pip"
chmod 700 "$SECRETS"
export PIP_CACHE_DIR="$DATA_DIR/.cache/pip"
[ -f "$CONSTRAINTS" ] && export PIP_CONSTRAINT="$CONSTRAINTS"
unset FILEBROWSER_CONFIG
stamp "boot start pod=${RUNPOD_POD_ID:-local} data=$DATA_DIR"

# ---- models directory: reuse an older /workspace/ComfyUI/models layout if that is what the
# volume already holds, so an existing download is never repeated.
if [ -n "${MODELS_DIR:-}" ]; then
    :
elif [ ! -e "$DATA_DIR/models" ] && [ -d /workspace/ComfyUI/models ]; then
    MODELS_DIR=/workspace/ComfyUI/models
else
    MODELS_DIR="$DATA_DIR/models"
fi
export MODELS_DIR
mkdir -p "$MODELS_DIR"
# Copy the empty standard subfolders (checkpoints, loras, vae, ...) without overwriting.
if [ -d "$COMFY/models" ] && [ ! -L "$COMFY/models" ]; then
    cp -rn "$COMFY/models/." "$MODELS_DIR/" 2>/dev/null || true
    rm -rf "$COMFY/models"
fi
ln -sfn "$MODELS_DIR" "$COMFY/models"
stamp "models at $MODELS_DIR"

# ---- persistent user data
for d in input output user; do
    if [ -d "$COMFY/$d" ] && [ ! -L "$COMFY/$d" ]; then
        cp -rn "$COMFY/$d/." "$DATA_DIR/$d/" 2>/dev/null || true
        rm -rf "${COMFY:?}/$d"
    fi
    ln -sfn "$DATA_DIR/$d" "$COMFY/$d"
done

# ---- custom nodes: image-managed nodes are re-synced when the image changes; nodes the
# user installed are left alone. Model-Manager keeps the user's API tokens in private.key.
BUNDLE="$COMFY/.runpod-bundle-version"
if ! cmp -s "$BUNDLE" "$DATA_DIR/custom_nodes/.aiangel-bundle-version"; then
    for node in "$BAKED_NODES"/*/; do
        name=$(basename "$node")
        mkdir -p "$DATA_DIR/custom_nodes/$name"
        rsync -a --delete --exclude=private.key --exclude=rgthree_config.json "$node" "$DATA_DIR/custom_nodes/$name/"
    done
    rsync -a --exclude="*/" "$BAKED_NODES/" "$DATA_DIR/custom_nodes/"
    cp "$BUNDLE" "$DATA_DIR/custom_nodes/.aiangel-bundle-version"
    stamp "custom nodes synced from image"
fi
rm -rf "$COMFY/custom_nodes"
ln -sfn "$DATA_DIR/custom_nodes" "$COMFY/custom_nodes"
python3.12 /opt/aiangel/seed_model_manager_keys.py \
    "$DATA_DIR/custom_nodes/ComfyUI-Model-Manager/private.key" || true

# H3 latent upscaler node: its repo ships no LICENSE file, so unlike the packs above it is never
# baked into the image. MODELS=...,h3upscaler both fetches this node's code (pinned commit, here)
# and its model file (a normal models.tsv preset, below).
case ",${MODELS// /}," in
    *,h3upscaler,*)
        UPSCALER_COMMIT=d7c01b9011f2e8439493f6c02c29995a27df276f
        UPSCALER_DIR="$DATA_DIR/custom_nodes/comfyui-minimax-h3-latent-upscaler"
        if [ ! -d "$UPSCALER_DIR" ]; then
            stamp "fetching H3 latent upscaler node $UPSCALER_COMMIT (no LICENSE, not baked in the image)"
            curl -fsSL "https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/archive/$UPSCALER_COMMIT.tar.gz" -o /tmp/h3upscaler.tar.gz \
                && mkdir -p "$UPSCALER_DIR" \
                && tar xzf /tmp/h3upscaler.tar.gz --strip-components=1 -C "$UPSCALER_DIR" \
                && rm -f /tmp/h3upscaler.tar.gz \
                || stamp "WARNING: H3 latent upscaler node fetch failed"
        fi
        ;;
esac

# Python packages live in the image, so a user-installed node needs its requirements again on
# every fresh container. The pip cache on the volume keeps that quick.
for req in "$DATA_DIR"/custom_nodes/*/requirements.txt; do
    [ -f "$req" ] || continue
    name=$(basename "$(dirname "$req")")
    [ -d "$BAKED_NODES/$name" ] && continue
    stamp "installing requirements for user node $name"
    python3.12 -m pip install -q -r "$req" >> "$LOG_DIR/user-nodes-pip.log" 2>&1 \
        || stamp "WARNING: requirements for $name failed, see $LOG_DIR/user-nodes-pip.log"
done

# ---- access passwords: use the env value, otherwise generate one once and keep it on the volume
secret() {
    local name=$1 given=$2 file="$SECRETS/$1"
    if [ -n "$given" ]; then
        printf '%s' "$given" > "$file"
    elif [ ! -s "$file" ]; then
        openssl rand -hex 8 > "$file"
    fi
    chmod 600 "$file"
    cat "$file"
}

if [ -n "${PUBLIC_KEY:-}" ]; then
    mkdir -p ~/.ssh && echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys && chmod 700 -R ~/.ssh
    [ -f /etc/ssh/ssh_host_ed25519_key ] || ssh-keygen -A -q
    /usr/sbin/sshd && stamp "sshd started (key auth)"
fi

FB_DB="$DATA_DIR/.filebrowser.db"
FB_PASS=$(secret filebrowser_password "${FILEBROWSER_PASSWORD:-}")
if [ ! -f "$FB_DB" ]; then
    filebrowser -d "$FB_DB" config init >/dev/null
    filebrowser -d "$FB_DB" config set --address 0.0.0.0 --port 8080 --root /workspace \
        --auth.method=json >/dev/null
    filebrowser -d "$FB_DB" users add admin "$FB_PASS" --perm.admin >/dev/null
else
    filebrowser -d "$FB_DB" users update admin --password "$FB_PASS" >/dev/null 2>&1 || true
fi
nohup filebrowser -d "$FB_DB" > "$LOG_DIR/filebrowser.log" 2>&1 &

JUPYTER_TOKEN=$(secret jupyter_password "${JUPYTER_PASSWORD:-}")
nohup jupyter lab --allow-root --no-browser --port=8888 --ip=0.0.0.0 \
    --ServerApp.root_dir=/workspace --IdentityProvider.token="$JUPYTER_TOKEN" \
    > "$LOG_DIR/jupyter.log" 2>&1 &

echo "================================================================"
echo "  FileBrowser  :8080  user admin  password $FB_PASS"
echo "  JupyterLab   :8888  token $JUPYTER_TOKEN"
echo "  (stored in $SECRETS; set FILEBROWSER_PASSWORD / JUPYTER_PASSWORD to choose your own)"
echo "================================================================"

# ---- model presets download in the background; ComfyUI does not wait for them
# "nsfw" is not a models.tsv preset: it adds the Civitai list in /opt/aiangel/nsfw.txt to EXTRA_MODELS.
case ",${MODELS// /}," in
    *,nsfw,*)
        MODELS=$(echo ",${MODELS// /}," | sed 's/,nsfw,/,/g; s/^,//; s/,$//')
        EXTRA_MODELS="$(cat /opt/aiangel/nsfw.txt)
${EXTRA_MODELS:-}"
        export EXTRA_MODELS
        [ -n "${CIVITAI_TOKEN:-}" ] || stamp "WARNING: MODELS=nsfw needs CIVITAI_TOKEN (Civitai API key); set it or use the Model list panel"
        ;;
esac
if [ -n "${MODELS:-}" ] || [ -n "${EXTRA_MODELS:-}" ]; then
    (
        [ -n "${MODELS:-}" ] && /opt/aiangel/download_models.sh "$MODELS"
        [ -n "${EXTRA_MODELS:-}" ] && python3.12 "$BAKED_NODES/ComfyUI-AiAngel/fetch.py"
    ) > "$LOG_DIR/models.log" 2>&1 &
    stamp "downloading models in background (log: $LOG_DIR/models.log)"
fi

# ---- ComfyUI
cd "$COMFY"
# shellcheck disable=SC2086
python3.12 main.py --listen 0.0.0.0 --port 8188 ${COMFYUI_ARGS:-} &
COMFY_PID=$!

(
    until curl -fs -o /dev/null http://127.0.0.1:8188/system_stats; do
        kill -0 "$COMFY_PID" 2>/dev/null || exit 0
        sleep 1
    done
    stamp "ComfyUI READY on :8188"
) &

SHUTTING_DOWN=0
trap 'SHUTTING_DOWN=1; kill $COMFY_PID 2>/dev/null' SIGTERM SIGINT
COMFY_EXIT=0
wait "$COMFY_PID" || COMFY_EXIT=$?
if [ "$SHUTTING_DOWN" = 1 ]; then
    pkill -TERM -f jupyter-lab 2>/dev/null || true
    pkill -TERM -x filebrowser 2>/dev/null || true
    exit 0
fi

stamp "ComfyUI exited (code $COMFY_EXIT). FileBrowser and JupyterLab stay up for debugging."
echo "  restart it with:  cd $COMFY && python3.12 main.py --listen 0.0.0.0 --port 8188 ${COMFYUI_ARGS:-}"
sleep infinity
