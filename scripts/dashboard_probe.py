# /// script
# dependencies = ["requests"]
# ///
"""Read-only probe of a live AI Angel dashboard (port 8189): state, outputs, logs, ZIP.

Secrets in /api/state are never printed (only whether they are present).

  uv run scripts/dashboard_probe.py https://<pod-id>-8189.proxy.runpod.net
"""

import argparse
import io
import json
import sys
import time
import zipfile

import requests


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    base = ap.parse_args().base.rstrip("/")
    s = requests.Session()

    t = time.monotonic()
    st = s.get(f"{base}/api/state", timeout=60).json()
    print(f"state {time.monotonic() - t:.1f}s")
    pod = st["pod"]
    print(" pod:", json.dumps({k: pod.get(k) for k in ("id", "gpu", "cuda", "image", "uptime_s")}))
    print(
        " vram:",
        pod.get("vram_used_mb"),
        "/",
        pod.get("vram_total_mb"),
        "util",
        pod.get("gpu_util"),
    )
    print(" disk:", json.dumps(pod.get("disk")))
    for sv in st["services"]:
        print(
            " service:",
            sv["key"],
            sv["state"],
            sv.get("url"),
            "secret present:",
            bool(sv.get("secret")),
        )
    print(" models_env:", st["models_env"])
    for p in st["presets"]:
        states = [f["state"] for f in p["files"]]
        gb = sum(f["size"] for f in p["files"]) / 1e9
        print(f" preset {p['name']:<11} in_env={p['in_env']!s:<5} {gb:6.1f} GB {states}")
    print(" jobs:", len(st["jobs"]), "keys set:", {k: v is not None for k, v in st["keys"].items()})
    print(" outputs:", st["outputs"])

    outs = s.get(f"{base}/api/outputs", timeout=60).json()["files"]
    print("outputs files:", len(outs), [o["path"] for o in outs[:5]])
    if outs:
        o = outs[-1]
        r = s.get(
            f"{base}/api/outputs/file",
            params={"path": o["path"]},
            headers={"Range": "bytes=0-99"},
            timeout=60,
        )
        print(" range get:", r.status_code, r.headers.get("Content-Range"), len(r.content))
        r = s.post(f"{base}/api/outputs/zip", json={"files": [o["path"]]}, timeout=300)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        print(
            " zip:",
            r.status_code,
            r.headers.get("Content-Disposition"),
            z.namelist(),
            "size ok:",
            z.getinfo(z.namelist()[0]).file_size == o["size"],
        )

    for name in ("boot", "models", "comfyui"):
        r = s.get(f"{base}/api/logs", params={"name": name, "lines": 400}, timeout=60)
        lines = r.json().get("lines", [])
        last = lines[-1][:140] if lines else None
        print(f"log {name}: {r.status_code} {len(lines)} lines; last: {last!r}")
        hits = [
            ln
            for ln in lines
            if any(w in ln for w in ("WARNING", "ERROR", "Traceback", "READY", "synced"))
        ]
        for ln in hits[-8:]:
            print("   ", ln[:160])


if __name__ == "__main__":
    main()
