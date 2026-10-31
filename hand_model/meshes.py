"""
Mesh primitives for the uHand UNO 3D model.

Every primitive returns a ``Mesh``: flat triangle soup (N*3 vertices) with one
normal per vertex. Units are millimetres, Z is up.
"""

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

Vec2 = Tuple[float, float]


@dataclass
class Mesh:
    vertices: np.ndarray  # (N, 3) float32
    normals: np.ndarray   # (N, 3) float32

    def transformed(self, matrix: np.ndarray) -> "Mesh":
        """Return a copy with a 4x4 rigid transform applied."""
        rot = matrix[:3, :3]
        v = self.vertices @ rot.T + matrix[:3, 3]
        n = self.normals @ rot.T
        return Mesh(v.astype(np.float32), n.astype(np.float32))

    @property
    def triangle_count(self) -> int:
        return len(self.vertices) // 3


def merge(meshes: Sequence[Mesh]) -> Mesh:
    return Mesh(
        np.concatenate([m.vertices for m in meshes]).astype(np.float32),
        np.concatenate([m.normals for m in meshes]).astype(np.float32),
    )


def _soup(tris: List[Tuple[np.ndarray, np.ndarray, np.ndarray]], smooth_normals=None) -> Mesh:
    verts = np.array([p for tri in tris for p in tri], dtype=np.float32).reshape(-1, 3)
    if smooth_normals is not None:
        norms = np.array(smooth_normals, dtype=np.float32).reshape(-1, 3)
    else:
        a, b, c = verts[0::3], verts[1::3], verts[2::3]
        fn = np.cross(b - a, c - a)
        ln = np.linalg.norm(fn, axis=1, keepdims=True)
        ln[ln == 0] = 1.0
        fn /= ln
        norms = np.repeat(fn, 3, axis=0)
    return Mesh(verts, norms.astype(np.float32))


def box(sx: float, sy: float, sz: float, center=(0.0, 0.0, 0.0)) -> Mesh:
    """Axis-aligned box of size (sx, sy, sz) centred at ``center``."""
    cx, cy, cz = center
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    rect = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    return extrude(rect, sz).transformed(_translate(cx, cy, cz - hz))


def _translate(x, y, z) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _polygon_area(poly: Sequence[Vec2]) -> float:
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


def triangulate(poly: Sequence[Vec2]) -> List[Tuple[int, int, int]]:
    """Ear-clipping triangulation of a simple polygon (any winding)."""
    pts = [tuple(map(float, p)) for p in poly]
    idx = list(range(len(pts)))
    if _polygon_area(pts) < 0:
        idx.reverse()

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    out = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        n = len(idx)
        for k in range(n):
            i0, i1, i2 = idx[(k - 1) % n], idx[k], idx[(k + 1) % n]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if cross(a, b, c) <= 1e-9:
                continue
            if any(inside(pts[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break  # degenerate; give up on the remainder
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def extrude(poly: Sequence[Vec2], height: float) -> Mesh:
    """Extrude a 2D polygon (XY plane) from z=0 to z=height."""
    pts = [np.array([p[0], p[1]], dtype=float) for p in poly]
    if _polygon_area(poly) < 0:
        pts = pts[::-1]
    tris = []
    for a, b, c in triangulate([tuple(p) for p in pts]):
        pa, pb, pc = pts[a], pts[b], pts[c]
        tris.append((np.r_[pa, height], np.r_[pb, height], np.r_[pc, height]))
        tris.append((np.r_[pa, 0.0], np.r_[pc, 0.0], np.r_[pb, 0.0]))
    n = len(pts)
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        a0, a1 = np.r_[p0, 0.0], np.r_[p1, 0.0]
        b0, b1 = np.r_[p0, height], np.r_[p1, height]
        tris.append((a0, a1, b1))
        tris.append((a0, b1, b0))
    return _soup(tris)


def rounded_rect(w: float, h: float, r: float, segments: int = 6) -> List[Vec2]:
    """Outline of a rectangle (centred at origin) with rounded corners."""
    r = min(r, w / 2, h / 2)
    pts = []
    corners = [(w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
               (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)]
    for cx, cy, start in corners:
        for s in range(segments + 1):
            a = np.radians(start + 90 * s / segments)
            pts.append((cx + r * np.cos(a), cy + r * np.sin(a)))
    return pts


def chamfered_rect(w: float, h: float, c: float) -> List[Vec2]:
    hw, hh = w / 2, h / 2
    return [(-hw + c, -hh), (hw - c, -hh), (hw, -hh + c), (hw, hh - c),
            (hw - c, hh), (-hw + c, hh), (-hw, hh - c), (-hw, -hh + c)]


def finger_profile(length: float, base_w: float, tip_w: float, tip_round: bool = True,
                   segments: int = 8) -> List[Vec2]:
    """Side outline of a phalanx: along +Y from 0..length, width along X."""
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
        pts += [(tip_w / 2, length), (-tip_w / 2, length)]
    return pts


def cylinder(radius: float, height: float, segments: int = 20, center=(0.0, 0.0, 0.0),
             axis: str = "z") -> Mesh:
    """Smooth-shaded closed cylinder along ``axis`` centred at ``center``."""
    tris, norms = [], []
    h = height / 2
    for i in range(segments):
        a0 = 2 * np.pi * i / segments
        a1 = 2 * np.pi * (i + 1) / segments
        c0, s0, c1, s1 = np.cos(a0), np.sin(a0), np.cos(a1), np.sin(a1)
        p0b = np.array([radius * c0, radius * s0, -h]); p1b = np.array([radius * c1, radius * s1, -h])
        p0t = np.array([radius * c0, radius * s0, h]); p1t = np.array([radius * c1, radius * s1, h])
        n0 = np.array([c0, s0, 0.0]); n1 = np.array([c1, s1, 0.0])
        tris += [(p0b, p1b, p1t), (p0b, p1t, p0t)]
        norms += [n0, n1, n1, n0, n1, n0]
        top, bot = np.array([0, 0, h]), np.array([0, 0, -h])
        tris += [(top, p0t, p1t), (bot, p1b, p0b)]
        norms += [(0, 0, 1)] * 3 + [(0, 0, -1)] * 3
    m = _soup(tris, norms)
    rot = np.eye(4)
    if axis == "x":
        rot[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    elif axis == "y":
        rot[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
    rot[:3, 3] = center
    return m.transformed(rot)


def arc(cx: float, cy: float, r: float, a0_deg: float, a1_deg: float, segments: int = 8) -> List[Vec2]:
    """Points along a circular arc from a0 to a1 (degrees, inclusive)."""
    return [(cx + r * np.cos(np.radians(a0_deg + (a1_deg - a0_deg) * i / segments)),
             cy + r * np.sin(np.radians(a0_deg + (a1_deg - a0_deg) * i / segments)))
            for i in range(segments + 1)]


def side_plate(profile_yz: Sequence[Vec2], width: float) -> Mesh:
    """Extrude a (y, z) side profile along X by ``width``, centred on x = 0."""
    m = extrude(profile_yz, width)  # profile in XY, thickness along Z
    rot = np.eye(4)
    rot[:3, :3] = [[0, 0, 1], [1, 0, 0], [0, 1, 0]]  # (x', y', z') -> (y, z, x)
    rot[0, 3] = -width / 2
    return m.transformed(rot)
