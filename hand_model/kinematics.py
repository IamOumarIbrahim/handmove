"""
Kinematic model of the Hiwonder uHand UNO (right hand).

Frames (millimetres, Z up):
  world  - static base. Origin at the centre of the tower footprint on the table.
  wrist  - rotates about world Z with servo 6. The hand housing is bolted to it.
  <finger>_1 / <finger>_2 - proximal and distal phalanx of each finger.

Servo convention follows gestures.py: 180 deg = finger open, 0 deg = closed,
90 deg = wrist centred. Dimensions are estimates from the published specs
(hand 165 x 90 mm, LFD-01 finger servos 22.3 x 12 x 23.2 mm) and the
official assembly renders. Tune the tables below to match a real hand.
"""

import math
from dataclasses import dataclass
from typing import Dict, Sequence, Tuple

import numpy as np

# --- Base / wrist geometry -------------------------------------------------
BOARD_Z = 8.0            # baseboard underside (nylon standoff height)
BOARD_T = 3.0            # acrylic thickness
TOWER_TOP_Z = 76.0       # top of the square side plates
WRIST_Z = 85.0           # top of the wrist servo horn (wrist frame origin)
HAND_BASE_Z = 16.0       # palm housing bottom, measured in the wrist frame

# --- Palm housing ---------------------------------------------------------
PALM_W = 52.0            # across the knuckles (X)
PALM_D = 36.0            # back-to-front (Y); +Y is the palm face
PALM_H = 75.0            # wrist to knuckle axle (Z)
FINGER_DEPTH = 12.0      # finger plate depth, back to front (Y)


@dataclass(frozen=True)
class FingerSpec:
    name: str
    channel: int                    # index into the 6-angle list
    root: Tuple[float, float, float]  # proximal joint, wrist frame
    lengths: Tuple[float, float]    # proximal, distal (mm)
    width: float                    # side-to-side plate width (X)
    splay_deg: float = 0.0          # sideways lean about the palm normal
    prox_max_deg: float = 80.0      # proximal flex at full close (servo 0)
    dist_max_deg: float = 95.0      # extra distal flex from the tie-rod
    z_dir: Tuple[float, float, float] = (0.0, 0.0, 1.0)   # finger direction when open
    y_hint: Tuple[float, float, float] = (0.0, 1.0, 0.0)  # direction it curls toward


_KNUCKLE_Z = HAND_BASE_Z + PALM_H

FINGERS: Tuple[FingerSpec, ...] = (
    # Right hand seen from the back: thumb on -X, pinky on +X, palm face +Y.
    FingerSpec("thumb", 0, (-PALM_W / 2 - 3.0, 8.0, HAND_BASE_Z + 22.0), (36.0, 30.0), 8.0,
               prox_max_deg=70.0, dist_max_deg=55.0,
               z_dir=(-1.0, 0.35, -0.15), y_hint=(0.4, 1.0, 0.15)),
    FingerSpec("index", 1, (-19.0, -2.0, _KNUCKLE_Z), (44.0, 40.0), 8.5, splay_deg=-3.0),
    FingerSpec("middle", 2, (-6.5, -2.0, _KNUCKLE_Z + 1.0), (48.0, 42.0), 8.5, splay_deg=0.0),
    FingerSpec("ring", 3, (6.5, -2.0, _KNUCKLE_Z), (45.0, 40.0), 8.5, splay_deg=2.0),
    FingerSpec("pinky", 4, (19.0, -2.0, _KNUCKLE_Z - 4.0), (38.0, 34.0), 8.0, splay_deg=5.0),
)

WRIST_CHANNEL = 5
WRIST_RANGE_DEG = 90.0   # servo 0..180 maps to -90..+90 deg yaw


# --- Matrix helpers -------------------------------------------------------
def translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def rot_x(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1:3, 1:3] = [[c, -s], [s, c]]
    return m


def rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def rot_z(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[:2, :2] = [[c, -s], [s, c]]
    return m


def frame_from(z_dir: Sequence[float], y_hint: Sequence[float]) -> np.ndarray:
    """Rotation whose local Z is ``z_dir`` and local Y leans toward ``y_hint``."""
    z = np.asarray(z_dir, float)
    z /= np.linalg.norm(z)
    y = np.asarray(y_hint, float)
    y = y - z * np.dot(y, z)
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = x, y, z
    return m


# --- Servo -> joint mapping ----------------------------------------------
def _clamp(angle: float) -> float:
    return max(0.0, min(180.0, float(angle)))


def curl_fraction(servo_deg: float) -> float:
    """0.0 = fully open (180 deg), 1.0 = fully closed (0 deg)."""
    return (180.0 - _clamp(servo_deg)) / 180.0


def finger_joint_angles(spec: FingerSpec, servo_deg: float) -> Tuple[float, float]:
    """Proximal and distal flex (deg) for one finger's servo angle.

    The uHand drives each finger with a tie-rod, so the distal joint follows
    the proximal one at a fixed ratio rather than moving independently.
    """
    f = curl_fraction(servo_deg)
    return f * spec.prox_max_deg, f * spec.dist_max_deg


def wrist_yaw_deg(servo_deg: float) -> float:
    return (_clamp(servo_deg) - 90.0) / 90.0 * WRIST_RANGE_DEG


def link_transforms(angles: Sequence[float]) -> Dict[str, np.ndarray]:
    """World transform of every moving link for a 6-angle pose."""
    angles = list(angles) + [90.0] * (6 - len(angles))
    out: Dict[str, np.ndarray] = {"world": np.eye(4)}
    wrist = translate(0.0, 0.0, WRIST_Z) @ rot_z(wrist_yaw_deg(angles[WRIST_CHANNEL]))
    out["wrist"] = wrist
    for spec in FINGERS:
        prox, dist = finger_joint_angles(spec, angles[spec.channel])
        base = wrist @ translate(*spec.root) @ frame_from(spec.z_dir, spec.y_hint) @ rot_y(spec.splay_deg)
        # Negative rotation about local X swings local +Z toward local +Y (palm side).
        p1 = base @ rot_x(-prox)
        p2 = p1 @ translate(0.0, 0.0, spec.lengths[0]) @ rot_x(-dist)
        out[f"{spec.name}_1"] = p1
        out[f"{spec.name}_2"] = p2
    return out


def fingertip_positions(angles: Sequence[float]) -> Dict[str, np.ndarray]:
    """World XYZ of each fingertip; handy for tests and calibration."""
    links = link_transforms(angles)
    tips = {}
    for spec in FINGERS:
        tip = links[f"{spec.name}_2"] @ np.array([0.0, 0.0, spec.lengths[1], 1.0])
        tips[spec.name] = tip[:3]
    return tips
