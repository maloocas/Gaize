from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"controller.py").read_text()


def test_crosshair_does_not_intercept_mouse_input():
    assert "setIgnoresMouseEvents_(True)" in SOURCE


def test_crosshair_tracks_system_mouse_and_flashes_on_click():
    assert "NSEvent.mouseLocation()" in SOURCE
    assert "def flashCrosshair_" in SOURCE
    assert "self.flashCrosshair_(None)" in SOURCE
    assert "target=click(show_keyboard=False)" in SOURCE


def test_double_blink_drag_posts_down_dragged_and_up_events():
    assert "kCGEventLeftMouseDown" in SOURCE
    assert "kCGEventLeftMouseDragged" in SOURCE
    assert "kCGEventLeftMouseUp" in SOURCE
    assert '"toggleDrag:"' in SOURCE
