"""Build-time patch for ComfyUI-Model-Manager (pinned release).

1. Accept Civitai links on every Civitai host (civitai.com, civitai.red, www.*), not only
   the exact host "civitai.com". The API calls themselves stay on civitai.com.
2. Civitai files typed "Diffusion Model" (UNet-only weights) default to the diffusion_models
   folder instead of checkpoints.

Each replacement must match exactly once, so a changed upstream release fails the build
instead of shipping a silently unpatched node.
"""

import sys
from pathlib import Path

REPLACEMENTS = [
    (
        'if host_name == "civitai.com":',
        'if host_name in ("civitai.com", "www.civitai.com", "civitai.red", "www.civitai.red"):',
    ),
    (
        '"type": self._resolve_model_type(res_data.get("type", "")),',
        '"type": "diffusion_models" if file.get("type") == "Diffusion Model"'
        ' else self._resolve_model_type(res_data.get("type", "")),',
    ),
    (
        "please input a URL from huggingface.co or civitai.com.",
        "please input a URL from huggingface.co, civitai.com or civitai.red.",
    ),
]


def patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            sys.exit(f"patch_model_manager: expected 1 match, found {count}: {old!r}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"patch_model_manager: patched {path}")


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
