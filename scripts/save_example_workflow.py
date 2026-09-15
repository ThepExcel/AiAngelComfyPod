"""Store a workflow saved from the real ComfyUI UI as a template example workflow.

Keeps what the UI wrote; only resets run-specific state so the committed file is stable: the zero
workflow id, the seed from the source example, and the source's canvas view.

usage: uv run python scripts/save_example_workflow.py UI_SAVED.json AiAngelH3-Clip.json \
    SOURCE_EXAMPLE.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "nodes" / "ComfyUI-AiAngel" / "example_workflows"

saved = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
source = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
saved["id"] = source["id"]
saved["extra"]["ds"] = source["extra"]["ds"]
seed = next(n for n in source["nodes"] if n["type"] == "RandomNoise")["widgets_values"][0]
for n in saved["nodes"]:
    if n["type"] == "RandomNoise":
        n["widgets_values"][0] = seed
        if "widgets_values_named" in n:
            n["widgets_values_named"]["noise_seed"] = seed
out = DEST / sys.argv[2]
out.write_text(
    json.dumps(saved, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
)
print(out, len(saved["nodes"]), "nodes, seed", seed)
