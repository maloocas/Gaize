import Foundation
import CoreGraphics

/// Camera -> screen-space gaze point.
/// TODO: replace stub with real MediaPipe Face Landmarker / iris tracking
/// (call out to a small local Python process, or a native MediaPipe C++ build),
/// plus a short per-user calibration step (4-9 point look-and-click) to map
/// eye landmarks to screen coordinates.
final class GazeTracker {
    var onGazePoint: ((CGPoint) -> Void)?

    func start() {
        // TODO: start camera capture + MediaPipe pipeline, call onGazePoint per frame.
    }

    func stop() {
        // TODO
    }
}
