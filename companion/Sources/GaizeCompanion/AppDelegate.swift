import AppKit
import ApplicationServices

/// Menu-bar entry point. Owns lifecycle of the six pieces:
/// GazeTracker (camera -> gaze point), Sensing (AX hit-test + dwell on the
/// target app), Overlay (highlight window), Output (TTS), VoiceCommands
/// (hands-free "select" / "explain"), Bridge (local WebSocket server to the
/// website).
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private let overlay = Overlay()
    private let bridge = Bridge()
    private let sensing = Sensing()
    private let gazeTracker = GazeTracker()
    private let output = Output()
    private let voiceCommands = VoiceCommands()

    func applicationDidFinishLaunching(_ notification: Notification) {
        requestAccessibilityPermission()

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
            guard let self else { return }
            self.bridge.send(event: "hover", element: element)
            self.output.speakExplanation(for: element)
        }

        sensing.onDwellConfirm = { [weak self] element in
            guard let self else { return }
            self.bridge.send(event: "action_completed", element: element)
            self.output.speakConfirmation(for: element)
        }

        voiceCommands.onSelectCommand = { [weak self] in
            self?.sensing.confirmCurrentElement()
        }

        voiceCommands.onExplainCommand = { [weak self] in
            self?.sensing.explainCurrentElement()
        }

        bridge.start()
        gazeTracker.start()
        voiceCommands.start()
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    /// AXIsProcessTrusted() alone never triggers macOS's permission dialog —
    /// it just silently returns false forever. Passing the prompt option is
    /// what actually adds Gaize to System Settings > Privacy & Security >
    /// Accessibility (unchecked) and shows the request dialog on first
    /// launch. The user still has to flip the checkbox there themselves and
    /// relaunch — macOS never allows a program to grant this itself.
    private func requestAccessibilityPermission() {
        let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options: NSDictionary = [promptKey: true]
        let trusted = AXIsProcessTrustedWithOptions(options)
        if !trusted {
            print("Gaize: Accessibility permission not yet granted. Enable Gaize in System Settings > Privacy & Security > Accessibility, then relaunch.")
        }
    }
}
