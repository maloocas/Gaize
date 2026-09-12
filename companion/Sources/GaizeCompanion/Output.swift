import AVFoundation

/// Spoken output, backed by KnowledgePack for real explanation text.
///
/// Tracks isSpeaking so VoiceCommands can mute itself while this is talking -
/// without that, the mic picks up our own TTS through the speakers and
/// transcribes it right back as a command (e.g. "Selecting compose" contains
/// "select", re-triggering the select command in a feedback loop).
final class Output: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private(set) var isSpeaking = false

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speakExplanation(for element: SensedElement) {
        speak(KnowledgePack.explanation(for: element))
    }

    func speakConfirmation(for element: SensedElement) {
        speak(KnowledgePack.confirmation(for: element))
    }

    func speak(_ text: String) {
        print("Output: speaking \"\(text)\"")
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
