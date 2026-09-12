#!/usr/bin/env python3
"""Install native dependencies once, then run the background Mac controller."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".native-venv"
PYTHON = VENV / "bin" / "python"


def main() -> None:
    if not PYTHON.exists():
        print("[OpenGaze] preparing the native controller (first run only)…", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", "--system-site-packages", str(VENV)])
    subprocess.check_call([str(PYTHON), "-m", "pip", "install", "-q", "-r",
                           str(ROOT / "requirements-native.txt")])
    launcher = ROOT / "OpenGaze.app" / "Contents" / "MacOS" / "OpenGaze"
    subprocess.check_call(["swiftc", str(ROOT / "native" / "launcher.swift"), "-o", str(launcher)])
    subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", str(ROOT / "OpenGaze.app")])
    try:
        subprocess.check_call(["open", "-n", str(ROOT / "OpenGaze.app")], cwd=ROOT)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
