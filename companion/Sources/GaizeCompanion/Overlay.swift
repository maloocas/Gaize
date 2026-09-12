import AppKit

/// Transparent, click-through, always-on-top window used to draw a highlight
/// ring around whatever on-screen element the website wants the user to go
/// to next.
final class Overlay {
    private var window: NSWindow?
    private var ringView: RingView?
    private let padding: CGFloat = 8

    /// `frame` is in AX/Quartz coordinates (top-left origin) — convert to
    /// Cocoa (bottom-left origin) before handing it to NSWindow.
    func highlight(_ axFrame: CGRect) {
        guard axFrame != .zero, let screen = NSScreen.main else { return }
        let screenHeight = screen.frame.height

        var cocoaFrame = CGRect(
            x: axFrame.minX - padding,
            y: screenHeight - axFrame.maxY - padding,
            width: axFrame.width + padding * 2,
            height: axFrame.height + padding * 2
        )

        print("Overlay: axFrame=\(axFrame) -> cocoaFrame=\(cocoaFrame), screen=\(screen.frame)")

        // Defensive clamp - keep the ring fully on-screen regardless of any
        // upstream frame quirk from the source app's AX tree.
        cocoaFrame = cocoaFrame.intersection(screen.frame)

        if window == nil {
            let panel = NSWindow(
                contentRect: cocoaFrame,
                styleMask: [.borderless],
                backing: .buffered,
                defer: false
            )
            panel.isOpaque = false
            panel.backgroundColor = .clear
            panel.level = .screenSaver
            panel.ignoresMouseEvents = true
            panel.collectionBehavior = [.canJoinAllSpaces, .stationary]
            panel.hasShadow = false

            let view = RingView(frame: NSRect(origin: .zero, size: cocoaFrame.size))
            panel.contentView = view

            window = panel
            ringView = view
        }

        window?.setFrame(cocoaFrame, display: true)
        ringView?.frame = NSRect(origin: .zero, size: cocoaFrame.size)
        ringView?.needsDisplay = true
        window?.orderFrontRegardless()
    }

    func clear() {
        window?.orderOut(nil)
    }
}

private final class RingView: NSView {
    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 2, dy: 2)
        let path = NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6)
        path.lineWidth = 4
        NSColor.systemBlue.setStroke()
        path.stroke()
    }
}
