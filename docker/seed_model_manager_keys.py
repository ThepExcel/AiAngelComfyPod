"""Put CIVITAI_TOKEN / HF_TOKEN from the pod environment into ComfyUI-Model-Manager's key store,
so its Download tab works without typing the keys in again. Keys already saved in the UI are
kept unless the environment provides a new value. Values are never printed."""

import os
import pickle
import sys
from pathlib import Path

store = Path(sys.argv[1])
env = {"civitai": os.environ.get("CIVITAI_TOKEN"), "huggingface": os.environ.get("HF_TOKEN")}
env = {k: v for k, v in env.items() if v}
if env and store.parent.is_dir():
    data = {}
    if store.exists():
        with open(store, "rb") as f:
            data = pickle.load(f)
    data.update(env)
    with open(store, "wb") as f:
        pickle.dump(data, f)
    try:
        store.chmod(0o600)
    except OSError:  # RunPod Global volumes refuse chmod; the keys are written anyway
        pass
    print(f"[aiangel] Model Manager keys set from env: {', '.join(sorted(env))}")
