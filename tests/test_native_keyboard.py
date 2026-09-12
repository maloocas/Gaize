from pathlib import Path


ROOT=Path(__file__).parents[1]
SOURCE=(ROOT/"native"/"controller.py").read_text()
BRIDGE=(ROOT/"native"/"bridge.py").read_text()


def test_keyboard_prefers_accessibility_caret_insertion():
    assert "insert_text(int(target[\"pid\"]),text)" in SOURCE
    assert "AXSelectedText" in BRIDGE
    assert "AXUIElementSetAttributeValue" in BRIDGE
    assert "type_text(text)" in BRIDGE


def test_typing_never_races_the_users_clipboard():
    body=BRIDGE.split("def insert_text",1)[1].split("RETURN_KEYCODE",1)[0]
    assert "NSPasteboard" not in body
    assert "kCGEventFlagMaskCommand" not in body


def test_keyboard_is_pointer_operable_without_physical_typing():
    assert "POINT + BLINK TO TYPE" in SOURCE
    assert "NSVisualEffectView" in SOURCE
    assert "make_key" in SOURCE


def test_keyboard_does_not_reopen_itself_on_blink_keypress():
    assert "click(show_keyboard=False)" in SOURCE
    assert 'int(target["pid"]) != os.getpid()' in SOURCE
