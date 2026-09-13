"""Smoke-test every custom drawRect_ path.

A wrong PyObjC selector inside drawRect_ is uniquely nasty: AppKit calls it from
the run loop, PyObjC converts the Python exception into an Objective-C one, and
the process dies with EXC_BREAKPOINT and no Python traceback. It has happened
twice here - NSColor.colorWithWhite_alpha_ given one argument instead of two,
and the four-argument arc selector given five - and both times the app simply
vanished at 60Hz with nothing in the log.

Needs AppKit, Vision and cv2, so it runs under the native venv and skips
elsewhere:  .native-venv/bin/python -m pytest tests/test_native_drawing.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "native"))

AppKit = pytest.importorskip("AppKit")
pytest.importorskip("Vision")
pytest.importorskip("cv2")

AppKit.NSApplication.sharedApplication()
import controller as C  # noqa: E402


class _Stub:
    """Every attribute the views read off the controller."""
    latest_gaze = None
    latest_seen = 0.0
    click_flash_until = 0.0
    drag_mode = False
    swipe_recording = False
    control_enabled = True
    collecting = None
    calibration = None
    failed = False
    long_blink_armed = False
    long_blink_progress = 0.0
    swipe_path = []
    edge_action = None


RETICLE_STATES = [
    ("idle", {}),
    ("click flash", {"click_flash_until": 1e18}),
    ("drag mode", {"drag_mode": True}),
    ("right click arming", {"long_blink_progress": 0.45}),
    ("right click armed", {"long_blink_progress": 1.0, "long_blink_armed": True}),
    ("progress overshoot", {"long_blink_progress": 1.8, "long_blink_armed": True}),
]


@pytest.mark.parametrize("label,state", RETICLE_STATES, ids=[s[0] for s in RETICLE_STATES])
def test_crosshair_draws_in_every_state(label, state):
    stub = _Stub()
    for key, value in state.items():
        setattr(stub, key, value)
    view = C.CrosshairView.alloc().initWithController_(stub)
    view.setFrame_(((0, 0), (52, 52)))
    view.drawRect_(((0, 0), (52, 52)))


KEY_STATES = [("normal", False, False, False), ("hovering", True, False, False),
              ("pressed", False, True, False), ("accent", False, False, True)]


@pytest.mark.parametrize("label,hover,press,accent", KEY_STATES, ids=[s[0] for s in KEY_STATES])
def test_key_draws_in_every_state(label, hover, press, accent):
    key = C.KeyView.alloc().initWithFrame_controller_title_value_accent_(
        ((0, 0), (100, 60)), None, "TYPE INTO APP" if accent else "A",
        "INSERT" if accent else "a", accent)
    key.hovering = hover
    key.pressed = press
    key.drawRect_(((0, 0), (100, 60)))


def test_swipe_trace_draws_with_and_without_a_path():
    for recording, path in ((False, []), (True, []), (True, [(1.0, 2.0)]),
                            (True, [(1.0, 2.0), (30.0, 40.0), (60.0, 10.0)])):
        stub = _Stub()
        stub.swipe_recording = recording
        stub.swipe_path = path
        view = C.SwipeTraceView.alloc().initWithController_frame_(
            stub, ((0, 0), (400, 300)))
        view.drawRect_(((0, 0), (400, 300)))


@pytest.mark.parametrize("action", [None, "FINISH", "CLOSE", "INSERT", "ENTER", "DELETE"])
def test_swipe_edge_actions_draw(action):
    stub = _Stub()
    stub.edge_action = action
    view = C.ExitStripView.alloc().initWithController_frame_(
        stub, ((0, 0), (1200, 800)))
    view.drawRect_(((0, 0), (1200, 800)))


def test_target_feedback_draws_without_targets():
    stub = _Stub()
    stub.target_overlay_screen = AppKit.NSScreen.mainScreen().frame()
    stub.accessibility_targets = []
    stub.click_marks = []
    stub.selected_target = None
    view = C.TargetFeedbackView.alloc().initWithController_frame_(
        stub, ((0, 0), (400, 300)))
    view.drawRect_(((0, 0), (400, 300)))
