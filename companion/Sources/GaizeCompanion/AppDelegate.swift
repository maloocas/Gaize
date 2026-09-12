import AppKit

/// Menu-bar entry point. Owns lifecycle of the four pieces:
/// GazeTracker (camera -> gaze point), Sensing (AX hit-test on the target app),
/// Overlay (highlight window), Bridge (local WebSocket server to the website).
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private let overlay = Overlay()
    private let bridge = Bridge()
    private let sensing = Sensing()
    private let gazeTracker = GazeTracker()

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem?.button?.title = "👁"

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        statusItem?.menu = menu

        bridge.onHighlightRequest = { [weak self] target in
            guard let self else { return }
            if let frame = self.sensing.screenFrame(forElementDescribed: target) {
                self.overlay.highlight(frame)
            }
        }

        gazeTracker.onGazePoint = { [weak self] point in
            guard let self else { return }
            self.sensing.updateGaze(at: point)
        }

        sensing.onDwellExplain = { [weak self] element in
            self?.bridge.send(event: "hover", element: element)
            // TODO: speak element.explanation via TTS / pre-recorded clip
        }

        sensing.onDwellConfirm = { [weak self] element in
            self?.bridge.send(event: "action_completed", element: element)
            // TODO: perform the actual AX action on the element
        }

        bridge.start()
        gazeTracker.start()
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }
}
