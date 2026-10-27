"""
Preset gestures, poses, and multi-frame animation sequences for uHand UNO.
Servo mapping:
  Channel 1: Thumb   (0-180°)
  Channel 2: Index   (0-180°)
  Channel 3: Middle  (0-180°)
  Channel 4: Ring    (0-180°)
  Channel 5: Pinky   (0-180°)
  Channel 6: Wrist   (0-180°)
"""

from typing import Dict, List, Tuple

# Default canonical poses: angles in degrees [Thumb, Index, Middle, Ring, Pinky, Wrist]
# 0° typically curled / closed; 180° extended / open; 90° neutral
PRESET_POSES: Dict[str, Tuple[int, int, int, int, int, int]] = {
    "Open Hand": (180, 180, 180, 180, 180, 90),
    "Fist": (0, 0, 0, 0, 0, 90),
    "Neutral (Calibrate)": (90, 90, 90, 90, 90, 90),
    "Thumbs Up": (180, 0, 0, 0, 0, 90),
    "Peace / Victory": (0, 180, 180, 0, 0, 90),
    "Pointing (Gun)": (180, 180, 0, 0, 0, 90),
    "OK Sign": (60, 60, 180, 180, 180, 90),
    "Rock On (Horns)": (30, 180, 0, 0, 180, 90),
    "Call Me": (180, 0, 0, 0, 180, 90),
    "Spock Salute": (180, 180, 180, 180, 180, 90),
    "Pinch": (70, 70, 0, 0, 0, 90),
    "Count 1": (0, 180, 0, 0, 0, 90),
    "Count 2": (0, 180, 180, 0, 0, 90),
    "Count 3": (0, 180, 180, 180, 0, 90),
    "Count 4": (0, 180, 180, 180, 180, 90),
    "Count 5": (180, 180, 180, 180, 180, 90),
    "Relaxed Palm": (120, 130, 130, 130, 120, 90),
    "Wrist Left": (180, 180, 180, 180, 180, 30),
    "Wrist Right": (180, 180, 180, 180, 180, 150),
}

# Pre-defined multi-step animation sequences
# Format of each keyframe: (angles_tuple, duration_ms)
PRESET_SEQUENCES: Dict[str, List[Tuple[Tuple[int, int, int, int, int, int], int]]] = {
    "Wave": [
        ((180, 180, 180, 180, 180, 50), 350),
        ((180, 180, 180, 180, 180, 130), 350),
        ((180, 180, 180, 180, 180, 50), 350),
        ((180, 180, 180, 180, 180, 130), 350),
        ((180, 180, 180, 180, 180, 90), 300),
    ],
    "Counting 1-5": [
        ((0, 0, 0, 0, 0, 90), 400),
        ((0, 180, 0, 0, 0, 90), 450),
        ((0, 180, 180, 0, 0, 90), 450),
        ((0, 180, 180, 180, 0, 90), 450),
        ((0, 180, 180, 180, 180, 90), 450),
        ((180, 180, 180, 180, 180, 90), 500),
        ((0, 0, 0, 0, 0, 90), 400),
    ],
    "Rock Paper Scissors": [
        # Shake 1
        ((0, 0, 0, 0, 0, 60), 200),
        ((0, 0, 0, 0, 0, 120), 200),
        # Shake 2
        ((0, 0, 0, 0, 0, 60), 200),
        ((0, 0, 0, 0, 0, 120), 200),
        # Shake 3
        ((0, 0, 0, 0, 0, 60), 200),
        ((0, 0, 0, 0, 0, 90), 200),
        # Show Paper (or replace with Scissors/Rock)
        ((180, 180, 180, 180, 180, 90), 800),
    ],
    "Finger Dance / Strum": [
        ((180, 0, 0, 0, 0, 90), 180),
        ((0, 180, 0, 0, 0, 90), 180),
        ((0, 0, 180, 0, 0, 90), 180),
        ((0, 0, 0, 180, 0, 90), 180),
        ((0, 0, 0, 0, 180, 90), 180),
        ((0, 0, 0, 180, 0, 90), 180),
        ((0, 0, 180, 0, 0, 90), 180),
        ((0, 180, 0, 0, 0, 90), 180),
        ((180, 0, 0, 0, 0, 90), 180),
        ((180, 180, 180, 180, 180, 90), 300),
    ],
    "Grab & Release": [
        ((180, 180, 180, 180, 180, 90), 400),
        ((120, 120, 120, 120, 120, 90), 300),
        ((30, 30, 30, 30, 30, 90), 400),
        ((0, 0, 0, 0, 0, 90), 500),
        ((180, 180, 180, 180, 180, 90), 400),
    ]
}
