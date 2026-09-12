#!/usr/bin/env python3
"""Start the local web app and native bridge, then open the control page."""

from __future__ import annotations

import argparse
import atexit
from pathlib import Path
import socket
import subprocess
import sys
import time
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PORT = 8766
WEB_PORT = 8000
children: list[subprocess.Popen] = []


def listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.15)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def stop_children() -> None:
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
    for child in reversed(children):
        if child.poll() is None:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()


def wait_for(port: int, label: str, child: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if listening(port):
            return
        if child is not None and child.poll() is not None:
            raise SystemExit(f"{label} stopped before it was ready (exit {child.returncode}).")
        time.sleep(0.1)
    raise SystemExit(f"Timed out waiting for {label} on port {port}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch OpenGaze local system control")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser window")
    args = parser.parse_args()
    atexit.register(stop_children)

    if listening(BRIDGE_PORT):
        print(f"[launcher] using bridge already running on 127.0.0.1:{BRIDGE_PORT}", flush=True)
    else:
        bridge = subprocess.Popen([sys.executable, str(ROOT / "native" / "bridge.py")], cwd=ROOT)
        children.append(bridge)
        wait_for(BRIDGE_PORT, "native bridge", bridge)

    if listening(WEB_PORT):
        print(f"[launcher] using web app already running on 127.0.0.1:{WEB_PORT}", flush=True)
    else:
        web = subprocess.Popen([str(ROOT / "run.sh")], cwd=ROOT)
        children.append(web)
        wait_for(WEB_PORT, "web app", web)

    url = f"http://localhost:{WEB_PORT}"
    print(f"[launcher] ready: {url}", flush=True)
    print("[launcher] press Ctrl+C to stop the processes started here", flush=True)
    if not args.no_open:
        webbrowser.open(url)

    try:
        while True:
            for child in children:
                if child.poll() is not None:
                    raise SystemExit(f"A required process stopped (exit {child.returncode}).")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
