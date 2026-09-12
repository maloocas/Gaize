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
MAX_NODES = 2500
MAX_DEPTH = 30
SCAN_BUDGET_SECONDS = 0.5
# Roles whose frame is a viewport: their contents are only visible inside it.
CLIP_ROLES = {"AXScrollArea", "AXWebArea"}
# Window-server owners that are never the app the user is looking at.
NOT_APPS = {"WindowManager", "Window Server", "Dock", "Control Center",
            "SystemUIServer", "Notification Center", "Spotlight"}
SYSTEM_UI_BUNDLE_IDS = {
    "com.apple.controlcenter", "com.apple.dock", "com.apple.systemuiserver",
}


# A busy or hung app otherwise blocks each query for macOS's default ~6s,
# which left the boxes stale for long stretches after switching windows.
AX_TIMEOUT_SECONDS = 0.25
try:
    AS.AXUIElementSetMessagingTimeout(AS.AXUIElementCreateSystemWide(), AX_TIMEOUT_SECONDS)
except Exception:
    pass


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


def overlaps(a, b):
    """Rectangles (x, y, w, h) share any area."""
    return a[0]<b[0]+b[2] and a[0]+a[2]>b[0] and a[1]<b[1]+b[3] and a[1]+a[3]>b[1]


def intersect(a, b):
    """The overlapping rectangle, or None."""
    x=max(a[0],b[0]); y=max(a[1],b[1])
    right=min(a[0]+a[2],b[0]+b[2]); bottom=min(a[1]+a[3],b[1]+b[3])
    return (x,y,right-x,bottom-y) if right>x and bottom>y else None


def _children(element):
    """Combine the collections used by native, web and virtualized controls.

    Lists and tables that report their visible children/rows are walked
    through those alone, so off-screen rows are never visited."""
    for attribute in ("AXVisibleChildren","AXVisibleRows"):
        values=_attr(element,attribute)
        if values:
            try: return list(values)
            except TypeError: pass
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
    # Real controls first (an icon or label inside a button must not replace
    # the button); among those, inner/specific controls beat the larger wrapper.
    for target in sorted(targets,key=lambda item:(item.get("role") not in TARGET_ROLES,
                                                  item["width"]*item["height"])):
        if any(_overlap_of_smaller(target,other)>=.88 for other in kept):
            continue
        kept.append(target)
        if len(kept)>=MAX_TARGETS: break
    return kept


SYSTEM_ROOTS_TTL_SECONDS = 15.0
_system_roots_cache = {"at": -1e9, "roots": []}


def _system_ui_roots(own_pid):
    """Cached: enumerating every running app and the window list each scan was
    a large fixed cost, and the Dock/menu extras rarely change."""
    now=time.monotonic()
    if now-_system_roots_cache["at"]>SYSTEM_ROOTS_TTL_SECONDS:
        _system_roots_cache["roots"]=_system_ui_roots_uncached(own_pid)
        _system_roots_cache["at"]=now
    return list(_system_roots_cache["roots"])


def _system_ui_roots_uncached(own_pid):
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
            if bundle in SYSTEM_UI_BUNDLE_IDS:
                roots.append((ax,0,pid,name))
            # Only the status-bar icons of other apps: walking their whole
            # tree used to burn the entire scan budget before the window.
            extras=_attr(ax,"AXExtrasMenuBar")
            if extras is not None: roots.append((extras,0,pid,name))
        except Exception:
            continue
    return roots


def front_window_app(own_pid):
    """Owner and bounds of the top real app window, skipping our own overlays
    and system processes (WindowManager was being reported as frontmost)."""
    try:
        windows=Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly|
            Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID) or []
    except Exception:
        return None
    for win in windows:
        pid=int(win.get("kCGWindowOwnerPID") or 0)
        name=str(win.get("kCGWindowOwnerName") or "")
        bounds=win.get("kCGWindowBounds") or {}
        if (win.get("kCGWindowLayer",1)!=0 or not pid or pid==int(own_pid)
                or name in NOT_APPS or float(win.get("kCGWindowAlpha",1))<.05
                or float(bounds.get("Width",0))<80 or float(bounds.get("Height",0))<80):
            continue
        return {"pid":pid,"name":name,
                "bounds":(float(bounds["X"]),float(bounds["Y"]),
                          float(bounds["Width"]),float(bounds["Height"]))}
    return None


_woken=set()


def _wake_accessibility(application, pid):
    """Electron (Claude, Slack, VS Code) and Chromium browsers expose only
    their window buttons until asked for the full tree; the tree appears on
    later scans. Asked once per process."""
    if pid in _woken: return
    _woken.add(pid)
    for name in ("AXManualAccessibility", "AXEnhancedUserInterface"):
        try: AS.AXUIElementSetAttributeValue(application, name, True)
        except Exception: pass


def _display_bounds():
    try:
        error,ids,count=Quartz.CGGetActiveDisplayList(16,None,None)
        return [(d.origin.x,d.origin.y,d.size.width,d.size.height)
                for d in (Quartz.CGDisplayBounds(i) for i in ids[:count])]
    except Exception:
        return None


def _on_a_display(target, displays=None):
    if displays is None: displays=_display_bounds()
    if not displays: return True
    return any(_visible(target,d) for d in displays)


def target_signature(targets):
    """Hashable summary used to skip applying/redrawing an unchanged scan."""
    return tuple(sorted((round(t["x"]),round(t["y"]),round(t["width"]),round(t["height"]),
                         t.get("role"),t.get("label"),t.get("pid")) for t in targets or []))


# Notifications that mean the visible controls moved or changed.
OBSERVED_NOTIFICATIONS = (
    "AXFocusedWindowChanged", "AXMainWindowChanged", "AXWindowMoved",
    "AXWindowResized", "AXWindowCreated", "AXWindowMiniaturized",
    "AXUIElementDestroyed", "AXCreated", "AXLayoutChanged",
    "AXSelectedChildrenChanged", "AXRowCountChanged", "AXSelectedTabChanged",
)


def observe_app(pid, on_change):
    """Register an AXObserver on pid's application element that calls
    on_change(notification) on the main run loop. Returns a handle to pass to
    stop_observing (keep it alive), or None."""
    def callback(_observer, _element, notification, _refcon):
        try: on_change(str(notification))
        except Exception: pass
    try:
        error, observer = AS.AXObserverCreate(int(pid), callback, None)
        if error != AS.kAXErrorSuccess or observer is None: return None
        application = AS.AXUIElementCreateApplication(int(pid))
        AS.AXUIElementSetMessagingTimeout(application, AX_TIMEOUT_SECONDS)
        added = [n for n in OBSERVED_NOTIFICATIONS
                 if AS.AXObserverAddNotification(observer, application, n, None)
                 == AS.kAXErrorSuccess]
        source = AS.AXObserverGetRunLoopSource(observer)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetMain(), source, Quartz.kCFRunLoopDefaultMode)
    except Exception:
        return None
    return {"pid": int(pid), "observer": observer, "application": application,
            "source": source, "callback": callback, "notifications": added}


def stop_observing(handle):
    if not handle: return
    try:
        for n in handle["notifications"]:
            AS.AXObserverRemoveNotification(handle["observer"], handle["application"], n)
        Quartz.CFRunLoopRemoveSource(Quartz.CFRunLoopGetMain(), handle["source"],
                                     Quartz.kCFRunLoopDefaultMode)
    except Exception:
        pass


def _visible(target, bounds):
    x,y,w,h=bounds
    return (target["x"]<x+w and target["x"]+target["width"]>x and
            target["y"]<y+h and target["y"]+target["height"]>y)


def discover_targets(own_pid: int | None = None) -> list[dict]:
    """Return bounded boxes for actionable elements in the frontmost window."""
    own_pid=int(own_pid or os.getpid())
    app = front_window_app(own_pid)
    if app is None:
        return []
    application = AS.AXUIElementCreateApplication(app["pid"])
    try: AS.AXUIElementSetMessagingTimeout(application, AX_TIMEOUT_SECONDS)
    except Exception: pass
    _wake_accessibility(application, app["pid"])
    focused = _attr(application, "AXFocusedWindow")
    if focused is None:
        windows = _attr(application, "AXWindows") or []
        focused = windows[0] if windows else application
    # The window the user is looking at goes first so it always gets the
    # budget; the Dock and menu-bar icons follow.
    # Each queue entry carries the visible rectangle it lives in ("clip").
    roots=[(focused,0,app["pid"],app["name"],app["bounds"])]
    menu_bar=_attr(application,"AXMenuBar")
    if menu_bar is not None:
        roots.append((menu_bar,0,app["pid"],app["name"],None))
    roots.extend(root+(None,) for root in _system_ui_roots(own_pid))

    queue = deque(roots)
    targets = []
    visited = 0; seen_elements=set(); seen_boxes=set()
    deadline = time.monotonic() + SCAN_BUDGET_SECONDS
    while queue and visited < MAX_NODES and len(targets) < MAX_CANDIDATES:
        if time.monotonic() >= deadline:
            break
        element, depth, target_pid, target_app, clip = queue.popleft()
        try: identity=hash(element)
        except Exception: identity=id(element)
        if identity in seen_elements: continue
        seen_elements.add(identity); visited += 1
        if visited%25==0:
            time.sleep(.001)  # yield promptly to camera/blink processing
        position = _point(_attr(element, "AXPosition"))
        size = _size(_attr(element, "AXSize"))
        frame=(None if position is None or size is None else
               (float(position.x),float(position.y),float(size.width),float(size.height)))
        # Scrolled out of view: skip it AND everything inside it. Walking the
        # thousands of off-screen messages in a long chat is what lagged the
        # machine. Zero-sized layout wrappers are not trusted for this.
        if (clip is not None and frame is not None and frame[2]>0 and frame[3]>0
                and not overlaps(frame,clip)):
            continue
        role = _attr(element, "AXRole")
        if role in CLIP_ROLES and frame is not None and frame[2]>0 and frame[3]>0:
            clip=frame if clip is None else (intersect(clip,frame) or clip)
        enabled = _attr(element, "AXEnabled")
        known_role=role in TARGET_ROLES
        actions=set() if known_role else _actions(element) & ACTIONABLE_ACTIONS
        if (known_role or actions) and enabled is not False:
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
                offscreen=clip is not None and not overlaps(box,clip)
                if box not in seen_boxes and not offscreen:   # scrolled out of view
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
            queue.extend((child,depth+1,target_pid,target_app,clip)
                         for child in _children(element))
    # An auto-hidden Dock still reports its items, just off the screen edge.
    displays=_display_bounds()
    return deduplicate_targets([t for t in targets if _on_a_display(t,displays)])
