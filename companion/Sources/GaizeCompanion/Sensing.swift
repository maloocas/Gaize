import AppKit
import ApplicationServices

struct SensedElement {
    let role: String
    let title: String
    let frame: CGRect
}

/// AX hit-testing on whatever's under the gaze point. Gaze settling on a new
/// element explains it exactly once — no auto-repeat, no auto-confirm timer.
/// After that, it's entirely voice-driven: say "explain" to hear it again,
/// "select" to confirm/press it, whenever the user is ready.
final class Sensing {
    var onDwellExplain: ((SensedElement) -> Void)?
    var onDwellConfirm: ((SensedElement) -> Void)?

    private let systemWide = AXUIElementCreateSystemWide()
    private var currentAXElement: AXUIElement?
    private var currentSensed: SensedElement?
    private var dwellStart: Date?
    private var hasExplainedCurrent = false

    private let explainDwellSeconds: TimeInterval = 0.4

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
            resetDwell()
            return
        }

        // Compare by AX element identity, not a rebuilt role/title/frame
        // string — tiny gaze jitter can make the same on-screen button
        // report marginally different frame values between frames, which
        // was causing the explanation to needlessly re-fire.
        let isSameElement = currentAXElement.map { CFEqual($0, axElement) } ?? false

        if !isSameElement {
            print("Sensing: new element role=\(sensed.role) title=\"\(sensed.title)\"")
            currentAXElement = axElement
            currentSensed = sensed
            dwellStart = Date()
            hasExplainedCurrent = false
            return
        }

        guard let start = dwellStart else { return }
        let elapsed = Date().timeIntervalSince(start)

        if !hasExplainedCurrent, elapsed >= explainDwellSeconds {
            hasExplainedCurrent = true
            print("Sensing: EXPLAIN firing for role=\(sensed.role) title=\"\(sensed.title)\"")
            onDwellExplain?(sensed)
        }
    }

    /// Fired by a "select"/"click"/"choose"/"confirm" voice command.
    @discardableResult
    func confirmCurrentElement() -> SensedElement? {
        guard let axElement = currentAXElement, let sensed = currentSensed else { return nil }
        AXUIElementPerformAction(axElement, kAXPressAction as CFString)
        onDwellConfirm?(sensed)
        resetDwell()
        return sensed
    }

    /// Fired directly by an "explain" voice command, to replay the
    /// explanation without waiting for the dwell timer to retrigger it.
    @discardableResult
    func explainCurrentElement() -> SensedElement? {
        guard let sensed = currentSensed else { return nil }
        onDwellExplain?(sensed)
        return sensed
    }

    /// Resolve a human-readable target description (from the website, e.g.
    /// "send button") to an on-screen frame, by walking the frontmost app's
    /// AX tree for a matching title/description. Used to draw the overlay.
    func screenFrame(forElementDescribed description: String) -> CGRect? {
        guard AXIsProcessTrusted(),
              let frontApp = NSWorkspace.shared.frontmostApplication else { return nil }

        let appElement = AXUIElementCreateApplication(frontApp.processIdentifier)
        return findElement(in: appElement, matching: description, depth: 0)?.frame
    }

    private func resetDwell() {
        currentAXElement = nil
        currentSensed = nil
        dwellStart = nil
        hasExplainedCurrent = false
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
        guard depth < 8 else { return nil }

        if let sensed = describe(element), !sensed.title.isEmpty,
           sensed.title.lowercased().contains(description.lowercased()) {
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
