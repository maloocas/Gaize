import Foundation

/// Real, spoken explanations for known UI elements, keyed by a lowercase
/// substring match against the element's title/description. Falls back to a
/// generic "this is the {label}" phrasing for anything not in the pack.
///
/// Demo app is Messages — extend this table as new buttons come up in
/// rehearsal rather than hardcoding elsewhere.
enum KnowledgePack {
    private static let entries: [(match: String, explanation: String)] = [
        ("compose", "This starts a new conversation, so you can message someone new."),
        ("new message", "This starts a new conversation, so you can message someone new."),
        ("send", "This sends the message you've typed."),
        ("attach", "This lets you attach a photo, file, or other item to your message."),
        ("camera", "This lets you take a photo or video to send."),
        ("details", "This shows more information about the conversation, like who's in it."),
        ("audio message", "This lets you record and send a short voice message."),
        ("app store", "This opens extra features you can send in a message, like games or stickers."),
        ("emoji", "This opens emoji you can add to your message."),
        ("search", "This searches your conversations and messages."),
        ("back", "This takes you back to the previous screen."),
    ]

    static func explanation(for element: SensedElement) -> String {
        let label = element.title.isEmpty ? element.role : element.title
        let haystack = label.lowercased()

        if let match = entries.first(where: { haystack.contains($0.match) }) {
            return match.explanation
        }

        return "This is the \(label)."
    }

    static func confirmation(for element: SensedElement) -> String {
        let label = element.title.isEmpty ? element.role : element.title
        return "Selecting \(label)."
    }
}
