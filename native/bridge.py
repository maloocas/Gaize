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
import os
import random
import threading
import time

import Quartz
import ApplicationServices as AS
from AppKit import (NSPasteboard, NSPasteboardTypeString,
                    NSRunningApplication, NSWorkspace)

HOST, PORT = "127.0.0.1", 8766

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
        print(f"[OpenGaze] cannot activate missing pid {pid}",flush=True)
        return False
    # Request all windows as well as ignoring the current app. A full-screen
    # non-activating keyboard panel can make CGWindow ordering disagree with
    # the actual key app, so window order must not veto key delivery.
    requested=bool(running.activateWithOptions_((1 << 0) | (1 << 1)))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if running.isActive():
            return True
        front = frontmost_app()
        if front is not None and front["pid"] == pid:
            return True
        time.sleep(0.05)
    # Activation is asynchronous and NSRunningApplication/CGWindow can lag or
    # disagree while our overlay is visible. If macOS accepted the request and
    # the process still exists, continue with the click instead of silently
    # dropping the user's text.
    alive=not running.isTerminated()
    print(f"[OpenGaze] activation confirmation timed out for pid {pid}; "
          f"requested={requested} alive={alive}; continuing={requested and alive}",flush=True)
    return requested and alive


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


def _app_at_point(point) -> dict | None:
    """Return the normal application window physically beneath a Quartz point."""
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    for window in windows:
        if window.get("kCGWindowLayer", 1) != 0:
            continue
        bounds = window.get("kCGWindowBounds") or {}
        x, y = float(bounds.get("X", 0)), float(bounds.get("Y", 0))
        width, height = float(bounds.get("Width", 0)), float(bounds.get("Height", 0))
        if x <= point.x <= x + width and y <= point.y <= y + height:
            pid = int(window.get("kCGWindowOwnerPID") or 0)
            if pid:
                return {"pid": pid,
                        "name": str(window.get("kCGWindowOwnerName") or "Application")}
    return None


def _focused_editable(target_app: dict | None = None) -> dict | None:
    """Describe the editable control that currently owns keyboard focus."""
    # NSWorkspace.frontmostApplication can lag behind a synthetic click and
    # return Terminal (the app that launched OpenGaze). Prefer the window that
    # was physically beneath the pointer when mouse-down was posted.
    target = target_app or frontmost_app()
    if target is None:
        return None
    # Blink-clicking an on-screen key must not interpret the keyboard's own
    # preview entry as a new target and recursively reopen the keyboard. The
    # panel now lives in this process rather than a spawned one, so the check
    # is simply whether focus stayed with us.
    pid = int(target["pid"])
    if pid == os.getpid():
        return None
    ax_app = AS.AXUIElementCreateApplication(pid)
    roles = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
    # Messages often focuses an internal child of its AXTextField rather than
    # the field itself. Walk upward until the real editable ancestor appears.
    element = _attr(ax_app, "AXFocusedUIElement")
    for _ in range(6):
        if element is None: break
        role = _attr(element, "AXRole")
        subrole = _attr(element, "AXSubrole")
        try:
            result = AS.AXUIElementIsAttributeSettable(element, "AXValue", None)
            settable = bool(result[1]) if isinstance(result, tuple) else bool(result)
        except Exception:
            settable = False
        if role in roles or subrole in roles or settable:
            return {"pid": pid, "app": str(target.get("name") or "Application"),
                    "role": str(subrole or role or "editable")}
        element = _attr(element, "AXParent")
    return None


def post_click(point, down, up, button):
    """One real-looking click. A down and up posted in the same instant with
    no click count is dropped by Chromium/Electron apps and some native
    controls, so mark it as a single click and hold the button briefly."""
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    under = _app_at_point(point)
    print(f"[OpenGaze] posting button {button} at ({point.x:.0f},{point.y:.0f}) "
          f"onto {under.get('name', under.get('pid')) if under else 'no window'}", flush=True)
    for kind in (down, up):
        event = Quartz.CGEventCreateMouseEvent(source, kind, point, button)
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventClickState, 1)
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGMouseEventButtonNumber, button)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        if kind == down:
            time.sleep(0.04)


def click(show_keyboard: bool = False):
    """Click wherever the pointer is, and report an editable target if any.

    Showing a keyboard is deliberately not this function's job. Displaying UI
    means owning a GUI event loop, which an HTTP handler thread does not have -
    the previous version worked around that by spawning a separate Tk process,
    which is what produced the second, uglier keyboard. The native controller
    owns its panel and calls this purely to find out what got focused.
    """
    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    target_app = _app_at_point(point)
    post_click(point, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp,
               Quartz.kCGMouseButtonLeft)
    # Focus changes land just after mouse-up, so look only after that settles.
    time.sleep(0.12)
    target = _focused_editable(target_app)
    if target is not None:
        target.update({"x":float(point.x),"y":float(point.y),"width":0.0,"height":0.0})
    return target


def insert_text(pid: int, text: str) -> bool:
    """Paste composed text reliably and leave that same text on the clipboard.

    AXSelectedText can return success while Messages silently ignores the write.
    Unicode events are also inconsistent in web and rich-text editors. Command-V
    is the compatible path; keeping the composed text on the clipboard avoids
    the old race where a delayed paste received prematurely restored contents.
    """
    if not activate(pid):
        return False
    time.sleep(.2)
    pasteboard=NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    if not pasteboard.setString_forType_(text,NSPasteboardTypeString):
        return False
    source=Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for is_down in (True,False):
        event=Quartz.CGEventCreateKeyboardEvent(source,9,is_down)  # V
        Quartz.CGEventSetFlags(event,Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,event)
    time.sleep(.15)
    return True


def click_target_and_type(target: dict, text: str) -> bool:
    """Restore focus by clicking the original text box, then type directly.

    This is the reliable path for Messages: its composer frequently loses AX
    focus while our non-activating keyboard is visible and can ignore paste.
    """
    pid=int(target["pid"])
    if not activate(pid): return False
    x=float(target["x"])+float(target.get("width",0))/2
    y=float(target["y"])+float(target.get("height",0))/2
    point=Quartz.CGPointMake(x,y)
    post_click(point,Quartz.kCGEventLeftMouseDown,Quartz.kCGEventLeftMouseUp,
               Quartz.kCGMouseButtonLeft)
    time.sleep(.12)
    type_text(text)
    return True


RETURN_KEYCODE = 36


def press_return(pid: int) -> bool:
    """Press Return in the target application.

    Sending a message is the whole point of a communication device, and in most
    apps that is Return rather than a button somewhere on screen. Posted as a
    real key event so the app treats it exactly like a typed Return.
    """
    if not activate(pid):
        return False
    time.sleep(.15)
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for is_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, RETURN_KEYCODE, is_down)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
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
