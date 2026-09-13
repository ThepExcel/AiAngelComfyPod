---
purpose: |
  Career/income: run ComfyUI video models (SCAIL-2, MiniMax H3) on rented RunPod GPUs fast and cheap, published as a public AI Angel template that earns creator credits
---
> STATUS: active · kind: tool · template: tool@1.0.0 · registry: claude-master/registry/projects.yaml

# AiAngelComfyPod

Career/income: run ComfyUI video models (SCAIL-2, MiniMax H3) on rented RunPod GPUs fast and cheap, published as a public AI Angel template that earns creator credits

## Commands

```bash
scripts/dev     # run the entry point (uv run python -m aiangelcomfypod)
scripts/test    # uv run pytest -q
scripts/lint    # uv run ruff check . && uv run ruff format --check .
```

## Architecture invariants

1. All Thai text crosses subprocess/API boundaries via UTF-8 file, never argv or stdin (cp874 rule).
2. Paid API calls emit an audit sidecar JSON (endpoint, request_id, cost_estimate) before returning.
3. Credentials are read from os.environ — never hardcoded, never printed in full.
4. Entry point uses argparse + `sys.stdout.reconfigure(encoding="utf-8")`.

## Boundaries

**always:** uv for all Python execution; ruff for lint+format; pytest for tests.
**ask-first:** adding a new external dependency; changing the public CLI interface.
**never:** print credential values; commit .env files; use inline Thai in subprocess argv.

## Mistakes log

| Date | Symptom | Root cause | Fix |
|------|---------|-----------|-----|
| — | — | — | — |

## Pointers

- Thai I/O pattern, audit-sidecar contract: see gold example `src/aiangelcomfypod/example.py`
- Visual assets: /visual-assist
- Slide decks: /slide-assist
