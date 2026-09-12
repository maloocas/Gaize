"""Guards against mixing macOS's two pointer coordinate systems.

NSEvent.mouseLocation() is Cocoa (origin bottom-left, y up).
CGEventCreateMouseEvent interprets its point as Quartz (origin top-left, y down).

Handing a Cocoa point to a CGEvent mirrors it vertically. On a 982pt display a
click near the top landed 682pt away near the bottom, which dragged whatever was
grabbed to the wrong end of the screen and left the drawn reticle and the real
cursor in two different places. These are source-level checks so they run
without a camera or a window server.
"""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def _body(name: str, end: str = "\n    def ") -> str:
    start = SOURCE.index(f"def {name}")
    rest = SOURCE[start:]
    cut = rest.find(end, 1)
    return rest[:cut] if cut != -1 else rest


def test_quartz_cursor_helper_exists():
    assert "def quartz_cursor()" in SOURCE
    assert "CGEventGetLocation" in _body("quartz_cursor")


def test_drag_events_use_quartz_space_not_the_cocoa_reticle_point():
    body = _body("updateCrosshair_")
    # The Cocoa point is legitimate here, but only for positioning the NSWindow.
    assert "setFrameOrigin_" in body
    drag_branch = body[body.index("elif self.drag_mode"):]
    assert "quartz_cursor()" in drag_branch, "drag must read Quartz coordinates"
    assert "NSEvent.mouseLocation" not in drag_branch, (
        "a Cocoa point posted as a CGEvent is mirrored vertically")


def test_toggle_drag_press_and_release_use_quartz_space():
    body = _body("toggleDrag_")
    assert "quartz_cursor()" in body
    assert "NSEvent.mouseLocation" not in body.split("point=quartz_cursor()")[-1]


def test_drag_is_released_on_exit():
    # Leaving a synthetic button held down locks up the whole machine, and the
    # person this is built for cannot reach a mouse to clear it.
    assert "def release_drag" in SOURCE
    assert "kCGEventLeftMouseUp" in _body("release_drag", end="\n    def quit_")
    assert "atexit.register(controller.release_drag)" in SOURCE
    assert "self.release_drag()" in _body("quit_")


def test_drag_events_are_throttled_to_actual_movement():
    drag_branch = _body("updateCrosshair_")
    assert "self.last_drag_point" in drag_branch, (
        "posting a drag every frame regardless of movement floods the system")
