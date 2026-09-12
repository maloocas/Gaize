from pathlib import Path


SOURCE=(Path(__file__).parents[1]/"native"/"controller.py").read_text()


def test_overlay_is_click_through_and_visible_across_spaces():
    body=SOURCE.split("def build_target_overlay",1)[1].split("def toggleTargetBoxes_",1)[0]
    assert "setIgnoresMouseEvents_(True)" in body
    assert "NSWindowCollectionBehaviorCanJoinAllSpaces" in body
    assert "orderFrontRegardless()" in body


def test_accessibility_scan_never_blocks_the_appkit_thread():
    body=SOURCE.split("def requestTargetScan_",1)[1].split("def applyTargets_",1)[0]
    assert "threading.Thread" in body
    assert "target_scan_running" in body


def test_scan_refresh_is_throttled_to_protect_blink_processing():
    assert '1.75,self,"requestTargetScan:"' in SOURCE


def test_overlay_draws_unlabeled_color_coded_boxes():
    body=SOURCE.split("class TargetOverlayView",1)[1].split("class CalibrationView",1)[0]
    assert "bezierPathWithRoundedRect" in body
    assert '"text"' in body and '"navigation"' in body and '"setting"' in body
    assert "drawAtPoint_withAttributes_" not in body
    assert "target.get(\"label\")" not in body
