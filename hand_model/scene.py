"""
Part list for the uHand UNO 3D model.

Each ``Part`` is a mesh in its link's local frame plus a material. The
renderer multiplies it by ``kinematics.link_transforms`` every frame, so
nothing here depends on OpenGL.
"""

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from . import kinematics as K
from .meshes import (Mesh, arc, box, chamfered_rect, cylinder, extrude, merge, rounded_rect,
                     side_plate)

RGB = Tuple[float, float, float]


@dataclass(frozen=True)
class Material:
    color: RGB
    specular: float = 0.3
    shininess: float = 30.0


ANODISED = Material((0.12, 0.12, 0.13), 0.55, 45.0)     # hand plates
ACRYLIC = Material((0.08, 0.08, 0.09), 0.8, 70.0)       # glossy base plates
SILVER = Material((0.72, 0.73, 0.76), 0.9, 80.0)        # linkages, screws
BRASS = Material((0.78, 0.62, 0.28), 0.8, 60.0)         # standoffs
SERVO = Material((0.2, 0.2, 0.21), 0.25, 20.0)
PCB_BLUE = Material((0.08, 0.33, 0.62), 0.3, 30.0)
PCB_BLACK = Material((0.06, 0.06, 0.06), 0.3, 30.0)
NYLON = Material((0.85, 0.85, 0.82), 0.2, 20.0)
KNOB_CAP = Material((0.85, 0.55, 0.25), 0.3, 30.0)
RED = Material((0.85, 0.08, 0.06), 0.5, 50.0)
YELLOW = Material((0.95, 0.80, 0.05), 0.5, 50.0)
HIGHLIGHT = Material((0.38, 0.69, 0.94), 0.5, 40.0)


@dataclass
class Part:
    name: str
    link: str          # key into kinematics.link_transforms()
    mesh: Mesh
    material: Material
    channel: int = -1  # servo channel this part belongs to (for highlighting)


def _proximal_profile(length: float, depth: float) -> list:
    """Side outline (y, z) of a proximal phalanx: a tapered capsule."""
    r0, r1 = depth / 2, depth / 2 - 1.0
    return arc(0.0, length, r1, 0, 180, 8) + arc(0.0, 0.0, r0, 180, 360, 8)


def _distal_profile(length: float, depth: float) -> list:
    """Side outline (y, z) of a fingertip: straight back, rounded tip hooked
    toward the palm (+Y) and a soft pad on the palm side."""
    r = depth / 2
    tip_r = r * 0.95
    pts = arc(0.0, 0.0, r, 180, 360, 8)                       # joint end
    pts += [(r + 0.8, length * 0.35), (r + 1.4, length * 0.6)]  # palm-side pad
    pts += arc(1.2, length - tip_r, tip_r, 0, 180, 10)        # tip
    pts += [(-r + 0.6, length * 0.55)]                         # back edge
    return pts


def _finger_parts(spec: K.FingerSpec) -> List[Part]:
    l1, l2 = spec.lengths
    w, d = spec.width, K.FINGER_DEPTH
    parts = [
        Part(f"{spec.name} proximal", f"{spec.name}_1", side_plate(_proximal_profile(l1, d), w), ANODISED, spec.channel),
        Part(f"{spec.name} distal", f"{spec.name}_2", side_plate(_distal_profile(l2, d - 1.0), w * 0.92), ANODISED, spec.channel),
    ]
    pin = w + 3.0
    hardware = [cylinder(2.4, pin, 14, center=(0, 0, 0), axis="x"),
                cylinder(2.4, pin, 14, center=(0, 0, l1), axis="x")]
    # Silver tie-rod: a curved link along the back of the proximal phalanx,
    # running from below the knuckle up to the middle joint.
    bend = [(-d / 2 - 1.5, -6.0), (-d / 2 - 3.0, l1 * 0.3), (-d / 2 - 2.5, l1 * 0.65), (-d / 2 + 1.0, l1 - 3.0)]
    for (y0, z0), (y1, z1) in zip(bend, bend[1:]):
        seg = np.hypot(y1 - y0, z1 - z0)
        ang = np.degrees(np.arctan2(y1 - y0, z1 - z0))
        m = box(1.6, 2.6, seg + 1.5).transformed(K.translate(w / 2 + 1.2, (y0 + y1) / 2, (z0 + z1) / 2) @ K.rot_x(-ang))
        hardware.append(m)
    parts.append(Part(f"{spec.name} hardware", f"{spec.name}_1", merge(hardware), SILVER, spec.channel))
    parts.append(Part(f"{spec.name} tip screw", f"{spec.name}_2",
                      cylinder(1.5, w + 1.0, 12, center=(0, 0, l2 * 0.4), axis="x"), SILVER, spec.channel))
    return parts


def _palm_parts() -> List[Part]:
    z0, h, w, d = K.HAND_BASE_Z, K.PALM_H, K.PALM_W, K.PALM_D
    zc = z0 + h / 2
    t = 2.0
    # Side plates: tall at the back, cut on a slant toward the palm face.
    side = [(-d / 2, z0), (d / 2, z0), (d / 2, z0 + h * 0.62), (d / 2 - 8.0, z0 + h * 0.8),
            (-d / 2 + 6.0, z0 + h + 2.0), (-d / 2, z0 + h + 2.0)]
    shell = [
        box(w, t, h + 2.0, center=(0, -d / 2 + t / 2, z0 + (h + 2.0) / 2)),  # back plate
        side_plate(side, t).transformed(K.translate(-w / 2 + t / 2, 0, 0)),  # thumb-side plate
        side_plate(side, t).transformed(K.translate(w / 2 - t / 2, 0, 0)),   # pinky-side plate
        box(w, d, t, center=(0, 0, z0 + t / 2)),                            # bottom plate
        box(w - 2 * t, t, h * 0.42, center=(0, d / 2 - t / 2, z0 + h * 0.21)),  # lower palm plate
    ]
    parts = [Part("palm housing", "wrist", merge(shell), ANODISED, 5)]

    # Four LFD-01 finger servos inside the palm, plus the thumb servo low down.
    sx, sy, sz = 12.0, 22.3, 23.2
    servos = []
    for i, x in enumerate((-18.0, -6.0, 6.0, 18.0)):
        zz = z0 + h - 20.0 - (i % 2) * 24.0
        servos.append(box(sx - 1.0, sy, sz, center=(x, 2.0, zz)))
    servos.append(box(sz, sy, sx, center=(-w / 2 + sz / 2 + 3.0, 3.0, z0 + 10.0)))
    parts.append(Part("finger servos", "wrist", merge(servos), SERVO))

    # Knuckle axle, brass cross-rods and screw heads.
    hardware = [cylinder(1.8, w + 4.0, 16, center=(0, -2.0, z0 + h), axis="x")]
    for x in (-w / 2, w / 2):
        for y, z in ((-d / 2 + 5, z0 + 8), (d / 2 - 5, z0 + 8), (-d / 2 + 5, z0 + h - 8), (4.0, z0 + h * 0.5)):
            hardware.append(cylinder(2.2, 1.2, 12, center=(x + np.sign(x) * 0.6, y, z), axis="x"))
    for x, z in ((-w / 2 + 6, z0 + 10), (w / 2 - 6, z0 + 10), (-w / 2 + 6, z0 + h - 6), (w / 2 - 6, z0 + h - 6)):
        hardware.append(cylinder(2.2, 1.2, 12, center=(x, -d / 2 - 0.6, z), axis="y"))
    parts.append(Part("palm screws", "wrist", merge(hardware), SILVER))
    rods = [cylinder(1.6, w + 2.0, 12, center=(0, d / 2 - 4.0, z), axis="x") for z in (z0 + 6.0, z0 + h * 0.5)]
    parts.append(Part("palm rods", "wrist", merge(rods), BRASS))

    # L-shaped bracket on the wrist servo horn.
    bracket = [
        box(40.0, 30.0, 2.5, center=(0, 0, 1.25)),
        box(30.0, 2.5, z0 + 30.0, center=(0, -d / 2 - 1.25, (z0 + 30.0) / 2)),
    ]
    parts.append(Part("wrist bracket", "wrist", merge(bracket), ANODISED, 5))
    return parts


def _base_parts() -> List[Part]:
    bz, bt = K.BOARD_Z, K.BOARD_T
    outline = [(-50, -35), (-35, -50), (195, -50), (200, -45), (200, 25), (195, 30),
               (55, 30), (50, 35), (35, 50), (-35, 50), (-50, 35)]
    board = extrude(outline, bt).transformed(K.translate(0, 0, bz))
    parts = [Part("baseboard", "world", board, ACRYLIC)]

    feet = [cylinder(3.0, bz, 12, center=(x, y, bz / 2))
            for x, y in ((-40, -40), (-40, 40), (40, 40), (190, -40), (190, 20), (60, -40))]
    parts.append(Part("nylon feet", "world", merge(feet), NYLON))

    # Tower: three square acrylic plates and the chamfered servo board on top.
    top = K.TOWER_TOP_Z
    pz0 = bz + bt
    ph = top - pz0
    plates = [
        box(3.0, 70.0, ph, center=(-38.5, 0, pz0 + ph / 2)),
        box(3.0, 70.0, ph, center=(38.5, 0, pz0 + ph / 2)),
        box(70.0, 3.0, ph, center=(0, 38.5, pz0 + ph / 2)),
    ]
    servo_board = extrude(chamfered_rect(84.0, 84.0, 16.0), 3.0).transformed(K.translate(0, 0, top))
    parts.append(Part("tower plates", "world", merge(plates + [servo_board]), ACRYLIC))

    # LFD-06 wrist servo hanging under the servo board; output shaft on the wrist axis.
    wrist_servo = [
        box(40.5, 20.0, 37.0, center=(10.0, 0, top - 18.5)),
        box(54.0, 20.0, 2.5, center=(10.0, 0, top - 5.0)),
        cylinder(6.0, 6.0, 20, center=(0, 0, top + 3.0)),
    ]
    parts.append(Part("wrist servo", "world", merge(wrist_servo), SERVO, 5))
    horn = cylinder(11.0, K.WRIST_Z - top - 3.0, 24, center=(0, 0, (K.WRIST_Z + top + 3.0) / 2))
    parts.append(Part("servo horn", "world", horn, SILVER, 5))

    # Arduino UNO + 6-knob expansion board on copper pillars.
    ax, ay = 98.0, -12.0
    pcb_z = bz + bt + 10.0
    parts.append(Part("arduino uno", "world", box(68.6, 53.4, 1.6, center=(ax, ay, pcb_z)), PCB_BLUE))
    pillars = [cylinder(1.6, 10.0, 8, center=(ax + dx, ay + dy, bz + bt + 5.0))
               for dx in (-30, 30) for dy in (-22, 22)]
    shield_z = pcb_z + 11.0
    pillars += [box(2.5, 2.5, 11.0, center=(ax + dx, ay + 24.0, pcb_z + 5.5)) for dx in (-25, 0, 25)]
    parts.append(Part("pillars", "world", merge(pillars), BRASS))
    parts.append(Part("expansion board", "world", box(68.6, 53.4, 1.6, center=(ax, ay, shield_z)), PCB_BLACK))

    knobs, caps = [], []
    for i in range(3):
        for j in range(2):
            kx, ky = ax - 14.0 + i * 13.0, ay - 2.0 + j * 14.0
            knobs.append(cylinder(5.5, 12.0, 18, center=(kx, ky, shield_z + 6.8)))
            caps.append(cylinder(5.0, 1.5, 18, center=(kx, ky, shield_z + 13.5)))
    parts.append(Part("knobs", "world", merge(knobs), PCB_BLACK))
    parts.append(Part("knob caps", "world", merge(caps), KNOB_CAP))
    parts.append(Part("red button", "world", cylinder(4.5, 7.0, 16, center=(ax - 26.0, ay - 18.0, shield_z + 4.3)), RED))
    parts.append(Part("yellow button", "world", cylinder(4.5, 7.0, 16, center=(ax - 12.0, ay - 18.0, shield_z + 4.3)), YELLOW))

    battery = extrude(rounded_rect(42.0, 78.0, 3.0), 24.0).transformed(K.translate(176.0, -10.0, bz + bt))
    parts.append(Part("battery box", "world", battery, PCB_BLACK))
    return parts


def build_parts(include_base: bool = True) -> List[Part]:
    parts = _palm_parts()
    for spec in K.FINGERS:
        parts += _finger_parts(spec)
    if include_base:
        parts += _base_parts()
    return parts


def scene_bounds(parts: List[Part]) -> Tuple[np.ndarray, np.ndarray]:
    """World-space bounding box of the rest pose (open hand)."""
    links = K.link_transforms([180, 180, 180, 180, 180, 90])
    pts = [p.mesh.transformed(links[p.link]).vertices for p in parts]
    allp = np.concatenate(pts)
    return allp.min(axis=0), allp.max(axis=0)
