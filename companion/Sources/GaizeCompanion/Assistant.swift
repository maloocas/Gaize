import Foundation

/// Answers spoken "how do I..." questions with a short spoken reply, and
/// picks the website goal that teaches it (if any) so its steps can be
/// highlighted. Uses OpenAI's chat completions API.
///
/// The API key is read from $OPENAI_API_KEY, else from
/// ~/Library/Application Support/Gaize/openai_key - never from the repo.
enum Assistant {
    struct Reply {
        let answer: String
        let goalID: String?
    }

    static let model = "gpt-4o-mini"

    /// Mirrors GOALS in website/app.js - ids must match.
    static let goals: [(id: String, title: String)] = [
        ("send-a-message", "Send a message"),
        ("add-an-attachment", "Add an attachment"),
        ("search-a-conversation", "Search your messages"),
        ("start-a-facetime-call", "Start a FaceTime call"),
        ("add-an-emoji", "Add an emoji"),
        ("filter-conversations", "Filter your conversation list"),
        ("send-a-photo", "Send a photo"),
        ("send-a-sticker", "Send a sticker"),
        ("create-a-poll", "Create a poll"),
        ("schedule-a-message", "Schedule a message"),
        ("create-a-genmoji", "Create a Genmoji"),
        ("generate-an-image", "Generate an image"),
        ("search-the-web-for-images", "Search the web for images"),
        ("add-a-message-effect", "Add a message effect"),
    ]

    private static var apiKey: String? {
        if let env = ProcessInfo.processInfo.environment["OPENAI_API_KEY"], !env.isEmpty { return env }
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Gaize/openai_key")
        return (try? String(contentsOf: url, encoding: .utf8))?
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static var systemPrompt: String {
        let goalList = goals.map { "- \($0.id): \($0.title)" }.joined(separator: "\n")
        var seen = Set<String>()
        let elements = KnowledgePack.entries.compactMap { entry -> String? in
            guard seen.insert(entry.key).inserted, let text = entry.explanations[.english] else { return nil }
            return "- \(entry.match): \(text)"
        }.joined(separator: "\n")

        return """
        You are Gaize, a friendly voice helper teaching someone to use the macOS Messages app hands-free. \
        Your reply is spoken aloud, so answer in 1 to 3 short, plain sentences - no lists, no markdown, no emoji.

        How Gaize is used:
        - Look at a button and say "select" to click it. Say "explain" to hear what it does.
        - To text someone: look at the compose button (top left) and say "select", say the contact's name and pause, \
        say the message and pause, then say "send".
        - Say "Gaize open" to open the lessons website.

        Messages elements:
        \(elements)

        Lessons (goals) that highlight each step on screen:
        \(goalList)

        Respond with JSON only: {"answer": "<spoken answer>", "goal": "<goal id that teaches this, or null>"}. \
        Use the person's actual words (e.g. a contact's name) in the answer. If a goal fits, mention that you'll \
        highlight each step for them.
        """
    }

    static func ask(_ question: String, lookingAt: String?, frontApp: String?,
                    language: AppLanguage, completion: @escaping (Reply?) -> Void) {
        guard let key = apiKey, !key.isEmpty else {
            print("Assistant: no OpenAI API key found")
            completion(nil)
            return
        }

        var context = "Answer in \(language.displayName)."
        if let frontApp { context += " The user is currently in \(frontApp)." }
        if let lookingAt, !lookingAt.isEmpty { context += " They are looking at \"\(lookingAt)\"." }

        let body: [String: Any] = [
            "model": model,
            "temperature": 0.3,
            "max_tokens": 200,
            "response_format": ["type": "json_object"],
            "messages": [
                ["role": "system", "content": systemPrompt],
                ["role": "user", "content": "\(context)\nQuestion: \(question)"],
            ],
        ]

        var request = URLRequest(url: URL(string: "https://api.openai.com/v1/chat/completions")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 15
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: request) { data, _, error in
            let reply = parse(data)
            if reply == nil {
                let detail = data.flatMap { String(data: $0, encoding: .utf8) } ?? error.map { "\($0)" } ?? "?"
                print("Assistant: request failed - \(detail.prefix(300))")
            }
            DispatchQueue.main.async { completion(reply) }
        }.resume()
    }

    private static func parse(_ data: Data?) -> Reply? {
        guard let data,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let content = ((json["choices"] as? [[String: Any]])?.first?["message"] as? [String: Any])?["content"] as? String,
              let inner = try? JSONSerialization.jsonObject(with: Data(content.utf8)) as? [String: Any],
              let answer = inner["answer"] as? String, !answer.isEmpty else { return nil }
        let goal = (inner["goal"] as? String).flatMap { id in goals.contains { $0.id == id } ? id : nil }
        return Reply(answer: answer, goalID: goal)
    }
}
