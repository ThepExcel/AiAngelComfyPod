"""Offline tests for docker/fetch_extra.py and docker/patch_model_manager.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "docker" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fx = load("fetch_extra")
pm = load("patch_model_manager")


def test_parse_entries_forms():
    raw = "https://civitai.red/models/1?modelVersionId=2 ; loras|https://x.test/a.safetensors\n"
    raw += "diffusion_models|https://civitai.com/models/3?modelVersionId=4|int8"
    assert fx.parse_entries(raw) == [
        (None, "https://civitai.red/models/1?modelVersionId=2", None),
        ("loras", "https://x.test/a.safetensors", None),
        ("diffusion_models", "https://civitai.com/models/3?modelVersionId=4", "int8"),
    ]


def test_parse_entries_rejects_unknown_folder():
    with pytest.raises(ValueError):
        fx.parse_entries("weights|https://x.test/a.safetensors")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://civitai.red/models/111/some-name?modelVersionId=222", ("111", "222")),
        ("https://www.civitai.com/models/111", ("111", None)),
        ("https://civitai.com/api/download/models/333", (None, "333")),
        ("https://civitai.com/model-versions/444", (None, "444")),
    ],
)
def test_civitai_ids(url, expected):
    assert fx.civitai_ids(url) == expected


FILES = [
    {"name": "demo_fp8.safetensors", "type": "Diffusion Model", "primary": True},
    {"name": "demo_int8.safetensors", "type": "Diffusion Model"},
    {"name": "demo.json", "type": "Workflow"},
]


def test_pick_file_primary_and_part():
    assert fx.pick_file(FILES, None)["name"] == "demo_fp8.safetensors"
    assert fx.pick_file(FILES, "int8")["name"] == "demo_int8.safetensors"
    with pytest.raises(ValueError):
        fx.pick_file(FILES, "nvfp4")


def test_pick_file_never_returns_a_workflow_when_weights_exist():
    files = [{"name": "w.json", "type": "Workflow", "primary": True}, *FILES[1:2]]
    assert fx.pick_file(files, None)["name"] == "demo_int8.safetensors"


def test_civitai_folder():
    assert fx.civitai_folder("Checkpoint", "Diffusion Model") == "diffusion_models"
    assert fx.civitai_folder("Checkpoint", "Model") == "checkpoints"
    assert fx.civitai_folder("LORA", "Model") == "loras"


def test_authed_civitai_url():
    base = "https://civitai.com/api/download/models/1"
    assert fx.authed_civitai_url(base, "k") == base + "?token=k"
    assert fx.authed_civitai_url(base + "?type=Model", "k") == base + "?type=Model&token=k"


def test_already_have_tolerates_kb_rounding(tmp_path):
    f = tmp_path / "m.safetensors"
    f.write_bytes(b"x" * 10_000)
    assert fx.already_have(f, 10_000 + 1000)
    assert not fx.already_have(f, 50_000)
    (tmp_path / "m.safetensors.aria2").write_bytes(b"")
    assert not fx.already_have(f, 10_000)


def test_patch_model_manager_applies_once_and_fails_on_drift(tmp_path):
    src = tmp_path / "information.py"
    src.write_text(
        "\n".join(
            [
                "raise RuntimeError(f'Unknown Website, "
                "please input a URL from huggingface.co or civitai.com.')",
                '"type": self._resolve_model_type(res_data.get("type", "")),',
                'if host_name == "civitai.com":',
            ]
        ),
        encoding="utf-8",
    )
    pm.patch(src)
    out = src.read_text(encoding="utf-8")
    assert '"civitai.red"' in out and '"Diffusion Model"' in out
    with pytest.raises(SystemExit):
        pm.patch(src)  # already patched: the originals no longer match
