"""Checks on the files that go into the public Docker image."""

import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "presets" / "models.tsv"
def _tracked_files(subdir: str) -> list[Path]:
    return sorted(
        p for p in (ROOT / subdir).rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )


IMAGE_FILES = [
    ROOT / "Dockerfile",
    *_tracked_files("docker"),
    *_tracked_files("nodes"),
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
    "latent_upscale_models",
}
# Every custom node pack baked into custom_nodes.baked, pinned by a commit SHA + sha256 ARG pair.
BAKED_NODE_PACKS = {
    "KREA2EDIT",
    "MAINODES",
    "SPECTRUM",
    "WDC",
    "H3PROMPTIDE",
    "RGTHREE",
    "EASYUSE",
    "VHS",
    "OBVPM",
    "SOLATTN",
}


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
        assert re.fullmatch(r"[a-z0-9_]+(,[a-z0-9_]+)*", preset), f"line {n}: preset {preset!r}"
        assert sub in KNOWN_SUBDIRS, f"line {n}: unknown models subdir {sub!r}"
        assert size.isdigit() and int(size) > 0, f"line {n}: size {size!r}"
        parsed = urlparse(url)
        assert parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS, f"line {n}: {url}"
        assert parsed.path.endswith("/" + name), f"line {n}: URL does not end in {name}"
        assert (sub, name) not in seen, f"line {n}: duplicate {sub}/{name}"
        seen.add((sub, name))


def preset_files(preset):
    return {row[3] for row in preset_rows() if preset in row[1].split(",")}


def test_presets_cover_both_video_models():
    presets = {p for row in preset_rows() for p in row[1].split(",")}
    assert {"h3", "h3core", "scail"} <= presets


def test_h3_preset_holds_what_the_template_workflows_load():
    import importlib.util

    spec = importlib.util.spec_from_file_location("h3wf", ROOT / "scripts" / "h3_workflows.py")
    h3wf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h3wf)
    core = {h3wf.TEXT_ENCODER, h3wf.VIDEO_VAE, h3wf.AUDIO_VAE}
    assert preset_files("h3core") == core, "h3core = what any H3 diffusion model needs"
    assert preset_files("h3") == core | {h3wf.UNET, h3wf.TURBO_LORA}
    assert preset_files("aiangelh3") == {h3wf.AIANGEL_UNET}, (
        "aiangelh3 = the merge only; pair with h3core"
    )
    graph = h3wf.clip("x", [], **h3wf.AIANGEL)
    loaded = {
        v
        for n in graph.values()
        for k, v in n["inputs"].items()
        if k in ("unet_name", "clip_name", "vae_name", "lora_name")
    }
    assert loaded == core | {h3wf.AIANGEL_UNET}, "the AiAngelH3 clip loads only h3core + aiangelh3"


def test_no_secrets_or_private_paths_in_image_files():
    token_like = re.compile(r"(hf_[A-Za-z0-9]{20,}|rpa_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})")
    for path in IMAGE_FILES:
        # front-end assets under docker/dashboard/web/ may be binary (png, ...); decode with
        # replacement so this stays a text-pattern scan instead of crashing on those.
        text = path.read_bytes().decode("utf-8", errors="replace")
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


def test_start_sh_node_sync_survives_global_volumes():
    """RunPod Global volumes refuse rsync's temp files; the sync must write in place and heal."""
    text = (ROOT / "docker" / "start.sh").read_text(encoding="utf-8")
    assert "rsync -a --delete" not in text
    assert text.count("--inplace") >= 2
    assert "! nodes_ok" in text, "a half-synced volume must re-sync even when the version matches"
    assert 'ln -sfn "${node%/}" "$dest"' in text, "fallback: run the node from the image"


def test_aiangel_node_version_covers_every_file():
    """The node's bundle-version hash decides whether an existing volume re-syncs the node. A hash
    of only *.py/*.js left renamed example workflows under their old names on a volume."""
    lines = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    line = next(ln for ln in lines if "AIANGEL_NODE=" in ln)
    assert "find . -type f" in line, line
    assert "*.py" not in line and "*.js" not in line, line


def test_example_workflow_names_can_open_from_a_link():
    """ComfyUI's ?template=<name>&source=<node> link only accepts [a-zA-Z0-9_.-]; the dashboard
    and the first-visit loader open AiAngelH3-Clip by that name."""
    import re

    wf_dir = ROOT / "nodes" / "ComfyUI-AiAngel" / "example_workflows"
    names = [p.stem for p in wf_dir.glob("*.json")]
    assert "AiAngelH3-Clip" in names
    assert all(re.fullmatch(r"[a-zA-Z0-9_.-]+", n) for n in names), names


def test_aiangelh3_example_workflows_load_the_merge():
    import json

    wf_dir = ROOT / "nodes" / "ComfyUI-AiAngel" / "example_workflows"
    for name in ("AiAngelH3-Clip.json", "AiAngelH3-Extend.json"):
        wf = json.loads((wf_dir / name).read_text(encoding="utf-8"))
        by_type = {}
        for n in wf["nodes"]:
            by_type.setdefault(n["type"], []).append(n)
        assert by_type["UNETLoader"][0]["widgets_values"][0] == "AiAngelH3-v1-int8.safetensors", (
            name
        )
        assert all(n["mode"] == 4 for n in by_type["LoraLoaderModelOnly"]), (
            f"{name}: turbo LoRA bypassed"
        )
        assert by_type["KSamplerSelect"][0]["widgets_values"][0] == "euler", name
        assert by_type["BasicScheduler"][0]["widgets_values"][:2] == ["simple", 8], name


def test_start_sh_fetches_h3_upscaler_opt_in():
    text = (ROOT / "docker" / "start.sh").read_text(encoding="utf-8")
    assert ",h3upscaler,*)" in text
    assert "LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler" in text
    assert preset_files("h3upscaler")


def test_h3_upscaler_node_is_never_baked():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "Comfyui_Minimax_h3_latent_Upscaler" not in text
    assert "LBH-123-AI" not in text


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


def test_dockerfile_exposes_the_dashboard_port():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^EXPOSE .*\b8189\b", text, re.MULTILINE), "dashboard is not EXPOSEd"
