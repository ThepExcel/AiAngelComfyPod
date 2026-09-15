# AI Angel Dashboard — HTTP contract (port 8189)

The dashboard is a standalone aiohttp server in the image (`docker/dashboard/server.py`, run with
`python3.12`), started by `start.sh` BEFORE ComfyUI, so it answers while ComfyUI is booting,
crashed or restarting. It serves the static front end from `docker/dashboard/web/` at `/` and the
JSON API below. Every JSON response is `Content-Type: application/json`; errors are
`{"error": "<human sentence>"}` with a 4xx/5xx status.

CSRF: a request with `Sec-Fetch-Site: cross-site` is refused with 403 unless it is a top-level page
open (`GET` + `Sec-Fetch-Mode: navigate` + `Sec-Fetch-Dest: document`), the same rule as the ComfyUI
patch (`docker/patch_comfy_origin.py`).

## GET /api/state  (front end polls every 2 s)

```json
{
  "pod": {
    "id": "l45bp7l06j9ekz",            // RUNPOD_POD_ID or null
    "gpu": "NVIDIA RTX PRO 6000 Blackwell Server Edition",   // nvidia-smi, null if none
    "vram_used_mb": 1234, "vram_total_mb": 97887, "gpu_util": 0,          // ints or null
    "cuda": "13.0",                     // from the image (env CUDA_VERSION or torch), string or null
    "image": "48fb63a",                 // /opt/aiangel/image-version (build writes the git sha) or null
    "uptime_s": 812,                    // since the dashboard process started
    "disk": {"workspace": {"used": 46000000000, "total": 120000000000},
             "container": {"used": 9000000000, "total": 30000000000}}
  },
  "services": [
    {"key": "comfyui", "name": "ComfyUI", "port": 8188, "url": "https://<pod>-8188.proxy.runpod.net/",
     "state": "ready" | "starting" | "down"},
    {"key": "filebrowser", "name": "FileBrowser", "port": 8080, "url": "...", "state": "ready" | "down",
     "user": "admin", "secret": "<password or null>"},
    {"key": "jupyter", "name": "JupyterLab", "port": 8888, "url": "...", "state": "ready" | "down",
     "secret": "<token or null>"}
  ],
  "models_env": "h3core,h3upscaler,aiangelh3",       // MODELS at boot
  "presets": [                                      // every preset name in models.tsv, table order
    {"name": "aiangelh3", "in_env": true,
     "files": [{"folder": "diffusion_models", "name": "AiAngelH3-v1-int8.safetensors",
                "size": 20970427336, "have_bytes": 20970427336,
                "state": "have" | "downloading" | "missing" | "queued" | "failed"}]}
  ],
  "jobs": [                                         // downloads queued in THIS dashboard, newest last
    {"id": 3, "label": "loras/foo.safetensors", "url": "https://...", "state": "queued" | "resolving" |
     "downloading" | "done" | "failed", "size": 123, "done_bytes": 45, "message": "..."}
  ],
  "keys": {"civitai": "abcd…wxyz" | null, "huggingface": null},
  "outputs": {"count": 42, "bytes": 1234567}
}
```

`if url` cannot be built (no RUNPOD_POD_ID, local run) use `http://<request host>:<port>/`.
`have_bytes` uses allocated blocks while a file grows (same idea as `_written_bytes` in the ComfyUI
node). `state` "downloading" = file exists, smaller than `size`, and it grew in the last 30 s.

## POST /api/keys   `{"civitai": "...", "huggingface": "..."}`
"" keeps, "-" clears. Same files as the ComfyUI panel: `$DATA_DIR/.secrets/civitai_token`,
`huggingface_token` (mode 600). Returns the masked `keys` object.

## POST /api/download   `{"text": "<pasted list>"}`
Same list format and parser as the Model list panel (`fetch.parse_entries`). Returns
`{"queued": n}` or 400 with the bad line.

## POST /api/preset   `{"name": "scail"}`
Queues every file of that models.tsv preset that is not already present at full size, as download
jobs (HF token sent only to huggingface.co). Returns `{"queued": n}`; unknown preset -> 400.
`"nsfw"` is not accepted here (it needs the kit text; the front end posts it via /api/download
after GET /api/kit/nsfw).

## GET /api/kit/nsfw
`{"text": "<contents of /opt/aiangel/nsfw.txt>"}` or 404.

## GET /api/outputs
`{"files": [{"path": "AiAngel/aiangelh3_00001_.mp4", "size": 949308, "mtime": 1789490432.8,
"kind": "video"}], "output_dir": "..."}` newest first (`outputs.list_outputs`).

## GET /api/outputs/file?path=<rel>[&download=1]
Streams one output file (range requests supported, so `<video>` can seek). `download=1` adds
`Content-Disposition: attachment`. Paths outside the output folder -> 400.

## POST /api/outputs/zip
Form field or JSON `files` = JSON list of relative paths (empty = all). Streams a STORED ZIP
(`outputs.zip_chunks`), filename `outputs.zip_name()`. Splitting into parts is done by the front
end (it posts one request per part).

## POST /api/comfy/restart
Stops the running ComfyUI (`main.py --port 8188`) and starts it again with the same arguments
(`COMFYUI_ARGS`), output appended to `$LOG_DIR/comfyui.log`. Returns `{"ok": true}` at once;
`/api/state` shows `starting` then `ready`.

## GET /api/logs?name=boot|models|comfyui&lines=200
`{"name": "...", "lines": ["..."]}` — tail of `$LOG_DIR/boot.log` (start.sh tees its own output
there), `$LOG_DIR/models.log`, and ComfyUI's log (`http://127.0.0.1:8188/internal/logs` when up,
else `$LOG_DIR/comfyui.log`). Secret values from `.secrets/` are replaced with `••••` in every line.
