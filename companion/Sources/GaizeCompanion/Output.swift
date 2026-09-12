import AVFoundation

/// Spoken output, backed by KnowledgePack for explanation text.
///
/// Three tiers, in preference order:
/// 1. A pre-rendered Chatterbox clip (Resources/audio/<language>/<key>.wav,
///    from chatterbox/generate_gaize_audio.py) for anything in KnowledgePack.
/// 2. The live Chatterbox server (chatterbox/tts_server.py, English only,
///    http://127.0.0.1:8766) for dynamic text - confirmations, the generic
///    "this is the X" fallback.
/// 3. AVSpeechSynthesizer with the best installed system voice, when neither
///    of the above is available.
///
/// Exposes isSpeaking and recentSpokenText so VoiceCommands can tell the
/// user's voice apart from our own TTS coming back through the speakers.
final class Output: NSObject, AVSpeechSynthesizerDelegate, AVAudioPlayerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var audioPlayer: AVAudioPlayer?

    private static let liveServerURL = URL(string: "http://127.0.0.1:8766/speak")!

    private var speakingSince: Date?
    private var lastText: String?
    private var lastTextValidUntil = Date.distantPast
    /// Bumped on every new utterance, so a slow live-TTS response for an
    /// older one can't start playing after a newer one.
    private var generation = 0

    /// Capped at 8s so a delegate callback that never arrives (a player
    /// replaced mid-playback doesn't report finishing) can't leave voice
    /// commands muted forever.
    var isSpeaking: Bool {
        guard let since = speakingSince else { return false }
        return Date().timeIntervalSince(since) < 8
    }

    /// What we're saying now, or said within the last 1.5s - the mic keeps
    /// hearing the tail of our speech briefly after playback ends.
    var recentSpokenText: String? {
        if isSpeaking { return lastText }
        return Date() < lastTextValidUntil ? lastText : nil
    }

    /// Like recentSpokenText but remembered for several seconds - the
    /// recognizer can surface our own words ("got it compose") well after we
    /// finished saying them, glued onto the user's next words.
    var lingeringSpokenText: String? {
        if isSpeaking { return lastText }
        return Date() < lastTextValidUntil.addingTimeInterval(6) ? lastText : nil
    }

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speakExplanation(for element: SensedElement) {
        let text = KnowledgePack.explanation(for: element)
        if let entry = KnowledgePack.matchedEntry(for: element),
           playPreRendered(key: entry.key, text: text) {
            return
        }
        speak(text)
    }

    func speakConfirmation(for element: SensedElement) {
        speak(KnowledgePack.confirmation(for: element))
    }

    private func beginSpeaking(_ text: String) {
        generation += 1
        audioPlayer?.stop()
        synthesizer.stopSpeaking(at: .immediate)
        speakingSince = Date()
        lastText = text
    }

    private func endSpeaking() {
        speakingSince = nil
        lastTextValidUntil = Date().addingTimeInterval(1.5)
    }

    private func playPreRendered(key: String, text: String) -> Bool {
        let language = AppSettings.shared.language.rawValue
        guard let url = Bundle.module.url(
            forResource: key,
            withExtension: "wav",
            subdirectory: "audio/\(language)"
        ), let player = try? AVAudioPlayer(contentsOf: url) else {
            return false
        }

        beginSpeaking(text)
        player.delegate = self
        audioPlayer = player
        print("Output: playing pre-rendered \(language)/\(key).wav")
        player.play()
        return true
    }

    func speak(_ text: String) {
        beginSpeaking(text)
        guard AppSettings.shared.language == .english else {
            speakSystemVoice(text)
            return
        }

        print("Output: requesting live TTS for \"\(text)\"")
        let myGeneration = generation

        var request = URLRequest(url: Self.liveServerURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text])
        request.timeoutInterval = 6

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self, self.generation == myGeneration else { return }
                guard error == nil, let data, !data.isEmpty,
                      (response as? HTTPURLResponse)?.statusCode == 200,
                      let player = try? AVAudioPlayer(data: data) else {
                    print("Output: live TTS unavailable (\(error?.localizedDescription ?? "bad response")), using system voice")
                    self.speakSystemVoice(text)
                    return
                }
                player.delegate = self
                self.audioPlayer = player
                print("Output: playing live TTS for \"\(text)\"")
                player.play()
            }
        }.resume()
    }

    private func speakSystemVoice(_ text: String) {
        print("Output: speaking (system voice) \"\(text)\"")
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.voice = Self.bestVoice(for: AppSettings.shared.language)
        synthesizer.speak(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        endSpeaking()
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        // Cancelled to make way for a newer utterance, which has already
        // marked itself as speaking - don't clobber that.
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        if player === audioPlayer {
            endSpeaking()
        }
    }

    /// Prefer an installed Premium, then Enhanced voice over the default
    /// compact one (downloaded via System Settings > Accessibility >
    /// Spoken Content).
    private static var cachedVoices: [AppLanguage: AVSpeechSynthesisVoice] = [:]

    private static func bestVoice(for language: AppLanguage) -> AVSpeechSynthesisVoice? {
        if let cached = cachedVoices[language] { return cached }

        let matching = AVSpeechSynthesisVoice.speechVoices().filter { $0.language == language.rawValue }
        let chosen = matching.first(where: { $0.quality == .premium })
            ?? matching.first(where: { $0.quality == .enhanced })
            ?? AVSpeechSynthesisVoice(language: language.rawValue)

        if let chosen {
            cachedVoices[language] = chosen
        }
        return chosen
    }
}
