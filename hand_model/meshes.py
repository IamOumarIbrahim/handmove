#   HANDMOVE - 3D hand model (meshes)
#        Oumar Ibrahim U22200741

# basic shapes for the uHand 3D model
# every shape gives back a Mesh: a list of triangles (N*3 vertices) and one
# normal for each vertex. units are mm and Z is up

import numpy as np


class Mesh:
    def __init__(self, vertices, normals):
        self.vertices = vertices  # (N, 3) float32
        self.normals = normals  # (N, 3) float32

    # gives a copy moved by a 4x4 matrix
    def transformed(self, matrix):
        rot = matrix[:3, :3]
        v = np.dot(self.vertices, rot.T) + matrix[:3, 3]
        n = np.dot(self.normals, rot.T)
        return Mesh(v.astype(np.float32), n.astype(np.float32))

    def triangle_count(self):
        return len(self.vertices) // 3


def merge(meshes):
    all_v = []
    all_n = []
    for m in meshes:
        all_v.append(m.vertices)
        all_n.append(m.normals)
    return Mesh(np.concatenate(all_v).astype(np.float32), np.concatenate(all_n).astype(np.float32))


# makes a mesh from a list of triangles, if no normals are given it uses
# the flat normal of each triangle
def make_mesh(tris, smooth_normals=None):
    points = []
    for tri in tris:
        for p in tri:
            points.append(p)
    verts = np.array(points, dtype=np.float32).reshape(-1, 3)
    if smooth_normals is not None:
        norms = np.array(smooth_normals, dtype=np.float32).reshape(-1, 3)
    else:
        a = verts[0::3]
        b = verts[1::3]
        c = verts[2::3]
        fn = np.cross(b - a, c - a)
        ln = np.linalg.norm(fn, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        fn /= ln
        norms = np.repeat(fn, 3, axis=0)
    return Mesh(verts, norms.astype(np.float32))


# box with size (sx, sy, sz) and its center at center
def box(sx, sy, sz, center=(0.0, 0.0, 0.0)):
    cx = center[0]
    cy = center[1]
    cz = center[2]
    hx = sx / 2
    hy = sy / 2
    hz = sz / 2
    rect = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    return extrude(rect, sz).transformed(move_matrix(cx, cy, cz - hz))


def move_matrix(x, y, z):
    m = np.eye(4)
    m[0, 3] = x
    m[1, 3] = y
    m[2, 3] = z
    return m


def polygon_area(poly):
    total = 0
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        total = total + (poly[i][0] * poly[j][1] - poly[j][0] * poly[i][1])
    return 0.5 * total


# 2d cross product of (a - o) and (b - o)
def cross2(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def point_in_triangle(p, a, b, c):
    if cross2(a, b, p) >= 0 and cross2(b, c, p) >= 0 and cross2(c, a, p) >= 0:
        return True
    return False


# ear clipping, cuts a simple polygon into trianlges (works both directions)
def triangulate(poly):
    pts = []
    for p in poly:
        pts.append((float(p[0]), float(p[1])))
    idx = list(range(len(pts)))
    if polygon_area(pts) < 0:
        idx.reverse()

    out = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        n = len(idx)
        found = False
        for k in range(n):
            i0 = idx[(k - 1) % n]
            i1 = idx[k]
            i2 = idx[(k + 1) % n]
            a = pts[i0]
            b = pts[i1]
            c = pts[i2]
            if cross2(a, b, c) <= 1e-9:
                continue
            # no other point can be inside the ear
            blocked = False
            for j in idx:
                if j != i0 and j != i1 and j != i2:
                    if point_in_triangle(pts[j], a, b, c):
                        blocked = True
                        break
            if blocked:
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            found = True
            break
        if not found:
            # bad polygon, just stop
            break
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


# pushes a 2d polygon (XY) up from z = 0 to z = height
def extrude(poly, height):
    pts = []
    for p in poly:
        pts.append(np.array([p[0], p[1]], dtype=float))
    if polygon_area(poly) < 0:
        pts.reverse()
    flat = []
    for p in pts:
        flat.append(tuple(p))
    tris = []
    for t in triangulate(flat):
        pa = pts[t[0]]
        pb = pts[t[1]]
        pc = pts[t[2]]
        # top and bottom
        tris.append((np.array([pa[0], pa[1], height]), np.array([pb[0], pb[1], height]),
                     np.array([pc[0], pc[1], height])))
        tris.append((np.array([pa[0], pa[1], 0.0]), np.array([pc[0], pc[1], 0.0]),
                     np.array([pb[0], pb[1], 0.0])))
    n = len(pts)
    # the sides
    for i in range(n):
        p0 = pts[i]
        p1 = pts[(i + 1) % n]
        a0 = np.array([p0[0], p0[1], 0.0])
        a1 = np.array([p1[0], p1[1], 0.0])
        b0 = np.array([p0[0], p0[1], height])
        b1 = np.array([p1[0], p1[1], height])
        tris.append((a0, a1, b1))
        tris.append((a0, b1, b0))
    return make_mesh(tris)


# rectangle outline (center at 0,0) with round corners
def rounded_rect(w, h, r, segments=6):
    if r > w / 2:
        r = w / 2
    if r > h / 2:
        r = h / 2
    pts = []
    corners = [(w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
               (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)]
    for corner in corners:
        cx = corner[0]
        cy = corner[1]
        start = corner[2]
        for s in range(segments + 1):
            a = np.radians(start + 90 * s / segments)
            pts.append((cx + r * np.cos(a), cy + r * np.sin(a)))
    return pts


def chamfered_rect(w, h, c):
    hw = w / 2
    hh = h / 2
    return [(-hw + c, -hh), (hw - c, -hh), (hw, -hh + c), (hw, hh - c),
            (hw - c, hh), (-hw + c, hh), (-hw, hh - c), (-hw, -hh + c)]


# side outline of a finger part, goes along +Y from 0 to length, width is X
def finger_profile(length, base_w, tip_w, tip_round=True, segments=8):
    pts = [(-base_w / 2, 0.0), (base_w / 2, 0.0)]
    if tip_round:
        r = tip_w / 2
        cy = length - r
        pts.append((tip_w / 2, cy))
        for s in range(1, segments):
            a = np.radians(180 * s / segments)
            pts.append((r * np.cos(a), cy + r * np.sin(a)))
        pts.append((-tip_w / 2, cy))
    else:
        pts.append((tip_w / 2, length))
        pts.append((-tip_w / 2, length))
    return pts


# closed cylinder with smooth sides along axis, centered at center
def cylinder(radius, height, segments=20, center=(0.0, 0.0, 0.0), axis="z"):
    tris = []
    norms = []
    h = height / 2
    for i in range(segments):
        a0 = 2 * np.pi * i / segments
        a1 = 2 * np.pi * (i + 1) / segments
        c0 = np.cos(a0)
        s0 = np.sin(a0)
        c1 = np.cos(a1)
        s1 = np.sin(a1)
        p0b = np.array([radius * c0, radius * s0, -h])
        p1b = np.array([radius * c1, radius * s1, -h])
        p0t = np.array([radius * c0, radius * s0, h])
        p1t = np.array([radius * c1, radius * s1, h])
        n0 = np.array([c0, s0, 0.0])
        n1 = np.array([c1, s1, 0.0])
        # side
        tris.append((p0b, p1b, p1t))
        tris.append((p0b, p1t, p0t))
        norms.append(n0)
        norms.append(n1)
        norms.append(n1)
        norms.append(n0)
        norms.append(n1)
        norms.append(n0)
        # top and bottom caps
        top = np.array([0, 0, h])
        bot = np.array([0, 0, -h])
        tris.append((top, p0t, p1t))
        tris.append((bot, p1b, p0b))
        for k in range(3):
            norms.append((0, 0, 1))
        for k in range(3):
            norms.append((0, 0, -1))
    m = make_mesh(tris, norms)
    rot = np.eye(4)
    if axis == "x":
        rot[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    elif axis == "y":
        rot[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
    rot[:3, 3] = center
    return m.transformed(rot)


# points on a circle arc from a0 to a1 in degrees (both ends included)
def arc(cx, cy, r, a0_deg, a1_deg, segments=8):
    pts = []
    for i in range(segments + 1):
        ang = np.radians(a0_deg + (a1_deg - a0_deg) * i / segments)
        pts.append((cx + r * np.cos(ang), cy + r * np.sin(ang)))
    return pts


# pushes a (y, z) side outline along X by width, centered on x = 0
def side_plate(profile_yz, width):
    # the profile is in XY and the thickness goes on Z
    m = extrude(profile_yz, width)
    rot = np.eye(4)
    # (x', y', z') -> (y, z, x)
    rot[:3, :3] = [[0, 0, 1], [1, 0, 0], [0, 1, 0]]
    rot[0, 3] = -width / 2
    return m.transformed(rot)
