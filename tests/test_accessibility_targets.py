from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/"native"))

# accessibility_targets imports ApplicationServices, which only exists in the
# native venv. Without this guard the missing module is a collection ERROR that
# aborts the whole suite, so none of the pure-Python tests run either.
pytest.importorskip("ApplicationServices")

import accessibility_targets as T  # noqa: E402


class _Point:
    x=10; y=20


class _Size:
    width=120; height=44


class _Element:
    def __init__(self,role,children=None,title=None):
        self.values={"AXRole":role,"AXEnabled":True,"AXPosition":_Point(),
                     "AXSize":_Size(),"AXChildren":children or [],"AXTitle":title}


def test_target_roles_cover_primary_computer_controls():
    for role in ("AXButton","AXTextField","AXTextArea","AXLink","AXSlider",
                 "AXCheckBox","AXRadioButton","AXMenuItem","AXPopUpButton"):
        assert role in T.TARGET_ROLES
    assert "AXDockItem" in T.TARGET_ROLES


def test_discovery_is_bounded_for_large_accessibility_trees():
    assert T.MAX_TARGETS <= 300
    # Runs on a background thread, so a longer scan never stalls the pointer.
    assert T.MAX_NODES <= 5000
    assert T.SCAN_BUDGET_SECONDS <= 1.0


def test_target_kind_distinguishes_text_navigation_and_settings():
    assert T._kind("AXTextField")=="text"
    assert T._kind("AXLink")=="navigation"
    assert T._kind("AXSlider")=="setting"
    assert T._kind("AXButton")=="action"


def test_custom_controls_are_discovered_by_accessibility_action():
    assert "AXPress" in T.ACTIONABLE_ACTIONS
    assert "AXShowMenu" in T.ACTIONABLE_ACTIONS


def test_browser_and_virtualized_child_collections_are_traversed():
    for attribute in ("AXChildren","AXVisibleChildren","AXRows","AXTabs","AXContents"):
        assert attribute in T.CHILD_ATTRIBUTES


def test_child_collections_are_fetched_in_one_cross_process_batch(monkeypatch):
    calls=[]
    child=object()
    monkeypatch.setattr(T,"_attrs",lambda _element,names:
                        calls.append(tuple(names)) or {name: ([child] if name=="AXVisibleRows" else None)
                                                       for name in names})
    assert T._children(object())==[child]
    assert len(calls)==1


def test_focused_window_is_queued_before_menu_and_system_extras():
    source=(ROOT/"native"/"accessibility_targets.py").read_text()
    body=source.split("def discover_targets",1)[1]
    assert 'queue = deque(roots)' in body
    assert 'extras.append((menu_bar' in body
    assert 'if not queue:\n            queue.extend(extras)' in body


def test_generic_layout_regions_are_not_targets_by_role_alone():
    for role in ("AXRow","AXCell","AXOutlineRow","AXGroup"):
        assert role not in T.TARGET_ROLES
    assert "AXMenuBarItem" in T.TARGET_ROLES


def test_nested_duplicate_boxes_keep_the_smallest_specific_target():
    outer={"x":10,"y":10,"width":110,"height":50,"role":"AXLink"}
    inner={"x":14,"y":13,"width":102,"height":44,"role":"AXButton"}
    result=T.deduplicate_targets([outer,inner])
    assert result==[inner]


def test_an_icon_inside_a_button_does_not_replace_the_button():
    button={"x":10,"y":10,"width":200,"height":30,"role":"AXButton"}
    icon={"x":14,"y":16,"width":17,"height":17,"role":"AXImage"}
    assert T.deduplicate_targets([button,icon])==[button]


def test_scrolled_out_content_is_outside_the_clip():
    viewport=(0,100,800,600)
    assert T.overlaps((10,150,50,20),viewport)
    assert not T.overlaps((10,-4000,50,20),viewport)      # a message far above
    assert T.intersect((0,0,1000,1000),viewport)==viewport
    assert T.intersect((0,0,10,10),viewport) is None


def test_distinct_neighbouring_buttons_are_not_deduplicated():
    left={"x":10,"y":10,"width":80,"height":40,"role":"AXButton"}
    right={"x":94,"y":10,"width":80,"height":40,"role":"AXButton"}
    assert len(T.deduplicate_targets([left,right]))==2


def test_system_ui_processes_cover_dock_and_menu_extras():
    assert "com.apple.dock" in T.SYSTEM_UI_BUNDLE_IDS
    assert "com.apple.systemuiserver" in T.SYSTEM_UI_BUNDLE_IDS
    assert "com.apple.controlcenter" in T.SYSTEM_UI_BUNDLE_IDS


def test_target_signature_ignores_order_and_subpixel_jitter():
    a={"x":10.0,"y":20.0,"width":30.0,"height":40.0,"role":"AXButton","label":"OK","pid":1}
    b={"x":50.0,"y":20.0,"width":30.0,"height":40.0,"role":"AXLink","label":"Go","pid":1}
    jitter=dict(a,x=10.2)
    assert T.target_signature([a,b])==T.target_signature([b,jitter])
    assert T.target_signature([a])!=T.target_signature([a,b])


def test_system_ui_roots_are_cached(monkeypatch):
    calls=[]
    monkeypatch.setattr(T,"_system_ui_roots_uncached",lambda pid:calls.append(pid) or ["root"])
    monkeypatch.setattr(T,"_system_roots_cache",{"at":-1e9,"roots":[]})
    assert T._system_ui_roots(1)==["root"] and T._system_ui_roots(1)==["root"]
    assert len(calls)==1
