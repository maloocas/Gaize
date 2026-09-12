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

    /// Fired by a "select"/"click"/"choose"/"confirm" voice command.
    @discardableResult
    func confirmCurrentElement() -> SensedElement? {
        guard let axElement = currentAXElement, let sensed = currentSensed else { return nil }
        AXUIElementPerformAction(axElement, kAXPressAction as CFString)
        onConfirmed?(sensed)
        resetCurrent()
        return sensed
    }

    /// Fired by an "explain"/"what is this" voice command.
    @discardableResult
    func explainCurrentElement() -> SensedElement? {
        guard let sensed = currentSensed else { return nil }
        onExplainRequested?(sensed)
        return sensed
    }

    /// Resolve a human-readable target description (from the website, e.g.
    /// "send button") to an on-screen frame, by walking the frontmost app's
    /// AX tree for a matching title/description. Used to draw the overlay.
    func screenFrame(forElementDescribed description: String) -> CGRect? {
        guard AXIsProcessTrusted(),
              let frontApp = NSWorkspace.shared.frontmostApplication else {
            print("Sensing.screenFrame: not trusted or no frontmost app")
            return nil
        }

        print("Sensing.screenFrame: searching \"\(frontApp.localizedName ?? "?")\" for \"\(description)\"")
        let appElement = AXUIElementCreateApplication(frontApp.processIdentifier)
        let found = findElement(in: appElement, matching: description, depth: 0)
        if found == nil {
            print("Sensing.screenFrame: no match for \"\(description)\" in \(frontApp.localizedName ?? "?")")
        }
        return found?.frame
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
