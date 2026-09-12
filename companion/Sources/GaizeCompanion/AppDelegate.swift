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
    private var highlightGeneration = 0
    private var globalClickMonitor: Any?

    /// Whether to pop up an on-screen keyboard after "compose" is
    /// confirmed - toggleable from the menu, since a teammate is building
    /// the real one to swap in for Dictation.showOnScreenKeyboard().
    private var showKeyboardOnCompose = true
    private var keyboardMenuItem: NSMenuItem?

    /// The field ("to_field" or "message_field") currently armed to
    /// receive the next spoken phrase as dictated text, and the AXUIElement
    /// to type it into. Set right after confirming that field, cleared
    /// after one dictation.
    private var dictationKey: String?
    private var dictationElement: AXUIElement?
    /// The To: field a contact name was last typed into - excluded from
    /// implicit recipient dictation, so speech after the name goes to the
    /// message body rather than adding more recipients.
    private var filledRecipientField: AXUIElement?
    private var lastWebsiteOpenAt = Date.distantPast

    func applicationDidFinishLaunching(_ notification: Notification) {
        requestAccessibilityPermission()

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        // 💤 asleep until "hey Gaize", 👁 while listening for commands.
        statusItem?.button?.title = "💤"

        let menu = NSMenu()
        let keyboardItem = NSMenuItem(title: "Show On-Screen Keyboard on Compose", action: #selector(toggleKeyboardOnCompose), keyEquivalent: "")
        keyboardItem.target = self
        keyboardItem.state = showKeyboardOnCompose ? .on : .off
        menu.addItem(keyboardItem)
        keyboardMenuItem = keyboardItem
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))
        statusItem?.menu = menu

        bridge.onHighlightRequest = { [weak self] target in
            guard let self else { return }
            self.highlightGeneration += 1
            let generation = self.highlightGeneration
            self.overlay.clear()
            self.highlight(target: target, attempt: 0, generation: generation)
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

        sensing.onConfirmed = { [weak self] element, axElement in
            guard let self else { return }
            // Remove the completed step's ring immediately. The website will
            // request the next target after it processes action_completed.
            self.overlay.clear()
            let key = KnowledgePack.matchedEntry(for: element)?.key
            self.bridge.send(event: "action_completed", element: element, key: key)
            self.output.speakConfirmation(for: element)
            print("AppDelegate: confirmed key=\(key ?? "nil") showKeyboardOnCompose=\(self.showKeyboardOnCompose)")

            if key == "compose", self.showKeyboardOnCompose {
                print("AppDelegate: launching on-screen keyboard")
                Dictation.showOnScreenKeyboard()
            }

            if key == "to_field" || key == "message_field" {
                print("AppDelegate: arming dictation for \(key ?? "?")")
                self.dictationKey = key
                self.dictationElement = axElement
            }
        }

        voiceCommands.onSelectCommand = { [weak self] in
            self?.sensing.confirmCurrentElement()
        }

        voiceCommands.onExplainCommand = { [weak self] in
            self?.sensing.explainCurrentElement()
        }

        voiceCommands.onOpenWebsiteCommand = { [weak self] in
            // The phrase path ("gaize open") and the standalone-"open" path
            // can both catch one utterance - open once.
            guard let self, Date().timeIntervalSince(self.lastWebsiteOpenAt) > 3 else { return }
            self.lastWebsiteOpenAt = Date()
            print("AppDelegate: opening website at \(AppDelegate.websiteURL)")
            self.output.speak("Opening Gaize.")
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

        voiceCommands.spokenTextNow = { [weak self] in
            self?.output.recentSpokenText
        }

        voiceCommands.onWebsiteAction = { [weak self] action in
            print("AppDelegate: website action \"\(action)\"")
            self?.bridge.sendAction(action)
        }

        // Armed explicitly (after selecting a text field / auto-advancing to
        // the message body), or implicitly whenever a new message's To:
        // field has focus - so just saying a contact's name fills it in.
        voiceCommands.isDictationModeActive = { [weak self] in
            guard let self else { return false }
            return self.dictationElement != nil || self.sensing.focusedRecipientField() != nil
        }

        voiceCommands.isRecipientPending = { [weak self] in
            guard let self, let field = self.sensing.focusedRecipientField() else { return false }
            return !(self.filledRecipientField.map { CFEqual($0, field) } ?? false)
        }

        voiceCommands.lingeringSpokenText = { [weak self] in
            self?.output.lingeringSpokenText
        }

        voiceCommands.onDictate = { [weak self] text in
            self?.performDictation(text)
        }

        voiceCommands.onSendCommand = { [weak self] in
            self?.performSend()
        }

        voiceCommands.onWake = { [weak self] announce in
            guard let self else { return }
            self.statusItem?.button?.title = "👁"
            if announce {
                self.output.speak(AppSettings.shared.language.wakeAcknowledgement)
            }
        }

        voiceCommands.onSleep = { [weak self] explicit in
            guard let self else { return }
            self.statusItem?.button?.title = "💤"
            if explicit {
                self.output.speak(AppSettings.shared.language.sleepAcknowledgement)
            }
        }

        bridge.onDebugWake = { [weak self] in
            self?.voiceCommands.wake()
        }

        voiceCommands.onQuestion = { [weak self] question in
            self?.answerQuestion(question)
        }

        bridge.onDebugQuestion = { [weak self] question in
            self?.answerQuestion(question)
        }

        bridge.onClearHighlight = { [weak self] in
            self?.overlay.clear()
        }

        bridge.onGoalComplete = { [weak self] title in
            guard let self else { return }
            print("AppDelegate: goal complete \"\(title)\"")
            self.overlay.clear()
            self.overlay.showBanner(title: "Goal complete", subtitle: title)
            // After "Message sent." finishes, rather than cutting it off.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                self.output.speak("Goal complete. Nice work!")
            }
        }

        bridge.onDebugSend = { [weak self] in
            self?.performSend()
        }

        bridge.onDebugDictate = { [weak self] text in
            self?.performDictation(text)
        }

        bridge.onDebugExplain = { [weak self] in
            self?.sensing.explainCurrentElement()
        }

        bridge.onDebugSelect = { [weak self] in
            self?.sensing.confirmCurrentElement()
        }

        bridge.onSetLanguage = { [weak self] languageCode in
            guard let self, let language = AppLanguage(rawValue: languageCode) else {
                print("AppDelegate: unknown language code \"\(languageCode)\"")
                return
            }
            // The website resends its current language on every connect,
            // including the common case where it's already what we're
            // set to - restarting the audio engine unnecessarily here
            // raced with startup once and left voice capture silently
            // dead for the rest of the session (no error, no more heard
            // transcripts). Only actually restart on a real change.
            guard AppSettings.shared.language != language else { return }
            print("AppDelegate: switching language to \(language.rawValue)")
            AppSettings.shared.language = language
            self.voiceCommands.restartForLanguageChange()
        }

        bridge.start()
        gazeTracker.start()
        voiceCommands.start()

        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: .leftMouseDown) { [weak self] _ in
            guard let self, let screenHeight = NSScreen.main?.frame.height else { return }
            let cocoaPoint = NSEvent.mouseLocation
            let axPoint = CGPoint(x: cocoaPoint.x, y: screenHeight - cocoaPoint.y)
            // Resolve the element during mouse-down, before the target app
            // handles the click and replaces controls such as Compose.
            self.sensing.reportPhysicalClick(at: axPoint)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let globalClickMonitor {
            NSEvent.removeMonitor(globalClickMonitor)
        }
    }

    /// Messages updates its accessibility tree asynchronously after an
    /// action (Compose revealing To:, Attach opening its picker, and so on).
    /// Retry briefly so the next tutorial ring follows the UI transition.
    /// A generation token prevents an older retry from replacing a newer
    /// highlight if the user advances quickly.
    private func highlight(target: String, attempt: Int, generation: Int) {
        guard generation == highlightGeneration else { return }
        print("AppDelegate: highlight requested for \"\(target)\" attempt=\(attempt + 1)")

        if let frame = sensing.screenFrame(forElementDescribed: target) {
            print("AppDelegate: found frame \(frame) for \"\(target)\", showing overlay")
            overlay.highlight(frame)
            return
        }

        guard attempt < 11 else {
            print("AppDelegate: no element found matching \"\(target)\" after retries")
            return
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            self?.highlight(target: target, attempt: attempt + 1, generation: generation)
        }
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    @objc private func toggleKeyboardOnCompose() {
        showKeyboardOnCompose.toggle()
        keyboardMenuItem?.state = showKeyboardOnCompose ? .on : .off
    }

    private func performDictation(_ spoken: String) {
        print("AppDelegate: dictation requested \"\(spoken)\" armed=\(dictationKey ?? "none") front=\(NSWorkspace.shared.frontmostApplication?.bundleIdentifier ?? "?")")
        // An empty To: field in a new message means the recipient comes
        // first - even if an earlier message's body is still armed (that
        // stale arming used to swallow the name). Skip only the To: field
        // we just filled, in case its value doesn't reflect the contact.
        if let recipientField = sensing.focusedRecipientField(),
           !(filledRecipientField.map { CFEqual($0, recipientField) } ?? false) {
            dictationKey = "to_field"
            dictationElement = recipientField
        }
        guard let axElement = dictationElement else { return }
        // A contact name is a few words at most. Longer utterances are
        // background speech (music, people talking nearby) that happened to
        // end while the To: field had focus - never type those as a recipient.
        if dictationKey == "to_field", spoken.split(separator: " ").count > 4 {
            print("AppDelegate: ignoring \"\(spoken)\" for To: - too long to be a contact name")
            return
        }
        // Contact names read better capitalized ("lucas ma" -> "Lucas Ma");
        // message text is typed as heard.
        let text = dictationKey == "to_field" ? spoken.capitalized : spoken
        print("AppDelegate: dictating \"\(text)\" into \(dictationKey ?? "?")")

        // Same root cause as the synthesized-click bug: a posted keystroke
        // event goes to whatever app is actually frontmost, not necessarily
        // the one that owns the target element. Activate it first.
        var pid: pid_t = 0
        AXUIElementGetPid(axElement, &pid)
        if let ownerApp = NSRunningApplication(processIdentifier: pid), !ownerApp.isActive {
            print("AppDelegate: activating dictation target app before typing (was backgrounded)")
            ownerApp.activate(options: [])
            Thread.sleep(forTimeInterval: 0.3)
        }

        sensing.click(axElement)
        Thread.sleep(forTimeInterval: 0.15)
        Dictation.type(text, into: axElement)

        if dictationKey == "to_field" {
            // Accept the top contact-autocomplete suggestion - Return only
            // does this here, never on the message body field, where it
            // would send prematurely.
            // Messages looks contacts up asynchronously - a Return sent the
            // instant the name is typed arrives before any suggestion exists
            // and does nothing (verified: the "Lucas Ma" suggestion was left
            // sitting open, unaccepted). Give the lookup time to populate.
            Thread.sleep(forTimeInterval: 0.8)
            Dictation.confirmAutocomplete()
            filledRecipientField = axElement
            // Moves the website's goal on, so its highlight follows to the
            // message box.
            bridge.sendCompleted(title: "to:")

            // Auto-advance: move straight to the message body and arm it
            // for the next thing said, instead of making the user look at
            // and separately "select" it - once a recipient is picked, the
            // next natural thing is to say the message.
            Thread.sleep(forTimeInterval: 0.2)
            if let messageField = sensing.focusElement(forElementDescribed: "message") {
                print("AppDelegate: auto-advanced to message field, arming dictation")
                dictationKey = "message_field"
                dictationElement = messageField
                return
            }
        }

        if dictationKey == "message_field" {
            bridge.sendCompleted(title: "message")
        }
        dictationKey = nil
        dictationElement = nil
    }

    /// Speaks the AI's answer, then starts the goal that teaches it so the
    /// website highlights each step in Messages.
    private func answerQuestion(_ question: String) {
        let language = AppSettings.shared.language
        print("AppDelegate: question \"\(question)\"")
        Assistant.ask(question,
                      lookingAt: sensing.currentSensed?.title,
                      frontApp: NSWorkspace.shared.frontmostApplication?.localizedName,
                      language: language) { [weak self] reply in
            guard let self else { return }
            guard let reply else {
                self.output.speak(language.assistantUnavailable)
                return
            }
            print("AppDelegate: answer \"\(reply.answer)\" goal=\(reply.goalID ?? "none")")
            self.output.speak(reply.answer)
            if let goal = reply.goalID {
                self.startGoalOnWebsite(goal)
            }
        }
    }

    /// Opens the website in the background if needed (the user stays in
    /// Messages), then tells it to begin the goal - its first step's
    /// highlight lands in Messages.
    private func startGoalOnWebsite(_ goalID: String, attempt: Int = 0) {
        if bridge.isConnected {
            bridge.sendAction("start_goal:\(goalID)")
            return
        }
        if attempt == 0 {
            let config = NSWorkspace.OpenConfiguration()
            config.activates = false
            NSWorkspace.shared.open(AppDelegate.websiteURL, configuration: config) { _, error in
                if let error { print("AppDelegate: failed to open website: \(error)") }
            }
        }
        guard attempt < 10 else {
            print("AppDelegate: website never connected, can't start goal \(goalID)")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.startGoalOnWebsite(goalID, attempt: attempt + 1)
        }
    }

    /// "send": focuses Messages' message body and presses Return, which is
    /// how Messages sends (there's no send button). Refuses on an empty body
    /// so a stray "send" can't do anything surprising.
    private func performSend() {
        let language = AppSettings.shared.language
        guard let messages = NSWorkspace.shared.runningApplications.first(where: {
            $0.bundleIdentifier == "com.apple.MobileSMS"
        }) else {
            print("AppDelegate: send - Messages not running")
            return
        }
        if !messages.isActive {
            messages.activate(options: [])
            Thread.sleep(forTimeInterval: 0.3)
        }
        guard let body = sensing.focusElement(forElementDescribed: "message") else {
            print("AppDelegate: send - no message field found")
            output.speak(language.nothingToSend)
            return
        }
        var value: CFTypeRef?
        AXUIElementCopyAttributeValue(body, kAXValueAttribute as CFString, &value)
        let text = ((value as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        print("AppDelegate: send - message field value \"\(text)\"")
        guard !text.isEmpty else {
            output.speak(language.nothingToSend)
            return
        }
        Thread.sleep(forTimeInterval: 0.15)
        Dictation.pressReturnToSend()
        dictationKey = nil
        dictationElement = nil
        filledRecipientField = nil
        output.speak(language.sentConfirmation)
        bridge.sendCompleted(title: "send")
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
