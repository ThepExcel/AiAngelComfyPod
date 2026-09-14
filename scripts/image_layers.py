# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Compressed layer sizes of a public image (ghcr.io or Docker Hub), to see what a cold pod must pull.

usage: uv run scripts/image_layers.py ghcr.io/thepexcel/aiangelcomfypod:cuda12.8
       uv run scripts/image_layers.py runpod/comfyui:1.3.0-rc.164-comfyuiv0.35.0-cuda12.8
"""

import sys

import requests

ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def main() -> None:
    ref = sys.argv[1]
    if ref.startswith("ghcr.io/"):
        repo, tag = ref[len("ghcr.io/"):].split(":")
        tok = requests.get("https://ghcr.io/token", params={"scope": f"repository:{repo}:pull", "service": "ghcr.io"}).json()["token"]
        reg = "https://ghcr.io/v2"
    else:
        repo, tag = ref.split(":")
        tok = requests.get("https://auth.docker.io/token", params={"service": "registry.docker.io", "scope": f"repository:{repo}:pull"}).json()["token"]
        reg = "https://registry-1.docker.io/v2"
    h = {"Authorization": f"Bearer {tok}", "Accept": ACCEPT}
    m = requests.get(f"{reg}/{repo}/manifests/{tag}", headers=h).json()
    if "manifests" in m:
        d = next(x["digest"] for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64")
        m = requests.get(f"{reg}/{repo}/manifests/{d}", headers=h).json()
    sizes = [l["size"] for l in m["layers"]]
    for i, s in enumerate(sizes):
        if s > 100_000_000:
            print(f"  layer {i:2d}: {s / 1e9:.2f} GB")
    print(f"{ref}: {len(sizes)} layers, {sum(sizes) / 1e9:.2f} GB compressed")


if __name__ == "__main__":
    main()
