"""Guards the wink gestures.

A left wink is a left click and a right wink a right click, on the selected
target if there is one, otherwise at the pointer. Natural blinks must never
click. Source-level checks: controller.py needs AppKit and a camera.
"""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def _body(name: str) -> str:
    start = SOURCE.index(f"def {name}")
    rest = SOURCE[start:]
    cut = rest.find("\n    def ", 1)
    return rest[:cut] if cut != -1 else rest


def test_right_click_posts_right_button_events_in_quartz_space():
    body = _body("rightClick_")
    assert "kCGEventRightMouseDown" in body and "kCGEventRightMouseUp" in body
    assert "kCGMouseButtonRight" in body
    # Same trap as the drag bug: a Cocoa point here would mirror vertically.
    assert "quartz_cursor()" in body
    assert "NSEvent.mouseLocation" not in body


def test_right_click_is_suppressed_where_it_makes_no_sense():
    body = _body("rightClick_")
    assert "pointer_over_keyboard()" in body
    assert "self.drag_mode" in body


def test_winks_click_and_natural_blinks_do_not():
    body = _body("handle_gesture")
    assert 'gesture=="wink_left": self.leftClick_(None)' in body
    assert "self.rightClick_(None)" in body
    # The only thing a natural blink does is end a swiped word.
    assert body.count('"blink"') == 1 and "swipe_boundary" in body


def test_a_wink_clicks_the_selected_target_first():
    body = _body("handle_gesture")
    assert "move_pointer(*center(target))" in body
    assert "self.clear_selection()" in body


def test_hard_blink_selects_or_zooms():
    body = _body("select_near_gaze")
    assert "candidates(" in body and "open_zoom" in body and "set_selected" in body


def test_a_non_gesture_fallback_exists():
    # Blink detection degrades under bad lighting; a right click that only
    # exists as a wink would be unavailable exactly when needed.
    assert '"rightClick:"' in SOURCE
    assert "Right Click at Pointer" in SOURCE
