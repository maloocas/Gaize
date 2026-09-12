#!/usr/bin/env python3
"""Install native dependencies once, then run the background Mac controller."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".native-venv"
PYTHON = VENV / "bin" / "python"
PID_FILE = Path("/private/tmp/opengaze.pid")
LOG_FILE = Path("/private/tmp/opengaze.log")


def main() -> None:
    build_env = os.environ.copy()
    build_env.update({
        "CLANG_MODULE_CACHE_PATH": "/private/tmp/opengaze-clang-cache",
        "PIP_CACHE_DIR": "/private/tmp/opengaze-pip-cache",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    })
    if not PYTHON.exists():
        print("[OpenGaze] preparing the native controller (first run only)…", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", "--system-site-packages", str(VENV)])
    subprocess.check_call([str(PYTHON), "-m", "pip", "install", "-q", "-r",
                           str(ROOT / "requirements-native.txt")], env=build_env)
    launcher = ROOT / "OpenGaze.app" / "Contents" / "MacOS" / "OpenGaze"
    subprocess.check_call(["swiftc", str(ROOT / "native" / "launcher.swift"), "-o", str(launcher)], env=build_env)
    subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", str(ROOT / "OpenGaze.app")])
    PID_FILE.unlink(missing_ok=True)
    LOG_FILE.write_text("")
    try:
        subprocess.check_call(["open", "-n", str(ROOT / "OpenGaze.app")], cwd=ROOT)
    except KeyboardInterrupt:
        return
    except subprocess.CalledProcessError:
        print("macOS could not launch OpenGaze.app. Startup log:",file=sys.stderr)
        if LOG_FILE.exists(): print(LOG_FILE.read_text(errors="replace")[-5000:],file=sys.stderr)
        raise SystemExit(1) from None
    for _ in range(30):
        if PID_FILE.exists():
            try:
                pid=int(PID_FILE.read_text().strip())
                os.kill(pid,0)
                print(f"OpenGaze is running (PID {pid}). Look for ‘Blink Click’ in the menu bar.")
                print("Move with the mouse, blink to click, and press Escape to quit.")
                return
            except (ValueError,ProcessLookupError,PermissionError):
                pass
        time.sleep(.1)
    print("OpenGaze did not stay running. Startup log:",file=sys.stderr)
    if LOG_FILE.exists(): print(LOG_FILE.read_text(errors="replace")[-5000:],file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
