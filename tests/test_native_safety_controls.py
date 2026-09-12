from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"controller.py").read_text()


def test_pause_releases_drag_and_cancels_pending_actions():
    body=SOURCE.split("def set_paused",1)[1].split("def emergencyStop_",1)[0]
    assert "self.pending_blink=False" in body
    assert "self.swipe_recording=False" in body
    assert "self.release_drag()" in body
    assert "self.hideKeyboard_(None)" in body


def test_paused_blinks_are_confined_to_safety_controls():
    assert "if self.paused and not on_safety: return" in SOURCE
    assert "if on_safety:" in SOURCE
    assert "a safety action must never reopen the keyboard" in SOURCE


def test_emergency_stop_releases_drag_and_terminates():
    body=SOURCE.split("def emergencyStop_",1)[1].split("def on_global_key",1)[0]
    assert "self.release_drag()" in body
    assert "self.running=False" in body
    assert "NSApp.terminate_" in body


def test_large_pause_and_stop_targets_are_always_visible():
    assert '"Ⅱ  PAUSE","PAUSE"' in SOURCE
    assert '"■  STOP","EMERGENCY_STOP"' in SOURCE
    assert "panel.orderFrontRegardless()" in SOURCE
