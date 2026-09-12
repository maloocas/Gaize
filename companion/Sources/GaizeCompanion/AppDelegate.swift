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
    /// The website step currently highlighted in Messages. Unrelated mouse
    /// clicks must not clear this target or advance the tutorial.
    private var highlightedTarget: String?
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
    /// Set once we've actually opened the website URL - distinct from
    /// bridge.isConnected (which drops on a background-tab-throttled
    /// WebSocket well before the tab itself closes) and from "is some
    /// browser window running" (true almost always, regardless of whether
    /// it's ever loaded our page).
    private var hasOpenedWebsite = false

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
            self.highlightedTarget = target
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
            let key = KnowledgePack.matchedEntry(for: element)?.key
            // Say what was just pressed on every click, whether or not it's
            // the lesson's current step - the user is hands-free and often
            // not reading the screen, so an unannounced click is invisible
            // to them. Only the tutorial bookkeeping below is gated.
            self.output.speakConfirmation(for: element)
            guard self.matchesHighlightedTarget(element, key: key) else {
                print("AppDelegate: ignoring unrelated click on \(element.title.isEmpty ? element.role : element.title), current target=\(self.highlightedTarget ?? "none")")
                return
            }
            // Remove the completed step's ring immediately. The website will
            // request the next target after it processes action_completed.
            self.overlay.clear()
            self.bridge.send(event: "action_completed", element: element, key: key)
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
            // Already open (e.g. coming back after a goal in Messages): switch
            // to it rather than opening the file URL again, which would add
            // a second tab. Gated on hasOpenedWebsite, which we set ourselves
            // right after actually opening it - not on the browser process
            // merely running (any browser window at all made bringBrowserToFront
            // "succeed" and skip opening the site outright, so "open gaize"
            // silently did nothing the very first time in a session) and not
            // on bridge.isConnected (a goal can run long enough in Messages
            // that the tab's WebSocket gets dropped by background-tab
            // throttling well before the tab itself closes - the website
            // reconnects on its own, without losing its state, but only if
            // nothing reloads it out from under that state in the meantime).
            if self.hasOpenedWebsite, self.bringBrowserToFront() {
                return
            }
            // Explicitly activate the browser once it opens the page - a
            // plain NSWorkspace.open can leave it opened but backgrounded
            // (e.g. if a matching tab already existed), which isn't "go
            // straight to it" from the user's point of view.
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            NSWorkspace.shared.open(AppDelegate.websiteURL, configuration: config) { [weak self] app, error in
                if let error {
                    print("AppDelegate: failed to open website: \(error)")
                    return
                }
                self?.hasOpenedWebsite = true
                app?.activate(options: [])
            }
        }

        voiceCommands.isQuizActive = { [weak self] in
            let mode = self?.bridge.websiteMode
            return mode == "quiz" || mode == "feedback"
        }

        voiceCommands.onQuizSpeech = { [weak self] text in
            self?.bridge.sendAction("quiz_say:\(text)")
        }

        voiceCommands.onOpenMessagesCommand = { [weak self] in
            guard let self else { return }
            print("AppDelegate: opening Messages")
            self.output.speak(AppSettings.shared.language.openingMessages)
            guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.MobileSMS") else {
                print("AppDelegate: Messages app not found")
                return
            }
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            NSWorkspace.shared.openApplication(at: url, configuration: config) { app, error in
                if let error {
                    print("AppDelegate: failed to open Messages: \(error)")
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
            guard let self else { return }
            print("AppDelegate: website action \"\(action)\"")
            if action.hasPrefix("open_goal:") || action == "quiz" || action == "scenario" {
                // Saying a goal's name should land on that goal's page -
                // open the site if needed, and bring the browser forward.
                self.sendToWebsite(action, bringToFront: true)
            } else {
                self.bridge.sendAction(action)
            }
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
            self?.highlightedTarget = nil
            self?.overlay.clear()
        }

        bridge.onGoalComplete = { [weak self] title in
            guard let self else { return }
            print("AppDelegate: goal complete \"\(title)\"")
            self.highlightedTarget = nil
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

        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: .leftMouseDown) { [weak self] event in
            guard let self, let screenHeight = NSScreen.main?.frame.height else { return }
            // Skip Gaize's own "select" clicks - only the user's count here.
            if event.cgEvent?.getIntegerValueField(.eventSourceUserData) == Sensing.syntheticClickTag { return }
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

    /// The website advances only when the selected element matches its
    /// current step. Keep that same boundary in the companion so an
    /// unrelated physical click cannot clear the user's current target.
    private func matchesHighlightedTarget(_ element: SensedElement, key: String?) -> Bool {
        guard let target = highlightedTarget?.lowercased(), !target.isEmpty else {
            return true
        }
        if target == "*" { return true }

        let title = element.title.lowercased()
        let canonicalKey: String
        switch key {
        case "to_field": canonicalKey = "to:"
        case "message_field": canonicalKey = "message"
        case let key where key != nil: canonicalKey = key!.replacingOccurrences(of: "_", with: " ")
        default: canonicalKey = ""
        }
        return title.contains(target) || canonicalKey == target
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

            // No auto-advance: arming and clicking the message field here
            // used to happen without the user ever asking for it - Gaize
            // must not click anything the user didn't gaze-select or say
            // "select" on. The user now says the message once they've
            // looked at and selected the message box themselves, same as
            // any other target.
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
            NSWorkspace.shared.open(AppDelegate.websiteURL, configuration: config) { [weak self] _, error in
                if let error {
                    print("AppDelegate: failed to open website: \(error)")
                    return
                }
                self?.hasOpenedWebsite = true
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

    /// Sends a voice_action to the website, opening it first if it isn't
    /// connected. With bringToFront, an already-open site's browser is
    /// activated rather than reopened (a file URL would add another tab).
    private func sendToWebsite(_ action: String, bringToFront: Bool, attempt: Int = 0) {
        if bridge.isConnected {
            bridge.sendAction(action)
            if bringToFront, attempt == 0 {
                bringBrowserToFront()
            }
            return
        }
        if attempt == 0 {
            let config = NSWorkspace.OpenConfiguration()
            config.activates = bringToFront
            NSWorkspace.shared.open(AppDelegate.websiteURL, configuration: config) { [weak self] _, error in
                if let error {
                    print("AppDelegate: failed to open website: \(error)")
                    return
                }
                self?.hasOpenedWebsite = true
            }
        }
        guard attempt < 10 else {
            print("AppDelegate: website never connected, dropping \(action)")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.sendToWebsite(action, bringToFront: bringToFront, attempt: attempt + 1)
        }
    }

    /// Activates the browser that opens the website (the default browser
    /// for file URLs), if it's already running, so the caller doesn't open
    /// another tab. Returns whether a running browser was found and
    /// activated - false means the caller should open the page fresh.
    @discardableResult
    private func bringBrowserToFront() -> Bool {
        guard let browserURL = NSWorkspace.shared.urlForApplication(toOpen: AppDelegate.websiteURL),
              let bundleID = Bundle(url: browserURL)?.bundleIdentifier,
              let browser = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first else { return false }
        browser.activate(options: [])
        return true
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
        guard let body = sensing.messageBodyField() else {
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
