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
    /// True while a new message's To: field is still empty - speech then is
    /// treated as a contact name.
    var isRecipientPending: (() -> Bool)?
    /// Output's text for several seconds after it's spoken, to strip our
    /// own echoed words out of a contact name.
    var lingeringSpokenText: (() -> String?)?

    private var recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var isAuthorized = false
    private var restartPending = false

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
    /// Words before this index in the current session were already typed.
    private var dictationStartIndex = 0
    private var pendingDictation: DispatchWorkItem?
    private let recipientSilence: TimeInterval = 1.0
    private let messageSilence: TimeInterval = 1.8

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
        // Coalesce - a send/dictation restart and the recognizer's own
        // final/error restart can land together, and two scheduled starts
        // would leave two recognition tasks running.
        guard !restartPending else { return }
        restartPending = true
        stop()
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.restartPending = false
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
        dictationStartIndex = 0
        pendingDictation?.cancel()
        pendingDictation = nil

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
            // Ignore callbacks from a session we already stopped (its
            // cancellation error would otherwise trigger another restart).
            guard let self, self.request === request else { return }
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
        // A send restarts the session (see checkForSend); ignore any result
        // still in flight from the old one.
        if sendFiredThisSession { return }

        // Dictation fires on a pause, not only on the recognizer's final
        // result - with room noise or our own TTS in the mic, a session can
        // stay open indefinitely (observed: "lucas" said four times, never
        // finalized, never typed).
        if result.isFinal {
            pendingDictation?.cancel()
            pendingDictation = nil
            if !commandFiredThisSession, let text = dictationCandidate(segments) {
                fireDictation(text, upTo: segments.count)
                return
            }
        } else {
            scheduleDictation(segments)
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
        guard !isEcho(phrase) else { return }
        let language = AppSettings.shared.language
        let action: () -> Void
        if language.sendKeywords.contains(phrase) {
            action = { [weak self] in
                print("VoiceCommands: SEND")
                self?.onSendCommand?()
            }
        } else if isOpenWebsitePhrase(phrase, language), isDictationModeActive?() != true {
            action = { [weak self] in
                print("VoiceCommands: OPEN WEBSITE (standalone \"\(phrase)\")")
                self?.onOpenWebsiteCommand?()
            }
        } else {
            return
        }

        let wordCount = segments.count
        let fire = { [weak self] in
            guard let self, !self.sendFiredThisSession else { return }
            self.sendFiredThisSession = true
            self.commandFiredThisSession = true
            self.recentTranscript.removeAll()
            action()
            // Start a fresh session - ignoring the rest of this one left
            // listening deaf: with room noise it never finalized, so it never
            // restarted (observed: "gaize open" unheard after a send).
            self.restartSoon()
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

    /// An exact standalone phrase, or a short phrase (up to 3 words) ending
    /// in "open" - "Gaize" gets misheard as all sorts ("can i open" observed).
    private func isOpenWebsitePhrase(_ phrase: String, _ language: AppLanguage) -> Bool {
        if language.openWebsitePhrases.contains(phrase) { return true }
        let words = phrase.split(separator: " ").map(String.init)
        guard let last = words.last, words.count <= 3 else { return false }
        return language.openWebsitePhrases.contains(last)
    }

    /// What to type for the words heard since the last dictation, or nil.
    /// For an empty To: field: the last pause-separated phrase, minus our
    /// own echoed words and repeats ("got it compose lucas lucas" -> "lucas"),
    /// if it's name-sized. For the message body: everything since.
    private func dictationCandidate(_ segments: [String]) -> String? {
        guard dictationStartIndex < segments.count else { return nil }
        let recipient = isRecipientPending?() == true
        guard recipient || isDictationModeActive?() == true else { return nil }

        let language = AppSettings.shared.language
        let pending = segments[dictationStartIndex...].joined(separator: " ")
        if language.selectKeywords.contains(where: pending.contains) { return nil }

        var start = segments.count - 1
        while start > dictationStartIndex, start < segmentArrivals.count,
              segmentArrivals[start].timeIntervalSince(segmentArrivals[start - 1]) < phrasePause {
            start -= 1
        }
        let phrase = segments[start...].joined(separator: " ")
            .trimmingCharacters(in: .punctuationCharacters.union(.whitespaces))
        if language.sendKeywords.contains(phrase) { return nil }

        guard recipient else { return isEcho(pending) ? nil : pending }

        let echoWords = Set((lingeringSpokenText?() ?? "").lowercased()
            .components(separatedBy: CharacterSet.letters.inverted).filter { !$0.isEmpty })
        var words: [String] = []
        for word in segments[start...] where !echoWords.contains(word) && words.last != word {
            words.append(word)
        }
        guard (1...3).contains(words.count) else { return nil }
        return words.joined(separator: " ")
    }

    private func scheduleDictation(_ segments: [String]) {
        pendingDictation?.cancel()
        pendingDictation = nil
        guard !commandFiredThisSession, let text = dictationCandidate(segments) else { return }
        let wordCount = segments.count
        // A name is short - act quickly. A message has natural mid-sentence
        // pauses, so wait longer before deciding it's finished.
        let delay = isRecipientPending?() == true ? recipientSilence : messageSilence
        let work = DispatchWorkItem { [weak self] in
            guard let self, !self.commandFiredThisSession, self.lastSegments.count == wordCount else { return }
            self.fireDictation(text, upTo: wordCount)
        }
        pendingDictation = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func fireDictation(_ text: String, upTo index: Int) {
        dictationStartIndex = index
        recentTranscript.removeAll()
        print("VoiceCommands: dictation \"\(text)\"")
        onDictate?(text)
        // Fresh session per dictation, so segment indices and the earlier
        // words don't linger in a session noise may keep open indefinitely.
        restartSoon()
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
