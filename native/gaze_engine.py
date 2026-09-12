"""Webcam gaze engine: MediaPipe face landmarks -> eye features -> ridge regression.

Python port of the Gaize/BeaverLabs-FCH web engine (RealEye-style), so gaze
runs inside the native controller:

  1. MediaPipe Face Landmarker finds 478 face landmarks, per-eye blink and
     squint scores, and the head pose.
  2. Each eye is cropped, shrunk to a small grayscale patch and normalized. The
     patches, iris positions and head pose form one feature vector per frame.
  3. Calibration stores quality-gated frames while the user looks at known
     points, then fits a ridge regression (features -> screen points), with the
     ridge strength chosen by leave-one-point-out cross-validation.
  4. Validation measures the median offset at a few more points and removes it.
  5. Live samples are median + adaptive-EMA smoothed, blinks and lost faces are
     marked invalid, and head movement away from the calibrated pose is flagged.

All coordinates are Quartz screen points (origin top-left). Thread-safe: the
camera thread calls process(); the UI thread drives calibration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import statistics
import threading

import cv2
import numpy as np

MODEL_PATH = Path(__file__).resolve().parents[1] / "public" / "vendor" / "face_landmarker.task"

# Landmark ids. "Left"/"right" are the subject's own eyes.
LEFT_EYE_CORNERS = (362, 263)
RIGHT_EYE_CORNERS = (33, 133)
LEFT_IRIS = (473, 474, 475, 476, 477)
RIGHT_IRIS = (468, 469, 470, 471, 472)
LEFT_LIDS = (386, 374)
RIGHT_LIDS = (159, 145)

PATCH_W, PATCH_H = 32, 16
GEOMETRY_WEIGHT = 8.0        # iris/pose features vs 1024 pixel features
BLINK = 0.45                 # frames with an eye this closed are not gaze
LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)


@dataclass
class Observation:
    features: np.ndarray
    x: float                 # face center, 0..1 of frame
    y: float
    scale: float             # face width, 0..1 of frame
    yaw: float
    pitch: float
    left_blink: float
    right_blink: float
    squint: float


@dataclass
class Sample:
    t: float
    valid: bool
    x: float = 0.0
    y: float = 0.0
    raw: tuple | None = None
    drift: bool = False
    reason: str = ""
    obs: Observation | None = field(default=None, repr=False)


def _eye_patch(gray, points, corners, width, height):
    a, b = points[corners[0]], points[corners[1]]
    ax, ay, bx, by = a[0] * width, a[1] * height, b[0] * width, b[1] * height
    eye_w = math.hypot(bx - ax, by - ay)
    if eye_w < 4:
        return None
    # Rotate so the eye corners are level, then crop 1.5 x 0.75 eye widths.
    angle = math.degrees(math.atan2(by - ay, bx - ax))
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    m = cv2.getRotationMatrix2D((cx, cy), angle, PATCH_W / (1.5 * eye_w))
    m[0, 2] += PATCH_W / 2 - cx
    m[1, 2] += PATCH_H / 2 - cy
    patch = cv2.warpAffine(gray, m, (PATCH_W, PATCH_H), flags=cv2.INTER_AREA)
    patch = cv2.equalizeHist(patch).astype(np.float32)
    return (patch - patch.mean()) / (patch.std() + 1e-6)


def _iris(points, iris, corners, lids):
    ix = sum(points[i][0] for i in iris) / len(iris)
    iy = sum(points[i][1] for i in iris) / len(iris)
    a, b = points[corners[0]], points[corners[1]]
    top, bottom = points[lids[0]], points[lids[1]]
    w = (b[0] - a[0]) or 1e-6
    h = (bottom[1] - top[1]) or 1e-6
    return ((ix - a[0]) / w, (iy - top[1]) / h)


def _pose(matrix):
    r = np.asarray(matrix)[:3, :3]
    yaw = math.asin(max(-1.0, min(1.0, -r[2, 0])))
    pitch = math.atan2(r[2, 1], r[2, 2])
    roll = math.atan2(r[1, 0], r[0, 0])
    return yaw, pitch, roll


def observe(frame_bgr, result):
    """Features and face condition from one landmarker result, or None."""
    if not result.face_landmarks:
        return None
    height, width = frame_bgr.shape[:2]
    points = [(p.x, p.y) for p in result.face_landmarks[0]]
    if len(points) < 478:
        return None
    shapes = {c.category_name: c.score for c in (result.face_blendshapes or [[]])[0]}
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    left = _eye_patch(gray, points, LEFT_EYE_CORNERS, width, height)
    right = _eye_patch(gray, points, RIGHT_EYE_CORNERS, width, height)
    if left is None or right is None:
        return None
    matrices = result.facial_transformation_matrixes
    yaw, pitch, roll = _pose(matrices[0]) if matrices else (0.0, 0.0, 0.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    scale = max(xs) - min(xs)
    geometry = np.array([*_iris(points, LEFT_IRIS, LEFT_EYE_CORNERS, LEFT_LIDS),
                         *_iris(points, RIGHT_IRIS, RIGHT_EYE_CORNERS, RIGHT_LIDS),
                         yaw, pitch, roll, cx, cy, scale], dtype=np.float32)
    return Observation(
        features=np.concatenate([left.ravel(), right.ravel(), geometry]),
        x=cx, y=cy, scale=scale, yaw=yaw, pitch=pitch,
        # MediaPipe names blendshapes from the viewer's side of a mirrored
        # image; the controller's calibration wink test settles which is which.
        left_blink=shapes.get("eyeBlinkLeft", 0.0),
        right_blink=shapes.get("eyeBlinkRight", 0.0),
        squint=max(shapes.get("eyeSquintLeft", 0.0), shapes.get("eyeSquintRight", 0.0)))


class RidgeGaze:
    """Standardized ridge regression, fitted in dual form (few samples, many features)."""

    def fit(self, features, targets, groups):
        x = np.asarray(features, dtype=np.float64)
        y = np.asarray(targets, dtype=np.float64)
        self.mean = x.mean(axis=0)
        self.std = x.std(axis=0) + 1e-6
        self.weight = np.ones(x.shape[1])
        self.weight[-10:] = GEOMETRY_WEIGHT
        z = self._standardize(x)
        groups = np.asarray(groups)
        self.lam = min(LAMBDAS, key=lambda lam: self._cv_error(z, y, groups, lam))
        self.y_mean = y.mean(axis=0)
        self.z = z
        self.alpha = np.linalg.solve(z @ z.T + self.lam * np.eye(len(z)), y - self.y_mean)
        return self

    def _standardize(self, x):
        return (x - self.mean) / self.std * self.weight

    @staticmethod
    def _cv_error(z, y, groups, lam):
        errors = []
        for g in np.unique(groups):
            train, test = groups != g, groups == g
            if train.sum() < 2:
                continue
            zt, yt = z[train], y[train]
            mean = yt.mean(axis=0)
            alpha = np.linalg.solve(zt @ zt.T + lam * np.eye(len(zt)), yt - mean)
            pred = z[test] @ zt.T @ alpha + mean
            errors.append(np.linalg.norm(pred - y[test], axis=1).mean())
        return float(np.mean(errors)) if errors else 0.0

    def predict(self, features):
        z = self._standardize(np.asarray(features, dtype=np.float64)[None, :])
        x, y = (z @ self.z.T @ self.alpha + self.y_mean)[0]
        return float(x), float(y)


def _quality(obs, previous):
    if obs is None:
        return "face not found"
    if max(obs.left_blink, obs.right_blink) > BLINK:
        return "blink"
    if obs.scale < 0.1:
        return "move closer"
    if previous is not None:
        motion = math.hypot(obs.x - previous.x, obs.y - previous.y)
        if motion > 0.018 or abs(obs.scale - previous.scale) / previous.scale > 0.05:
            return "hold head still"
    return None


def _drifted(obs, ref):
    if ref is None:
        return False
    return (math.hypot(obs.x - ref["x"], obs.y - ref["y"]) >= 0.045
            or abs(obs.scale - ref["scale"]) / ref["scale"] >= 0.15
            or abs(obs.yaw - ref["yaw"]) >= 0.14
            or abs(obs.pitch - ref["pitch"]) >= 0.14)


class GazeEngine:
    def __init__(self, screen_w, screen_h, model_path=MODEL_PATH):
        import mediapipe as mp
        from mediapipe.tasks import python as tasks
        from mediapipe.tasks.python import vision
        self.mp = mp
        self.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO, num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True))
        self.screen_w, self.screen_h = screen_w, screen_h
        self.lock = threading.Lock()
        self.last_ts = 0
        self.reset()

    def reset(self):
        with getattr(self, "lock", threading.Lock()):
            self.model = None
            self.features, self.targets, self.groups, self.conditions = [], [], [], []
            self.validation = []
            self.bias = (0.0, 0.0)
            self.reference = None
            self.collect = None      # (kind, x, y, [obs]) while capturing a target
            self.previous = None
            self.recent = []
            self.smooth = None

    @property
    def calibrated(self):
        return self.model is not None

    def process(self, frame_bgr, t):
        """One camera frame -> (Sample, Observation or None)."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        ts = max(self.last_ts + 1, int(t * 1000))
        self.last_ts = ts
        obs = observe(frame_bgr, self.landmarker.detect_for_video(image, ts))
        with self.lock:
            if self.collect is not None:
                reason = _quality(obs, self.previous)
                if obs is not None:
                    self.previous = obs
                if reason is None:
                    self.collect[3].append(obs)
            return self._sample(obs, t), obs

    def _sample(self, obs, t):
        if obs is None:
            return Sample(t, False, reason="no-face")
        if max(obs.left_blink, obs.right_blink) > BLINK:
            return Sample(t, False, reason="blink", obs=obs)
        if self.model is None:
            return Sample(t, False, reason="uncalibrated", obs=obs)
        gx, gy = self.model.predict(obs.features)
        raw = (min(max(gx + self.bias[0], 0.0), self.screen_w),
               min(max(gy + self.bias[1], 0.0), self.screen_h))
        # Five-sample median, then an EMA that follows big jumps faster.
        self.recent = (self.recent + [raw])[-5:]
        fx = statistics.median(p[0] for p in self.recent)
        fy = statistics.median(p[1] for p in self.recent)
        if self.smooth is None:
            self.smooth = [fx, fy]
        jump = math.hypot(fx - self.smooth[0], fy - self.smooth[1]) / self.screen_w * 1500
        alpha = 0.5 if jump > 180 else 0.32 if jump > 70 else 0.17
        self.smooth[0] += (fx - self.smooth[0]) * alpha
        self.smooth[1] += (fy - self.smooth[1]) * alpha
        return Sample(t, True, self.smooth[0], self.smooth[1], raw,
                      _drifted(obs, self.reference), obs=obs)

    # -- calibration: begin_target, wait while frames arrive, end_target ------

    def begin_target(self, kind, x, y):
        with self.lock:
            self.collect = (kind, x, y, [])
            self.previous = None

    def end_target(self, minimum=4):
        """Stores the captured frames. Returns how many passed the quality gate."""
        with self.lock:
            kind, x, y, frames = self.collect
            self.collect = None
        if len(frames) < minimum:
            return len(frames)
        if kind == "calibration":
            group = len(set(self.groups))
            for obs in frames:
                self.features.append(obs.features)
                self.targets.append((x, y))
                self.groups.append(group)
                self.conditions.append(obs)
        elif self.model is not None:
            preds = [self.model.predict(obs.features) for obs in frames]
            self.validation.append((x, y, statistics.median(p[0] for p in preds),
                                    statistics.median(p[1] for p in preds)))
        return len(frames)

    def finish_calibration(self):
        if len(set(self.groups)) < 5:
            raise ValueError("fewer than five calibration points were captured")
        model = RidgeGaze().fit(self.features, self.targets, self.groups)
        c = self.conditions
        reference = {k: statistics.median(getattr(o, k) for o in c)
                     for k in ("x", "y", "scale", "yaw", "pitch")}
        with self.lock:
            self.model, self.reference = model, reference
            self.features, self.targets, self.conditions = [], [], []

    def finish_validation(self):
        """Applies the median bias. Returns (points, median error after the fix)."""
        v = self.validation
        with self.lock:
            self.recent, self.smooth = [], None
            if v:
                self.bias = (statistics.median(p[0] - p[2] for p in v),
                             statistics.median(p[1] - p[3] for p in v))
        if len(v) < 2:
            return len(v), None
        return len(v), statistics.median(
            math.hypot(p[2] + self.bias[0] - p[0], p[3] + self.bias[1] - p[1]) for p in v)

    def save(self, path):
        """Persist the fitted calibration (model, reference pose, bias)."""
        import pickle, time
        with self.lock:
            if self.model is None:
                raise ValueError("not calibrated")
            state = {"version": 1, "screen": (self.screen_w, self.screen_h),
                     "model": self.model, "reference": self.reference,
                     "bias": self.bias, "saved_at": time.time()}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(state))

    def load(self, path):
        """Restore a calibration written by save(). Only our own file is ever
        read (pickle must never load untrusted data)."""
        import pickle
        state = pickle.loads(path.read_bytes())
        if tuple(state["screen"]) != (self.screen_w, self.screen_h):
            raise ValueError("saved for a different screen size")
        self.reset()
        with self.lock:
            self.model, self.reference = state["model"], state["reference"]
            self.bias = tuple(state["bias"])

    def close(self):
        self.landmarker.close()
