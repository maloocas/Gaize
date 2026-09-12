import AppKit
import ApplicationServices

/// Menu-bar entry point. Owns lifecycle of the six pieces:
/// GazeTracker (camera -> gaze point), Sensing (AX hit-test, tracks what's
/// currently gazed at, never speaks on its own), Overlay (highlight window),
/// Output (TTS), VoiceCommands ("explain"/"what is this" to hear about the
/// current element, "select" to confirm it, "open website" to launch the
/// site), Bridge (local WebSocket server to the website).
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
            print("AppDelegate: highlight requested for \"\(target)\"")
            if let frame = self.sensing.screenFrame(forElementDescribed: target) {
                print("AppDelegate: found frame \(frame) for \"\(target)\", showing overlay")
                self.overlay.highlight(frame)
            } else {
                print("AppDelegate: no element found matching \"\(target)\" in frontmost app")
            }
        }

        gazeTracker.onGazePoint = { [weak self] point in
            guard let self else { return }
            self.sensing.updateGaze(at: point)
        }

        sensing.onExplainRequested = { [weak self] element in
            guard let self else { return }
            self.bridge.send(event: "hover", element: element)
            self.output.speakExplanation(for: element)
        }

        sensing.onConfirmed = { [weak self] element in
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

        voiceCommands.onOpenWebsiteCommand = {
            print("AppDelegate: opening website at \(AppDelegate.websiteURL)")
            // Explicitly activate the browser once it opens the page - a
            // plain NSWorkspace.open can leave it opened but backgrounded
            // (e.g. if a matching tab already existed), which isn't "go
            // straight to it" from the user's point of view.
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            NSWorkspace.shared.open(AppDelegate.websiteURL, configuration: config) { app, error in
                if let error {
                    print("AppDelegate: failed to open website: \(error)")
                    return
                }
                app?.activate(options: [])
            }
        }

        voiceCommands.isMuted = { [weak self] in
            self?.output.isSpeaking ?? false
        }

        bridge.onDebugExplain = { [weak self] in
            self?.sensing.explainCurrentElement()
        }

        bridge.onSetLanguage = { [weak self] languageCode in
            guard let self, let language = AppLanguage(rawValue: languageCode) else {
                print("AppDelegate: unknown language code \"\(languageCode)\"")
                return
            }
            print("AppDelegate: switching language to \(language.rawValue)")
            AppSettings.shared.language = language
            self.voiceCommands.restartForLanguageChange()
        }

        bridge.start()
        gazeTracker.start()
        voiceCommands.start()
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    /// Resolved at compile time from this source file's location, so "open
    /// website" works regardless of where Gaize.app is launched from -
    /// relies on the repo layout staying companion/Sources/GaizeCompanion/
    /// with website/ as a sibling of companion/ (i.e. both directly under
    /// the Gaize repo root). This was off by one directory level before
    /// (pointed at companion/website/index.html, which doesn't exist) -
    /// NSWorkspace.shared.open silently did nothing for the bad path with
    /// no earlier error reporting, so it went unnoticed until adding the
    /// OpenConfiguration completion handler surfaced the real error.
    private static let websiteURL: URL = {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // GaizeCompanion
            .deletingLastPathComponent() // Sources
            .deletingLastPathComponent() // companion
            .deletingLastPathComponent() // Gaize (repo root)
            .appendingPathComponent("website/index.html")
    }()

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
