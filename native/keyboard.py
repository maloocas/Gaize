#!/usr/bin/env python3
"""Large floating keyboard automatically opened after clicking a text field."""
import argparse
import time
import tkinter as tk

import Quartz
import ApplicationServices as AS
from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication


def post_text(text: str) -> None:
    source=Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for start in range(0, len(text), 20):
        chunk = text[start:start + 20]
        down = Quartz.CGEventCreateKeyboardEvent(source, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(down, len(chunk), chunk)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        up=Quartz.CGEventCreateKeyboardEvent(source,0,False)
        Quartz.CGEventKeyboardSetUnicodeString(up,len(chunk),chunk)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap,up)


def set_focused_text(pid: int, text: str) -> bool:
    """Insert through Accessibility; unlike key events this survives refocus."""
    app=AS.AXUIElementCreateApplication(pid)
    error,focused=AS.AXUIElementCopyAttributeValue(app,"AXFocusedUIElement",None)
    if error or focused is None: return False
    # AXSelectedText replaces the current selection or inserts at the caret.
    return AS.AXUIElementSetAttributeValue(focused,"AXSelectedText",text)==0


class GazeKeyboard:
    def __init__(self, pid: int, app_name: str):
        self.pid = pid
        self.root = tk.Tk()
        self.root.title(f"OpenGaze Keyboard — {app_name}")
        self.root.configure(bg="#162536")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", .94)
        width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        height = min(570, int(screen_height * 0.5))
        self.root.geometry(f"{width}x{height}+0+{screen_height-height}")
        self.text = tk.StringVar()
        tk.Label(self.root, text=f"◉  POINT + BLINK TO TYPE INTO {app_name}", bg="#162536",
                 fg="#bfeaff", font=("Helvetica", 13, "bold")).pack(pady=(12, 0))
        entry = tk.Entry(self.root, textvariable=self.text,
                         font=("Helvetica", 30), bg="#eaf7ff", fg="#10283a",
                         relief="flat", highlightthickness=2, highlightbackground="#ffffff")
        entry.pack(fill="x", padx=24, pady=12, ipady=12)
        entry.focus_set()
        for row in ("QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"):
            frame = tk.Frame(self.root, bg="#162536")
            frame.pack(fill="x", padx=28, pady=4)
            for letter in row:
                self._button(frame, letter, lambda v=letter.lower(): self.insert(v)).pack(
                    side="left", expand=True, fill="both", padx=4)
        actions = tk.Frame(self.root, bg="#162536")
        actions.pack(fill="both", expand=True, padx=28, pady=9)
        for label, command in (("⌫ DELETE", self.delete),
                               ("SPACE", lambda: self.insert(" ")),
                               ("CANCEL", self.root.destroy)):
            self._button(actions, label, command, small=True).pack(
                side="left", expand=True, fill="both", padx=4)
        self._button(actions, "TYPE INTO FIELD ↗", self.submit,
                     small=True, accent=True).pack(side="left", expand=True, fill="both", padx=4)
        self.root.bind("<Return>", lambda _event: self.submit())
        self.root.bind("<Escape>", lambda _event: self.root.destroy())

    @staticmethod
    def _button(parent, label, command, small=False, accent=False):
        return tk.Button(parent, text=label, command=command,
                         font=("Helvetica", 15 if small else 22, "bold"),
                         bg="#39aee8" if accent else "#b8d9ec",
                         fg="#082033", activebackground="#ffffff", activeforeground="#07131c",
                         relief="flat", bd=0, padx=10, pady=13,
                         highlightthickness=2, highlightbackground="#3b4652")

    def insert(self, value: str) -> None:
        self.text.set(self.text.get() + value)

    def delete(self) -> None:
        self.text.set(self.text.get()[:-1])

    def submit(self) -> None:
        text = self.text.get()
        self.root.withdraw()
        target = NSRunningApplication.runningApplicationWithProcessIdentifier_(self.pid)
        if target is not None:
            target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            time.sleep(0.35)
            if not set_focused_text(self.pid,text): post_text(text)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--app", default="application")
    args = parser.parse_args()
    GazeKeyboard(args.pid, args.app).run()
