import AppKit

/// Transparent, click-through, always-on-top window used to draw a highlight
/// ring/arrow around whatever on-screen element the website wants the user
/// to go to next.
final class Overlay {
    private var window: NSWindow?

    func highlight(_ frame: CGRect) {
        // TODO: create/reuse a borderless NSWindow at screen level
        // (.screenSaver or above), ignoresMouseEvents = true, draw a
        // pulsing ring at `frame` in its content view.
    }

    func clear() {
        window?.orderOut(nil)
    }
}
