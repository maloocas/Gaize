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
    body=SOURCE.split("class TargetOverlayView",1)[1].split("class TargetFeedbackView",1)[0]
    assert "bezierPathWithRoundedRect" in body
    assert '"text"' in body and '"navigation"' in body and '"setting"' in body
    assert "drawAtPoint_withAttributes_" not in body
    assert "target.get(\"label\")" not in body


def test_static_boxes_are_not_invalidated_by_the_60hz_pointer_timer():
    timer=SOURCE.split("def updateCrosshair_",1)[1].split("def flashCrosshair_",1)[0]
    assert "target_overlay_view.setNeedsDisplay_(True)" in timer
    assert "target_boxes_view.setNeedsDisplay_(True)" not in timer
    assert "self.click_marks and self.ui_tick%2==0" in timer
    assert '1/30,self,"updateCrosshair:"' in SOURCE


def test_target_boxes_are_drawn_once_and_hide_really_hides_them():
    boxes=SOURCE.split("class TargetOverlayView",1)[1].split("class TargetFeedbackView",1)[0]
    feedback=SOURCE.split("class TargetFeedbackView",1)[1].split("class ZoomView",1)[0]
    assert "if not self.controller.target_boxes_enabled: return" in boxes
    assert "for target in self.controller.accessibility_targets" not in feedback


def test_partial_refresh_drops_stale_boxes_from_a_refreshed_process():
    body=SOURCE.split("def merge_partial_scan",1)[1].split("def _background_qos",1)[0]
    assert "return list(new)" in body
    assert "overlaps(box(t),box(n))" not in body


def test_every_completed_scan_replaces_targets_and_invalidates_box_layer():
    body=SOURCE.split("def applyTargets_",1)[1].split("# ------------------------------------------------------------ scrolling",1)[0]
    signature_branch=body.index("if signature==self.target_signature")
    assert body.index("self.accessibility_targets=") < signature_branch
    assert body.index("self.target_boxes_view.setNeedsDisplay_(True)") < signature_branch
