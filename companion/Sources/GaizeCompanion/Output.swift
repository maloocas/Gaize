import AVFoundation

/// Spoken output. TODO: swap generated phrasing for real pre-written
/// explanation clips per element/app once those exist (see docs in website
/// content); this generator is a placeholder that's always available.
final class Output {
    private let synthesizer = AVSpeechSynthesizer()

    func speakExplanation(for element: SensedElement) {
        let label = element.title.isEmpty ? element.role : element.title
        speak("This is the \(label).")
    }

    func speakConfirmation(for element: SensedElement) {
        let label = element.title.isEmpty ? element.role : element.title
        speak("Selecting \(label).")
    }

    func speak(_ text: String) {
        synthesizer.stopSpeaking(at: .word)
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        synthesizer.speak(utterance)
    }
}
