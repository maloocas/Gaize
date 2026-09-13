"""Layout and activation guards for the overshoot swipe keyboard."""
from pathlib import Path


SOURCE = (Path(__file__).parents[1] / "native" / "controller.py").read_text()


def _body(name: str) -> str:
    start = SOURCE.index(f"def {name}")
    rest = SOURCE[start:]
    cut = rest.find("\n    def ", 1)
    return rest[:cut] if cut != -1 else rest


def test_keyboard_types_are_explicit_and_swipe_is_current():
    assert 'KEYBOARD_SWIPE = "swipe"' in SOURCE
    assert 'KEYBOARD_STANDARD = "standard"' in SOURCE
    assert "self.keyboard_mode=KEYBOARD_SWIPE" in SOURCE


def test_edge_actions_only_fire_on_entry_at_the_extreme_boundary():
    body = _body("track_keyboard_pointer")
    assert "EDGE_TRIGGER = 24.0" in SOURCE
    assert 'action="FINISH" if x<width/2 else "CLOSE"' in body
    assert 'action="INSERT" if y>=height/2 else "ENTER"' in body
    assert 'action="DELETE"' in body
    assert "if action!=previous" in body


def test_swipe_keyboard_has_no_clickable_action_row_and_keeps_key_padding():
    body = _body("build_swipe_keyboard")
    assert "actions=" not in body
    assert "(width-gap*11)/12" in body
    assert "(self.suggestion_row_y-14-gap*3)/4" in body
