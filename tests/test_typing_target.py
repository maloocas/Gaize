from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"bridge.py").read_text()


def test_click_binds_keyboard_to_window_under_pointer():
    body=SOURCE.split("def click",1)[1].split("def insert_text",1)[0]
    assert "target_app = _app_at_point(point)" in body
    assert "_focused_editable(target_app)" in body


def test_editable_lookup_does_not_use_stale_workspace_frontmost_app():
    body=SOURCE.split("def _focused_editable",1)[1].split("def click",1)[0]
    assert "frontmostApplication()" not in body
    assert "target_app or frontmost_app()" in body
