"""Discover gaze-worthy controls in the frontmost macOS application.

The returned rectangles remain in Quartz global screen coordinates (origin at
the top-left). Drawing and future pointer snapping can consume the same target
records without performing another Accessibility API tree walk.
"""
from __future__ import annotations

from collections import deque
import os
import time

import ApplicationServices as AS
import AppKit
import Quartz

from bridge import frontmost_app


TARGET_ROLES = {
    "AXButton", "AXCheckBox", "AXColorWell", "AXComboBox",
    "AXDisclosureTriangle", "AXDockItem", "AXIncrementor", "AXLink", "AXMenuButton",
    "AXMenuBarItem", "AXMenuItem", "AXPopUpButton", "AXRadioButton",
    "AXSearchField", "AXSlider", "AXTab",
    "AXTextArea", "AXTextField", "AXToggle",
}
EDITABLE_ROLES = {"AXComboBox", "AXSearchField", "AXTextArea", "AXTextField"}
ACTIONABLE_ACTIONS = {
    "AXCancel", "AXConfirm", "AXDecrement", "AXIncrement", "AXPick",
    "AXPress", "AXShowMenu",
}
CHILD_ATTRIBUTES = ("AXChildren", "AXVisibleChildren", "AXRows", "AXTabs", "AXContents")
MAX_TARGETS = 250
MAX_CANDIDATES = 500
MAX_NODES = 1800
MAX_DEPTH = 30
SCAN_BUDGET_SECONDS = 0.45
SYSTEM_UI_BUNDLE_IDS = {
    "com.apple.controlcenter", "com.apple.dock", "com.apple.systemuiserver",
}


def _attr(element, name):
    try:
        error, value = AS.AXUIElementCopyAttributeValue(element, name, None)
        return value if error == AS.kAXErrorSuccess else None
    except Exception:
        return None


def _point(value):
    try:
        ok, point = AS.AXValueGetValue(value, AS.kAXValueCGPointType, None)
        return point if ok else None
    except Exception:
        return None


def _size(value):
    try:
        ok, size = AS.AXValueGetValue(value, AS.kAXValueCGSizeType, None)
        return size if ok else None
    except Exception:
        return None


def _actions(element):
    try:
        error, actions = AS.AXUIElementCopyActionNames(element, None)
        return set(actions or []) if error == AS.kAXErrorSuccess else set()
    except Exception:
        return set()


def _children(element):
    """Combine the collections used by native, web and virtualized controls."""
    result=[]; seen=set()
    for attribute in CHILD_ATTRIBUTES:
        values=_attr(element,attribute)
        if values is None or isinstance(values,(str,bytes)):
            continue
        try: iterator=iter(values)
        except TypeError: continue
        for child in iterator:
            try: identity=hash(child)
            except Exception: identity=id(child)
            if identity not in seen:
                seen.add(identity); result.append(child)
    return result


def _explicit_label(element):
    for name in ("AXTitle", "AXDescription", "AXHelp", "AXValue"):
        value = _attr(element, name)
        if isinstance(value, str) and value.strip():
            return " ".join(value.strip().split())[:44]
    return None


def _label(element, role):
    return _explicit_label(element) or role.removeprefix("AX")


def _kind(role):
    if role in EDITABLE_ROLES: return "text"
    if role in {"AXLink", "AXTab"}: return "navigation"
    if role in {"AXCheckBox", "AXRadioButton", "AXSlider", "AXToggle"}: return "setting"
    return "action"


def _overlap_of_smaller(first,second):
    left=max(first["x"],second["x"]); top=max(first["y"],second["y"])
    right=min(first["x"]+first["width"],second["x"]+second["width"])
    bottom=min(first["y"]+first["height"],second["y"]+second["height"])
    intersection=max(0,right-left)*max(0,bottom-top)
    smaller=min(first["width"]*first["height"],second["width"]*second["height"])
    return intersection/smaller if smaller else 0.0


def deduplicate_targets(targets):
    """Collapse nested AX wrappers that describe the same visual control."""
    kept=[]
    # Inner/specific controls win over the larger link/group wrapper around it.
    for target in sorted(targets,key=lambda item:item["width"]*item["height"]):
        if any(_overlap_of_smaller(target,other)>=.88 for other in kept):
            continue
        kept.append(target)
        if len(kept)>=MAX_TARGETS: break
    return kept


def _system_ui_roots(own_pid):
    """Accessibility roots for the Dock and right-side menu-bar controls."""
    roots=[]
    # Menu extras are not consistently attributed to SystemUIServer on recent
    # macOS releases. Discover the owner PIDs of the small elevated windows in
    # the menu-bar band so Wi-Fi, battery, clock and third-party extras are not
    # missed merely because their bundle identifier changed.
    menu_pids=set()
    try:
        windows=Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly|
            Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
        for window in windows:
            bounds=window.get("kCGWindowBounds") or {}
            pid=int(window.get("kCGWindowOwnerPID") or 0)
            y=float(bounds.get("Y",9999)); height=float(bounds.get("Height",9999))
            if pid and pid!=int(own_pid) and y<=48 and height<=120:
                menu_pids.add(pid)
    except Exception:
        pass
    try:
        applications=AppKit.NSWorkspace.sharedWorkspace().runningApplications()
    except Exception:
        return roots
    for application in applications or []:
        try:
            bundle=str(application.bundleIdentifier() or "").lower()
            pid=int(application.processIdentifier())
            if (bundle not in SYSTEM_UI_BUNDLE_IDS and pid not in menu_pids) or pid==int(own_pid):
                continue
            name=str(application.localizedName() or bundle)
            ax=AS.AXUIElementCreateApplication(pid)
            roots.append((ax,0,pid,name))
            menu=_attr(ax,"AXMenuBar")
            if menu is not None: roots.append((menu,0,pid,name))
        except Exception:
            continue
    return roots


def discover_targets(own_pid: int | None = None) -> list[dict]:
    """Return bounded boxes for actionable elements in the frontmost window."""
    app = frontmost_app()
    if app is None or int(app["pid"]) == int(own_pid or os.getpid()):
        return []
    application = AS.AXUIElementCreateApplication(int(app["pid"]))
    focused = _attr(application, "AXFocusedWindow")
    if focused is None:
        windows = _attr(application, "AXWindows") or []
        focused = windows[0] if windows else application
    # System controls are shallow and latency-sensitive, so put them ahead of a
    # potentially enormous browser accessibility tree.
    roots=_system_ui_roots(own_pid or os.getpid())
    roots.append((focused,0,int(app["pid"]),str(app["name"])))
    menu_bar=_attr(application,"AXMenuBar")
    if menu_bar is not None:
        roots.append((menu_bar,0,int(app["pid"]),str(app["name"])))

    queue = deque(roots)
    targets = []
    visited = 0; seen_elements=set(); seen_boxes=set()
    deadline = time.monotonic() + SCAN_BUDGET_SECONDS
    while queue and visited < MAX_NODES and len(targets) < MAX_CANDIDATES:
        if time.monotonic() >= deadline:
            break
        element, depth, target_pid, target_app = queue.popleft()
        try: identity=hash(element)
        except Exception: identity=id(element)
        if identity in seen_elements: continue
        seen_elements.add(identity); visited += 1
        if visited%25==0:
            time.sleep(.001)  # yield promptly to camera/blink processing
        role = _attr(element, "AXRole")
        enabled = _attr(element, "AXEnabled")
        known_role=role in TARGET_ROLES
        actions=set() if known_role else _actions(element) & ACTIONABLE_ACTIONS
        if (known_role or actions) and enabled is not False:
            position = _point(_attr(element, "AXPosition"))
            size = _size(_attr(element, "AXSize"))
            # Generic groups/rows sometimes advertise AXPress for an enormous
            # content region. Keep a custom-role target only when it is named
            # and plausibly sized like a control.
            custom_ok=(known_role or
                       (_explicit_label(element) is not None and
                        size is not None and size.width<=700 and size.height<=260))
            if (position is not None and size is not None and
                    custom_ok and
                    5 <= size.width <= 2400 and 5 <= size.height <= 1600):
                box=(round(float(position.x),1),round(float(position.y),1),
                     round(float(size.width),1),round(float(size.height),1))
                if box not in seen_boxes:
                    seen_boxes.add(box)
                    role_name=str(role or "AXAction")
                    targets.append({
                        "x": float(position.x), "y": float(position.y),
                        "width": float(size.width), "height": float(size.height),
                        "role": role_name, "kind": _kind(role_name),
                        "label": _label(element, role_name),
                        "pid": target_pid, "app": target_app,
                    })
        if depth < MAX_DEPTH:
            queue.extend((child,depth+1,target_pid,target_app)
                         for child in _children(element))
    return deduplicate_targets(targets)
