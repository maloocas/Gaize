#!/usr/bin/env python3
"""Local-only macOS control bridge.

Run with the system Python (which has PyObjC):
    python3 native/bridge.py

The browser sends pointer moves, switch clicks and text to localhost. The server
never binds to a network interface and rejects non-local clients.

Two things here are load-bearing beyond plumbing:

  * Arming. Control starts DISARMED. A page served from this machine's own dev
    server arms automatically; any other origin - including the public deployed
    site - must present the pairing code printed in this terminal. Without that,
    any page the user happens to visit could move the mouse and type on a
    machine that has the bridge running.

  * The panic key. Pressing Escape three times quickly disarms everything. A
    dwell-clicking pointer driven by a jittery signal is genuinely dangerous for
    someone who cannot reach the keyboard, so the caregiver needs a hardware-
    speed way out that does not depend on the browser still being responsive.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import random
import subprocess
import sys
import threading
import time

import Quartz
import ApplicationServices as AS
from AppKit import (NSPasteboard, NSPasteboardTypeString,
                    NSRunningApplication, NSWorkspace)

HOST, PORT = "127.0.0.1", 8766
KEYBOARD = Path(__file__).with_name("keyboard.py")

LOCAL_ORIGINS = ("http://localhost:8000", "http://127.0.0.1:8000")
REMOTE_ORIGINS = ("https://aac-accelerator.vercel.app",)
ALLOWED_ORIGINS = LOCAL_ORIGINS + REMOTE_ORIGINS

PAIRING_CODE = f"{random.randint(0, 999999):06d}"

_state_lock = threading.Lock()
_armed = False
_last_panic_reason = None

# Recently frontmost applications, most recent first. The control UI runs in a
# browser, so by the time the user presses "send" the browser owns focus and
# naive typing would land in our own page. Remembering where they came from is
# what makes typing into Mail, Slack or anywhere else actually work.
_app_history: list[dict] = []
_history_lock = threading.Lock()
_keyboard_lock = threading.Lock()
_keyboard_process = None


def is_armed() -> bool:
    with _state_lock:
        return _armed


def set_armed(value: bool, reason: str | None = None) -> None:
    global _armed, _last_panic_reason
    with _state_lock:
        _armed = value
        if not value:
            _last_panic_reason = reason
    print(f"[bridge] control {'ARMED' if value else 'DISARMED'}"
          + (f" ({reason})" if reason else ""), flush=True)


def frontmost_app() -> dict | None:
    """Frontmost application, queried from the window server.

    NSWorkspace.frontmostApplication() is driven by Cocoa notifications and
    needs a running run loop to stay current. This bridge serves HTTP on threads
    that have no run loop, where that API silently returns whatever it cached at
    launch - it reported one stale app forever. Asking the window server for the
    front-most on-screen window instead is a direct query with no such
    dependency.
    """
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    for win in windows:
        if win.get("kCGWindowLayer", 1) != 0:
            continue                      # skip menu bar, docks, overlays
        pid = win.get("kCGWindowOwnerPID")
        name = win.get("kCGWindowOwnerName")
        if not pid or not name:
            continue
        return {"pid": int(pid), "name": str(name),
                "window": str(win.get("kCGWindowName") or "")}
    return None


def _track_frontmost():
    """Keep a short history of frontmost apps."""
    while True:
        try:
            entry = frontmost_app()
            if entry is not None:
                with _history_lock:
                    if not _app_history or _app_history[0]["pid"] != entry["pid"]:
                        _app_history.insert(0, entry)
                        # Drop any older record of the same app, keep it short.
                        seen, trimmed = set(), []
                        for item in _app_history:
                            if item["pid"] in seen:
                                continue
                            seen.add(item["pid"])
                            trimmed.append(item)
                        _app_history[:] = trimmed[:6]
        except Exception:
            pass
        time.sleep(0.3)


def previous_app() -> dict | None:
    """The most recent app that is not the one currently in front."""
    with _history_lock:
        if len(_app_history) < 2:
            return None
        return _app_history[1]


def activate(pid: int, timeout: float = 1.2) -> bool:
    """Bring an app forward and wait until it really is frontmost."""
    running = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if running is None:
        return False
    running.activateWithOptions_(1 << 1)   # NSApplicationActivateIgnoringOtherApps
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        front = frontmost_app()
        if front is not None and front["pid"] == pid:
            return True
        time.sleep(0.05)
    return False


# ----------------------------------------------------------------- control


def screen_size():
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return float(bounds.size.width), float(bounds.size.height)


def move(x, y):
    width, height = screen_size()
    point = Quartz.CGPointMake(max(0, min(1, x)) * width, max(0, min(1, y)) * height)
    event = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _focused_editable() -> dict | None:
    """Describe the editable control that currently owns keyboard focus."""
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None
    # Blink-clicking an on-screen key must not interpret the keyboard's own
    # preview entry as a new target and recursively replace the keyboard.
    with _keyboard_lock:
        if (_keyboard_process is not None and _keyboard_process.poll() is None
                and int(app.processIdentifier()) == _keyboard_process.pid):
            return None
    ax_app = AS.AXUIElementCreateApplication(app.processIdentifier())
    focused = _attr(ax_app, "AXFocusedUIElement")
    if focused is None:
        return None
    role = _attr(focused, "AXRole")
    subrole = _attr(focused, "AXSubrole")
    result = AS.AXUIElementIsAttributeSettable(focused, "AXValue", None)
    settable = bool(result[1]) if isinstance(result, tuple) else bool(result)
    roles = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
    if not (role in roles or subrole in roles or settable):
        return None
    return {"pid": int(app.processIdentifier()), "app": app.localizedName(),
            "role": str(subrole or role or "editable")}


def _show_keyboard(target: dict) -> None:
    """Open one floating keyboard, bound to the app containing the field."""
    global _keyboard_process
    with _keyboard_lock:
        if _keyboard_process is not None and _keyboard_process.poll() is None:
            _keyboard_process.terminate()
        _keyboard_process = subprocess.Popen(
            [sys.executable, str(KEYBOARD), "--pid", str(target["pid"]),
             "--app", str(target["app"])],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def click(show_keyboard: bool = True):
    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(
            None, kind, point, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    # Focus changes land just after mouse-up. Inspect the real target and open
    # the keyboard only for an editable control—not merely any blink click.
    time.sleep(0.12)
    target = _focused_editable()
    if target and show_keyboard:
        _show_keyboard(target)
    return target


def insert_text(pid: int, text: str) -> bool:
    """Paste into the target app and restore the user's clipboard afterward."""
    if not activate(pid):
        return False
    time.sleep(.2)
    pasteboard=NSPasteboard.generalPasteboard()
    previous=pasteboard.stringForType_(NSPasteboardTypeString)
    pasteboard.clearContents()
    pasteboard.setString_forType_(text,NSPasteboardTypeString)
    source=Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for is_down in (True,False):
        event=Quartz.CGEventCreateKeyboardEvent(source,9,is_down)  # V
        Quartz.CGEventSetFlags(event,Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,event)
    time.sleep(.35)
    pasteboard.clearContents()
    if previous is not None:
        pasteboard.setString_forType_(previous,NSPasteboardTypeString)
    return True


def type_text(text):
    # Unicode events avoid keyboard-layout assumptions. Small chunks prevent
    # applications from dropping characters on long AAC phrases.
    for start in range(0, len(text), 20):
        chunk = text[start:start + 20]
        down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(down, len(chunk), chunk)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


# ------------------------------------------------------------- AX context


def _attr(element, name):
    if element is None:
        return None
    err, value = AS.AXUIElementCopyAttributeValue(element, name, None)
    return value if err == 0 else None


def read_context(of_previous: bool = False) -> dict:
    """What is the user actually looking at right now?

    Deliberately a handful of targeted queries rather than a tree walk. Measured
    on this machine: a focused-element query costs ~50ms, while walking a large
    Electron window's accessibility tree did not finish in two minutes. Apps also
    differ enormously in what they expose - Chrome surfaces plenty, while
    Finder, VS Code and Spotify surfaced nothing at all - so every field here is
    optional and the caller must cope with an empty result.
    """
    target = previous_app() if of_previous else frontmost_app()
    if target is None:
        return {"app": None}
    ax = AS.AXUIElementCreateApplication(target["pid"])
    window = _attr(ax, "AXFocusedWindow")
    focused = _attr(ax, "AXFocusedUIElement")

    value = _attr(focused, "AXValue")
    selected = _attr(focused, "AXSelectedText")
    return {
        "app": target["name"],
        "window": _attr(window, "AXTitle"),
        "role": _attr(focused, "AXRole"),
        "text": value if isinstance(value, str) else None,
        "selection": selected if isinstance(selected, str) else None,
        "editable": bool(AS.AXUIElementIsAttributeSettable(focused, "AXValue", None)[1])
        if focused else False,
    }


# ------------------------------------------------------------- panic key


def _panic_tap():
    """Escape pressed three times within two seconds disarms control."""
    presses = []
    ESCAPE = 53

    def callback(proxy, event_type, event, refcon):
        if event_type == Quartz.kCGEventKeyDown:
            code = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode)
            if code == ESCAPE:
                now = time.monotonic()
                presses.append(now)
                del presses[:-3]
                if len(presses) == 3 and now - presses[0] <= 2.0:
                    presses.clear()
                    set_armed(False, "panic key (Escape x3)")
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown), callback, None)
    if tap is None:
        print("[bridge] WARNING: could not install panic key listener "
              "(needs Input Monitoring permission). Escape x3 will not work.", flush=True)
        return
    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
    Quartz.CGEventTapEnable(tap, True)
    Quartz.CFRunLoopRun()


# ---------------------------------------------------------------- server

CONTROL_ROUTES = {"move", "click", "type"}


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204); self._headers(); self.end_headers()

    def do_POST(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_error(403); return
        origin = self.headers.get("Origin", "")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_error(403); return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            body = json.loads(self.rfile.read(length) or b"{}")
            route = self.path.strip("/")
            payload = {"ok": True, "armed": is_armed(), "screen": screen_size()}

            if route in CONTROL_ROUTES and not is_armed():
                payload = {"ok": False, "armed": False, "error": "disarmed",
                           "hint": "POST /arm with the pairing code shown in the bridge terminal"}
                self._respond(403, payload); return

            if route == "move":
                move(float(body["x"]), float(body["y"]))
            elif route == "click":
                target = click()
                payload["editable"] = bool(target)
                payload["keyboard_opened"] = bool(target)
                payload["target"] = target
            elif route == "type":
                target = body.get("target")
                if target == "previous":
                    prev = previous_app()
                    if prev is None:
                        self._respond(409, {"ok": False, "armed": True,
                                            "error": "no previous app to return to"}); return
                    if not activate(prev["pid"]):
                        self._respond(409, {"ok": False, "armed": True,
                                            "error": f"could not focus {prev['name']}"}); return
                    payload["typed_into"] = prev["name"]
                    time.sleep(0.25)   # let the app settle its first responder
                type_text(str(body.get("text", "")))
            elif route == "context":
                payload["context"] = read_context(
                    of_previous=bool(body.get("previous")))
                payload["previous_app"] = previous_app()
            elif route == "arm":
                # A page served by this machine's own dev server is already
                # local; anything else has to prove local presence with the code.
                if origin in LOCAL_ORIGINS or str(body.get("code", "")) == PAIRING_CODE:
                    set_armed(True, f"origin {origin or 'unknown'}")
                    payload["armed"] = True
                else:
                    self._respond(403, {"ok": False, "armed": False,
                                        "error": "bad pairing code"}); return
            elif route == "panic":
                set_armed(False, "requested by client")
                payload["armed"] = False
            elif route == "status":
                payload["needs_code"] = origin in REMOTE_ORIGINS
                payload["last_panic"] = _last_panic_reason
                with _history_lock:
                    payload["app_history"] = [a["name"] for a in _app_history]
                payload["previous_app"] = previous_app()
            else:
                raise ValueError("unknown route")

            self._respond(200, payload)
        except Exception as exc:
            self._respond(400, {"ok": False, "error": str(exc)})

    def _respond(self, status, payload):
        self.send_response(status); self._headers(); self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def _headers(self):
        self.send_header("Content-Type", "application/json")
        origin = self.headers.get("Origin", LOCAL_ORIGINS[0])
        self.send_header("Access-Control-Allow-Origin",
                         origin if origin in ALLOWED_ORIGINS else LOCAL_ORIGINS[0])
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        # A secure Vercel page calling a loopback service is a Private Network
        # Access request. Without this acknowledgement Chromium blocks the POST
        # during preflight, so the pairing code never reaches /arm.
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    trusted = AS.AXIsProcessTrusted()
    print(f"bridge: http://{HOST}:{PORT}   Accessibility trusted: {trusted}", flush=True)
    if not trusted:
        print("Grant Accessibility permission to your terminal in System Settings, "
              "then restart this script.", flush=True)
    print(f"pairing code for {REMOTE_ORIGINS[0]}: {PAIRING_CODE}", flush=True)
    print("control starts DISARMED. Panic: press Escape three times to disarm.", flush=True)
    threading.Thread(target=_panic_tap, daemon=True).start()
    threading.Thread(target=_track_frontmost, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
