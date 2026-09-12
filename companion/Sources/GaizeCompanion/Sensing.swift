import Foundation
import CoreGraphics
import ApplicationServices

struct SensedElement {
    let role: String
    let title: String
    let frame: CGRect
}

/// AX hit-testing on the target app (Messages, to start) + dwell-time state
/// machine: gaze settles on an element -> explain; settles again -> confirm.
final class Sensing {
    var onDwellExplain: ((SensedElement) -> Void)?
    var onDwellConfirm: ((SensedElement) -> Void)?

    private var currentElement: SensedElement?
    private var dwellStart: Date?
    private var hasExplainedCurrent = false

    private let explainDwellSeconds: TimeInterval = 0.4
    private let confirmDwellSeconds: TimeInterval = 0.8

    /// Called on every gaze-tracker frame with the current screen-space gaze point.
    func updateGaze(at point: CGPoint) {
        // TODO: AXUIElementCopyElementAtPosition(systemWideElement, point.x, point.y, &element)
        // then read kAXRoleAttribute / kAXTitleAttribute / kAXFrameAttribute.
        // Drive dwellStart / hasExplainedCurrent off whether the hit element
        // changed, and fire onDwellExplain / onDwellConfirm at the thresholds above.
    }

    /// Resolve a human-readable target description (from the website, e.g.
    /// "the send button") to an on-screen frame, by walking the target app's
    /// AX tree for a matching role/title. Used to draw the "go here" overlay.
    func screenFrame(forElementDescribed description: String) -> CGRect? {
        // TODO
        return nil
    }
}
