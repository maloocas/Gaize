import Foundation

/// Real, spoken explanations for known UI elements, keyed by a lowercase
/// substring match against the element's title/description (AX titles stay
/// in the target app's own language regardless of AppSettings.shared.language -
/// only what we *say back* is translated). Falls back to a generic
/// "this is the {label}" phrasing for anything not in the pack.
///
/// Demo app is Messages — extend this table as new buttons come up in
/// rehearsal rather than hardcoding elsewhere.
enum KnowledgePack {
    private static let entries: [(match: String, explanations: [AppLanguage: String])] = [
        ("compose", [
            .english: "This starts a new conversation, so you can message someone new.",
            .spanish: "Esto inicia una nueva conversación para escribirle a alguien nuevo.",
            .french: "Ceci démarre une nouvelle conversation pour écrire à quelqu'un de nouveau.",
        ]),
        ("new message", [
            .english: "This starts a new conversation, so you can message someone new.",
            .spanish: "Esto inicia una nueva conversación para escribirle a alguien nuevo.",
            .french: "Ceci démarre une nouvelle conversation pour écrire à quelqu'un de nouveau.",
        ]),
        ("send", [
            .english: "This sends the message you've typed.",
            .spanish: "Esto envía el mensaje que escribiste.",
            .french: "Ceci envoie le message que vous avez écrit.",
        ]),
        ("attach", [
            .english: "This lets you attach a photo, file, or other item to your message.",
            .spanish: "Esto te permite adjuntar una foto, archivo u otro elemento a tu mensaje.",
            .french: "Ceci vous permet de joindre une photo, un fichier ou un autre élément à votre message.",
        ]),
        ("camera", [
            .english: "This lets you take a photo or video to send.",
            .spanish: "Esto te permite tomar una foto o video para enviar.",
            .french: "Ceci vous permet de prendre une photo ou une vidéo à envoyer.",
        ]),
        ("details", [
            .english: "This shows more information about the conversation, like who's in it.",
            .spanish: "Esto muestra más información sobre la conversación, como quién participa.",
            .french: "Ceci affiche plus d'informations sur la conversation, comme qui y participe.",
        ]),
        ("audio message", [
            .english: "This lets you record and send a short voice message.",
            .spanish: "Esto te permite grabar y enviar un breve mensaje de voz.",
            .french: "Ceci vous permet d'enregistrer et d'envoyer un court message vocal.",
        ]),
        ("app store", [
            .english: "This opens extra features you can send in a message, like games or stickers.",
            .spanish: "Esto abre funciones adicionales que puedes enviar en un mensaje, como juegos o stickers.",
            .french: "Ceci ouvre des fonctionnalités supplémentaires à envoyer dans un message, comme des jeux ou des autocollants.",
        ]),
        ("emoji", [
            .english: "This opens emoji you can add to your message.",
            .spanish: "Esto abre emojis que puedes agregar a tu mensaje.",
            .french: "Ceci ouvre des emojis à ajouter à votre message.",
        ]),
        ("search", [
            .english: "This searches your conversations and messages.",
            .spanish: "Esto busca en tus conversaciones y mensajes.",
            .french: "Ceci recherche dans vos conversations et messages.",
        ]),
        ("back", [
            .english: "This takes you back to the previous screen.",
            .spanish: "Esto te lleva de vuelta a la pantalla anterior.",
            .french: "Ceci vous ramène à l'écran précédent.",
        ]),
        ("facetime", [
            .english: "This starts a FaceTime video call.",
            .spanish: "Esto inicia una videollamada de FaceTime.",
            .french: "Ceci démarre un appel vidéo FaceTime.",
        ]),
        ("filter", [
            .english: "This filters and sorts your conversation list.",
            .spanish: "Esto filtra y ordena tu lista de conversaciones.",
            .french: "Ceci filtre et trie votre liste de conversations.",
        ]),
    ]

    static func explanation(for element: SensedElement) -> String {
        let label = element.title.isEmpty ? element.role : element.title
        let haystack = label.lowercased()
        let language = AppSettings.shared.language

        if let match = entries.first(where: { haystack.contains($0.match) }),
           let text = match.explanations[language] {
            return text
        }

        return language.genericExplanationTemplate(label)
    }

    static func confirmation(for element: SensedElement) -> String {
        let label = element.title.isEmpty ? element.role : element.title
        return AppSettings.shared.language.confirmationTemplate(label)
    }
}
