import AVFoundation

/// Spoken output, backed by KnowledgePack for real explanation text.
final class Output {
    private let synthesizer = AVSpeechSynthesizer()

    func speakExplanation(for element: SensedElement) {
        speak(KnowledgePack.explanation(for: element))
    }

    func speakConfirmation(for element: SensedElement) {
        speak(KnowledgePack.confirmation(for: element))
    }

    func speak(_ text: String) {
        print("Output: speaking \"\(text)\"")
        synthesizer.stopSpeaking(at: .word)
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        synthesizer.speak(utterance)
    }
}
