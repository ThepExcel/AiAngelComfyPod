# /// script
# dependencies = ["requests", "websocket-client"]
# ///
"""Run a Python snippet on a live AI Angel pod through its JupyterLab kernel and print the output.

The Jupyter token is read from the pod's dashboard (/api/state) and never printed.

  uv run scripts/pod_exec.py <pod-id> <file.py> [--timeout 900]
"""

import argparse
import json
import sys
import uuid

import requests
import websocket


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("pod")
    ap.add_argument("file")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    code = open(a.file, encoding="utf-8").read()

    state = requests.get(f"https://{a.pod}-8189.proxy.runpod.net/api/state", timeout=60).json()
    token = next(s["secret"] for s in state["services"] if s["key"] == "jupyter")
    base = f"https://{a.pod}-8888.proxy.runpod.net"
    h = {"Authorization": f"token {token}"}
    kernel = requests.post(f"{base}/api/kernels", headers=h, json={"name": "python3"}, timeout=60)
    kernel.raise_for_status()
    kid = kernel.json()["id"]
    try:
        ws = websocket.create_connection(
            f"wss://{a.pod}-8888.proxy.runpod.net/api/kernels/{kid}/channels",
            header=[f"Authorization: token {token}"],
            timeout=a.timeout,
        )
        msg_id = uuid.uuid4().hex
        ws.send(
            json.dumps(
                {
                    "header": {
                        "msg_id": msg_id,
                        "username": "aiangel",
                        "session": uuid.uuid4().hex,
                        "msg_type": "execute_request",
                        "version": "5.3",
                    },
                    "parent_header": {},
                    "metadata": {},
                    "content": {
                        "code": code,
                        "silent": False,
                        "store_history": False,
                        "user_expressions": {},
                        "allow_stdin": False,
                    },
                    "channel": "shell",
                }
            )
        )
        while True:
            m = json.loads(ws.recv())
            if m.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            t, c = m["msg_type"], m["content"]
            if t == "stream":
                print(c["text"], end="", flush=True)
            elif t == "error":
                print("\n".join(c["traceback"]))
            elif t == "status" and c["execution_state"] == "idle":
                break
        ws.close()
    finally:
        requests.delete(f"{base}/api/kernels/{kid}", headers=h, timeout=60)


if __name__ == "__main__":
    main()
