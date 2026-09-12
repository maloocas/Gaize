from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"keyboard.py").read_text()


def test_keyboard_prefers_accessibility_caret_insertion():
    assert 'AXUIElementSetAttributeValue(focused,"AXSelectedText",text)' in SOURCE
    assert "if not set_focused_text(self.pid,text): post_text(text)" in SOURCE


def test_keyboard_is_pointer_operable_without_physical_typing():
    assert "POINT + BLINK TO TYPE" in SOURCE
    assert "tk.Button" in SOURCE


def test_keyboard_does_not_reopen_itself_on_blink_keypress():
    bridge=(Path(__file__).parents[1]/"native"/"bridge.py").read_text()
    assert "app.processIdentifier()) == _keyboard_process.pid" in bridge
