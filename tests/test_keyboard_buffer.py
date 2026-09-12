"""Guards the on-screen keyboard's text buffer against being silently wiped.

The panel is deliberately non-activating so the application being typed into
keeps keyboard focus. The consequence is that pressing one of our own keys
leaves that other application frontmost, so a focus probe reports it and cannot
distinguish "the user pressed a key" from "the user clicked a new text field".

When that distinction was missing, every blink re-ran show_keyboard(), which
reset the buffer. Each new character appeared to replace the previous one, and
INSERT read an already-emptied buffer so nothing was ever pasted.

Source-level checks: controller.py imports Vision and cv2, which are not present
in the test environment.
"""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def _body(name: str) -> str:
    start = SOURCE.index(f"def {name}")
    rest = SOURCE[start:]
    cut = rest.find("\n    def ", 1)
    return rest[:cut] if cut != -1 else rest


def test_key_presses_are_told_apart_from_clicking_a_new_field():
    assert "def pointer_over_keyboard" in SOURCE
    body = _body("commitBlink_")
    assert "pointer_over_keyboard()" in body
    assert "return" in body.split("on_keyboard")[-1], (
        "a click on our own panel must not fall through to show_keyboard")


def test_pointer_containment_compares_like_with_like():
    body = _body("pointer_over_keyboard")
    # NSWindow.frame() is Cocoa, so the point must be Cocoa too - using the
    # Quartz cursor here would mirror the test vertically.
    assert "NSEvent.mouseLocation()" in body
    assert "frame()" in body
    assert "quartz_cursor" not in body


def test_show_keyboard_does_not_unconditionally_clear_the_buffer():
    body = _body("show_keyboard")
    assert "self.keyboard_text=\"\"" in body, "it must still reset sometimes"
    reset_line = body.index("self.keyboard_text=\"\"")
    guard = body[:reset_line]
    assert "fresh" in guard, "the reset has to sit behind a freshness guard"
    assert "keyboard_visible()" in guard
    assert "!=" in guard and "pid" in guard, (
        "a different target application should start a new message")


def test_keys_accept_the_first_click_while_our_app_is_inactive():
    # Without this the click that would normally just activate the window is
    # swallowed, eating the key press.
    assert "def acceptsFirstMouse_" in SOURCE
    assert "return True" in _body("acceptsFirstMouse_")
