from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"controller.py").read_text()


def test_crosshair_does_not_intercept_mouse_input():
    assert "setIgnoresMouseEvents_(True)" in SOURCE


def test_crosshair_tracks_system_mouse_and_flashes_on_click():
    assert "NSEvent.mouseLocation()" in SOURCE
    assert '"flashCrosshair:"' in SOURCE
