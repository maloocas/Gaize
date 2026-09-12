import AppKit
import ApplicationServices

struct SensedElement {
    let role: String
    let title: String
    let frame: CGRect
}

/// AX hit-testing on whatever's under the gaze point. Purely tracks which
/// element the gaze is currently on — it never speaks on its own. Speaking
/// only happens on demand, via a voice command: "explain"/"what is this" to
/// hear about the current element, "select" to confirm/press it.
final class Sensing {
    var onExplainRequested: ((SensedElement) -> Void)?
    var onConfirmed: ((SensedElement) -> Void)?

    private let systemWide = AXUIElementCreateSystemWide()
    private var currentAXElement: AXUIElement?
    private var currentSensed: SensedElement?

    private var lastHeartbeat = Date.distantPast

    /// Called on every gaze-tracker frame with the current screen-space gaze
    /// point, top-left origin (Quartz/AX coordinates, not Cocoa).
    func updateGaze(at point: CGPoint) {
        if Date().timeIntervalSince(lastHeartbeat) > 1.0 {
            lastHeartbeat = Date()
            print("Sensing: heartbeat, gaze point = \(point)")
        }

        guard AXIsProcessTrusted() else {
            print("Sensing: NOT TRUSTED, skipping hit-test")
            return
        }

        var axElementRef: AXUIElement?
        let result = AXUIElementCopyElementAtPosition(
            systemWide,
            Float(point.x),
            Float(point.y),
            &axElementRef
        )

        guard result == .success, let axElement = axElementRef, let sensed = describe(axElement) else {
            resetCurrent()
            return
        }

        // Compare by AX element identity, not a rebuilt role/title/frame
        // string — tiny gaze jitter can make the same on-screen button
        // report marginally different frame values between frames.
        let isSameElement = currentAXElement.map { CFEqual($0, axElement) } ?? false
        if !isSameElement {
            print("Sensing: new element role=\(sensed.role) title=\"\(sensed.title)\"")
            currentAXElement = axElement
            currentSensed = sensed
        }
    }

    /// Browsers report AXUIElementPerformAction(.press) as .success on a
    /// plain <button> without necessarily routing it to the JS click
    /// handler - the AX action path is proven reliable for native apps
    /// (Messages), so only browser-owned elements get a real synthesized
    /// click instead.
    private static let browserBundleIDs: Set<String> = [
        "com.google.Chrome", "com.apple.Safari", "org.mozilla.firefox",
        "com.microsoft.edgemac", "com.brave.Browser",
    ]

    /// Fired by a "select"/"click"/"choose"/"confirm" voice command.
    @discardableResult
    func confirmCurrentElement() -> SensedElement? {
        guard let axElement = currentAXElement, let sensed = currentSensed else { return nil }

        var pid: pid_t = 0
        AXUIElementGetPid(axElement, &pid)
        let ownerBundleID = NSRunningApplication(processIdentifier: pid)?.bundleIdentifier ?? ""

        if Self.browserBundleIDs.contains(ownerBundleID) {
            print("Sensing: confirming \"\(sensed.title)\" via synthesized click (browser-owned)")
            synthesizeClick(at: sensed.frame)
        } else {
            AXUIElementPerformAction(axElement, kAXPressAction as CFString)
        }

        onConfirmed?(sensed)
        resetCurrent()
        return sensed
    }

    /// Posts a real mouse-down/mouse-up at the element's center, in
    /// AX/Quartz (top-left origin) coordinates.
    private func synthesizeClick(at frame: CGRect) {
        guard frame.width > 0, frame.height > 0 else { return }
        let point = CGPoint(x: frame.midX, y: frame.midY)

        let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
        let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }

    /// Fired by an "explain"/"what is this" voice command.
    @discardableResult
    func explainCurrentElement() -> SensedElement? {
        guard let sensed = currentSensed else { return nil }
        onExplainRequested?(sensed)
        return sensed
    }

    /// The demo's fixed target app. The website runs in a browser, which is
    /// what's actually frontmost when the user clicks a goal — so this can't
    /// use NSWorkspace.frontmostApplication (that was the bug: highlight
    /// requests were searching the browser's AX tree, not Messages').
    ///
    /// Matched by bundle identifier, not localizedName == "Messages" -
    /// Messages' background "Messages Assistant Extension" helper process
    /// also reports that same localizedName, and .first(where:) was
    /// silently picking that windowless helper instead of the real app,
    /// which is why every window/AX-tree query kept failing.
    private static let targetAppName = "Messages"
    private static let targetBundleID = "com.apple.MobileSMS"

    /// Resolve a human-readable target description (from the website, e.g.
    /// "send button") to an on-screen frame, by walking the target app's AX
    /// tree for a matching title/description. Used to draw the overlay.
    func screenFrame(forElementDescribed description: String) -> CGRect? {
        guard AXIsProcessTrusted() else {
            print("Sensing.screenFrame: not trusted")
            return nil
        }

        guard let targetApp = NSWorkspace.shared.runningApplications.first(where: {
            $0.bundleIdentifier == Self.targetBundleID
        }) else {
            print("Sensing.screenFrame: \(Self.targetAppName) is not running")
            return nil
        }

        // Messages (a Mac Catalyst app) only answers window/AX-tree queries
        // while it's the active app - in the background, kAXWindowsAttribute
        // and kAXFocusedWindowAttribute both report empty/error. Since the
        // whole point of this call is to show the user where to look in
        // Messages, bringing it to the front here is also just correct UX,
        // not only a technical workaround.
        if !targetApp.isActive {
            print("Sensing.screenFrame: activating \(Self.targetAppName) (was backgrounded)")
            targetApp.activate(options: [])
            Thread.sleep(forTimeInterval: 0.5)
        }

        print("Sensing.screenFrame: searching \"\(Self.targetAppName)\" for \"\(description)\"")
        let appElement = AXUIElementCreateApplication(targetApp.processIdentifier)

        // Messages is a Mac Catalyst (UIKit-on-Mac) app - Catalyst apps
        // don't expose their real AX tree until this is explicitly turned
        // on, otherwise window/children queries fail with kAXErrorCannotComplete.
        AXUIElementSetAttributeValue(appElement, "AXManualAccessibility" as CFString, kCFBooleanTrue)

        // The app element's kAXChildrenAttribute doesn't reliably surface
        // windows for every app - kAXWindowsAttribute is the documented,
        // reliable way to get them, so start the search there instead.
        // Fall back to kAXFocusedWindowAttribute if that fails - some
        // Catalyst apps answer the single-focused-window query even when
        // full window enumeration errors out.
        var windowsRef: CFTypeRef?
        let windowsResult = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &windowsRef)
        var windows: [AXUIElement] = []

        if windowsResult == .success, let list = windowsRef as? [AXUIElement] {
            windows = list
        } else {
            print("Sensing.screenFrame: kAXWindowsAttribute failed (axError=\(windowsResult.rawValue)), trying focused window")
            var focusedRef: CFTypeRef?
            let focusedResult = AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &focusedRef)
            if focusedResult == .success, let focused = focusedRef {
                windows = [focused as! AXUIElement]
            } else {
                print("Sensing.screenFrame: kAXFocusedWindowAttribute also failed (axError=\(focusedResult.rawValue))")
                return nil
            }
        }

        print("Sensing.screenFrame: \(Self.targetAppName) has \(windows.count) window(s)")

        for window in windows {
            if let found = findElement(in: window, matching: description, depth: 0) {
                return found.frame
            }
        }

        print("Sensing.screenFrame: no match for \"\(description)\" in \(Self.targetAppName)")
        return nil
    }

    private func resetCurrent() {
        currentAXElement = nil
        currentSensed = nil
    }

    private func describe(_ element: AXUIElement) -> SensedElement? {
        let role = stringAttribute(element, kAXRoleAttribute as CFString) ?? "unknown"
        let title = stringAttribute(element, kAXTitleAttribute as CFString)
            ?? stringAttribute(element, kAXDescriptionAttribute as CFString)
            ?? ""

        guard let position = pointAttribute(element, kAXPositionAttribute as CFString),
              let size = sizeAttribute(element, kAXSizeAttribute as CFString) else {
            return SensedElement(role: role, title: title, frame: .zero)
        }

        return SensedElement(role: role, title: title, frame: CGRect(origin: position, size: size))
    }

    private func findElement(in element: AXUIElement, matching description: String, depth: Int) -> SensedElement? {
        guard depth < 25 else { return nil }

        if let sensed = describe(element), !sensed.title.isEmpty,
           sensed.title.lowercased().contains(description.lowercased()),
           sensed.frame.width > 0, sensed.frame.height > 0 {
            return sensed
        }

        var childrenRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
              let children = childrenRef as? [AXUIElement] else {
            return nil
        }

        for child in children {
            if let found = findElement(in: child, matching: description, depth: depth + 1) {
                return found
            }
        }
        return nil
    }

    private func stringAttribute(_ element: AXUIElement, _ attribute: CFString) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success else { return nil }
        return value as? String
    }

    private func pointAttribute(_ element: AXUIElement, _ attribute: CFString) -> CGPoint? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let axValue = value else { return nil }
        var point = CGPoint.zero
        guard CFGetTypeID(axValue) == AXValueGetTypeID(),
              AXValueGetValue((axValue as! AXValue), .cgPoint, &point) else { return nil }
        return point
    }

    private func sizeAttribute(_ element: AXUIElement, _ attribute: CFString) -> CGSize? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let axValue = value else { return nil }
        var size = CGSize.zero
        guard CFGetTypeID(axValue) == AXValueGetTypeID(),
              AXValueGetValue((axValue as! AXValue), .cgSize, &size) else { return nil }
        return size
    }
}
