import AVFoundation

/// Spoken output, backed by KnowledgePack for explanation text.
///
/// Three tiers, in preference order:
/// 1. A pre-rendered Chatterbox TTS clip (Resources/audio/<language>/<key>.wav
///    - see chatterbox/generate_gaize_audio.py in the sibling chatterbox
///    repo) for anything in KnowledgePack, in the current language.
/// 2. The live Chatterbox server (chatterbox/tts_server.py, English only,
///    must be started separately - http://127.0.0.1:8766) for dynamic text
///    that can't be pre-rendered (confirmations like "Selecting X", the
///    generic "this is the X" fallback) - a few seconds slower than (1) but
///    still Chatterbox's natural voice rather than the robotic system one.
/// 3. AVSpeechSynthesizer with the best installed system voice, whenever
///    neither of the above is available (non-English, or the live server
///    isn't running).
///
/// Tracks isSpeaking (across all three paths) so VoiceCommands can mute
/// itself while this is talking - without that, the mic picks up our own
/// TTS through the speakers and transcribes it right back as a command
/// (e.g. "Selecting compose" contains "select", re-triggering it).
final class Output: NSObject, AVSpeechSynthesizerDelegate, AVAudioPlayerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var audioPlayer: AVAudioPlayer?
    private(set) var isSpeaking = false

    private static let liveServerURL = URL(string: "http://127.0.0.1:8766/speak")!

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speakExplanation(for element: SensedElement) {
        if let entry = KnowledgePack.matchedEntry(for: element),
           playPreRendered(key: entry.key) {
            return
        }
        speak(KnowledgePack.explanation(for: element))
    }

    func speakConfirmation(for element: SensedElement) {
        speak(KnowledgePack.confirmation(for: element))
    }

    /// Plays Resources/audio/<language>/<key>.wav if it exists. Returns
    /// false (having played nothing) if there's no clip for this key/language,
    /// so the caller can fall back to live TTS.
    private func playPreRendered(key: String) -> Bool {
        let language = AppSettings.shared.language.rawValue
        guard let url = Bundle.module.url(
            forResource: key,
            withExtension: "wav",
            subdirectory: "audio/\(language)"
        ) else {
            return false
        }

        do {
            let player = try AVAudioPlayer(contentsOf: url)
            player.delegate = self
            audioPlayer = player
            print("Output: playing pre-rendered \(language)/\(key).wav")
            synthesizer.stopSpeaking(at: .immediate)
            isSpeaking = true
            player.play()
            return true
        } catch {
            print("Output: failed to play \(url): \(error)")
            return false
        }
    }

    /// Dynamic text (not in KnowledgePack): tries the live Chatterbox
    /// server first (English only), falling back to the system voice if
    /// it's not running, times out, or errors.
    func speak(_ text: String) {
        let language = AppSettings.shared.language
        guard language == .english else {
            speakSystemVoice(text)
            return
        }

        print("Output: requesting live TTS for \"\(text)\"")
        isSpeaking = true

        var request = URLRequest(url: Self.liveServerURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["text": text])
        request.timeoutInterval = 6

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self else { return }

            guard error == nil, let data, !data.isEmpty,
                  (response as? HTTPURLResponse)?.statusCode == 200 else {
                print("Output: live TTS server unavailable (\(error?.localizedDescription ?? "bad response")), falling back to system voice")
                DispatchQueue.main.async { self.speakSystemVoice(text) }
                return
            }

            DispatchQueue.main.async {
                self.playLiveAudio(data, text: text)
            }
        }.resume()
    }

    private func playLiveAudio(_ data: Data, text: String) {
        do {
            let player = try AVAudioPlayer(data: data)
            player.delegate = self
            audioPlayer = player
            print("Output: playing live TTS for \"\(text)\"")
            player.play()
        } catch {
            print("Output: failed to play live TTS audio: \(error), falling back to system voice")
            speakSystemVoice(text)
        }
    }

    private func speakSystemVoice(_ text: String) {
        print("Output: speaking (system voice) \"\(text)\"")
        audioPlayer?.stop()
        synthesizer.stopSpeaking(at: .word)
        isSpeaking = true
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.voice = Self.bestVoice(for: AppSettings.shared.language)
        synthesizer.speak(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        isSpeaking = false
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        isSpeaking = false
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        isSpeaking = false
    }

    /// The default AVSpeechSynthesisVoice(language:) picks the robotic
    /// "compact" voice. Prefer an installed Premium, then Enhanced voice
    /// for the language - these are the natural-sounding Siri-quality
    /// voices, downloaded via System Settings > Accessibility > Spoken
    /// Content > System Voice (or Voices...). Falls back to the default
    /// compact voice if neither is installed.
    private static var cachedVoices: [AppLanguage: AVSpeechSynthesisVoice] = [:]

    private static func bestVoice(for language: AppLanguage) -> AVSpeechSynthesisVoice? {
        if let cached = cachedVoices[language] { return cached }

        let matching = AVSpeechSynthesisVoice.speechVoices().filter { $0.language == language.rawValue }
        let chosen = matching.first(where: { $0.quality == .premium })
            ?? matching.first(where: { $0.quality == .enhanced })
            ?? AVSpeechSynthesisVoice(language: language.rawValue)

        if let chosen {
            print("Output: using voice \"\(chosen.name)\" (\(chosen.quality.rawValue)) for \(language.rawValue)")
            cachedVoices[language] = chosen
        }
        return chosen
    }
}
