import AppKit
import ApplicationServices

/// Voice-dictates spoken text into a text field via synthesized keystrokes,
/// and surfaces an on-screen keyboard as an option when compose is selected.
///
/// The on-screen keyboard is a placeholder for the teammate's real custom
/// keyboard - for now it launches macOS's built-in Accessibility Keyboard,
/// which should be a drop-in swap for whatever they build (just call their
/// show/open function instead of showOnScreenKeyboard() below).
enum Dictation {
    /// Types `text` into `element` via a single synthesized keystroke event
    /// carrying the whole string - works across apps without needing to
    /// know the field's exact AX API for setting text directly.
    static func type(_ text: String, into element: AXUIElement) {
        AXUIElementSetAttributeValue(element, kAXFocusedAttribute as CFString, kCFBooleanTrue)

        guard let source = CGEventSource(stateID: .hidSystemState) else { return }
        let utf16 = Array(text.utf16)

        let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true)
        down?.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: utf16)
        down?.post(tap: .cghidEventTap)

        let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false)
        up?.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: utf16)
        up?.post(tap: .cghidEventTap)
    }

    /// Accepts the top autocomplete suggestion (e.g. a matched contact in
    /// Messages' To: field) by pressing Return. Only appropriate for fields
    /// where Return means "accept the suggestion," not "send" - callers
    /// must not use this on the message-body field.
    private static let returnKeyCode: CGKeyCode = 0x24

    static func confirmAutocomplete() {
        guard let source = CGEventSource(stateID: .hidSystemState) else { return }
        CGEvent(keyboardEventSource: source, virtualKey: returnKeyCode, keyDown: true)?.post(tap: .cghidEventTap)
        CGEvent(keyboardEventSource: source, virtualKey: returnKeyCode, keyDown: false)?.post(tap: .cghidEventTap)
    }

    /// Sends the Messages draft - Return in the message body. Only called
    /// by the explicit "send" voice command, after checking the body has text.
    static func pressReturnToSend() {
        confirmAutocomplete()
    }

    /// Placeholder for the teammate's on-screen keyboard. macOS's built-in
    /// Accessibility Keyboard is actually KeyboardAccessAgent.app
    /// (com.apple.KeyboardAccessAgent) under the hood, not the more
    /// guessable "AccessibilityKeyboard" bundle ID.
    static func showOnScreenKeyboard() {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.KeyboardAccessAgent") else {
            print("Dictation: Accessibility Keyboard app not found")
            return
        }
        print("Dictation: opening on-screen keyboard at \(url)")
        let config = NSWorkspace.OpenConfiguration()
        NSWorkspace.shared.open(url, configuration: config) { app, error in
            if let error {
                print("Dictation: failed to open on-screen keyboard: \(error)")
            }
        }
    }
}
