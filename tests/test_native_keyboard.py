from pathlib import Path


ROOT=Path(__file__).parents[1]
SOURCE=(ROOT/"native"/"controller.py").read_text()
BRIDGE=(ROOT/"native"/"bridge.py").read_text()


def test_keyboard_uses_reliable_paste_insertion():
    assert "insert_text(int(target[\"pid\"]),text)" in SOURCE
    assert "NSPasteboardTypeString" in BRIDGE
    assert "kCGEventFlagMaskCommand" in BRIDGE


def test_messages_reclicks_text_target_and_emulates_keypresses():
    helper=BRIDGE.split("def click_target_and_type",1)[1].split("RETURN_KEYCODE",1)[0]
    assert "post_click(point" in helper
    assert "type_text(text)" in helper
    insert=SOURCE.split('elif value=="INSERT"',1)[1].split('elif value=="ENTER"',1)[0]
    assert "click_target_and_type(target,text)" in insert


def test_overlay_window_order_does_not_cancel_accepted_activation():
    activate=BRIDGE.split("def activate",1)[1].split("# ----------------------------------------------------------------- control",1)[0]
    assert "running.isActive()" in activate
    assert "return requested and alive" in activate


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


def test_selected_text_box_is_keyboard_binding_fallback():
    body=SOURCE.split("def leftClick_",1)[1].split("def rightClick_",1)[0]
    assert "selected_hint=self.selected_target" in body
    assert 'selected_hint.get("kind")=="text"' in body
    gestures=SOURCE.split("def handle_gesture",1)[1].split("def select_near_gaze",1)[0]
    assert gestures.index("self.leftClick_(None)") < gestures.rindex("self.clear_selection()")
