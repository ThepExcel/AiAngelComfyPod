"""Checks on the files that go into the public Docker image."""

import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "presets" / "models.tsv"
IMAGE_FILES = [
    ROOT / "Dockerfile",
    *sorted(p for p in (ROOT / "docker").iterdir() if p.is_file()),
    *sorted(p for p in (ROOT / "nodes").rglob("*") if p.is_file() and "__pycache__" not in p.parts),
    PRESETS,
]
ALLOWED_HOSTS = {"huggingface.co"}
KNOWN_SUBDIRS = {
    "checkpoints",
    "clip_vision",
    "diffusion_models",
    "loras",
    "text_encoders",
    "vae",
    "vae_approx",
    "upscale_models",
    "controlnet",
    "embeddings",
}
# Every custom node pack baked into custom_nodes.baked, pinned by a commit SHA + sha256 ARG pair.
BAKED_NODE_PACKS = {"KREA2EDIT", "MAINODES", "SPECTRUM", "WDC", "H3PROMPTIDE"}


def preset_rows():
    rows = []
    for n, line in enumerate(PRESETS.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        cols = line.split("\t")
        assert len(cols) == 5, f"line {n}: expected 5 tab-separated columns, got {len(cols)}"
        rows.append((n, *cols))
    return rows


def test_presets_are_well_formed():
    rows = preset_rows()
    assert rows
    seen = set()
    for n, preset, sub, name, size, url in rows:
        assert re.fullmatch(r"[a-z0-9_]+", preset), f"line {n}: preset name {preset!r}"
        assert sub in KNOWN_SUBDIRS, f"line {n}: unknown models subdir {sub!r}"
        assert size.isdigit() and int(size) > 0, f"line {n}: size {size!r}"
        parsed = urlparse(url)
        assert parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS, f"line {n}: {url}"
        assert parsed.path.endswith("/" + name), f"line {n}: URL does not end in {name}"
        assert (sub, name) not in seen, f"line {n}: duplicate {sub}/{name}"
        seen.add((sub, name))


def test_presets_cover_both_video_models():
    presets = {row[1] for row in preset_rows()}
    assert {"h3", "scail"} <= presets


def test_no_secrets_or_private_paths_in_image_files():
    token_like = re.compile(r"(hf_[A-Za-z0-9]{20,}|rpa_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})")
    for path in IMAGE_FILES:
        text = path.read_text(encoding="utf-8")
        assert not token_like.search(text), f"{path.name}: looks like an API token"
        assert "D:/" not in text and "C:\\" not in text, f"{path.name}: local Windows path"


def test_nsfw_kit_is_a_valid_model_list():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fetch_for_kit", ROOT / "nodes" / "ComfyUI-AiAngel" / "fetch.py"
    )
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    entries = fetch.parse_entries((ROOT / "presets" / "nsfw.txt").read_text(encoding="utf-8"))
    assert len(entries) >= 5
    for folder, url, _ in entries:
        assert folder in KNOWN_SUBDIRS, url
        host = urlparse(url).hostname
        assert host in {"civitai.red", "civitai.com", "huggingface.co"}, url
        assert host == "huggingface.co" or "modelVersionId=" in url, f"pin a version: {url}"


def test_start_sh_strips_nsfw_from_presets():
    text = (ROOT / "docker" / "start.sh").read_text(encoding="utf-8")
    assert "/opt/aiangel/nsfw.txt" in text and "s/,nsfw,/,/g" in text


def test_baked_custom_nodes_are_pinned():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for pack in BAKED_NODE_PACKS:
        commit = re.search(rf"ARG {pack}_COMMIT=([0-9a-f]+)", text)
        sha256 = re.search(rf"ARG {pack}_SHA256=([0-9a-f]+)", text)
        assert commit, f"{pack}: no ARG {pack}_COMMIT in Dockerfile"
        assert sha256, f"{pack}: no ARG {pack}_SHA256 in Dockerfile"
        assert len(commit.group(1)) == 40, f"{pack}: COMMIT is not a full 40-char SHA"
        assert len(sha256.group(1)) == 64, f"{pack}: SHA256 is not a full 64-char digest"
        assert f"{{{pack}_COMMIT}}" in text, f"{pack}: COMMIT ARG never referenced"
        assert f"{{{pack}_SHA256}}" in text, f"{pack}: SHA256 ARG never referenced"


def test_shell_scripts_use_lf_line_endings():
    for path in (ROOT / "docker").glob("*.sh"):
        assert b"\r" not in path.read_bytes(), f"{path.name} has CRLF; bash in the container breaks"
