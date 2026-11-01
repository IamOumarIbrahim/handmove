#   HANDMOVE - EEG Bridge (mapper)
#        Oumar Ibrahim U22200741

# turns the decoder probabilities into servo angles for HandController
# rules so the hand is safe and smooth:
# - probabilities are smoothed (exponential)
# - a class is only used when its smoothed prob stays over threshold for
#   dwell_s, if not the pose just stays
# - servos move to the pose at max max_speed_dps degrees per second
# - we send at most send_hz times a second and only when a angle moved by
#   min_delta or more so the ble link dosnt get flooded

import time

import numpy as np

from .sources import FINGER_LABELS, REST

OPEN = 180
CLOSED = 0
WRIST = 90


# bend one finger (1 = thumb .. 5 = pinky) and keep the others open
def single_finger_pose(finger):
    angles = [OPEN, OPEN, OPEN, OPEN, OPEN, WRIST]
    if finger >= 1 and finger <= 5:
        angles[finger - 1] = CLOSED
    return tuple(angles)


DEFAULT_POSES = {}
DEFAULT_POSES[REST] = (OPEN, OPEN, OPEN, OPEN, OPEN, WRIST)
for f in range(1, 6):
    DEFAULT_POSES[f] = single_finger_pose(f)
FIST = (CLOSED, CLOSED, CLOSED, CLOSED, CLOSED, WRIST)


class IntentMapper:
    def __init__(self, classes, poses=None, threshold=0.6, smoothing=0.35, dwell_s=0.4,
                 max_speed_dps=400.0, send_hz=10.0, min_delta=2, start_pose=DEFAULT_POSES[REST]):
        self.classes = list(classes)
        if not poses:
            poses = {}
        self.poses = {}
        for c in self.classes:
            if c in poses:
                pose = poses[c]
            else:
                pose = DEFAULT_POSES.get(c, start_pose)
            angles = []
            for a in pose:
                angles.append(int(a))
            self.poses[c] = tuple(angles)
        self.threshold = threshold
        self.smoothing = smoothing
        self.dwell_s = dwell_s
        self.max_speed_dps = max_speed_dps
        self.send_hz = send_hz
        self.min_delta = min_delta
        self.reset(start_pose)

    def reset(self, pose=DEFAULT_POSES[REST]):
        n = len(self.classes)
        if n < 1:
            n = 1
        self.smoothed = np.full(len(self.classes), 1.0 / n)
        self.committed = None
        self._candidate = None
        self._candidate_since = 0.0
        self.current = np.array(pose, dtype=float)
        self.target = np.array(pose, dtype=float)
        self._last_sent = np.array(pose, dtype=float)
        self._last_send_t = -1e9
        self._last_t = None

    def class_name(self, c):
        if c is None:
            return "-"
        return FINGER_LABELS.get(c, str(c))

    # give it one probability list (same order as classes)
    # returns the angles to send or None
    def update(self, probs, now=None):
        if now is None:
            now = time.monotonic()
        p = np.asarray(probs, dtype=float)
        self.smoothed = self.smoothing * p + (1 - self.smoothing) * self.smoothed
        best = int(np.argmax(self.smoothed))
        best_cls = self.classes[best]

        if self.smoothed[best] >= self.threshold:
            if best_cls != self._candidate:
                self._candidate = best_cls
                self._candidate_since = now
            if now - self._candidate_since >= self.dwell_s and best_cls != self.committed:
                self.commit(best_cls)
        else:
            self._candidate = None
        return self.step(now)

    def commit(self, cls):
        self.committed = cls
        self.target = np.array(self.poses[cls], dtype=float)

    def set_target(self, angles):
        self.target = np.clip(np.array(angles, dtype=float), 0, 180)

    # moves a bit toward the target (speed limited)
    # returns angles when its time to send
    def step(self, now=None):
        if now is None:
            now = time.monotonic()
        if self._last_t is None:
            dt = 0.0
        else:
            dt = now - self._last_t
            if dt < 0.0:
                dt = 0.0
        self._last_t = now
        max_stp = self.max_speed_dps * dt
        delta = np.clip(self.target - self.current, -max_stp, max_stp)
        self.current = self.current + delta

        if now - self._last_send_t < 1.0 / self.send_hz:
            return None
        rounded = np.round(self.current)
        biggest = np.max(np.abs(rounded - self._last_sent))
        if biggest < self.min_delta and not np.array_equal(rounded, self.target):
            return None
        if np.array_equal(rounded, self._last_sent):
            return None
        self._last_sent = rounded
        self._last_send_t = now
        result = []
        for a in rounded:
            result.append(int(a))
        return result
