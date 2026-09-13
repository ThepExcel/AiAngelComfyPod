"""example.py — gold standard reference demonstrating house conventions.

This module shows:
- argparse CLI entry point
- sys.stdout.reconfigure(encoding="utf-8") for cp874 safety
- Thai text via UTF-8 file, never argv (cp874 boundary rule)
- os.environ credential read (never hardcoded)
- audit sidecar JSON stub for any paid API call
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # cp874 boundary on Windows

    parser = argparse.ArgumentParser(description="Career/income: run ComfyUI video models (SCAIL-2, MiniMax H3) on rented RunPod GPUs fast and cheap, published as a public AI Angel template that earns creator credits")
    parser.add_argument("--msg-file", type=Path, help="UTF-8 text file (use for Thai input)")
    parser.add_argument("--output", type=Path, default=None, help="Output file path")
    args = parser.parse_args()

    # Read Thai content from file (never from argv — cp874 boundary)
    text = ""
    if args.msg_file:
        text = args.msg_file.read_text(encoding="utf-8")

    # Read credentials from environment (never print the value)
    api_key = os.environ.get("MY_API_KEY", "")
    if api_key:
        print(f"API key loaded (last 4: ...{api_key[-4:]})")

    # --- Example paid API call stub ---
    # BEFORE any real paid call, write the audit sidecar:
    def _write_audit_sidecar(stem: Path, endpoint: str, params: dict) -> None:
        sidecar = stem.with_suffix(".sidecar.json")
        sidecar.write_text(
            json.dumps({
                "endpoint": endpoint,
                "params": params,
                "timestamp_iso": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                "cost_estimate": None,  # fill in after you know the model/tokens
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    output = args.output or Path("output.txt")
    _write_audit_sidecar(output, "example-endpoint", {"text_len": len(text)})

    # Write result as UTF-8 file
    output.write_text(f"processed: {text}\n", encoding="utf-8")
    print(f"done: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
