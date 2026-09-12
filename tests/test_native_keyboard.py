from pathlib import Path


ROOT=Path(__file__).parents[1]
SOURCE=(ROOT/"native"/"controller.py").read_text()
BRIDGE=(ROOT/"native"/"bridge.py").read_text()


def test_keyboard_uses_reliable_paste_insertion():
    assert "insert_text(int(target[\"pid\"]),text)" in SOURCE
    assert "NSPasteboardTypeString" in BRIDGE
    assert "kCGEventFlagMaskCommand" in BRIDGE


def test_typing_does_not_restore_stale_clipboard_contents():
    body=BRIDGE.split("def insert_text",1)[1].split("RETURN_KEYCODE",1)[0]
    assert "previous" not in body
    assert "setString_forType_(text" in body
    assert body.count("clearContents()") == 1


def test_keyboard_is_pointer_operable_without_physical_typing():
    assert "LOOK + WINK TO TYPE" in SOURCE
    assert "NSVisualEffectView" in SOURCE
    assert "make_key" in SOURCE


def test_keyboard_does_not_reopen_itself_on_blink_keypress():
    assert "click(show_keyboard=False)" in SOURCE
    assert 'int(target["pid"]) != os.getpid()' in SOURCE
