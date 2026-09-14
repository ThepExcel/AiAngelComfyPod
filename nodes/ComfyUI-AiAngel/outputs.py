"""List ComfyUI output files and stream a chosen set as one ZIP.

Used by the "Outputs" sidebar tab (this package's __init__.py). No ComfyUI imports, so it runs
in the offline tests.

The ZIP is STORED (no compression): images and videos are already compressed, so deflate only
burns CPU. It is written straight to the HTTP response while files are read, so the download
starts at once and nothing is copied to disk first.
"""

from __future__ import annotations

import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
CHUNK = 1 << 20


def kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE:
        return "image"
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    return "other"


def list_outputs(root: Path) -> list[dict]:
    """Every file under root (hidden files and folders skipped), newest first."""
    root = root.resolve()
    files = []
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        st = path.stat()
        files.append(
            {
                "path": rel.as_posix(),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "kind": kind(path.name),
            }
        )
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files


def safe_files(root: Path, rels: list[str]) -> list[tuple[Path, str]]:
    """Resolve requested relative paths; refuse anything outside root or missing."""
    root = root.resolve()
    out = []
    seen = set()
    for rel in rels:
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError(f"not inside the output folder: {rel}")
        if not path.is_file():
            raise ValueError(f"no such file: {rel}")
        arc = path.relative_to(root).as_posix()
        if arc not in seen:
            seen.add(arc)
            out.append((path, arc))
    return out


class _Sink:
    """Write-only file object: zipfile appends bytes, the caller takes them out in pieces."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data = b"".join(self._parts)
        self._parts.clear()
        return data


def zip_chunks(files: list[tuple[Path, str]], chunk: int = CHUNK) -> Iterator[bytes]:
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for path, arc in files:
            info = zipfile.ZipInfo.from_file(path, arc)
            info.compress_type = zipfile.ZIP_STORED
            with path.open("rb") as src, zf.open(info, "w") as dst:
                while block := src.read(chunk):
                    dst.write(block)
                    yield sink.take()
            yield sink.take()
    yield sink.take()


def zip_name(now: float | None = None) -> str:
    return time.strftime("aiangel-outputs-%Y%m%d-%H%M%S.zip", time.localtime(now))
