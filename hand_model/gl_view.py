"""
OpenGL viewport (Tkinter) for the uHand UNO 3D model.

Controls: left-drag orbit, right/middle-drag pan, wheel zoom,
double-click reset view. Call ``set_angles`` whenever the servo angles change;
the view eases toward the new pose so steps look like real servo motion.
"""

import math
import time
from typing import Dict, List, Optional, Sequence

import numpy as np
from OpenGL import GL
from pyopengltk import OpenGLFrame

from . import kinematics as K
from .scene import HIGHLIGHT, Part, build_parts, scene_bounds

VIEW_PRESETS = {
    # name: (azimuth, elevation) in degrees; azimuth 0 looks from -Y (back of hand)
    "Iso": (-35.0, 22.0),
    "Back": (0.0, 8.0),
    "Palm": (180.0, 8.0),
    "Side": (-90.0, 8.0),
    "Top": (0.0, 85.0),
}


def _perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2], m[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def _look_at(eye: np.ndarray, target: np.ndarray, up=(0.0, 0.0, 1.0)) -> np.ndarray:
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


class HandGLView(OpenGLFrame):
    BG_TOP = (0.16, 0.20, 0.24)
    BG_BOTTOM = (0.06, 0.07, 0.09)

    def __init__(self, master, include_base: bool = True, **kw):
        super().__init__(master, **kw)
        self.parts: List[Part] = build_parts(include_base)
        lo, hi = scene_bounds(self.parts)
        self._center = (lo + hi) / 2
        self._radius = float(np.linalg.norm(hi - lo)) / 2
        self._lists: Dict[int, int] = {}
        self._gl_ready = False

        self.target_angles = [90.0] * 6
        self.shown_angles = [90.0] * 6
        self.highlight_channel: Optional[int] = None
        self.show_grid = True
        self.ease = True
        self._easing_job = None
        self._last_tick = 0.0

        self.reset_view()
        self._drag_start = None
        self._drag_button = 0
        self.bind("<ButtonPress-1>", lambda e: self._press(e, 1))
        self.bind("<ButtonPress-2>", lambda e: self._press(e, 2))
        self.bind("<ButtonPress-3>", lambda e: self._press(e, 3))
        self.bind("<B1-Motion>", self._drag)
        self.bind("<B2-Motion>", self._drag)
        self.bind("<B3-Motion>", self._drag)
        self.bind("<Double-Button-1>", lambda e: (self.reset_view(), self.request_redraw()))
        self.bind("<MouseWheel>", self._wheel)                       # Windows / macOS
        self.bind("<Button-4>", lambda e: self._zoom(0.9))           # X11
        self.bind("<Button-5>", lambda e: self._zoom(1.1))

    # ------------------------------------------------------------------ API
    def set_angles(self, angles: Sequence[float], immediate: bool = False) -> None:
        self.target_angles = [float(a) for a in list(angles)[:6]]
        if immediate or not self.ease:
            self.shown_angles = list(self.target_angles)
            self.request_redraw()
            return
        if self._easing_job is None:
            self._last_tick = time.perf_counter()
            self._easing_job = self.after(0, self._ease_step)

    def set_view(self, name: str) -> None:
        self.azimuth, self.elevation = VIEW_PRESETS[name]
        self.request_redraw()

    def reset_view(self) -> None:
        self.azimuth, self.elevation = VIEW_PRESETS["Iso"]
        self.distance = self._radius * 2.6
        self.pan = np.zeros(3)

    def request_redraw(self) -> None:
        if self._gl_ready and self.winfo_ismapped():
            self._display()

    # -------------------------------------------------------------- easing
    def _ease_step(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, now - self._last_tick)
        self._last_tick = now
        # Roughly LFD-01 speed: 0.11 s / 60 deg -> ~545 deg/s.
        max_step = 545.0 * dt
        done = True
        for i, (cur, tgt) in enumerate(zip(self.shown_angles, self.target_angles)):
            diff = tgt - cur
            if abs(diff) > max_step:
                self.shown_angles[i] = cur + math.copysign(max_step, diff)
                done = False
            else:
                self.shown_angles[i] = tgt
        self.request_redraw()
        self._easing_job = None if done else self.after(16, self._ease_step)

    # --------------------------------------------------------------- mouse
    def _press(self, event, button: int) -> None:
        self._drag_start = (event.x, event.y)
        self._drag_button = button

    def _drag(self, event) -> None:
        if self._drag_start is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._drag_start = (event.x, event.y)
        if self._drag_button == 1:
            self.azimuth -= dx * 0.5
            self.elevation = max(-89.0, min(89.0, self.elevation + dy * 0.5))
        else:
            scale = self.distance / max(1, self.winfo_height()) * 0.9
            right, up, _ = self._camera_axes()
            self.pan += (-dx * right + dy * up) * scale
        self.request_redraw()

    def _wheel(self, event) -> None:
        self._zoom(0.9 if event.delta > 0 else 1.1)

    def _zoom(self, factor: float) -> None:
        self.distance = max(self._radius * 0.6, min(self._radius * 8, self.distance * factor))
        self.request_redraw()

    def _camera_axes(self):
        az, el = math.radians(self.azimuth), math.radians(self.elevation)
        fwd = np.array([-math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), -math.sin(el)])
        right = np.cross(fwd, [0, 0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        return right, up, fwd

    # ------------------------------------------------------------------ GL
    def initgl(self) -> None:
        GL.glViewport(0, 0, self.width, self.height)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_NORMALIZE)
        GL.glEnable(GL.GL_MULTISAMPLE)
        GL.glShadeModel(GL.GL_SMOOTH)
        GL.glEnable(GL.GL_LIGHTING)
        GL.glLightModelfv(GL.GL_LIGHT_MODEL_AMBIENT, (0.28, 0.28, 0.30, 1.0))
        GL.glLightModeli(GL.GL_LIGHT_MODEL_LOCAL_VIEWER, GL.GL_TRUE)
        GL.glLightModeli(GL.GL_LIGHT_MODEL_TWO_SIDE, GL.GL_FALSE)
        for light, diffuse, spec in ((GL.GL_LIGHT0, 0.85, 0.9), (GL.GL_LIGHT1, 0.35, 0.2), (GL.GL_LIGHT2, 0.3, 0.4)):
            GL.glEnable(light)
            GL.glLightfv(light, GL.GL_DIFFUSE, (diffuse, diffuse, diffuse, 1.0))
            GL.glLightfv(light, GL.GL_SPECULAR, (spec, spec, spec, 1.0))
        GL.glEnable(GL.GL_COLOR_MATERIAL)
        GL.glColorMaterial(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE)
        if not self._lists:
            self._compile_parts()
        self._gl_ready = True

    def _compile_parts(self) -> None:
        for i, part in enumerate(self.parts):
            lst = GL.glGenLists(1)
            GL.glNewList(lst, GL.GL_COMPILE)
            GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
            GL.glEnableClientState(GL.GL_NORMAL_ARRAY)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, np.ascontiguousarray(part.mesh.vertices))
            GL.glNormalPointer(GL.GL_FLOAT, 0, np.ascontiguousarray(part.mesh.normals))
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(part.mesh.vertices))
            GL.glDisableClientState(GL.GL_NORMAL_ARRAY)
            GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
            GL.glEndList()
            self._lists[i] = lst

    def _draw_background(self) -> None:
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_LIGHTING)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(*self.BG_BOTTOM)
        GL.glVertex2f(-1, -1)
        GL.glVertex2f(1, -1)
        GL.glColor3f(*self.BG_TOP)
        GL.glVertex2f(1, 1)
        GL.glVertex2f(-1, 1)
        GL.glEnd()
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_LIGHTING)

    def _draw_grid(self) -> None:
        GL.glDisable(GL.GL_LIGHTING)
        GL.glLineWidth(1.0)
        GL.glBegin(GL.GL_LINES)
        GL.glColor3f(0.22, 0.27, 0.31)
        step, extent = 20, 260
        for v in range(-extent, extent + 1, step):
            GL.glVertex3f(v + 70, -extent, -0.2)
            GL.glVertex3f(v + 70, extent, -0.2)
            GL.glVertex3f(-extent + 70, v, -0.2)
            GL.glVertex3f(extent + 70, v, -0.2)
        GL.glEnd()
        GL.glEnable(GL.GL_LIGHTING)

    def redraw(self) -> None:
        w, h = max(1, self.width), max(1, self.height)
        GL.glViewport(0, 0, w, h)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        self._draw_background()
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)

        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        aspect = w / h
        fovy = 35.0 if aspect >= 1 else math.degrees(2 * math.atan(math.tan(math.radians(17.5)) / aspect ** 0.75))
        GL.glLoadMatrixf(_perspective(fovy, aspect, max(1.0, self.distance * 0.05), self.distance * 6).T)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()

        # Head-light style lighting: fixed relative to the camera.
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, (0.4, 0.8, 1.0, 0.0))
        GL.glLightfv(GL.GL_LIGHT1, GL.GL_POSITION, (-1.0, -0.2, 0.3, 0.0))
        GL.glLightfv(GL.GL_LIGHT2, GL.GL_POSITION, (0.0, 0.3, -1.0, 0.0))

        _, _, fwd = self._camera_axes()
        target = self._center + self.pan
        eye = target - fwd * self.distance
        GL.glLoadMatrixf(_look_at(eye, target).T)

        if self.show_grid:
            self._draw_grid()

        links = K.link_transforms(self.shown_angles)
        for i, part in enumerate(self.parts):
            mat = part.material
            if self.highlight_channel is not None and part.channel == self.highlight_channel \
                    and part.link != "world":
                mat = HIGHLIGHT
            GL.glColor3f(*mat.color)
            GL.glMaterialfv(GL.GL_FRONT_AND_BACK, GL.GL_SPECULAR, (mat.specular,) * 3 + (1.0,))
            GL.glMaterialf(GL.GL_FRONT_AND_BACK, GL.GL_SHININESS, mat.shininess)
            GL.glPushMatrix()
            GL.glMultMatrixf(np.ascontiguousarray(links[part.link].T, dtype=np.float32))
            GL.glCallList(self._lists[i])
            GL.glPopMatrix()

    def snapshot(self) -> np.ndarray:
        """Read back the current frame as an (h, w, 3) uint8 array."""
        self.tkMakeCurrent()
        self.redraw()
        GL.glFinish()
        data = GL.glReadPixels(0, 0, self.width, self.height, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
        img = np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 3)
        return img[::-1].copy()
