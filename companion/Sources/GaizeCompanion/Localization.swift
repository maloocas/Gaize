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
        ]
        case .spanish: return [
            "abrir sitio web", "abrir el sitio web", "mostrar objetivos",
            "gaize abre", "gay abre", "gase abre",
        ]
        case .french: return [
            "ouvrir le site", "ouvrir le site web", "afficher les objectifs",
            "gaize ouvre", "gay ouvre", "gaz ouvre",
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
