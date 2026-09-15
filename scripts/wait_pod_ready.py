# /// script
# dependencies = ["requests"]
# ///
"""Wait for a newly deployed AI Angel pod: find the running pod (newest, optionally from a template),
then poll its dashboard until ComfyUI is ready and the boot models are present. Prints progress.

  uv run scripts/wait_pod_ready.py [--template kv4dk65aim] [--minutes 60]
"""

import argparse
import os
import sys
import time
import winreg

import requests


def api_key() -> str:
    key = os.environ.get("RUNPOD_API_KEY")
    if key:
        return key
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        return winreg.QueryValueEx(k, "RUNPOD_API_KEY")[0]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="kv4dk65aim")
    ap.add_argument("--minutes", type=int, default=60)
    a = ap.parse_args()
    h = {"Authorization": f"Bearer {api_key()}"}
    t0 = time.monotonic()
    pod = None
    last = ""
    while time.monotonic() - t0 < a.minutes * 60:
        if pod is None:
            pods = requests.get("https://rest.runpod.io/v1/pods", headers=h, timeout=30).json()
            pods = [
                p
                for p in pods
                if p.get("desiredStatus") == "RUNNING" and p.get("templateId") == a.template
            ]
            if pods:
                pods.sort(key=lambda p: p.get("lastStartedAt") or "", reverse=True)
                pod = pods[0]["id"]
                print(
                    f"+{time.monotonic() - t0:.0f}s pod {pod} image {pods[0].get('imageName')}",
                    flush=True,
                )
        else:
            try:
                st = requests.get(
                    f"https://{pod}-8189.proxy.runpod.net/api/state", timeout=20
                ).json()
                comfy = next(s["state"] for s in st["services"] if s["key"] == "comfyui")
                files = [f["state"] for p in st["presets"] if p["in_env"] for f in p["files"]]
                line = f"comfyui={comfy} image={st['pod'].get('image')} models={files.count('have')}/{len(files)}"
                if line != last:
                    print(f"+{time.monotonic() - t0:.0f}s {line}", flush=True)
                    last = line
                if comfy == "ready" and files and all(s == "have" for s in files):
                    print(f"READY {pod}")
                    return
            except (requests.RequestException, ValueError, KeyError, StopIteration):
                pass
        time.sleep(15)
    print(f"TIMEOUT pod={pod}")


if __name__ == "__main__":
    main()
