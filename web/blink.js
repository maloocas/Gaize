/* Blink-as-switch (design doc s5).
 *
 * Deliberately NOT gaze-point tracking. We only need one bit - "did they blink
 * just now" - which a plain RGB webcam gives reliably without calibration rigs
 * or IR hardware.
 *
 * Method: MediaPipe Face Mesh landmarks -> eye aspect ratio (EAR) per eye,
 * averaged. EAR collapses toward zero when the lid closes. A blink is a
 * *closed-then-open* transition whose closed phase falls inside a plausible
 * duration window, which rejects both camera noise and someone simply resting
 * their eyes.
 *
 * The runtime and model are vendored under web/vendor/, so this works with no
 * network at all - venue wifi cannot break the demo.
 */
import { FaceLandmarker, FilesetResolver } from "./vendor/vision_bundle.mjs";
import {
  LEFT_EYE, RIGHT_EYE, meanEar, createBlinkGate, thresholdFromSamples,
} from "./blink-core.js";

export function initBlink({ video, overlay, placeholder, onBlink, onEar, onStatus }) {
  let landmarker = null;
  let stream = null;
  let running = false;
  let rafId = null;
  let lastVideoTime = -1;

  let threshold = 0.21;
  let calibrating = false;
  let calibSamples = [];
  const gate = createBlinkGate();
  let lastClosed = false;

  const ctx = overlay.getContext("2d");

  async function ensureLandmarker() {
    if (landmarker) return landmarker;
    onStatus("loading face model…", "loading");
    // Vendored wasm + model: no CDN, no network.
    const fileset = await FilesetResolver.forVisionTasks("./vendor/wasm");
    landmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: "./vendor/face_landmarker.task", delegate: "GPU" },
      runningMode: "VIDEO",
      numFaces: 1,
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: false,
    });
    return landmarker;
  }

  async function start() {
    try {
      await ensureLandmarker();
    } catch (err) {
      onStatus(`could not load face model: ${err.message}`, "error");
      return false;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" }, audio: false,
      });
    } catch (err) {
      onStatus(`camera blocked: ${err.message}. Keyboard switch still works.`, "error");
      return false;
    }
    video.srcObject = stream;
    await video.play().catch(() => {});
    placeholder.style.display = "none";
    overlay.width = video.videoWidth || 640;
    overlay.height = video.videoHeight || 480;
    running = true;
    onStatus("tracking — blink to select. Calibrate for best results.", "live");
    loop();
    return true;
  }

  function stop() {
    running = false;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    video.srcObject = null;
    placeholder.style.display = "";
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    onStatus("camera off — keyboard switch active", "off");
  }

  function draw(pts) {
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!pts) return;
    ctx.strokeStyle = lastClosed ? "#ffd23f" : "#3fb950";
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = 2;
    for (const idx of [LEFT_EYE, RIGHT_EYE]) {
      ctx.beginPath();
      idx.forEach((i, n) => {
        const p = pts[i];
        if (!p) return;
        const x = p.x * overlay.width, y = p.y * overlay.height;
        if (n === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.stroke();
    }
  }

  function handleEar(ear) {
    if (calibrating) {
      calibSamples.push(ear);
      return;
    }
    const result = gate.update(ear, threshold, performance.now());
    lastClosed = result.closed;
    if (result.blink) {
      onBlink();
      onStatus(`blink ✓ (${Math.round(result.heldMs)}ms closed)`, "live");
    }
  }

  function loop() {
    if (!running) return;
    rafId = requestAnimationFrame(loop);
    if (!landmarker || video.readyState < 2) return;
    if (video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;

    let result;
    try {
      result = landmarker.detectForVideo(video, performance.now());
    } catch {
      return;
    }
    const pts = result?.faceLandmarks?.[0];
    if (!pts) {
      draw(null);
      onEar(0, threshold);
      return;
    }
    const ear = meanEar(pts);
    if (ear === null) return;
    onEar(ear, threshold);
    handleEar(ear);
    draw(pts);
  }

  /** Sample the operator's eyes-open EAR and set the threshold from it.
   *  This is the fix for individual eye shape, glasses and venue lighting
   *  (doc s11) - a hardcoded threshold does not survive a new face. */
  function calibrate() {
    if (!running) return;
    calibrating = true;
    calibSamples = [];
    onStatus("calibrating — keep eyes OPEN and look at the camera…", "loading");
    setTimeout(() => {
      calibrating = false;
      if (calibSamples.length < 10) {
        onStatus("calibration failed — no stable face. Try more light.", "error");
        return;
      }
      const calib = thresholdFromSamples(calibSamples);
      if (!calib) {
        onStatus("calibration failed \u2014 not enough stable samples.", "error");
        return;
      }
      const { open } = calib;
      threshold = calib.threshold;
      gate.reset();
      const slider = document.getElementById("earSlider");
      const out = document.getElementById("earSliderOut");
      if (slider) slider.value = String(threshold);
      if (out) out.textContent = threshold.toFixed(3);
      onStatus(`calibrated: open EAR ${open.toFixed(3)} → threshold ${threshold.toFixed(3)}`, "live");
    }, 3000);
  }

  return {
    start, stop, calibrate,
    running: () => running,
    setThreshold: (v) => { threshold = v; },
  };
}
