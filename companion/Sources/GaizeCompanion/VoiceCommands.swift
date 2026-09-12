import Speech
import AVFoundation

/// Always-listening keyword spotting so the whole interaction can stay
/// hands-free: say "select" / "click" to confirm the currently gazed-at
/// element immediately (instead of waiting out the dwell timer), or
/// "explain" / "what is this" to replay its explanation. Keywords and the
/// recognizer's locale follow AppSettings.shared.language - call
/// restartForLanguageChange() after changing it.
///
/// Needs Microphone + Speech Recognition permission (NSMicrophoneUsageDescription
/// / NSSpeechRecognitionUsageDescription in Info.plist once this is packaged
/// as a signed .app — see beaverlab's packaging/ for the pattern).
final class VoiceCommands {
    var onSelectCommand: (() -> Void)?
    var onExplainCommand: (() -> Void)?
    var onOpenWebsiteCommand: (() -> Void)?
    /// Fired with "home" / "back" / "learn" / "quiz" / "scenario" - direct
    /// voice navigation of the website's own buttons, sent to it as a
    /// bridge message rather than routed through gaze/AX at all.
    var onWebsiteAction: ((String) -> Void)?
    /// Checked before acting on any recognized command - lets the caller
    /// mute us while Output is speaking, to avoid hearing our own TTS.
    var isMuted: (() -> Bool)?

    private var recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var lastHandledSegmentCount = 0
    private var isAuthorized = false

    /// On-device speech recognition finalizes a result (and this app then
    /// restarts the recognizer) after almost any short pause - often after
    /// a single word - so a multi-word phrase like "open website" can land
    /// as two separate, isolated results. Keeping a short rolling window of
    /// recently heard text (instead of only ever looking at one result at a
    /// time) lets phrase matching span those restarts.
    private var recentTranscript: [(text: String, at: Date)] = []
    private let recentTranscriptWindow: TimeInterval = 4.0

    func start() {
        SFSpeechRecognizer.requestAuthorization { [weak self] authStatus in
            guard authStatus == .authorized else {
                print("VoiceCommands: speech recognition not authorized")
                return
            }
            DispatchQueue.main.async {
                self?.isAuthorized = true
                self?.startListening()
            }
        }
    }

    func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }

    /// Call after changing AppSettings.shared.language - swaps in a
    /// recognizer for the new locale and restarts the listening loop.
    func restartForLanguageChange() {
        guard isAuthorized else { return }
        print("VoiceCommands: restarting for language \(AppSettings.shared.language.rawValue)")
        stop()
        startListening()
    }

    private func startListening() {
        let language = AppSettings.shared.language
        guard let recognizer = SFSpeechRecognizer(locale: language.locale), recognizer.isAvailable else {
            print("VoiceCommands: recognizer unavailable for \(language.rawValue)")
            return
        }
        self.recognizer = recognizer

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request
        lastHandledSegmentCount = 0

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            print("VoiceCommands: failed to start audio engine: \(error)")
            return
        }

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self, let result else { return }
            self.handle(result)

            if error != nil || result.isFinal {
                // Restart the recognition window so we keep listening
                // continuously rather than stopping after one utterance.
                self.stop()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                    self.startListening()
                }
            }
        }
    }

    private func handle(_ result: SFSpeechRecognitionResult) {
        let segments = result.bestTranscription.segments
        guard segments.count > lastHandledSegmentCount else { return }

        let newWords = segments[lastHandledSegmentCount...]
            .map { $0.substring.lowercased() }
            .joined(separator: " ")
        lastHandledSegmentCount = segments.count

        print("VoiceCommands: heard \"\(newWords)\"")

        if isMuted?() == true {
            print("VoiceCommands: muted (Output is speaking), ignoring \"\(newWords)\"")
            return
        }

        let now = Date()
        recentTranscript.append((newWords, now))
        recentTranscript.removeAll { now.timeIntervalSince($0.at) > recentTranscriptWindow }
        let recentText = recentTranscript.map(\.text).joined(separator: " ")

        let language = AppSettings.shared.language

        if language.openWebsiteKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onOpenWebsiteCommand?()
        } else if language.homeKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onWebsiteAction?("home")
        } else if language.backToGoalsKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onWebsiteAction?("back")
        } else if language.takeQuizKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onWebsiteAction?("quiz")
        } else if language.tryScenarioKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onWebsiteAction?("scenario")
        } else if language.learnKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onWebsiteAction?("learn")
        } else if language.selectKeywords.contains(where: newWords.contains) {
            onSelectCommand?()
        } else if language.explainKeywords.contains(where: recentText.contains) {
            recentTranscript.removeAll()
            onExplainCommand?()
        }
    }
}
