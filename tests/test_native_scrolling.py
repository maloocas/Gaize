from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"controller.py").read_text()


def _body(name, end):
    return SOURCE.split(f"def {name}",1)[1].split(end,1)[0]


def test_scroll_requires_visible_dwell_before_posting_events():
    body=_body("updateScroll_", "\n    def ")
    assert "SCROLL_DWELL_SECONDS" in body
    assert "CGEventCreateScrollWheelEvent" in body
    assert "kCGScrollEventUnitPixel" in body


def test_scroll_stops_for_every_conflicting_or_unsafe_mode():
    body=_body("updateScroll_", "\n    def ")
    for condition in ("self.paused", "not self.control_enabled",
                      "self.keyboard_visible()", "self.drag_mode",
                      "self.swipe_recording"):
        assert condition in body
    assert "self.reset_scroll_state()" in body


def test_scroll_zones_are_large_persistent_eye_targets():
    assert "class ScrollZoneView" in SOURCE
    assert 'arrow="▲" if self.direction>0 else "▼"' in SOURCE
    body=_body("build_scroll_controls", "\n    def ")
    assert "panel.orderFrontRegardless()" in body
    # Otherwise wheel events land on our overlay instead of the app beneath it.
    assert "panel.setIgnoresMouseEvents_(True)" in body


def test_blinks_over_scroll_controls_do_not_click_through():
    body=_body("leftClick_", "\n    @objc.python_method")
    assert "if self.scroll_direction_at_pointer(): return" in body
