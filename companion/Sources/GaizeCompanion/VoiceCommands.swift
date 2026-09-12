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
    /// Checked before acting on any recognized command - lets the caller
    /// mute us while Output is speaking, to avoid hearing our own TTS.
    var isMuted: (() -> Bool)?

    private var recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var lastHandledSegmentCount = 0
    private var isAuthorized = false

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

        if isMuted?() == true {
            print("VoiceCommands: muted (Output is speaking), ignoring \"\(newWords)\"")
            return
        }

        let language = AppSettings.shared.language

        if language.openWebsiteKeywords.contains(where: newWords.contains) {
            onOpenWebsiteCommand?()
        } else if language.selectKeywords.contains(where: newWords.contains) {
            onSelectCommand?()
        } else if language.explainKeywords.contains(where: newWords.contains) {
            onExplainCommand?()
        }
    }
}
