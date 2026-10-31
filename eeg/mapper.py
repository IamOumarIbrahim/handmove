"""
Turns decoder probabilities into servo angles for HandController.

Safety and smoothness rules:
- Probabilities are exponentially smoothed.
- A class is only committed after its smoothed probability stays above
  `threshold` for `dwell_s`; otherwise the current pose is held.
- Servos move toward the committed pose at no more than `max_speed_dps`.
- Commands are sent at most `send_hz` times per second and only when an angle
  changed by at least `min_delta` degrees, so the BLE link is not flooded.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .sources import FINGER_LABELS, REST

OPEN = 180
CLOSED = 0
WRIST = 90

Pose = Tuple[int, int, int, int, int, int]


def single_finger_pose(finger: int) -> Pose:
    """Flex one finger (1=thumb .. 5=pinky), keep the others open."""
    angles = [OPEN] * 5 + [WRIST]
    if 1 <= finger <= 5:
        angles[finger - 1] = CLOSED
    return tuple(angles)  # type: ignore[return-value]


DEFAULT_POSES: Dict[int, Pose] = {REST: (OPEN, OPEN, OPEN, OPEN, OPEN, WRIST)}
DEFAULT_POSES.update({f: single_finger_pose(f) for f in range(1, 6)})
FIST: Pose = (CLOSED, CLOSED, CLOSED, CLOSED, CLOSED, WRIST)


class IntentMapper:
    def __init__(self, classes: Sequence[int], poses: Optional[Dict[int, Sequence[int]]] = None,
                 threshold: float = 0.6, smoothing: float = 0.35, dwell_s: float = 0.4,
                 max_speed_dps: float = 400.0, send_hz: float = 10.0, min_delta: int = 2,
                 start_pose: Sequence[int] = DEFAULT_POSES[REST]):
        self.classes = list(classes)
        self.poses = {c: tuple(int(a) for a in (poses or {}).get(c, DEFAULT_POSES.get(c, start_pose)))
                      for c in self.classes}
        self.threshold = threshold
        self.smoothing = smoothing
        self.dwell_s = dwell_s
        self.max_speed_dps = max_speed_dps
        self.send_hz = send_hz
        self.min_delta = min_delta
        self.reset(start_pose)

    def reset(self, pose: Sequence[int] = DEFAULT_POSES[REST]) -> None:
        self.smoothed = np.full(len(self.classes), 1.0 / max(1, len(self.classes)))
        self.committed: Optional[int] = None
        self._candidate: Optional[int] = None
        self._candidate_since = 0.0
        self.current = np.array(pose, dtype=float)
        self.target = np.array(pose, dtype=float)
        self._last_sent = np.array(pose, dtype=float)
        self._last_send_t = -1e9
        self._last_t: Optional[float] = None

    def class_name(self, c: Optional[int]) -> str:
        return "-" if c is None else FINGER_LABELS.get(c, str(c))

    def update(self, probs: Sequence[float], now: Optional[float] = None) -> Optional[List[int]]:
        """Feed one probability vector (ordered like `classes`). Returns angles to send, or None."""
        now = time.monotonic() if now is None else now
        p = np.asarray(probs, dtype=float)
        self.smoothed = self.smoothing * p + (1 - self.smoothing) * self.smoothed
        best = int(np.argmax(self.smoothed))
        best_cls = self.classes[best]

        if self.smoothed[best] >= self.threshold:
            if best_cls != self._candidate:
                self._candidate, self._candidate_since = best_cls, now
            if now - self._candidate_since >= self.dwell_s and best_cls != self.committed:
                self.commit(best_cls)
        else:
            self._candidate = None
        return self.step(now)

    def commit(self, cls: int) -> None:
        self.committed = cls
        self.target = np.array(self.poses[cls], dtype=float)

    def set_target(self, angles: Sequence[int]) -> None:
        self.target = np.clip(np.array(angles, dtype=float), 0, 180)

    def step(self, now: Optional[float] = None) -> Optional[List[int]]:
        """Advance the rate-limited motion. Returns angles when a send is due."""
        now = time.monotonic() if now is None else now
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now
        max_step = self.max_speed_dps * dt
        delta = np.clip(self.target - self.current, -max_step, max_step)
        self.current = self.current + delta

        if now - self._last_send_t < 1.0 / self.send_hz:
            return None
        rounded = np.round(self.current)
        if np.max(np.abs(rounded - self._last_sent)) < self.min_delta and not np.array_equal(rounded, self.target):
            return None
        if np.array_equal(rounded, self._last_sent):
            return None
        self._last_sent = rounded
        self._last_send_t = now
        return [int(a) for a in rounded]
