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
    func highlight(_ axFrame: CGRect, color: NSColor = .systemBlue) {
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
        ringView?.strokeColor = color
        ringView?.needsDisplay = true
        window?.orderFrontRegardless()
    }

    func clear() {
        window?.orderOut(nil)
    }

    private var banner: NSWindow?

    /// A brief "Goal complete" style popup, centered near the top of the
    /// screen over whatever app the user is in - they're usually in
    /// Messages, not looking at the website, when a goal finishes.
    func showBanner(title: String, subtitle: String, duration: TimeInterval = 3.5) {
        guard let screen = NSScreen.main else { return }
        banner?.orderOut(nil)

        let size = CGSize(width: 420, height: 110)
        let frame = CGRect(
            x: screen.frame.midX - size.width / 2,
            y: screen.frame.maxY - size.height - 140,
            width: size.width, height: size.height
        )
        let panel = NSWindow(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.level = .screenSaver
        panel.ignoresMouseEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary]
        panel.hasShadow = true

        let background = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        background.material = .hudWindow
        background.state = .active
        background.wantsLayer = true
        background.layer?.cornerRadius = 18
        background.layer?.masksToBounds = true

        let titleLabel = NSTextField(labelWithString: "✓  " + title)
        titleLabel.font = .systemFont(ofSize: 24, weight: .bold)
        titleLabel.textColor = .systemGreen
        let subtitleLabel = NSTextField(labelWithString: subtitle)
        subtitleLabel.font = .systemFont(ofSize: 15, weight: .medium)
        subtitleLabel.textColor = .labelColor
        subtitleLabel.lineBreakMode = .byTruncatingTail

        let stack = NSStackView(views: [titleLabel, subtitleLabel])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 6
        stack.translatesAutoresizingMaskIntoConstraints = false
        background.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: background.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: background.centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: background.widthAnchor, constant: -32),
        ])

        panel.contentView = background
        panel.alphaValue = 0
        panel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { $0.duration = 0.2; panel.animator().alphaValue = 1 }
        banner = panel

        DispatchQueue.main.asyncAfter(deadline: .now() + duration) { [weak self, weak panel] in
            guard let panel else { return }
            NSAnimationContext.runAnimationGroup({ $0.duration = 0.3; panel.animator().alphaValue = 0 }) {
                panel.orderOut(nil)
                if self?.banner === panel { self?.banner = nil }
            }
        }
    }
}

private final class RingView: NSView {
    var strokeColor: NSColor = .systemBlue

    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 2, dy: 2)
        let path = NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6)
        path.lineWidth = 4
        strokeColor.setStroke()
        path.stroke()
    }
}
