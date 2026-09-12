import Foundation

/// Supported spoken languages. Adding one means: a BCP-47 code (used for
/// both SFSpeechRecognizer and AVSpeechSynthesisVoice), and translated
/// command keywords - KnowledgePack carries the translated explanations.
enum AppLanguage: String, CaseIterable {
    case english = "en-US"
    case spanish = "es-ES"
    case french = "fr-FR"

    var displayName: String {
        switch self {
        case .english: return "English"
        case .spanish: return "Español"
        case .french: return "Français"
        }
    }

    var locale: Locale { Locale(identifier: rawValue) }

    var selectKeywords: [String] {
        switch self {
        case .english: return ["select", "click", "choose", "confirm"]
        case .spanish: return ["seleccionar", "selecciona", "elegir", "confirmar"]
        case .french: return ["sélectionner", "sélectionne", "choisir", "confirmer"]
        }
    }

    var explainKeywords: [String] {
        switch self {
        case .english: return ["explain", "what is this", "what's this"]
        case .spanish: return ["explica", "explicar", "qué es esto"]
        case .french: return ["explique", "expliquer", "qu'est-ce que c'est"]
        }
    }

    /// "Gaize" is not a real word, so on-device speech recognition
    /// transcribes it inconsistently (observed: "gay" for "Gaize" said
    /// alone before "open") - these variants cover the common mishearings
    /// rather than relying on one exact spelling.
    var openWebsiteKeywords: [String] {
        switch self {
        case .english: return [
            "open website", "open the website", "show website", "open goals", "show goals",
            "gaize open", "gaze open", "gay open", "days open", "guys open", "case open",
            // "open Gaize" order too - the natural thing to say after "hey Gaize".
            // ("Opening Gaize", our own reply, doesn't contain any of these.)
            "open gaize", "open gaze", "open gays", "open guys", "open gay", "open days", "open case",
            "open the gaize", "open gauze",
        ]
        case .spanish: return [
            "abrir sitio web", "abrir el sitio web", "mostrar objetivos",
            "gaize abre", "gay abre", "gase abre",
            "abre gaize", "abrir gaize", "abre gay", "abre gase",
        ]
        case .french: return [
            "ouvrir le site", "ouvrir le site web", "afficher les objectifs",
            "gaize ouvre", "gay ouvre", "gaz ouvre",
            "ouvre gaize", "ouvrir gaize", "ouvre gay", "ouvre gaz",
        ]
        }
    }

    /// Website navigation, spoken directly (not tied to gaze/AX accuracy) -
    /// sent to the website as a "voice_action" bridge message and handled
    /// by its own JS, since it already knows exactly which function each
    /// button calls.
    var homeKeywords: [String] {
        switch self {
        case .english: return ["go home", "home"]
        case .spanish: return ["ir a inicio", "inicio"]
        case .french: return ["aller à l'accueil", "accueil"]
        }
    }

    var backToGoalsKeywords: [String] {
        switch self {
        case .english: return ["back to goals", "go back"]
        case .spanish: return ["volver a objetivos", "regresar"]
        case .french: return ["retour aux objectifs", "retour"]
        }
    }

    var learnKeywords: [String] {
        switch self {
        case .english: return ["learn this goal", "start learning", "learn"]
        case .spanish: return ["aprender este objetivo", "aprender"]
        case .french: return ["apprendre cet objectif", "apprendre"]
        }
    }

    var takeQuizKeywords: [String] {
        switch self {
        case .english: return ["take a quiz", "take quiz", "start quiz"]
        case .spanish: return ["hacer un cuestionario", "empezar cuestionario"]
        case .french: return ["faire un quiz", "commencer le quiz"]
        }
    }

    var tryScenarioKeywords: [String] {
        switch self {
        case .english: return ["try a scenario", "try scenario", "start scenario"]
        case .spanish: return ["probar un escenario", "empezar escenario"]
        case .french: return ["essayer un scénario", "commencer le scénario"]
        }
    }

    /// Sends the message typed into Messages' body. Matched only against a
    /// whole utterance (exactly one of these), never as a substring - so a
    /// dictated "send me the file" is typed, not sent half-written.
    var sendKeywords: [String] {
        switch self {
        case .english: return ["send", "send it", "send message", "send the message", "send text", "send the text"]
        case .spanish: return ["enviar", "envía", "envia", "enviar mensaje", "envíalo", "envialo"]
        case .french: return ["envoyer", "envoie", "envoyer le message", "envoie-le"]
        }
    }

    /// Standalone-phrase versions of "Gaize open" - recognition often drops
    /// the unfamiliar "Gaize" and hears just "open" (observed). Matched only
    /// as a whole pause-separated phrase, and never while dictating.
    var openWebsitePhrases: [String] {
        switch self {
        case .english: return ["open", "open gaize", "open gaze", "gaize", "open up"]
        case .spanish: return ["abre", "abrir", "abrir gaize"]
        case .french: return ["ouvre", "ouvrir", "ouvrir gaize"]
        }
    }

    /// A phrase starting with one of these (after a pause) is a question for
    /// the AI assistant - "how do I send a message to Lucas".
    var questionStarters: [String] {
        switch self {
        case .english: return [
            "how do i", "how can i", "how would i", "how to", "how does", "where is", "where's",
            "what does", "can you show me", "show me how", "help me", "teach me",
        ]
        case .spanish: return ["cómo", "como puedo", "dónde está", "donde esta", "qué hace", "ayúdame", "enséñame"]
        case .french: return ["comment", "où est", "que fait", "aide-moi", "montre-moi"]
        }
    }

    var assistantUnavailable: String {
        switch self {
        case .english: return "Sorry, I couldn't get an answer right now."
        case .spanish: return "Lo siento, no pude obtener una respuesta ahora."
        case .french: return "Désolé, je n'ai pas pu obtenir de réponse pour le moment."
        }
    }

    /// "Hey Gaize" wakes Gaize up - until then everything heard is ignored.
    /// "Gaize" isn't a real word, so common mishearings are included.
    var wakePhrases: [String] {
        switch self {
        case .english: return [
            "hey gaize", "hey gaze", "hey gays", "hey guys", "hey gay", "hey days", "hey case",
            "hey guise", "hey gauze", "hey geez", "hi gaize", "hi gaze", "okay gaize", "ok gaize",
        ]
        case .spanish: return ["hola gaize", "oye gaize", "hola gay", "oye gay", "hola gase", "oye gase"]
        case .french: return ["salut gaize", "dis gaize", "hé gaize", "salut gay", "salut gaz", "dis gay"]
        }
    }

    /// Puts Gaize back to sleep.
    var sleepPhrases: [String] {
        switch self {
        case .english: return [
            "goodbye gaize", "bye gaize", "goodbye gaze", "bye gaze", "bye guys",
            "stop listening", "go to sleep",
        ]
        case .spanish: return ["adiós gaize", "adios gaize", "deja de escuchar", "a dormir"]
        case .french: return ["au revoir gaize", "arrête d'écouter", "va dormir"]
        }
    }

    var wakeAcknowledgement: String {
        switch self {
        case .english: return "I'm listening."
        case .spanish: return "Te escucho."
        case .french: return "Je vous écoute."
        }
    }

    var sleepAcknowledgement: String {
        switch self {
        // Must not contain a wake phrase - the mic hears this through the
        // speakers, and "say hey Gaize when you need me" woke it right back up.
        case .english: return "Okay, I'll stop listening."
        case .spanish: return "De acuerdo, dejo de escuchar."
        case .french: return "D'accord, j'arrête d'écouter."
        }
    }

    /// Saying a goal's name opens it on the website (like clicking its card).
    /// Ids match GOALS in website/app.js. Checked in order, first match wins.
    /// Never "send message"/"send the message" - those are the send command.
    var goalCommands: [(id: String, phrases: [String])] {
        switch self {
        case .english: return [
            ("send-a-message", ["send a message", "send a text", "send a new message"]),
            ("add-an-attachment", ["add an attachment", "add attachment", "attach a file"]),
            ("search-a-conversation", ["search your messages", "search my messages", "search messages"]),
            ("start-a-facetime-call", ["start a facetime call", "facetime call", "face time call", "start facetime"]),
            ("add-an-emoji", ["add an emoji", "add emoji"]),
            ("filter-conversations", ["filter your conversation list", "filter your conversations",
                                      "filter my conversations", "filter conversations"]),
            ("send-a-photo", ["send a photo", "send a picture", "send photo"]),
            ("send-a-sticker", ["send a sticker", "send sticker"]),
            ("create-a-poll", ["create a poll", "make a poll", "create poll"]),
            ("schedule-a-message", ["schedule a message", "schedule a text", "schedule message"]),
            ("create-a-genmoji", ["create a genmoji", "make a genmoji", "create a gen moji", "create genmoji"]),
            ("generate-an-image", ["generate an image", "generate image", "make an image"]),
            ("search-the-web-for-images", ["search the web for images", "search the web", "web images"]),
            ("add-a-message-effect", ["add a message effect", "message effect", "add an effect"]),
        ]
        case .spanish: return [
            ("send-a-message", ["enviar un mensaje"]),
            ("add-an-attachment", ["añadir un archivo adjunto", "adjuntar un archivo"]),
            ("search-a-conversation", ["buscar mensajes", "buscar en mis mensajes"]),
            ("start-a-facetime-call", ["llamada facetime", "llamada de facetime"]),
            ("add-an-emoji", ["añadir un emoji", "agregar un emoji"]),
            ("filter-conversations", ["filtrar conversaciones", "filtrar las conversaciones"]),
            ("send-a-photo", ["enviar una foto"]),
            ("send-a-sticker", ["enviar un sticker", "enviar una pegatina"]),
            ("create-a-poll", ["crear una encuesta"]),
            ("schedule-a-message", ["programar un mensaje"]),
            ("create-a-genmoji", ["crear un genmoji"]),
            ("generate-an-image", ["generar una imagen"]),
            ("search-the-web-for-images", ["buscar imágenes en la web", "buscar imagenes en la web"]),
            ("add-a-message-effect", ["efecto de mensaje", "añadir un efecto"]),
        ]
        case .french: return [
            ("send-a-message", ["envoyer un message"]),
            ("add-an-attachment", ["ajouter une pièce jointe"]),
            ("search-a-conversation", ["rechercher dans les messages", "rechercher les messages"]),
            ("start-a-facetime-call", ["appel facetime", "passer un appel facetime"]),
            ("add-an-emoji", ["ajouter un emoji"]),
            ("filter-conversations", ["filtrer les conversations"]),
            ("send-a-photo", ["envoyer une photo"]),
            ("send-a-sticker", ["envoyer un autocollant", "envoyer un sticker"]),
            ("create-a-poll", ["créer un sondage"]),
            ("schedule-a-message", ["programmer un message"]),
            ("create-a-genmoji", ["créer un genmoji"]),
            ("generate-an-image", ["générer une image"]),
            ("search-the-web-for-images", ["rechercher des images sur le web"]),
            ("add-a-message-effect", ["effet de message", "ajouter un effet"]),
        ]
        }
    }

    /// Launches and focuses the Messages app.
    var openMessagesKeywords: [String] {
        switch self {
        case .english: return [
            "open messages", "open message", "open imessage", "open i message", "open the messages",
            "open the messages app", "launch messages",
        ]
        case .spanish: return ["abrir mensajes", "abre mensajes", "abrir imessage", "abre imessage"]
        case .french: return ["ouvrir messages", "ouvre messages", "ouvrir les messages", "ouvre les messages"]
        }
    }

    var openingMessages: String {
        switch self {
        case .english: return "Opening Messages."
        case .spanish: return "Abriendo Mensajes."
        case .french: return "J'ouvre Messages."
        }
    }

    var sentConfirmation: String {
        switch self {
        case .english: return "Message sent."
        case .spanish: return "Mensaje enviado."
        case .french: return "Message envoyé."
        }
    }

    var nothingToSend: String {
        switch self {
        case .english: return "There's no message to send yet."
        case .spanish: return "Todavía no hay mensaje para enviar."
        case .french: return "Il n'y a pas encore de message à envoyer."
        }
    }

    /// Removes an explicit dictation verb while keeping plain speech valid.
    func dictationText(from phrase: String) -> String {
        let prefixes: [String]
        switch self {
        case .english: prefixes = ["type ", "enter "]
        case .spanish: prefixes = ["escribe ", "ingresa "]
        case .french: prefixes = ["écris ", "tape "]
        }

        let lowercased = phrase.lowercased()
        for prefix in prefixes where lowercased.hasPrefix(prefix) {
            return String(phrase.dropFirst(prefix.count))
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return phrase
    }

    var genericExplanationTemplate: (String) -> String {
        switch self {
        case .english: return { "This is the \($0)." }
        case .spanish: return { "Esto es \($0)." }
        case .french: return { "Ceci est \($0)." }
        }
    }

    var confirmationTemplate: (String) -> String {
        switch self {
        // Deliberately free of the select keywords ("select", "seleccionar",
        // ...) - the mic hears this through the speakers, and "Selecting X"
        // contained "select", which is what forced muting select mid-speech.
        case .english: return { "Got it, \($0)." }
        case .spanish: return { "Listo, \($0)." }
        case .french: return { "D'accord, \($0)." }
        }
    }
}

/// Single shared setting, read by Output, VoiceCommands, and KnowledgePack.
/// Changed via the menu bar's Language submenu.
final class AppSettings {
    static let shared = AppSettings()
    private init() {}

    var language: AppLanguage = .english
}
