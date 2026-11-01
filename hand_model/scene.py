#   HANDMOVE - 3D hand model (parts list)
#        Oumar Ibrahim U22200741

# all the parts of the uHand 3D model
# each Part is a mesh in the frame of its link plus a material
# the renderer multiplys it by kinematics.link_transforms every frame
# so nothing in here needs opengl

import numpy as np

from . import kinematics as K
from .meshes import (Mesh, arc, box, chamfered_rect, cylinder, extrude, merge, rounded_rect,
                     side_plate)


class Material:
    def __init__(self, color, specular=0.3, shininess=30.0):
        self.color = color
        self.specular = specular
        self.shininess = shininess


ANODISED = Material((0.12, 0.12, 0.13), 0.55, 45.0)  # hand plates
ACRYLIC = Material((0.08, 0.08, 0.09), 0.8, 70.0)  # shiny base plates
SILVER = Material((0.72, 0.73, 0.76), 0.9, 80.0)  # links, screws
BRASS = Material((0.78, 0.62, 0.28), 0.8, 60.0)  # standoffs
SERVO = Material((0.2, 0.2, 0.21), 0.25, 20.0)
PCB_BLUE = Material((0.08, 0.33, 0.62), 0.3, 30.0)
PCB_BLACK = Material((0.06, 0.06, 0.06), 0.3, 30.0)
NYLON = Material((0.85, 0.85, 0.82), 0.2, 20.0)
KNOB_CAP = Material((0.85, 0.55, 0.25), 0.3, 30.0)
RED = Material((0.85, 0.08, 0.06), 0.5, 50.0)
YELLOW = Material((0.95, 0.80, 0.05), 0.5, 50.0)
HIGHLIGHT = Material((0.38, 0.69, 0.94), 0.5, 40.0)


class Part:
    def __init__(self, name, link, mesh, material, channel=-1):
        self.name = name
        self.link = link  # key from kinematics.link_transforms()
        self.mesh = mesh
        self.material = material
        self.channel = channel  # servo channel of this part (for highlight)


# side outline (y, z) of the first finger part, a capsule that gets thiner
def proximal_profile(length, depth):
    r0 = depth / 2
    r1 = depth / 2 - 1.0
    return arc(0.0, length, r1, 0, 180, 8) + arc(0.0, 0.0, r0, 180, 360, 8)


# side outline (y, z) of the finger tip: straight back, round tip that
# hooks to the palm (+Y) and a soft pad on the palm side
def distal_profile(length, depth):
    r = depth / 2
    tip_r = r * 0.95
    pts = arc(0.0, 0.0, r, 180, 360, 8)  # joint end
    pts.append((r + 0.8, length * 0.35))  # pad
    pts.append((r + 1.4, length * 0.6))
    pts += arc(1.2, length - tip_r, tip_r, 0, 180, 10)  # tip
    pts.append((-r + 0.6, length * 0.55))  # back edge
    return pts


def finger_parts(spec):
    l1 = spec.lengths[0]
    l2 = spec.lengths[1]
    w = spec.width
    d = K.FINGER_DEPTH
    parts = []
    parts.append(Part(spec.name + " proximal", spec.name + "_1", side_plate(proximal_profile(l1, d), w),
                      ANODISED, spec.channel))
    parts.append(Part(spec.name + " distal", spec.name + "_2", side_plate(distal_profile(l2, d - 1.0), w * 0.92),
                      ANODISED, spec.channel))
    pin = w + 3.0
    hardware = []
    hardware.append(cylinder(2.4, pin, 14, center=(0, 0, 0), axis="x"))
    hardware.append(cylinder(2.4, pin, 14, center=(0, 0, l1), axis="x"))
    # silver tie rod, a bent link on the back of the first finger part
    # from under the knuckle up to the middle joint
    bend = [(-d / 2 - 1.5, -6.0), (-d / 2 - 3.0, l1 * 0.3), (-d / 2 - 2.5, l1 * 0.65), (-d / 2 + 1.0, l1 - 3.0)]
    for i in range(len(bend) - 1):
        y0 = bend[i][0]
        z0 = bend[i][1]
        y1 = bend[i + 1][0]
        z1 = bend[i + 1][1]
        seg = np.hypot(y1 - y0, z1 - z0)
        ang = np.degrees(np.arctan2(y1 - y0, z1 - z0))
        mat = np.dot(K.translate(w / 2 + 1.2, (y0 + y1) / 2, (z0 + z1) / 2), K.rot_x(-ang))
        m = box(1.6, 2.6, seg + 1.5).transformed(mat)
        hardware.append(m)
    parts.append(Part(spec.name + " hardware", spec.name + "_1", merge(hardware), SILVER, spec.channel))
    screw = cylinder(1.5, w + 1.0, 12, center=(0, 0, l2 * 0.4), axis="x")
    parts.append(Part(spec.name + " tip screw", spec.name + "_2", screw, SILVER, spec.channel))
    return parts


def palm_parts():
    z0 = K.HAND_BASE_Z
    h = K.PALM_H
    w = K.PALM_W
    d = K.PALM_D
    t = 2.0
    # side plates: tall at the back and cut at an angle to the palm side
    side = [(-d / 2, z0), (d / 2, z0), (d / 2, z0 + h * 0.62), (d / 2 - 8.0, z0 + h * 0.8),
            (-d / 2 + 6.0, z0 + h + 2.0), (-d / 2, z0 + h + 2.0)]
    shell = []
    shell.append(box(w, t, h + 2.0, center=(0, -d / 2 + t / 2, z0 + (h + 2.0) / 2)))  # back plate
    shell.append(side_plate(side, t).transformed(K.translate(-w / 2 + t / 2, 0, 0)))  # thumb side
    shell.append(side_plate(side, t).transformed(K.translate(w / 2 - t / 2, 0, 0)))  # pinky side
    shell.append(box(w, d, t, center=(0, 0, z0 + t / 2)))  # bottom
    shell.append(box(w - 2 * t, t, h * 0.42, center=(0, d / 2 - t / 2, z0 + h * 0.21)))  # lower palm
    parts = [Part("palm housing", "wrist", merge(shell), ANODISED, 5)]

    # 4 LFD-01 finger servos in the palm and the thumb servo lower down
    sx = 12.0
    sy = 22.3
    sz = 23.2
    servos = []
    xs = [-18.0, -6.0, 6.0, 18.0]
    for i in range(4):
        zz = z0 + h - 20.0 - (i % 2) * 24.0
        servos.append(box(sx - 1.0, sy, sz, center=(xs[i], 2.0, zz)))
    servos.append(box(sz, sy, sx, center=(-w / 2 + sz / 2 + 3.0, 3.0, z0 + 10.0)))
    parts.append(Part("finger servos", "wrist", merge(servos), SERVO))

    # knuckle axle, brass rods and screw heads
    hardware = [cylinder(1.8, w + 4.0, 16, center=(0, -2.0, z0 + h), axis="x")]
    for x in (-w / 2, w / 2):
        spots = [(-d / 2 + 5, z0 + 8), (d / 2 - 5, z0 + 8), (-d / 2 + 5, z0 + h - 8), (4.0, z0 + h * 0.5)]
        for spot in spots:
            y = spot[0]
            z = spot[1]
            hardware.append(cylinder(2.2, 1.2, 12, center=(x + np.sign(x) * 0.6, y, z), axis="x"))
    back_screws = [(-w / 2 + 6, z0 + 10), (w / 2 - 6, z0 + 10), (-w / 2 + 6, z0 + h - 6), (w / 2 - 6, z0 + h - 6)]
    for s in back_screws:
        hardware.append(cylinder(2.2, 1.2, 12, center=(s[0], -d / 2 - 0.6, s[1]), axis="y"))
    parts.append(Part("palm screws", "wrist", merge(hardware), SILVER))
    rods = []
    for z in (z0 + 6.0, z0 + h * 0.5):
        rods.append(cylinder(1.6, w + 2.0, 12, center=(0, d / 2 - 4.0, z), axis="x"))
    parts.append(Part("palm rods", "wrist", merge(rods), BRASS))

    # L bracket on the wrist servo horn
    bracket = []
    bracket.append(box(40.0, 30.0, 2.5, center=(0, 0, 1.25)))
    bracket.append(box(30.0, 2.5, z0 + 30.0, center=(0, -d / 2 - 1.25, (z0 + 30.0) / 2)))
    parts.append(Part("wrist bracket", "wrist", merge(bracket), ANODISED, 5))
    return parts


def base_parts():
    bz = K.BOARD_Z
    bt = K.BOARD_T
    outline = [(-50, -35), (-35, -50), (195, -50), (200, -45), (200, 25), (195, 30),
               (55, 30), (50, 35), (35, 50), (-35, 50), (-50, 35)]
    board = extrude(outline, bt).transformed(K.translate(0, 0, bz))
    parts = [Part("baseboard", "world", board, ACRYLIC)]

    feet = []
    for spot in ((-40, -40), (-40, 40), (40, 40), (190, -40), (190, 20), (60, -40)):
        feet.append(cylinder(3.0, bz, 12, center=(spot[0], spot[1], bz / 2)))
    parts.append(Part("nylon feet", "world", merge(feet), NYLON))

    # tower: 3 square acrylic plates and the servo board with cut corners on top
    top = K.TOWER_TOP_Z
    pz0 = bz + bt
    ph = top - pz0
    plates = []
    plates.append(box(3.0, 70.0, ph, center=(-38.5, 0, pz0 + ph / 2)))
    plates.append(box(3.0, 70.0, ph, center=(38.5, 0, pz0 + ph / 2)))
    plates.append(box(70.0, 3.0, ph, center=(0, 38.5, pz0 + ph / 2)))
    servo_board = extrude(chamfered_rect(84.0, 84.0, 16.0), 3.0).transformed(K.translate(0, 0, top))
    plates.append(servo_board)
    parts.append(Part("tower plates", "world", merge(plates), ACRYLIC))

    # LFD-06 wrist servo under the servo board, shaft is on the wrist axis
    wrist_servo = []
    wrist_servo.append(box(40.5, 20.0, 37.0, center=(10.0, 0, top - 18.5)))
    wrist_servo.append(box(54.0, 20.0, 2.5, center=(10.0, 0, top - 5.0)))
    wrist_servo.append(cylinder(6.0, 6.0, 20, center=(0, 0, top + 3.0)))
    parts.append(Part("wrist servo", "world", merge(wrist_servo), SERVO, 5))
    horn = cylinder(11.0, K.WRIST_Z - top - 3.0, 24, center=(0, 0, (K.WRIST_Z + top + 3.0) / 2))
    parts.append(Part("servo horn", "world", horn, SILVER, 5))

    # arduino uno + the 6 knob expansion board on copper pillars
    ax = 98.0
    ay = -12.0
    pcb_z = bz + bt + 10.0
    parts.append(Part("arduino uno", "world", box(68.6, 53.4, 1.6, center=(ax, ay, pcb_z)), PCB_BLUE))
    pillars = []
    for dx in (-30, 30):
        for dy in (-22, 22):
            pillars.append(cylinder(1.6, 10.0, 8, center=(ax + dx, ay + dy, bz + bt + 5.0)))
    shield_z = pcb_z + 11.0
    for dx in (-25, 0, 25):
        pillars.append(box(2.5, 2.5, 11.0, center=(ax + dx, ay + 24.0, pcb_z + 5.5)))
    parts.append(Part("pillars", "world", merge(pillars), BRASS))
    parts.append(Part("expansion board", "world", box(68.6, 53.4, 1.6, center=(ax, ay, shield_z)), PCB_BLACK))

    knobs = []
    caps = []
    for i in range(3):
        for j in range(2):
            kx = ax - 14.0 + i * 13.0
            ky = ay - 2.0 + j * 14.0
            knobs.append(cylinder(5.5, 12.0, 18, center=(kx, ky, shield_z + 6.8)))
            caps.append(cylinder(5.0, 1.5, 18, center=(kx, ky, shield_z + 13.5)))
    parts.append(Part("knobs", "world", merge(knobs), PCB_BLACK))
    parts.append(Part("knob caps", "world", merge(caps), KNOB_CAP))
    red_btn = cylinder(4.5, 7.0, 16, center=(ax - 26.0, ay - 18.0, shield_z + 4.3))
    parts.append(Part("red button", "world", red_btn, RED))
    yelow_btn = cylinder(4.5, 7.0, 16, center=(ax - 12.0, ay - 18.0, shield_z + 4.3))
    parts.append(Part("yellow button", "world", yelow_btn, YELLOW))

    battery = extrude(rounded_rect(42.0, 78.0, 3.0), 24.0).transformed(K.translate(176.0, -10.0, bz + bt))
    parts.append(Part("battery box", "world", battery, PCB_BLACK))
    return parts


def build_parts(include_base=True):
    parts = palm_parts()
    for spec in K.FINGERS:
        parts += finger_parts(spec)
    if include_base:
        parts += base_parts()
    return parts


# bounding box in world space for the open hand pose
def scene_bounds(parts):
    links = K.link_transforms([180, 180, 180, 180, 180, 90])
    pts = []
    for p in parts:
        pts.append(p.mesh.transformed(links[p.link]).vertices)
    allp = np.concatenate(pts)
    return allp.min(axis=0), allp.max(axis=0)
