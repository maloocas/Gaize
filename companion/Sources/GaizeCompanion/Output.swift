import AVFoundation

/// Spoken output, backed by KnowledgePack for explanation text.
///
/// Explanations for known elements play a pre-rendered Chatterbox TTS clip
/// (Resources/audio/<language>/<key>.wav - see chatterbox/generate_gaize_audio.py
/// in the sibling chatterbox repo) when one exists for the current language,
/// since Chatterbox sounds far more natural than the system voice but is far
/// too slow (seconds per line, CPU) to run live. Everything else - the
/// generic "this is the X" fallback, and all "Selecting X" confirmations,
/// which both involve dynamic element names we can't pre-render - uses
/// AVSpeechSynthesizer with the best installed system voice.
///
/// Tracks isSpeaking (across both playback paths) so VoiceCommands can mute
/// itself while this is talking - without that, the mic picks up our own
/// TTS through the speakers and transcribes it right back as a command
/// (e.g. "Selecting compose" contains "select", re-triggering it).
final class Output: NSObject, AVSpeechSynthesizerDelegate, AVAudioPlayerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var audioPlayer: AVAudioPlayer?
    private(set) var isSpeaking = false

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

    func speak(_ text: String) {
        print("Output: speaking \"\(text)\"")
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
