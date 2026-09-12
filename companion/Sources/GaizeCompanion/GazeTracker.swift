import AppKit

/// TEMPORARY MOCK: reports the real mouse cursor position as the "gaze
/// point," in AX/Quartz coordinates (top-left origin), so the rest of the
/// pipeline (Sensing/Overlay/Bridge) can be built and demoed before the real
/// camera + MediaPipe tracker lands.
///
/// Tracker team: replace the body of `start()`/`stop()` with the real camera
/// capture + gaze-estimation pipeline (plus a calibration step). Keep the
/// `onGazePoint` contract identical — a screen-space CGPoint, top-left
/// origin, called at roughly the display's frame rate — and nothing else in
/// the app needs to change.
final class GazeTracker {
    var onGazePoint: ((CGPoint) -> Void)?

    private var timer: Timer?

    func start() {
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { [weak self] _ in
            guard let screenHeight = NSScreen.main?.frame.height else { return }
            let cocoaPoint = NSEvent.mouseLocation
            let axPoint = CGPoint(x: cocoaPoint.x, y: screenHeight - cocoaPoint.y)
            self?.onGazePoint?(axPoint)
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }
}
