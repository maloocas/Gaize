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
STARTUP_TIMEOUT = 240
LAUNCH_GRACE = 10


def controller_running() -> bool:
    """True while the controller process the launcher exec'd into is alive."""
    return subprocess.run(["pgrep", "-f", "native/controller.py"],
                          capture_output=True).returncode == 0


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
    launcher.parent.mkdir(exist_ok=True)  # git does not keep the empty folder
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
    # controller.py writes the PID file last, once mediapipe, OpenCV and the
    # camera are all up; a cold run also builds the matplotlib font cache. That
    # is comfortably over a minute, so waiting a fixed three seconds reported
    # every healthy first launch as a failure. Wait on the process instead, and
    # only give up once it is actually gone.
    deadline = time.monotonic() + STARTUP_TIMEOUT
    launched_by = time.monotonic() + LAUNCH_GRACE
    said_waiting = False
    while time.monotonic() < deadline:
        if PID_FILE.exists():
            try:
                pid=int(PID_FILE.read_text().strip())
                os.kill(pid,0)
                print(f"OpenGaze is running (PID {pid}). Look for ‘OpenGaze’ in the menu bar.")
                print("Wink left/right to click, hard blink to select, press Escape 3 times to quit.")
                return
            except (ValueError,ProcessLookupError,PermissionError):
                pass
        # `open -n` returns immediately, so allow a grace period before a
        # missing process counts as a launch that died rather than one that
        # has not appeared yet.
        if time.monotonic() > launched_by and not controller_running():
            break
        if not said_waiting and time.monotonic() > launched_by:
            print("[OpenGaze] still starting — loading the gaze model…", flush=True)
            said_waiting = True
        time.sleep(.2)
    print("OpenGaze did not stay running. Startup log:",file=sys.stderr)
    if LOG_FILE.exists(): print(LOG_FILE.read_text(errors="replace")[-5000:],file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
