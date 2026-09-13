#!/bin/bash
# Download the model presets named in $1 (comma separated, or "all") into $MODELS_DIR.
# A file already present at the exact expected byte size is skipped, so re-running on a
# volume that holds the models costs nothing. HF_TOKEN is sent only to huggingface.co.
set -uo pipefail

WANT="${1:-}"
MODELS_DIR="${MODELS_DIR:?MODELS_DIR not set}"
PRESETS="${PRESETS_FILE:-/opt/aiangel/models.tsv}"
PARALLEL="${DOWNLOAD_PARALLEL:-3}"
T0=$(date +%s)

stamp() { echo "[models $(date -u +%FT%TZ) +$(( $(date +%s) - T0 ))s] $*"; }

wanted() {
    [ "$WANT" = all ] && return 0
    case ",${WANT// /}," in *",$1,"*) return 0 ;; esac
    return 1
}

known=$(cut -f1 "$PRESETS" | sort -u | tr '\n' ' ')
for p in ${WANT//,/ }; do
    [ "$p" = all ] && continue
    awk -F'\t' -v p="$p" '$1 == p { found = 1 } END { exit !found }' "$PRESETS" \
        || stamp "WARNING: unknown preset '$p' (known: $known)"
done

rm -f "$MODELS_DIR/.aiangel-download-done" "$MODELS_DIR/.aiangel-download-failed"
while IFS=$'\t' read -r preset sub name size url; do
    [ -z "$name" ] && continue
    wanted "$preset" || continue
    dest="$MODELS_DIR/$sub"
    mkdir -p "$dest"
    have=$(stat -c %s "$dest/$name" 2>/dev/null || echo 0)
    if [ "$have" = "$size" ]; then
        stamp "have $sub/$name"
        continue
    fi
    auth=()
    case "$url" in
        https://huggingface.co/*) [ -n "${HF_TOKEN:-}" ] && auth=(--header="Authorization: Bearer $HF_TOKEN") ;;
    esac
    (
        aria2c -q -x 16 -s 16 -c --auto-file-renaming=false "${auth[@]}" -d "$dest" -o "$name" "$url" \
            && stamp "got $sub/$name" || stamp "DOWNLOAD FAILED $sub/$name"
    ) &
    while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]; do sleep 2; done
done < "$PRESETS"
wait

bad=0
while IFS=$'\t' read -r preset sub name size url; do
    [ -z "$name" ] && continue
    wanted "$preset" || continue
    have=$(stat -c %s "$MODELS_DIR/$sub/$name" 2>/dev/null || echo 0)
    if [ "$have" != "$size" ]; then
        stamp "SIZE MISMATCH $sub/$name have=$have want=$size"
        bad=1
    fi
done < "$PRESETS"

if [ "$bad" = 0 ]; then
    stamp "ALL PRESET MODELS READY ($WANT) — refresh the ComfyUI page (press R) to see them"
    touch "$MODELS_DIR/.aiangel-download-done"
else
    stamp "SOME MODELS MISSING — restart the pod to resume; partial files continue where they stopped"
    touch "$MODELS_DIR/.aiangel-download-failed"
fi
