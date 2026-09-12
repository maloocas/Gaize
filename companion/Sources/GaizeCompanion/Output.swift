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
        utterance.voice = AVSpeechSynthesisVoice(language: AppSettings.shared.language.rawValue)
        synthesizer.speak(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        isSpeaking = false
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        isSpeaking = false
    }
}
