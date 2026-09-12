"""Guards the right-click gesture.

Right click is a deliberate long eye hold. Single and double blinks were already
taken by click and drag, and chaining a reliable third blink is hard, so the
gesture uses duration instead of counting - a range that was previously
discarded as the user resting their eyes.

Source-level checks: controller.py imports Vision and cv2.
"""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def _body(name: str) -> str:
    start = SOURCE.index(f"def {name}")
    rest = SOURCE[start:]
    cut = rest.find("\n    def ", 1)
    return rest[:cut] if cut != -1 else rest


def test_long_hold_window_cannot_overlap_an_ordinary_blink():
    ns: dict = {}
    for line in SOURCE.splitlines():
        if line.startswith(("LONG_BLINK_MIN", "LONG_BLINK_MAX")):
            exec(line, ns)
    # process() treats 0.07-0.9s as a blink; the long hold must start after that
    # or one gesture would ambiguously trigger both.
    assert ns["LONG_BLINK_MIN"] > 0.9
    assert ns["LONG_BLINK_MAX"] > ns["LONG_BLINK_MIN"]


def test_right_click_posts_right_button_events_in_quartz_space():
    body = _body("rightClick_")
    assert "kCGEventRightMouseDown" in body and "kCGEventRightMouseUp" in body
    assert "kCGMouseButtonRight" in body
    # Same trap as the drag bug: a Cocoa point here would mirror vertically.
    assert "quartz_cursor()" in body
    assert "NSEvent.mouseLocation" not in body


def test_long_hold_cancels_a_pending_left_click():
    body = _body("rightClick_")
    assert "self.pending_blink=False" in body, (
        "otherwise the delayed single-click timer also fires a left click")
    assert "blink_generation" in body


def test_right_click_is_suppressed_where_it_makes_no_sense():
    body = _body("rightClick_")
    assert "pointer_over_keyboard()" in body
    assert "self.drag_mode" in body


def test_process_routes_hold_duration_to_the_right_gesture():
    body = _body("process")
    assert "handleLongBlink:" in body
    assert "handleBlink:" in body
    assert "LONG_BLINK_MIN" in body and "LONG_BLINK_MAX" in body


def test_a_non_gesture_fallback_exists():
    # Blink detection degrades under bad lighting; a right click that only
    # exists as a timed eye hold would be unavailable exactly when needed.
    assert '"rightClick:"' in SOURCE
    assert "Right Click at Pointer" in SOURCE


def test_reticle_shows_the_hold_arming():
    assert "long_blink_progress" in SOURCE
    assert "appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_" in SOURCE
