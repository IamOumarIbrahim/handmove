#   HANDMOVE - 3D hand model (kinematics)
#        Oumar Ibrahim U22200741

# kinematics of the hiwonder uHand UNO (right hand)
# frames are in mm with Z up
#   world - the base, origin is the middle of the tower on the table
#   wrist - turns around world Z with servo 6, the hand is bolted to it
#   <finger>_1 / <finger>_2 - first and second part of each finger
#
# servos work like gestures.py: 180 = finger open, 0 = closed, 90 = wrist in the middle
# sizes are guesses from the specs (hand 165 x 90 mm, LFD-01 servos
# 22.3 x 12 x 23.2 mm) and the assembly pictures, change the numbers
# below if they dont match a real hand

import math

import numpy as np

# base and wrist
BOARD_Z = 8.0  # bottom of the baseboard (standoff height)
BOARD_T = 3.0  # acrylic thickness
TOWER_TOP_Z = 76.0  # top of the side plates
WRIST_Z = 85.0  # top of the wrist servo horn (wrist frame origin)
HAND_BASE_Z = 16.0  # bottom of the palm, in the wrist frame

# palm
PALM_W = 52.0  # across the knuckles (X)
PALM_D = 36.0  # back to front (Y), +Y is the palm side
PALM_H = 75.0  # wrist to knuckle axle (Z)
FINGER_DEPTH = 12.0  # finger plate depth (Y)


class FingerSpec:
    def __init__(self, name, channel, root, lengths, width, splay_deg=0.0, prox_max_deg=80.0,
                 dist_max_deg=95.0, z_dir=(0.0, 0.0, 1.0), y_hint=(0.0, 1.0, 0.0)):
        self.name = name
        self.channel = channel  # which of the 6 angles
        self.root = root  # first joint, wrist frame
        self.lengths = lengths  # first, second part (mm)
        self.width = width  # plate width (X)
        self.splay_deg = splay_deg  # lean to the side
        self.prox_max_deg = prox_max_deg  # first joint bend when closed (servo 0)
        self.dist_max_deg = dist_max_deg  # extra bend of the tip from the tie rod
        self.z_dir = z_dir  # where the finger points when open
        self.y_hint = y_hint  # the way it curls


KNUCKLE_Z = HAND_BASE_Z + PALM_H

# right hand seen from the back: thumb on -X, pinky on +X, palm is +Y
FINGERS = (
    FingerSpec("thumb", 0, (-PALM_W / 2 - 3.0, 8.0, HAND_BASE_Z + 22.0), (36.0, 30.0), 8.0,
               prox_max_deg=70.0, dist_max_deg=55.0,
               z_dir=(-1.0, 0.35, -0.15), y_hint=(0.4, 1.0, 0.15)),
    FingerSpec("index", 1, (-19.0, -2.0, KNUCKLE_Z), (44.0, 40.0), 8.5, splay_deg=-3.0),
    FingerSpec("middle", 2, (-6.5, -2.0, KNUCKLE_Z + 1.0), (48.0, 42.0), 8.5, splay_deg=0.0),
    FingerSpec("ring", 3, (6.5, -2.0, KNUCKLE_Z), (45.0, 40.0), 8.5, splay_deg=2.0),
    FingerSpec("pinky", 4, (19.0, -2.0, KNUCKLE_Z - 4.0), (38.0, 34.0), 8.0, splay_deg=5.0),
)

WRIST_CHANNEL = 5
WRIST_RANGE_DEG = 90.0  # servo 0..180 is -90..+90 deg


# matrix fuctions

def translate(x, y, z):
    m = np.eye(4)
    m[0, 3] = x
    m[1, 3] = y
    m[2, 3] = z
    return m


def rot_x(deg):
    a = math.radians(deg)
    c = math.cos(a)
    s = math.sin(a)
    m = np.eye(4)
    m[1, 1] = c
    m[1, 2] = -s
    m[2, 1] = s
    m[2, 2] = c
    return m


def rot_y(deg):
    a = math.radians(deg)
    c = math.cos(a)
    s = math.sin(a)
    m = np.eye(4)
    m[0, 0] = c
    m[0, 2] = s
    m[2, 0] = -s
    m[2, 2] = c
    return m


def rot_z(deg):
    a = math.radians(deg)
    c = math.cos(a)
    s = math.sin(a)
    m = np.eye(4)
    m[0, 0] = c
    m[0, 1] = -s
    m[1, 0] = s
    m[1, 1] = c
    return m


# rotation where local Z is z_dir and local Y leans to y_hint
def frame_from(z_dir, y_hint):
    z = np.asarray(z_dir, float)
    z /= np.linalg.norm(z)
    y = np.asarray(y_hint, float)
    y = y - z * np.dot(y, z)
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    m = np.eye(4)
    m[:3, 0] = x
    m[:3, 1] = y
    m[:3, 2] = z
    return m


# servo -> joints

def clamp_angle(angle):
    a = float(angle)
    if a > 180.0:
        a = 180.0
    if a < 0.0:
        a = 0.0
    return a


# 0.0 = open (180 deg), 1.0 = closed (0 deg)
def curl_fraction(servo_deg):
    return (180.0 - clamp_angle(servo_deg)) / 180.0


# bend of the first and second joint for one finger
# the uHand uses a tie rod so the tip just follows the first joint
def finger_joint_angles(spec, servo_deg):
    f = curl_fraction(servo_deg)
    prox = f * spec.prox_max_deg
    dist = f * spec.dist_max_deg
    return prox, dist


def wrist_yaw_deg(servo_deg):
    return (clamp_angle(servo_deg) - 90.0) / 90.0 * WRIST_RANGE_DEG


# world matrix of every moving part for a pose of 6 angles
def link_transforms(angles):
    angles = list(angles)
    while len(angles) < 6:
        angles.append(90.0)
    out = {}
    out["world"] = np.eye(4)
    wrist = np.dot(translate(0.0, 0.0, WRIST_Z), rot_z(wrist_yaw_deg(angles[WRIST_CHANNEL])))
    out["wrist"] = wrist
    for spec in FINGERS:
        prox, dist = finger_joint_angles(spec, angles[spec.channel])
        root = spec.root
        base = np.dot(wrist, translate(root[0], root[1], root[2]))
        base = np.dot(base, frame_from(spec.z_dir, spec.y_hint))
        base = np.dot(base, rot_y(spec.splay_deg))
        # minus rotation around X moves local +Z to local +Y (the palm side)
        p1 = np.dot(base, rot_x(-prox))
        p2 = np.dot(p1, translate(0.0, 0.0, spec.lengths[0]))
        p2 = np.dot(p2, rot_x(-dist))
        out[spec.name + "_1"] = p1
        out[spec.name + "_2"] = p2
    return out


# world xyz of every finger tip (used in the tests)
def fingertip_positions(angles):
    links = link_transforms(angles)
    tips = {}
    for spec in FINGERS:
        point = np.array([0.0, 0.0, spec.lengths[1], 1.0])
        tip = np.dot(links[spec.name + "_2"], point)
        tips[spec.name] = tip[:3]
    return tips
