#   HANDMOVE - 3D hand model (opengl view)
#        Oumar Ibrahim U22200741

# opengl view inside tkinter for the uHand 3D model
# mouse: left drag = orbit, right/middle drag = pan, wheel = zoom,
# double click = reset the view
# call set_angles when the servo angles change, the view moves slowly to the
# new pose so it looks like a real servo

import math
import time

import numpy as np
from OpenGL import GL
from pyopengltk import OpenGLFrame

from . import kinematics as K
from .scene import HIGHLIGHT, Part, build_parts, scene_bounds

# name: (azimuth, elevation) in degrees, azimuth 0 looks from -Y (back of the hand)
VIEW_PRESETS = {
    "Iso": (-35.0, 22.0),
    "Back": (0.0, 8.0),
    "Palm": (180.0, 8.0),
    "Side": (-90.0, 8.0),
    "Top": (0.0, 85.0),
}


def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, target, up=(0.0, 0.0, 1.0)):
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[:3, 3] = -np.dot(m[:3, :3], eye)
    return m


class HandGLView(OpenGLFrame):
    BG_TOP = (0.16, 0.20, 0.24)
    BG_BOTTOM = (0.06, 0.07, 0.09)

    def __init__(self, master, include_base=True, **kw):
        OpenGLFrame.__init__(self, master, **kw)
        self.parts = build_parts(include_base)
        lo, hi = scene_bounds(self.parts)
        self._center = (lo + hi) / 2
        self._radius = float(np.linalg.norm(hi - lo)) / 2
        self._lists = {}
        self._gl_ready = False

        self.target_angles = [90.0] * 6
        self.shown_angles = [90.0] * 6
        self.highlight_channel = None
        self.show_grid = True
        self.ease = True
        self._easing_job = None
        self._last_tick = 0.0

        self.reset_view()
        self._drag_start = None
        self._drag_button = 0
        self.bind("<ButtonPress-1>", self._press_left)
        self.bind("<ButtonPress-2>", self._press_middle)
        self.bind("<ButtonPress-3>", self._press_right)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<B2-Motion>", self._drag)
        self.bind("<B3-Motion>", self._drag)
        self.bind("<Double-Button-1>", self._double_click)
        self.bind("<MouseWheel>", self._wheel)  # windows / mac
        self.bind("<Button-4>", self._wheel_up)  # linux
        self.bind("<Button-5>", self._wheel_down)

    # functions the gui uses

    def set_angles(self, angles, immediate=False):
        new_angles = []
        for a in list(angles)[:6]:
            new_angles.append(float(a))
        self.target_angles = new_angles
        if immediate or not self.ease:
            self.shown_angles = list(self.target_angles)
            self.request_redraw()
            return
        if self._easing_job is None:
            self._last_tick = time.perf_counter()
            self._easing_job = self.after(0, self._ease_step)

    def set_view(self, name):
        self.azimuth = VIEW_PRESETS[name][0]
        self.elevation = VIEW_PRESETS[name][1]
        self.request_redraw()

    def reset_view(self):
        self.azimuth = VIEW_PRESETS["Iso"][0]
        self.elevation = VIEW_PRESETS["Iso"][1]
        self.distance = self._radius * 2.6
        self.pan = np.zeros(3)

    def request_redraw(self):
        if self._gl_ready and self.winfo_ismapped():
            self._display()

    # smooth movment

    def _ease_step(self):
        now = time.perf_counter()
        dt = now - self._last_tick
        if dt > 0.1:
            dt = 0.1
        self._last_tick = now
        # about the LFD-01 speed: 0.11 s for 60 deg so ~545 deg/s
        max_step = 545.0 * dt
        done = True
        for i in range(len(self.shown_angles)):
            if i >= len(self.target_angles):
                break
            cur = self.shown_angles[i]
            tgt = self.target_angles[i]
            diff = tgt - cur
            if abs(diff) > max_step:
                self.shown_angles[i] = cur + math.copysign(max_step, diff)
                done = False
            else:
                self.shown_angles[i] = tgt
        self.request_redraw()
        if done:
            self._easing_job = None
        else:
            self._easing_job = self.after(16, self._ease_step)

    # mouse

    def _press_left(self, event):
        self._press(event, 1)

    def _press_middle(self, event):
        self._press(event, 2)

    def _press_right(self, event):
        self._press(event, 3)

    def _press(self, event, button):
        self._drag_start = (event.x, event.y)
        self._drag_button = button

    def _double_click(self, event):
        self.reset_view()
        self.request_redraw()

    def _drag(self, event):
        if self._drag_start is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._drag_start = (event.x, event.y)
        if self._drag_button == 1:
            self.azimuth -= dx * 0.5
            el = self.elevation + dy * 0.5
            if el > 89.0:
                el = 89.0
            if el < -89.0:
                el = -89.0
            self.elevation = el
        else:
            height = self.winfo_height()
            if height < 1:
                height = 1
            scale = self.distance / height * 0.9
            right, up, fwd = self._camera_axes()
            self.pan += (-dx * right + dy * up) * scale
        self.request_redraw()

    def _wheel(self, event):
        if event.delta > 0:
            self._zoom(0.9)
        else:
            self._zoom(1.1)

    def _wheel_up(self, event):
        self._zoom(0.9)

    def _wheel_down(self, event):
        self._zoom(1.1)

    def _zoom(self, factor):
        dist = self.distance * factor
        if dist > self._radius * 8:
            dist = self._radius * 8
        if dist < self._radius * 0.6:
            dist = self._radius * 0.6
        self.distance = dist
        self.request_redraw()

    def _camera_axes(self):
        az = math.radians(self.azimuth)
        el = math.radians(self.elevation)
        fwd = np.array([-math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), -math.sin(el)])
        right = np.cross(fwd, [0, 0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        return right, up, fwd

    # opengl

    def initgl(self):
        GL.glViewport(0, 0, self.width, self.height)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_NORMALIZE)
        GL.glEnable(GL.GL_MULTISAMPLE)
        GL.glShadeModel(GL.GL_SMOOTH)
        GL.glEnable(GL.GL_LIGHTING)
        GL.glLightModelfv(GL.GL_LIGHT_MODEL_AMBIENT, (0.28, 0.28, 0.30, 1.0))
        GL.glLightModeli(GL.GL_LIGHT_MODEL_LOCAL_VIEWER, GL.GL_TRUE)
        GL.glLightModeli(GL.GL_LIGHT_MODEL_TWO_SIDE, GL.GL_FALSE)
        # 3 lights: (light, diffuse, specular)
        lights = [(GL.GL_LIGHT0, 0.85, 0.9), (GL.GL_LIGHT1, 0.35, 0.2), (GL.GL_LIGHT2, 0.3, 0.4)]
        for item in lights:
            light = item[0]
            diffuse = item[1]
            spec = item[2]
            GL.glEnable(light)
            GL.glLightfv(light, GL.GL_DIFFUSE, (diffuse, diffuse, diffuse, 1.0))
            GL.glLightfv(light, GL.GL_SPECULAR, (spec, spec, spec, 1.0))
        GL.glEnable(GL.GL_COLOR_MATERIAL)
        GL.glColorMaterial(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE)
        if not self._lists:
            self._compile_parts()
        self._gl_ready = True

    def _compile_parts(self):
        for i in range(len(self.parts)):
            part = self.parts[i]
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

    def _draw_background(self):
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_LIGHTING)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glBegin(GL.GL_QUADS)
        GL.glColor3f(self.BG_BOTTOM[0], self.BG_BOTTOM[1], self.BG_BOTTOM[2])
        GL.glVertex2f(-1, -1)
        GL.glVertex2f(1, -1)
        GL.glColor3f(self.BG_TOP[0], self.BG_TOP[1], self.BG_TOP[2])
        GL.glVertex2f(1, 1)
        GL.glVertex2f(-1, 1)
        GL.glEnd()
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_LIGHTING)

    def _draw_grid(self):
        GL.glDisable(GL.GL_LIGHTING)
        GL.glLineWidth(1.0)
        GL.glBegin(GL.GL_LINES)
        GL.glColor3f(0.22, 0.27, 0.31)
        step = 20
        extent = 260
        for v in range(-extent, extent + 1, step):
            GL.glVertex3f(v + 70, -extent, -0.2)
            GL.glVertex3f(v + 70, extent, -0.2)
            GL.glVertex3f(-extent + 70, v, -0.2)
            GL.glVertex3f(extent + 70, v, -0.2)
        GL.glEnd()
        GL.glEnable(GL.GL_LIGHTING)

    def redraw(self):
        w = self.width
        h = self.height
        if w < 1:
            w = 1
        if h < 1:
            h = 1
        GL.glViewport(0, 0, w, h)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        self._draw_background()
        GL.glClear(GL.GL_DEPTH_BUFFER_BIT)

        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        aspect = w / h
        # tall windows get a wider fov so the hand still fits
        if aspect >= 1:
            fovy = 35.0
        else:
            fovy = math.degrees(2 * math.atan(math.tan(math.radians(17.5)) / aspect ** 0.75))
        near = self.distance * 0.05
        if near < 1.0:
            near = 1.0
        GL.glLoadMatrixf(perspective(fovy, aspect, near, self.distance * 6).T)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()

        # head light, the lights stay fixed to the camera
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, (0.4, 0.8, 1.0, 0.0))
        GL.glLightfv(GL.GL_LIGHT1, GL.GL_POSITION, (-1.0, -0.2, 0.3, 0.0))
        GL.glLightfv(GL.GL_LIGHT2, GL.GL_POSITION, (0.0, 0.3, -1.0, 0.0))

        right, up, fwd = self._camera_axes()
        target = self._center + self.pan
        eye = target - fwd * self.distance
        GL.glLoadMatrixf(look_at(eye, target).T)

        if self.show_grid:
            self._draw_grid()

        links = K.link_transforms(self.shown_angles)
        for i in range(len(self.parts)):
            part = self.parts[i]
            mat = part.material
            # the moving parts of the selected servo get the highlight colour
            if self.highlight_channel is not None and part.channel == self.highlight_channel:
                if part.link != "world":
                    mat = HIGHLIGHT
            GL.glColor3f(mat.color[0], mat.color[1], mat.color[2])
            GL.glMaterialfv(GL.GL_FRONT_AND_BACK, GL.GL_SPECULAR, (mat.specular, mat.specular, mat.specular, 1.0))
            GL.glMaterialf(GL.GL_FRONT_AND_BACK, GL.GL_SHININESS, mat.shininess)
            GL.glPushMatrix()
            GL.glMultMatrixf(np.ascontiguousarray(links[part.link].T, dtype=np.float32))
            GL.glCallList(self._lists[i])
            GL.glPopMatrix()

    # reads the current picture back as a (h, w, 3) uint8 array
    def snapshot(self):
        self.tkMakeCurrent()
        self.redraw()
        GL.glFinish()
        data = GL.glReadPixels(0, 0, self.width, self.height, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
        img = np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 3)
        return img[::-1].copy()
