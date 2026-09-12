import AppKit
import ApplicationServices

struct SensedElement {
    let role: String
    let title: String
    let frame: CGRect
}

/// AX hit-testing on whatever's under the gaze point. Purely tracks which
/// element the gaze is currently on — it never speaks on its own. Speaking
/// only happens on demand, via a voice command: "explain"/"what is this" to
/// hear about the current element, "select" to confirm/press it.
final class Sensing {
    var onExplainRequested: ((SensedElement) -> Void)?
    /// Carries the raw AXUIElement alongside the description - used for
    /// dictating spoken text into a text field right after confirming it.
    var onConfirmed: ((SensedElement, AXUIElement) -> Void)?

    private let systemWide = AXUIElementCreateSystemWide()
    private var currentAXElement: AXUIElement?
    private(set) var currentSensed: SensedElement?

    /// A short rolling window of recent hit-tests (~250ms at the gaze
    /// tracker's 30fps) - a "select" acts on whichever element was hit
    /// most often in this window, not just the single most recent sample.
    /// Speech recognition takes hundreds of ms to transcribe "select," and
    /// people naturally start glancing toward the next thing right as they
    /// finish speaking - trusting only the latest instantaneous sample
    /// made select act on wherever gaze had already drifted to, not what
    /// the user actually meant.
    private var recentHits: [(element: AXUIElement, sensed: SensedElement)] = []
    private let recentHitsCapacity = 8

    private var lastHeartbeat = Date.distantPast

    /// Called on every gaze-tracker frame with the current screen-space gaze
    /// point, top-left origin (Quartz/AX coordinates, not Cocoa).
    /// The last point the gaze tracker reported - "select" clicks exactly here.
    private var lastGazePoint: CGPoint?

    func updateGaze(at point: CGPoint) {
        lastGazePoint = point

        if Date().timeIntervalSince(lastHeartbeat) > 1.0 {
            lastHeartbeat = Date()
            print("Sensing: heartbeat, gaze point = \(point)")
        }

        guard AXIsProcessTrusted() else {
            print("Sensing: NOT TRUSTED, skipping hit-test")
            return
        }

        // A single failed hit-test (gaze crossing a gap between elements)
        // used to wipe the whole recent-history window, leaving select with
        // nothing to act on - now it just skips that frame.
        guard let (axElement, sensed) = hitTest(at: point) else { return }

        recentHits.append((axElement, sensed))
        if recentHits.count > recentHitsCapacity {
            recentHits.removeFirst()
        }

        // Compare by AX element identity, not a rebuilt role/title/frame
        // string — tiny gaze jitter can make the same on-screen button
        // report marginally different frame values between frames.
        let isSameElement = currentAXElement.map { CFEqual($0, axElement) } ?? false
        if !isSameElement {
            print("Sensing: new element role=\(sensed.role) title=\"\(sensed.title)\"")
            currentAXElement = axElement
            currentSensed = sensed
        }
    }

    /// Whichever element was actually hit most often in the recent window -
    /// see recentHits' doc comment for why this beats "whatever's current."
    private func mostFrequentRecentHit() -> (element: AXUIElement, sensed: SensedElement)? {
        guard !recentHits.isEmpty else { return nil }

        var counts: [CFHashCode: (element: AXUIElement, sensed: SensedElement, count: Int)] = [:]
        for hit in recentHits {
            let hash = CFHash(hit.element)
            if var existing = counts[hash], CFEqual(existing.element, hit.element) {
                existing.count += 1
                counts[hash] = existing
            } else {
                counts[hash] = (hit.element, hit.sensed, 1)
            }
        }
        return counts.values.max(by: { $0.count < $1.count }).map { ($0.element, $0.sensed) }
    }

    private func hitTest(at point: CGPoint) -> (element: AXUIElement, sensed: SensedElement)? {
        var ref: AXUIElement?
        guard AXUIElementCopyElementAtPosition(systemWide, Float(point.x), Float(point.y), &ref) == .success,
              let element = ref, let sensed = describe(element) else { return nil }
        return (element, sensed)
    }

    /// "select" is a click: a real mouse click at the gaze point, every
    /// time. It used to AXPress the tracked element instead, which silently
    /// does nothing on anything that isn't a button (a conversation row, a
    /// text label), and it did nothing at all whenever the recent gaze
    /// history happened to be empty - both made select feel random.
    @discardableResult
    func confirmCurrentElement() -> SensedElement? {
        guard let point = lastGazePoint else {
            print("Sensing: select with no gaze point yet - nothing to click")
            return nil
        }

        // Only used to describe what got clicked (spoken confirmation,
        // website step tracking) and to pick which app to bring forward -
        // the click itself happens regardless.
        let target = hitTest(at: point) ?? mostFrequentRecentHit()
        let sensed = target?.sensed ?? SensedElement(role: "unknown", title: "", frame: .zero)

        // A click posts to whatever window is topmost at that point, and an
        // inactive window often swallows the first click just to activate
        // itself - bring the owning app forward first.
        if let element = target?.element {
            var pid: pid_t = 0
            AXUIElementGetPid(element, &pid)
            if let owner = NSRunningApplication(processIdentifier: pid),
               !owner.isActive, pid != ProcessInfo.processInfo.processIdentifier {
                print("Sensing: activating \(owner.bundleIdentifier ?? "?") before click")
                owner.activate(options: [])
                Thread.sleep(forTimeInterval: 0.25)
            }
        }

        print("Sensing: CLICK at \(point) on \"\(sensed.title)\" (\(sensed.role))")
        synthesizeClick(at: point)
        onConfirmed?(sensed, target?.element ?? systemWide)
        recentHits.removeAll()
        return sensed
    }

    /// Posts a real mouse-down/mouse-up at `point`, in AX/Quartz (top-left
    /// origin) coordinates.
    private func synthesizeClick(at point: CGPoint) {
        let source = CGEventSource(stateID: .hidSystemState)
        let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
        let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
        down?.setIntegerValueField(.mouseEventClickState, value: 1)
        up?.setIntegerValueField(.mouseEventClickState, value: 1)
        down?.post(tap: .cghidEventTap)
        usleep(30_000)
        up?.post(tap: .cghidEventTap)
    }

    /// Fired by an "explain"/"what is this" voice command.
    @discardableResult
    func explainCurrentElement() -> SensedElement? {
        guard let sensed = currentSensed else { return nil }
        onExplainRequested?(sensed)
        return sensed
    }

    /// The demo's fixed target app. The website runs in a browser, which is
    /// what's actually frontmost when the user clicks a goal — so this can't
    /// use NSWorkspace.frontmostApplication (that was the bug: highlight
    /// requests were searching the browser's AX tree, not Messages').
    ///
    /// Matched by bundle identifier, not localizedName == "Messages" -
    /// Messages' background "Messages Assistant Extension" helper process
    /// also reports that same localizedName, and .first(where:) was
    /// silently picking that windowless helper instead of the real app,
    /// which is why every window/AX-tree query kept failing.
    private static let targetAppName = "Messages"
    private static let targetBundleID = "com.apple.MobileSMS"

    /// Resolve a human-readable target description (from the website, e.g.
    /// "send button") to an on-screen frame, by walking the target app's AX
    /// tree for a matching title/description. Used to draw the overlay.
    func screenFrame(forElementDescribed description: String) -> CGRect? {
        guard let windows = targetAppWindows() else { return nil }

        print("Sensing.screenFrame: searching \"\(Self.targetAppName)\" for \"\(description)\"")
        for window in windows {
            if let found = findElement(in: window, matching: description, depth: 0) {
                return found.sensed.frame
            }
        }

        print("Sensing.screenFrame: no match for \"\(description)\" in \(Self.targetAppName)")
        return nil
    }

    /// Activates the target app if needed and returns its windows - shared
    /// by screenFrame and focusElement, both of which need to walk the same
    /// AX tree.
    private func reopen(_ app: NSRunningApplication) {
        guard let url = app.bundleURL else { return }
        let config = NSWorkspace.OpenConfiguration()
        config.activates = true
        NSWorkspace.shared.openApplication(at: url, configuration: config)
    }

    private func targetAppWindows(attempt: Int = 0) -> [AXUIElement]? {
        guard AXIsProcessTrusted() else {
            print("Sensing: not trusted")
            return nil
        }

        guard let targetApp = NSWorkspace.shared.runningApplications.first(where: {
            $0.bundleIdentifier == Self.targetBundleID
        }) else {
            print("Sensing: \(Self.targetAppName) is not running")
            return nil
        }

        // Messages (a Mac Catalyst app) only answers window/AX-tree queries
        // while it's the active app - in the background, kAXWindowsAttribute
        // and kAXFocusedWindowAttribute both report empty/error. Since the
        // whole point of this call is to show the user where to look in
        // Messages, bringing it to the front here is also just correct UX,
        // not only a technical workaround.
        if !targetApp.isActive {
            print("Sensing: activating \(Self.targetAppName) (was backgrounded)")
            targetApp.activate(options: [])
            Thread.sleep(forTimeInterval: 0.5)
        }

        let appElement = AXUIElementCreateApplication(targetApp.processIdentifier)

        // Messages is a Mac Catalyst (UIKit-on-Mac) app - Catalyst apps
        // don't expose their real AX tree until this is explicitly turned
        // on, otherwise window/children queries fail with kAXErrorCannotComplete.
        AXUIElementSetAttributeValue(appElement, "AXManualAccessibility" as CFString, kCFBooleanTrue)

        // The app element's kAXChildrenAttribute doesn't reliably surface
        // windows for every app - kAXWindowsAttribute is the documented,
        // reliable way to get them, so start the search there instead.
        // Fall back to kAXFocusedWindowAttribute if that fails - some
        // Catalyst apps answer the single-focused-window query even when
        // full window enumeration errors out.
        var windowsRef: CFTypeRef?
        let windowsResult = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute as CFString, &windowsRef)

        if windowsResult == .success, let list = windowsRef as? [AXUIElement] {
            if !list.isEmpty || attempt > 0 { return list }
            // Messages keeps running with zero windows after its last one is
            // closed - activating it then shows nothing, which is why "Learn
            // this goal" sometimes didn't visibly take you to Messages. A
            // reopen (same as clicking its Dock icon) makes it open a window.
            print("Sensing: \(Self.targetAppName) has no windows - reopening")
            reopen(targetApp)
            Thread.sleep(forTimeInterval: 1.0)
            return targetAppWindows(attempt: attempt + 1)
        }

        print("Sensing: kAXWindowsAttribute failed (axError=\(windowsResult.rawValue)), trying focused window")
        var focusedRef: CFTypeRef?
        let focusedResult = AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &focusedRef)
        if focusedResult == .success, let focused = focusedRef {
            return [focused as! AXUIElement]
        }

        print("Sensing: kAXFocusedWindowAttribute also failed (axError=\(focusedResult.rawValue))")
        return nil
    }

    private func resetCurrent() {
        currentAXElement = nil
        currentSensed = nil
        recentHits.removeAll()
    }

    private func describe(_ element: AXUIElement) -> SensedElement? {
        var role = stringAttribute(element, kAXRoleAttribute as CFString) ?? "unknown"
        var title = stringAttribute(element, kAXTitleAttribute as CFString)
            ?? stringAttribute(element, kAXDescriptionAttribute as CFString)
            ?? ""
        // The element geometry (frame) is queried from, once we borrow a
        // title from a parent - must also borrow ITS frame, not the original
        // leaf's. A leaf with no title (an inner <span>, an icon glyph) also
        // tends to have an imprecise or degenerate frame - clicking it could
        // silently miss the real clickable region even though the spoken
        // title now sounds correct.
        var geometrySource = element

        // Gaze precision is imperfect: it often lands on an untitled child
        // (an inner <span>, an AXStaticText) instead of the actual button
        // wrapping it - which used to produce nonsense like "Selecting
        // AXStaticText." The click itself still works (it bubbles up to
        // the real button), but the spoken title was meaningless and
        // KnowledgePack/matchedEntry couldn't match it either. Walk up to
        // the nearest ancestor with a real title/description instead.
        if title.isEmpty {
            var current = element
            for _ in 0..<5 {
                var parentRef: CFTypeRef?
                guard AXUIElementCopyAttributeValue(current, kAXParentAttribute as CFString, &parentRef) == .success,
                      let parentRaw = parentRef else { break }
                let parent = parentRaw as! AXUIElement

                let parentTitle = stringAttribute(parent, kAXTitleAttribute as CFString)
                    ?? stringAttribute(parent, kAXDescriptionAttribute as CFString)
                    ?? ""
                if !parentTitle.isEmpty {
                    title = parentTitle
                    role = stringAttribute(parent, kAXRoleAttribute as CFString) ?? role
                    geometrySource = parent
                    break
                }
                current = parent
            }
        }

        guard let position = pointAttribute(geometrySource, kAXPositionAttribute as CFString),
              let size = sizeAttribute(geometrySource, kAXSizeAttribute as CFString) else {
            return SensedElement(role: role, title: title, frame: .zero)
        }

        return SensedElement(role: role, title: title, frame: CGRect(origin: position, size: size))
    }

    private func findElement(in element: AXUIElement, matching description: String, depth: Int, exact: Bool? = nil) -> (element: AXUIElement, sensed: SensedElement)? {
        guard let exact else {
            // Prefer an exact title match anywhere in the tree over a partial
            // one - Messages' attach "+" button is titled exactly "add", and
            // a contains-match alone would hit "Add Contact" first.
            return findElement(in: element, matching: description, depth: depth, exact: true)
                ?? findElement(in: element, matching: description, depth: depth, exact: false)
        }
        guard depth < 25 else { return nil }

        let wanted = description.lowercased()
        if let sensed = describe(element), !sensed.title.isEmpty,
           sensed.frame.width > 0, sensed.frame.height > 0 {
            let title = sensed.title.lowercased()
            if exact ? title == wanted : title.contains(wanted) {
                return (element, sensed)
            }
        }

        var childrenRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenRef) == .success,
              let children = childrenRef as? [AXUIElement] else {
            return nil
        }

        for child in children {
            if let found = findElement(in: child, matching: description, depth: depth + 1, exact: exact) {
                return found
            }
        }
        return nil
    }

    /// Finds an element in the target app (Messages) by title match and
    /// gives it AX focus - used to auto-advance from the To: field to the
    /// message body after a recipient is confirmed, without requiring the
    /// user to separately look at/select it.
    @discardableResult
    func focusElement(forElementDescribed description: String) -> AXUIElement? {
        guard let windows = targetAppWindows() else { return nil }
        for window in windows {
            if let found = findElement(in: window, matching: description, depth: 0) {
                AXUIElementSetAttributeValue(found.element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
                // Setting AX focus alone doesn't move the caret in Messages
                // (verified: it stayed in To: after the recipient was
                // accepted) - clicking the field does.
                let frame = found.sensed.frame
                if frame.width > 0, frame.height > 0 {
                    synthesizeClick(at: CGPoint(x: frame.midX, y: frame.midY))
                }
                return found.element
            }
        }
        return nil
    }

    /// Clicks the center of `element` - the only reliable way to put the
    /// caret into a Messages (Catalyst) text field. Setting AX focus doesn't
    /// move it, so dictated text kept landing wherever the caret already was
    /// (verified: a contact name ended up in the message body, To: empty).
    func click(_ element: AXUIElement) {
        guard let frame = describe(element)?.frame, frame.width > 0, frame.height > 0 else { return }
        synthesizeClick(at: CGPoint(x: frame.midX, y: frame.midY))
    }

    /// Messages' empty To: field, if Messages is in front and a new message
    /// is open - i.e. the user is starting a new message, however they got
    /// there (compose button, Cmd+N, a click). Doesn't require the field to
    /// have keyboard focus: it often loses its caret (the on-screen
    /// keyboard, a stray click), and requiring focus made saying a name do
    /// nothing. Dictation focuses it before typing anyway.
    func focusedRecipientField() -> AXUIElement? {
        guard AXIsProcessTrusted(),
              let front = NSWorkspace.shared.frontmostApplication?.bundleIdentifier,
              front == Self.targetBundleID || front == "com.apple.KeyboardAccessAgent",
              let messages = NSWorkspace.shared.runningApplications.first(where: {
                  $0.bundleIdentifier == Self.targetBundleID
              }) else { return nil }

        let app = AXUIElementCreateApplication(messages.processIdentifier)
        AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)

        // Empty = no recipient yet, so a finished message's To: field
        // doesn't keep swallowing speech.
        func isEmptyRecipientField(_ element: AXUIElement) -> Bool {
            let title = (stringAttribute(element, kAXTitleAttribute as CFString)
                ?? stringAttribute(element, kAXDescriptionAttribute as CFString) ?? "").lowercased()
            let value = (stringAttribute(element, kAXValueAttribute as CFString) ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            // Unfocused, the empty field reports its own label ("To:") as
            // its value - that still means no recipient.
            return title == "to:" && (value.isEmpty || value.lowercased() == "to:")
        }

        var ref: CFTypeRef?
        if AXUIElementCopyAttributeValue(app, kAXFocusedUIElementAttribute as CFString, &ref) == .success,
           let raw = ref, isEmptyRecipientField(raw as! AXUIElement) {
            return (raw as! AXUIElement)
        }

        var windowsRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &windowsRef) == .success,
              let windows = windowsRef as? [AXUIElement] else { return nil }
        for window in windows {
            if let found = findElement(in: window, matching: "to:", depth: 0, exact: true) {
                if isEmptyRecipientField(found.element) { return found.element }
                print("Sensing: To: field found but not empty (value=\(stringAttribute(found.element, kAXValueAttribute as CFString) ?? "nil"))")
            }
        }
        print("Sensing: no empty To: field in \(windows.count) window(s)")
        return nil
    }

    private func stringAttribute(_ element: AXUIElement, _ attribute: CFString) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success else { return nil }
        return value as? String
    }

    private func pointAttribute(_ element: AXUIElement, _ attribute: CFString) -> CGPoint? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let axValue = value else { return nil }
        var point = CGPoint.zero
        guard CFGetTypeID(axValue) == AXValueGetTypeID(),
              AXValueGetValue((axValue as! AXValue), .cgPoint, &point) else { return nil }
        return point
    }

    private func sizeAttribute(_ element: AXUIElement, _ attribute: CFString) -> CGSize? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let axValue = value else { return nil }
        var size = CGSize.zero
        guard CFGetTypeID(axValue) == AXValueGetTypeID(),
              AXValueGetValue((axValue as! AXValue), .cgSize, &size) else { return nil }
        return size
    }
}
