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

    var openWebsiteKeywords: [String] {
        switch self {
        case .english: return [
            "open website", "open the website", "show website", "open goals", "show goals",
            "gaize open", "gaize, open", "hey gaize open", "hey gaize, open",
        ]
        case .spanish: return [
            "abrir sitio web", "abrir el sitio web", "mostrar objetivos",
            "gaize abre", "gaize, abre", "oye gaize abre",
        ]
        case .french: return [
            "ouvrir le site", "ouvrir le site web", "afficher les objectifs",
            "gaize ouvre", "gaize, ouvre", "hé gaize ouvre",
        ]
        }
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
        case .english: return { "Selecting \($0)." }
        case .spanish: return { "Seleccionando \($0)." }
        case .french: return { "Sélection de \($0)." }
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
