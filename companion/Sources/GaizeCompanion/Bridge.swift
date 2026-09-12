import Foundation
import Network

/// Local WebSocket server (localhost:8765) that the website connects to.
/// Website -> companion: { "type": "highlight", "target": "send button" }
///                        { "type": "set_language", "language": "es-ES" }
/// Companion -> website: { "type": "hover" | "action_completed", "role": "...", "title": "..." }
final class Bridge {
    static let port: UInt16 = 8765

    var onHighlightRequest: ((String) -> Void)?
    var onSetLanguage: ((String) -> Void)?
    /// Debug-only: triggers the same thing "explain" (the voice command)
    /// does, for testing without needing to actually speak.
    var onDebugExplain: (() -> Void)?

    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private let queue = DispatchQueue(label: "gaize.bridge")

    func start() {
        let params = NWParameters.tcp
        let wsOptions = NWProtocolWebSocket.Options()
        wsOptions.autoReplyPing = true
        params.defaultProtocolStack.applicationProtocols.insert(wsOptions, at: 0)

        guard let port = NWEndpoint.Port(rawValue: Bridge.port) else { return }

        do {
            let listener = try NWListener(using: params, on: port)
            listener.newConnectionHandler = { [weak self] connection in
                self?.accept(connection)
            }
            listener.start(queue: queue)
            self.listener = listener
        } catch {
            print("Bridge: failed to start listener on port \(Bridge.port): \(error)")
        }
    }

    private func accept(_ connection: NWConnection) {
        connections.append(connection)

        connection.stateUpdateHandler = { [weak self, weak connection] state in
            switch state {
            case .failed, .cancelled:
                guard let connection else { return }
                self?.connections.removeAll { $0 === connection }
            default:
                break
            }
        }

        connection.start(queue: queue)
        receive(on: connection)
    }

    private func receive(on connection: NWConnection) {
        connection.receiveMessage { [weak self] data, _, _, error in
            if let data, !data.isEmpty {
                self?.handle(data)
            }
            if error == nil {
                self?.receive(on: connection)
            }
        }
    }

    private func handle(_ data: Data) {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else { return }

        switch type {
        case "highlight":
            guard let target = json["target"] as? String else { return }
            DispatchQueue.main.async { [weak self] in
                self?.onHighlightRequest?(target)
            }
        case "set_language":
            guard let language = json["language"] as? String else { return }
            DispatchQueue.main.async { [weak self] in
                self?.onSetLanguage?(language)
            }
        case "debug_explain":
            DispatchQueue.main.async { [weak self] in
                self?.onDebugExplain?()
            }
        default:
            break
        }
    }

    func send(event: String, element: SensedElement) {
        let payload: [String: Any] = ["type": event, "role": element.role, "title": element.title]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }

        let metadata = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "gaizeEvent", metadata: [metadata])

        for connection in connections {
            connection.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { _ in })
        }
    }
}
