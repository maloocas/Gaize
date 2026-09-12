from pathlib import Path
import sys


ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/"native"))
import accessibility_targets as T


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
    assert T.MAX_NODES <= 2000
    assert T.SCAN_BUDGET_SECONDS <= .5


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


def test_generic_layout_regions_are_not_targets_by_role_alone():
    for role in ("AXRow","AXCell","AXOutlineRow","AXGroup"):
        assert role not in T.TARGET_ROLES
    assert "AXMenuBarItem" in T.TARGET_ROLES


def test_nested_duplicate_boxes_keep_the_smallest_specific_target():
    outer={"x":10,"y":10,"width":110,"height":50,"role":"AXLink"}
    inner={"x":14,"y":13,"width":102,"height":44,"role":"AXButton"}
    result=T.deduplicate_targets([outer,inner])
    assert result==[inner]


def test_distinct_neighbouring_buttons_are_not_deduplicated():
    left={"x":10,"y":10,"width":80,"height":40,"role":"AXButton"}
    right={"x":94,"y":10,"width":80,"height":40,"role":"AXButton"}
    assert len(T.deduplicate_targets([left,right]))==2


def test_system_ui_processes_cover_dock_and_menu_extras():
    assert "com.apple.dock" in T.SYSTEM_UI_BUNDLE_IDS
    assert "com.apple.systemuiserver" in T.SYSTEM_UI_BUNDLE_IDS
    assert "com.apple.controlcenter" in T.SYSTEM_UI_BUNDLE_IDS
