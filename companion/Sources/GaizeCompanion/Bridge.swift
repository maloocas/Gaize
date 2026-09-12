import Foundation
import Network

/// Local WebSocket server (localhost:8765) that the website connects to.
/// Website -> companion: { "type": "highlight", "target": "send button" }
/// Companion -> website: { "type": "hover" | "action_completed", "element": "..." }
///
/// TODO: implement with Network.framework (NWListener + NWProtocolWebSocket),
/// or swap in a small library if that proves fiddly. Keep the wire format
/// as plain JSON text frames so the website side stays a few lines of JS.
final class Bridge {
    static let port: UInt16 = 8765

    var onHighlightRequest: ((String) -> Void)?

    private var listener: NWListener?

    func start() {
        // TODO: start NWListener on Bridge.port, accept connections,
        // decode incoming JSON frames, dispatch to onHighlightRequest.
    }

    func send(event: String, element: SensedElement) {
        // TODO: encode { "type": event, "role": element.role, "title": element.title }
        // and broadcast to connected website client(s).
    }
}
