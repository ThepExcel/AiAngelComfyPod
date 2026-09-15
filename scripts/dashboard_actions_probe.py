# /// script
# dependencies = ["requests"]
# ///
"""Exercise the write routes of a live AI Angel dashboard: keys save/clear, preset queue, ComfyUI
restart. Only touches keys that are empty; restart makes ComfyUI unavailable for about a minute.

  uv run scripts/dashboard_actions_probe.py https://<pod-id>-8189.proxy.runpod.net
"""

import argparse
import sys
import time

import requests


def body(r: requests.Response):
    try:
        return r.json()
    except ValueError:
        return r.text[:300]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    base = ap.parse_args().base.rstrip("/")
    s = requests.Session()

    keys = s.get(f"{base}/api/state", timeout=60).json()["keys"]
    if keys["civitai"] is None:
        r = s.post(
            f"{base}/api/keys",
            json={"civitai": "probe-dummy-0000-key", "huggingface": ""},
            timeout=60,
        )
        print("keys save:", r.status_code, body(r))
        r = s.post(f"{base}/api/keys", json={"civitai": "-", "huggingface": ""}, timeout=60)
        print("keys clear:", r.status_code, body(r))
    else:
        print("keys: civitai key already set, not touched")

    r = s.post(f"{base}/api/preset", json={"name": "h3upscaler"}, timeout=60)
    print("preset h3upscaler (already present):", r.status_code, body(r))
    r = s.post(f"{base}/api/preset", json={"name": "nope"}, timeout=60)
    print("preset unknown:", r.status_code, body(r))

    r = s.post(f"{base}/api/comfy/restart", json={}, timeout=60)
    print("restart:", r.status_code, body(r))
    t0 = time.monotonic()
    seen = []
    while time.monotonic() - t0 < 300:
        st = next(
            x["state"]
            for x in s.get(f"{base}/api/state", timeout=60).json()["services"]
            if x["key"] == "comfyui"
        )
        if not seen or seen[-1][1] != st:
            seen.append((round(time.monotonic() - t0), st))
            print(f"  +{seen[-1][0]}s comfyui {st}")
        if st == "ready" and len(seen) > 1:
            break
        time.sleep(2)
    lines = s.get(f"{base}/api/logs", params={"name": "boot", "lines": 400}, timeout=60).json()[
        "lines"
    ]
    print("boot log mentions restart:", [ln for ln in lines if "restart" in ln.lower()][-3:])
    lines = s.get(f"{base}/api/logs", params={"name": "comfyui", "lines": 50}, timeout=60).json()[
        "lines"
    ]
    print("comfyui log after restart, last:", lines[-1][:140] if lines else None)


if __name__ == "__main__":
    main()
