"""Derive the AiAngelH3 example workflows from the AiAngel H3 ones (same layout and notes).

Changes: the merge in the model loader, the turbo LoRA node bypassed (kept, so a user can turn it
back on), euler / simple 8 steps (h3_workflows.AIANGEL), MODELS=h3core,aiangelh3 in titles and
notes, its own save prefix. The result is loaded, run and re-saved from the real ComfyUI UI on a
pod before it is committed (scripts/save_example_workflow.py), so the saved file is what the UI
writes.

usage: uv run python scripts/make_aiangelh3_workflows.py OUT_DIR
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "nodes" / "ComfyUI-AiAngel" / "example_workflows"

spec = importlib.util.spec_from_file_location("h3wf", ROOT / "scripts" / "h3_workflows.py")
h3wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h3wf)
A = h3wf.AIANGEL

TEXT = [
    ("## H3 Hybrid · ", "## AiAngelH3 · "),
    ("`MODELS=h3`", "`MODELS=h3core,aiangelh3`"),
    (
        "**Your LoRA:** add *LoraLoaderModelOnly* between *Turbo LoRA* and"
        " *Comfy Kitchen attention*.",
        "**Your LoRA:** add *LoraLoaderModelOnly* between *Turbo LoRA (off)* and *Comfy Kitchen"
        " attention*; concept LoRAs work well at low strength (0.4 to 0.9).\n"
        "**Turbo LoRA stays off:** AiAngelH3 has the turbo delta merged in; stacking the LoRA made"
        " results worse. Model page: https://huggingface.co/AiAngelGallery/AiAngelH3",
    ),
]
SPEED_NOTE = (
    "### AiAngelH3 settings\n\n"
    "- Sampler **euler**, scheduler **simple**, **8 steps**\n"
    "- **No turbo LoRA** (bypassed node, purple)\n"
    "- Comfy Kitchen attention on\n\n"
    "__TIMING__\n\n"
    "Width/height must be multiples of 32. 576×1024 for drafts; 720×1280 for finals.\n\n"
    "License: MiniMax H3 Community License (not licensed in the EU, UK, KR or US); label published"
    " results as AI-generated; no paid generation services outside Civitai."
)


def set_widget(node: dict, name: str, value) -> None:
    names = list(node["widgets_values_named"])
    node["widgets_values_named"][name] = value
    node["widgets_values"][names.index(name)] = value


def convert(wf: dict, prefix: str, timing: str) -> dict:
    for n in wf["nodes"]:
        t = n["type"]
        if t == "UNETLoader":
            set_widget(n, "unet_name", A["unet"])
        elif t == "LoraLoaderModelOnly" and n.get("title", "").startswith("Turbo LoRA"):
            n["mode"] = 4  # bypass: the model passes straight through
            n["title"] = "Turbo LoRA (off for AiAngelH3)"
        elif t == "KSamplerSelect":
            set_widget(n, "sampler_name", A["sampler"])
        elif t == "BasicScheduler":
            set_widget(n, "scheduler", A["scheduler"])
            set_widget(n, "steps", A["steps"])
        elif t == "SaveVideo":
            set_widget(n, "filename_prefix", prefix)
        elif t == "MarkdownNote":
            text = n["widgets_values_named"]["text"]
            if n.get("title") == "Speed notes":
                text = SPEED_NOTE.replace("__TIMING__", timing)
            for old, new in TEXT:
                text = text.replace(old, new)
            set_widget(n, "text", text)
    for g in wf["groups"]:
        g["title"] = g["title"].replace("(MODELS=h3)", "(MODELS=h3core,aiangelh3)")
    return wf


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    timing = sys.argv[2] if len(sys.argv) > 2 else "Timing: not measured yet."
    for src, dst, prefix in (
        ("H3 Hybrid - Clip (MODELS=h3).json", "AiAngelH3 - Clip.json", "AiAngel/aiangelh3"),
        (
            "H3 Hybrid - Extend (MODELS=h3).json",
            "AiAngelH3 - Extend.json",
            "AiAngel/aiangelh3-extend",
        ),
    ):
        wf = json.loads((SRC / src).read_text(encoding="utf-8"))
        text = json.dumps(convert(wf, prefix, timing), indent=1, ensure_ascii=False)
        (out / dst).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(out / dst)
