import Speech
import AVFoundation

/// Always-listening keyword spotting so the whole interaction can stay
/// hands-free: "select" clicks wherever the user is looking, "explain" /
/// "what is this" describes it, plus website navigation and dictation.
/// Keywords and the recognizer's locale follow AppSettings.shared.language -
/// call restartForLanguageChange() after changing it.
///
/// Needs Microphone + Speech Recognition permission (Info.plist usage
/// strings, and launching from the signed Gaize.app bundle).
final class VoiceCommands {
    var onSelectCommand: (() -> Void)?
    var onExplainCommand: (() -> Void)?
    var onOpenWebsiteCommand: (() -> Void)?
    /// Saying just "send" (the whole utterance) sends the Messages draft.
    var onSendCommand: (() -> Void)?
    /// Fired with "home" / "back" / "learn" / "quiz" / "scenario" - direct
    /// voice navigation of the website's own buttons.
    var onWebsiteAction: ((String) -> Void)?
    /// True while Output is speaking - most commands are ignored then, so
    /// the mic doesn't act on our own TTS coming back through the speakers.
    var isMuted: (() -> Bool)?
    /// What Output is saying (or just said) - lets "select" and dictation
    /// still work mid-speech, by only ignoring words that are our own
    /// speech echoing back rather than everything.
    var spokenTextNow: (() -> String?)?
    /// When true, the next full utterance that isn't a command is typed
    /// into the armed text field via onDictate.
    var isDictationModeActive: (() -> Bool)?
    var onDictate: ((String) -> Void)?

    private var recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var isAuthorized = false

    /// Words of the current recognition session as last seen. Partial
    /// results revise earlier words ("sell" -> "select"), they don't only
    /// append - diffing against this catches revisions. The old "only look
    /// at segments past the last count" logic silently dropped them.
    private var lastSegments: [String] = []
    /// Segment indices in this session that already fired a select, so a
    /// later revision of the same word ("select" -> "selected") can't click
    /// twice.
    private var firedSelectIndices: Set<Int> = []
    private var lastSelectAt = Date.distantPast
    private var commandFiredThisSession = false
    private var segmentArrivals: [Date] = []
    private var sendFiredThisSession = false
    private var pendingSend: DispatchWorkItem?
    private let phrasePause: TimeInterval = 0.7
    private let sendSilence: TimeInterval = 1.0

    /// Recognition often finalizes after a single word, so a multi-word
    /// phrase like "open website" can land as two isolated sessions - a
    /// short rolling window of recent text lets phrases span them.
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

    func restartForLanguageChange() {
        guard isAuthorized else { return }
        print("VoiceCommands: restarting for language \(AppSettings.shared.language.rawValue)")
        stop()
        startListening()
    }

    private func restartSoon(after delay: TimeInterval = 0.1) {
        stop()
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.startListening()
        }
    }

    private func startListening() {
        let language = AppSettings.shared.language
        guard let recognizer = SFSpeechRecognizer(locale: language.locale), recognizer.isAvailable else {
            print("VoiceCommands: recognizer unavailable for \(language.rawValue), retrying")
            restartSoon(after: 1.0)
            return
        }
        self.recognizer = recognizer

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request
        lastSegments = []
        firedSelectIndices = []
        commandFiredThisSession = false
        segmentArrivals = []
        sendFiredThisSession = false
        pendingSend?.cancel()
        pendingSend = nil

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        // installTap traps if a tap is already installed on this bus;
        // removeTap is a safe no-op when there isn't one.
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            print("VoiceCommands: failed to start audio engine: \(error), retrying")
            restartSoon(after: 1.0)
            return
        }

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let result {
                self.handle(result)
            }
            // Must restart on an error even when there's no result - the
            // recognizer ends a session with a result-less error after a
            // stretch of silence (and at its ~1 minute session cap). The
            // old `guard let result else { return }` skipped the restart in
            // exactly that case, so listening silently died until relaunch.
            if error != nil || result?.isFinal == true {
                self.restartSoon()
            }
        }
    }

    private func handle(_ result: SFSpeechRecognitionResult) {
        let segments = result.bestTranscription.segments.map { $0.substring.lowercased() }
        let language = AppSettings.shared.language

        var firstChanged = 0
        while firstChanged < segments.count, firstChanged < lastSegments.count,
              segments[firstChanged] == lastSegments[firstChanged] {
            firstChanged += 1
        }
        lastSegments = segments

        // Wall-clock arrival of each word - a revised word keeps its slot's
        // original time. Used to split speech into pause-separated phrases.
        let arrivedAt = Date()
        segmentArrivals = segments.indices.map { i in
            i < segmentArrivals.count ? segmentArrivals[i] : arrivedAt
        }
        checkForSend(segments, isFinal: result.isFinal)
        // Words after a send (background noise) mustn't be dictated or acted on.
        if sendFiredThisSession { return }

        // Dictation takes the whole finished utterance, so a multi-word name
        // or message isn't cut off at its first word.
        if result.isFinal, isDictationModeActive?() == true, !commandFiredThisSession {
            let full = segments.joined(separator: " ")
            let isCommand = language.selectKeywords.contains(where: full.contains)
            if !full.isEmpty, !isCommand, !isEcho(full) {
                print("VoiceCommands: dictation \"\(full)\"")
                recentTranscript.removeAll()
                onDictate?(full)
                return
            }
        }

        guard firstChanged < segments.count else { return }
        let changedIndices = Array(firstChanged..<segments.count)
        let newWords = changedIndices.map { segments[$0] }.joined(separator: " ")
        print("VoiceCommands: heard \"\(newWords)\"")

        // "select" is a click and is honored even while Output is speaking -
        // a select said during a several-second confirmation used to be
        // dropped outright. Only our own speech echoing back is ignored.
        if let index = changedIndices.first(where: { i in
            language.selectKeywords.contains(where: segments[i].contains)
        }) {
            if isEcho(newWords) {
                print("VoiceCommands: ignoring \"\(newWords)\" - echo of our own speech")
            } else if firedSelectIndices.contains(index) {
                // Same word revised by a later partial result - already clicked.
            } else if Date().timeIntervalSince(lastSelectAt) < 0.6 {
                print("VoiceCommands: ignoring duplicate select within 0.6s")
            } else {
                firedSelectIndices.insert(index)
                lastSelectAt = Date()
                commandFiredThisSession = true
                recentTranscript.removeAll()
                print("VoiceCommands: SELECT")
                onSelectCommand?()
            }
            return
        }

        if isMuted?() == true {
            print("VoiceCommands: muted (Output is speaking), ignoring \"\(newWords)\"")
            return
        }

        let now = Date()
        recentTranscript.append((newWords, now))
        recentTranscript.removeAll { now.timeIntervalSince($0.at) > recentTranscriptWindow }
        let recentText = recentTranscript.map(\.text).joined(separator: " ")

        let fire: (() -> Void) -> Void = { action in
            self.recentTranscript.removeAll()
            self.commandFiredThisSession = true
            action()
        }

        if language.openWebsiteKeywords.contains(where: recentText.contains) {
            fire { onOpenWebsiteCommand?() }
        } else if language.homeKeywords.contains(where: recentText.contains) {
            fire { onWebsiteAction?("home") }
        } else if language.backToGoalsKeywords.contains(where: recentText.contains) {
            fire { onWebsiteAction?("back") }
        } else if language.takeQuizKeywords.contains(where: recentText.contains) {
            fire { onWebsiteAction?("quiz") }
        } else if language.tryScenarioKeywords.contains(where: recentText.contains) {
            fire { onWebsiteAction?("scenario") }
        } else if language.learnKeywords.contains(where: recentText.contains) {
            fire { onWebsiteAction?("learn") }
        } else if language.explainKeywords.contains(where: recentText.contains) {
            fire { onExplainCommand?() }
        }
    }

    /// "send" must be a phrase on its own: a pause before it (or the start
    /// of the session) and ~1s of silence after. A whole-utterance match
    /// failed live - background speech right after "send" landed in the same
    /// recognition session, so the final text was never just "send". The
    /// silence-after rule keeps "send me the file" as dictation.
    private func checkForSend(_ segments: [String], isFinal: Bool) {
        pendingSend?.cancel()
        pendingSend = nil
        guard !sendFiredThisSession, !segments.isEmpty else { return }

        // Start of the trailing phrase: the last word that arrived after a pause.
        var start = segments.count - 1
        while start > 0,
              segmentArrivals[start].timeIntervalSince(segmentArrivals[start - 1]) < phrasePause {
            start -= 1
        }
        let phrase = segments[start...].joined(separator: " ")
            .trimmingCharacters(in: .punctuationCharacters.union(.whitespaces))
        guard AppSettings.shared.language.sendKeywords.contains(phrase), !isEcho(phrase) else { return }

        let wordCount = segments.count
        let fire = { [weak self] in
            guard let self, !self.sendFiredThisSession else { return }
            self.sendFiredThisSession = true
            self.commandFiredThisSession = true
            self.recentTranscript.removeAll()
            print("VoiceCommands: SEND")
            self.onSendCommand?()
        }
        if isFinal {
            fire()
            return
        }
        // Fire once no further word has followed for a moment.
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.lastSegments.count == wordCount else { return }
            fire()
        }
        pendingSend = work
        DispatchQueue.main.asyncAfter(deadline: .now() + sendSilence, execute: work)
    }

    /// True if every heard word appears in what Output is saying (or just
    /// said) - i.e. the mic is hearing our own TTS, not the user.
    private func isEcho(_ heard: String) -> Bool {
        guard let spoken = spokenTextNow?()?.lowercased() else { return false }
        let words = heard.split(separator: " ")
        guard !words.isEmpty else { return false }
        return words.allSatisfy { spoken.contains($0) }
    }
}
