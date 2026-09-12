#!/usr/bin/env python3
"""Local-only macOS control bridge for OpenGaze Assist.

Run with the system Python (which has PyObjC on the demo Mac):
    python3 native/bridge.py

The browser sends normalized gaze positions, blink clicks and keyboard text to
localhost. The server never binds to the network and rejects non-local clients.
macOS will ask for Accessibility permission the first time.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

import Quartz
import ApplicationServices as AS

HOST, PORT = "127.0.0.1", 8765


def screen_size():
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return float(bounds.size.width), float(bounds.size.height)


def move(x, y):
    width, height = screen_size()
    point = Quartz.CGPointMake(max(0, min(1, x)) * width, max(0, min(1, y)) * height)
    event = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def click():
    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    for kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(None, kind, point, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


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


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204); self._headers(); self.end_headers()

    def do_POST(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_error(403); return
        origin = self.headers.get("Origin", "")
        if origin and origin not in ("http://localhost:8000", "http://127.0.0.1:8000", "https://aac-accelerator.vercel.app"):
            self.send_error(403); return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            body = json.loads(self.rfile.read(length) or b"{}")
            route = self.path.strip("/")
            if route == "move": move(float(body["x"]), float(body["y"]))
            elif route == "click": click()
            elif route == "type": type_text(str(body.get("text", "")))
            elif route != "status": raise ValueError("unknown route")
            self.send_response(200); self._headers(); self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "screen": screen_size()}).encode())
        except Exception as exc:
            self.send_response(400); self._headers(); self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())

    def _headers(self):
        self.send_header("Content-Type", "application/json")
        origin = self.headers.get("Origin", "http://localhost:8000")
        allowed = ("http://localhost:8000", "http://127.0.0.1:8000", "https://aac-accelerator.vercel.app")
        self.send_header("Access-Control-Allow-Origin", origin if origin in allowed else allowed[0])
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    trusted = AS.AXIsProcessTrusted()
    print(f"OpenGaze bridge: http://{HOST}:{PORT}  Accessibility trusted: {trusted}")
    if not trusted:
        print("Grant Accessibility permission to Terminal in System Settings, then restart this script.")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
