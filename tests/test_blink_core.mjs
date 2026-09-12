/* Tests for the blink decision logic (public/blink-core.js).
 * Run: node tests/test_blink_core.mjs
 *
 * These cover the failure modes that cannot be reproduced on demand in front of
 * a webcam: noisy frames, a long deliberate eye-rest, double-triggering, and an
 * operator whose open-eye EAR sits far from the default threshold. */
import assert from "node:assert/strict";
import {
  meanEar, earFor, createBlinkGate, thresholdFromSamples, LEFT_EYE, RIGHT_EYE,
} from "../public/blink-core.js";

let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log(`  ok   ${name}`); }
  catch (e) { failed++; console.log(`  FAIL ${name}\n       ${e.message}`); }
}

/* ---- helpers: synthesise landmark sets with a chosen aperture ---- */
function eyeLandmarks(aperture) {
  // Build a 468-slot sparse array with the 12 points the EAR uses.
  const pts = [];
  const put = (idx, x, y) => { pts[idx] = { x, y }; };
  for (const eye of [LEFT_EYE, RIGHT_EYE]) {
    const [outer, up1, up2, inner, low2, low1] = eye;
    put(outer, 0.0, 0.0);
    put(inner, 0.1, 0.0);          // horizontal span = 0.1
    put(up1, 0.03, -aperture / 2);
    put(up2, 0.07, -aperture / 2);
    put(low1, 0.03, aperture / 2);
    put(low2, 0.07, aperture / 2);
  }
  return pts;
}

/** Feed a gate a sequence of (ear, dtMs) and count blinks. */
function feed(gate, steps, threshold = 0.21, startTime = 1000) {
  let now = startTime, blinks = 0;
  for (const [ear, dt] of steps) {
    now += dt;
    if (gate.update(ear, threshold, now).blink) blinks++;
  }
  return blinks;
}

const OPEN = 0.30, SHUT = 0.10;
const frames = (ear, count, dt = 33) => Array.from({ length: count }, () => [ear, dt]);

console.log("\nEAR geometry");
test("open eye gives a higher EAR than a closed one", () => {
  assert.ok(meanEar(eyeLandmarks(0.12)) > meanEar(eyeLandmarks(0.02)));
});
test("EAR matches the closed-form value", () => {
  // vertical = 2 * aperture, horizontal = 0.1  ->  EAR = aperture / 0.1
  assert.ok(Math.abs(meanEar(eyeLandmarks(0.03)) - 0.3) < 1e-9);
});
test("missing landmarks yield null rather than NaN", () => {
  assert.equal(earFor([], LEFT_EYE), null);
});
test("meanEar tolerates one unusable eye", () => {
  const pts = eyeLandmarks(0.03);
  RIGHT_EYE.forEach((i) => { delete pts[i]; });
  assert.ok(Math.abs(meanEar(pts) - 0.3) < 1e-9);
});
test("degenerate horizontal span does not divide by zero", () => {
  const pts = [];
  LEFT_EYE.forEach((i) => { pts[i] = { x: 0, y: 0 }; });
  assert.equal(earFor(pts, LEFT_EYE), null);
});

console.log("\nBlink detection");
test("a normal blink fires exactly once", () => {
  const g = createBlinkGate();
  assert.equal(feed(g, [...frames(OPEN, 5), ...frames(SHUT, 5), ...frames(OPEN, 5)]), 1);
});
test("fires on reopening, not while the eye is still shut", () => {
  const g = createBlinkGate();
  assert.equal(feed(g, [...frames(OPEN, 3), ...frames(SHUT, 6)]), 0);
});
test("a single noisy frame is not a blink", () => {
  const g = createBlinkGate();
  assert.equal(feed(g, [...frames(OPEN, 5), [SHUT, 33], ...frames(OPEN, 5)]), 0);
});
test("a long eye-rest is not a blink", () => {
  const g = createBlinkGate();
  // ~1.65s closed, past maxClosedMs
  assert.equal(feed(g, [...frames(OPEN, 3), ...frames(SHUT, 50), ...frames(OPEN, 3)]), 0);
});
test("two deliberate blinks fire twice", () => {
  const g = createBlinkGate();
  const seq = [...frames(OPEN, 5), ...frames(SHUT, 5), ...frames(OPEN, 20),
               ...frames(SHUT, 5), ...frames(OPEN, 5)];
  assert.equal(feed(g, seq), 2);
});
test("refractory period suppresses an immediate re-fire", () => {
  const g = createBlinkGate();
  // Two blinks only ~130ms apart - a bounce, not two intentional signals.
  const seq = [...frames(OPEN, 5), ...frames(SHUT, 4), ...frames(OPEN, 2),
               ...frames(SHUT, 4), ...frames(OPEN, 5)];
  assert.equal(feed(g, seq), 1);
});
test("steady open eyes never fire", () => {
  const g = createBlinkGate();
  assert.equal(feed(g, frames(OPEN, 300)), 0);
});
test("a narrow-eyed operator fires once the threshold is calibrated", () => {
  // Open EAR of 0.18 sits below the 0.21 default: uncalibrated it reads as
  // permanently closed and never fires. This is the glasses / eye-shape case.
  const narrowOpen = 0.18, narrowShut = 0.07;
  const seq = [...frames(narrowOpen, 5), ...frames(narrowShut, 5), ...frames(narrowOpen, 5)];
  assert.equal(feed(createBlinkGate(), seq, 0.21), 0, "default threshold should fail here");
  const { threshold } = thresholdFromSamples(Array(40).fill(narrowOpen));
  assert.equal(feed(createBlinkGate(), seq, threshold), 1, "calibrated threshold should work");
});
test("reset clears the refractory lockout", () => {
  const g = createBlinkGate();
  feed(g, [...frames(OPEN, 5), ...frames(SHUT, 5), ...frames(OPEN, 2)]);
  g.reset();
  assert.equal(feed(g, [...frames(OPEN, 3), ...frames(SHUT, 5), ...frames(OPEN, 3)], 0.21, 1000), 1);
});

console.log("\nCalibration");
test("threshold sits below the open baseline", () => {
  const { open, threshold } = thresholdFromSamples(Array(40).fill(0.30));
  assert.ok(Math.abs(open - 0.30) < 1e-9);
  assert.ok(threshold < open && threshold > 0.15);
});
test("a stray blink during calibration does not drag the threshold down", () => {
  const clean = thresholdFromSamples(Array(40).fill(0.30)).threshold;
  const noisy = thresholdFromSamples([...Array(36).fill(0.30), 0.05, 0.05, 0.06, 0.04]).threshold;
  assert.ok(Math.abs(clean - noisy) < 0.01, `clean ${clean} vs noisy ${noisy}`);
});
test("too few samples refuses to calibrate", () => {
  assert.equal(thresholdFromSamples([0.3, 0.3]), null);
});
test("threshold is clamped into a sane band", () => {
  assert.ok(thresholdFromSamples(Array(40).fill(0.9)).threshold <= 0.33);
  assert.ok(thresholdFromSamples(Array(40).fill(0.01)).threshold >= 0.10);
});

console.log(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed ? 1 : 0);
