/* Pure blink logic - no DOM, no MediaPipe, no camera.
 *
 * Split out from blink.js so the part that actually decides "was that a blink"
 * can be tested without a webcam and a cooperative face. Everything here is a
 * pure function of numbers, so the venue-day failure modes (noisy EAR, long
 * eye-rests, double-triggers, an operator whose eyes are simply narrower) are
 * all reachable in a test.
 */

// Six-point EAR landmarks per eye, MediaPipe Face Mesh indexing.
// Order: [outer, upper1, upper2, inner, lower2, lower1]
export const RIGHT_EYE = [33, 160, 158, 133, 153, 144];
export const LEFT_EYE = [362, 385, 387, 263, 373, 380];

export const BLINK_DEFAULTS = {
  minClosedMs: 70,        // below this it is sensor noise, not a blink
  maxClosedMs: 900,       // above this they are resting their eyes, not signalling
  refractoryMs: 380,      // one blink cannot fire twice
  closedFramesNeeded: 2,  // consecutive sub-threshold frames before "closed"
};

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Eye aspect ratio for one eye. Returns null if landmarks are missing. */
export function earFor(points, indices) {
  const p = indices.map((i) => points[i]);
  if (p.some((q) => !q)) return null;
  const vertical = dist(p[1], p[5]) + dist(p[2], p[4]);
  const horizontal = dist(p[0], p[3]);
  if (horizontal < 1e-6) return null;
  return vertical / (2 * horizontal);
}

/** Average EAR across both eyes, ignoring an eye whose landmarks are missing. */
export function meanEar(points) {
  const vals = [earFor(points, LEFT_EYE), earFor(points, RIGHT_EYE)]
    .filter((v) => v !== null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

/**
 * The blink state machine.
 *
 * Fires on the closed -> open transition rather than on eye-closure, so a long
 * deliberate rest never fires, and the duration window is checked against the
 * whole closed phase.
 */
export function createBlinkGate(options = {}) {
  const cfg = { ...BLINK_DEFAULTS, ...options };
  let closedFrames = 0;
  let closedSince = 0;
  let lastFire = -Infinity;

  return {
    /** Feed one frame. Returns a result object describing what happened. */
    update(ear, threshold, now) {
      if (ear < threshold) {
        closedFrames += 1;
        if (closedFrames === cfg.closedFramesNeeded) closedSince = now;
        return { blink: false, closed: closedFrames >= cfg.closedFramesNeeded };
      }
      // Eye is open. If it was closed, judge the closed phase we just left.
      if (closedFrames >= cfg.closedFramesNeeded) {
        const heldMs = now - closedSince;
        closedFrames = 0;
        if (heldMs < cfg.minClosedMs) return { blink: false, closed: false, reason: "too short" };
        if (heldMs > cfg.maxClosedMs) return { blink: false, closed: false, reason: "too long" };
        if (now - lastFire < cfg.refractoryMs) return { blink: false, closed: false, reason: "refractory" };
        lastFire = now;
        return { blink: true, closed: false, heldMs };
      }
      closedFrames = 0;
      return { blink: false, closed: false };
    },
    isClosed: () => closedFrames >= cfg.closedFramesNeeded,
    reset() { closedFrames = 0; lastFire = -Infinity; },
  };
}

/**
 * Pick a blink threshold from EAR samples taken with the eyes open.
 *
 * Uses the interquartile mean so a stray blink during calibration cannot drag
 * the threshold down, then takes a fixed fraction of the open baseline. This is
 * what makes the detector survive a different operator, glasses, or venue
 * lighting instead of relying on a hardcoded constant (doc s5, s11).
 */
export function thresholdFromSamples(samples, fraction = 0.72,
                                     floor = 0.10, ceiling = 0.33) {
  if (!samples || samples.length < 10) return null;
  const sorted = [...samples].sort((a, b) => a - b);
  const mid = sorted.slice(
    Math.floor(sorted.length * 0.25),
    Math.ceil(sorted.length * 0.75));
  const open = mid.reduce((a, b) => a + b, 0) / mid.length;
  return {
    open,
    threshold: Math.max(floor, Math.min(ceiling, open * fraction)),
  };
}
