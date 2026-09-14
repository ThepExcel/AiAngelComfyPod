"""Copy every ComfyUI output from a running pod to this computer, several files at a time.

Needs only Python 3.9+ (no packages). Download it from your pod and run it:

    python pull.py https://<pod-id>-8188.proxy.runpod.net  ./outputs
    python pull.py <pod url> ./outputs --only video --since-hours 6 --jobs 6

Files already here at the same size are skipped, so run it again whenever you like; only new
results are fetched. A download that was cut off resumes from where it stopped.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode

UA = {"User-Agent": "AiAngelComfyPod-pull/1.0"}


def list_remote(base: str) -> list[dict]:
    req = urllib.request.Request(f"{base}/aiangel/outputs", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["files"]


def select(
    files: list[dict], only: str | None, since_hours: float | None, now: float
) -> list[dict]:
    out = []
    for f in files:
        if only and f["kind"] != only:
            continue
        if since_hours is not None and f["mtime"] < now - since_hours * 3600:
            continue
        out.append(f)
    return out


def local_path(dest: Path, rel: str) -> Path:
    parts = PurePosixPath(rel).parts
    if not parts or any(p in ("..", "") or p.startswith("/") for p in parts):
        raise ValueError(f"refusing unsafe path from server: {rel}")
    return dest.joinpath(*parts)


def view_url(base: str, rel: str) -> str:
    p = PurePosixPath(rel)
    query = {"filename": p.name, "type": "output"}
    if str(p.parent) != ".":
        query["subfolder"] = str(p.parent)
    return f"{base}/view?{urlencode(query, quote_via=quote)}"


def fetch_one(base: str, f: dict, dest: Path) -> tuple[str, int]:
    """Returns (status, bytes transferred). status: skipped / done."""
    target = local_path(dest, f["path"])
    if target.exists() and target.stat().st_size == f["size"]:
        return "skipped", 0
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > f["size"]:
        part.unlink()
        have = 0
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    got = 0
    part.touch()
    if have < f["size"]:
        req = urllib.request.Request(view_url(base, f["path"]), headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            mode = "ab" if have and r.status == 206 else "wb"
            with part.open(mode) as out:
                while block := r.read(1 << 20):
                    out.write(block)
                    got += len(block)
    if part.stat().st_size != f["size"]:
        raise OSError(f"size mismatch for {f['path']}: {part.stat().st_size} != {f['size']}")
    part.replace(target)
    return "done", got


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("pod_url", help="ComfyUI address, e.g. https://abc123-8188.proxy.runpod.net")
    ap.add_argument("dest", type=Path, help="local folder to copy into")
    ap.add_argument("--jobs", type=int, default=4, help="files downloaded at the same time")
    ap.add_argument("--only", choices=["image", "video", "audio", "other"])
    ap.add_argument("--since-hours", type=float, help="only files made in the last N hours")
    args = ap.parse_args(argv)

    base = args.pod_url.rstrip("/")
    files = select(list_remote(base), args.only, args.since_hours, time.time())
    total = sum(f["size"] for f in files)
    print(f"{len(files)} file(s) on the pod, {total / 1e9:.2f} GB -> {args.dest}")

    t0 = time.time()
    moved = done = skipped = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(fetch_one, base, f, args.dest): f for f in files}
        for fut in as_completed(futures):
            f = futures[fut]
            try:
                status, n = fut.result()
            except Exception as e:
                failed += 1
                print(f"  FAILED {f['path']}: {e}")
                continue
            moved += n
            if status == "skipped":
                skipped += 1
            else:
                done += 1
                print(f"  got {f['path']} ({f['size'] / 1e6:.1f} MB)")
    secs = max(time.time() - t0, 1e-6)
    print(
        f"done {done}, already here {skipped}, failed {failed} · "
        f"{moved / 1e6:.0f} MB in {secs:.0f}s ({moved / 1e6 / secs:.1f} MB/s)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
