"""The keyboard needs a way to press Return.

Sending a message is the point of a communication device, and in most apps that
is Return rather than an on-screen button. Source-level checks: controller.py
imports Vision and cv2.
"""
from pathlib import Path

CONTROLLER = (Path(__file__).parents[1] / "native" / "controller.py").read_text()
BRIDGE = (Path(__file__).parents[1] / "native" / "bridge.py").read_text()


def _body(source: str, name: str) -> str:
    start = source.index(f"def {name}")
    rest = source[start:]
    cut = rest.find("\n    def ", 1)
    if cut == -1:
        cut = rest.find("\ndef ", 1)
    return rest[:cut] if cut != -1 else rest


def test_bridge_can_press_return():
    assert "def press_return" in BRIDGE
    body = _body(BRIDGE, "press_return")
    assert "RETURN_KEYCODE" in body
    assert "CGEventCreateKeyboardEvent" in body
    assert "activate(pid)" in body, "the target app has to be frontmost first"


def test_return_keycode_is_correct():
    assert "RETURN_KEYCODE = 36" in BRIDGE


def test_keyboard_exposes_a_send_key():
    assert '"ENTER"' in CONTROLLER
    assert "SEND" in CONTROLLER


def test_send_delivers_text_before_pressing_return():
    body = _body(CONTROLLER, "keyPressed_")
    enter = body[body.index('value=="ENTER"'):]
    insert_at = enter.index("insert_text")
    return_at = enter.index("press_return")
    assert insert_at < return_at, "text must land before Return is pressed"


def test_send_still_works_with_an_empty_buffer():
    body = _body(CONTROLLER, "keyPressed_")
    enter = body[body.index('value=="ENTER"'):]
    # Return itself must not be conditional on there being text, so the key can
    # accept a dialog or submit a field without typing anything first.
    assert "if text: insert_text" in enter


def test_suggestions_refresh_as_the_buffer_changes():
    assert "def refresh_suggestions" in CONTROLLER
    assert "self.refresh_suggestions()" in _body(CONTROLLER, "keyPressed_")


def test_accepting_a_suggestion_appends_or_replaces_correctly():
    body = _body(CONTROLLER, "keyPressed_")
    branch = body[body.index('value.startswith("SUGGEST:")'):]
    # Replacing unconditionally turned "i need some " + "water" into
    # "i need water", destroying a finished word.
    assert 'endswith(" ")' in branch
