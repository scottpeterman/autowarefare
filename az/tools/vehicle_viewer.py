#!/usr/bin/env python3
"""
Auto Warfare — Vehicle Viewer
=============================
An orbital wireframe inspector for the AW vehicle hulls, re-adopted from the
Battlezone ``bz_model_viewer.py`` (PyQt6 + QOpenGLWidget, orbital camera,
QPainter HUD). It keeps that viewer's proven render/orbit/HUD core and changes
only the *model acquisition*: instead of scanning a ``models/`` directory by
filename, it imports the **real game model dicts** directly — the same objects
``draw_tank`` renders — so what you see here is exactly what spawns on the field.

Why the rewrite of the acquisition layer: the AW model files
(``outdoor/models/vehicles.py``) ``import az.common...`` at module load, which the
original bare-stem directory scanner can't resolve. Importing the dicts by their
real package path sidesteps that and guarantees the viewer never drifts from the
game.

Two AW-specific overlays answer "how did they come out":
  * **Forward arrow (-Z).** Vehicles are authored -Z forward (``heading=0`` faces
    the player's spawn forward; the gun fires along -Z). The arrow marks -Z so
    you can confirm each hull's nose / barrel points downrange.
  * **Hit circle.** ``Tank.bounding_radius`` derives from the model's 2D (XZ)
    extent, so the silhouette *is* the hitbox. The floor ring is that exact
    circle (``model_radius_2d * scale``) — the sizing you tuned per chassis,
    drawn to scale against the wireframe.

Run from the project root (so ``az`` is importable):

    python -m az.tools.vehicle_viewer

Controls:
    Mouse drag    Orbit camera
    Mouse wheel   Zoom
    1-4           Jump to model (Tank ref / Sedan / Pickup / Flatbed)
    [ / ]         Prev / next model
    C             Cycle color scheme (blue default — the AW phosphor)
    G             Toggle floor grid
    H             Toggle hit circle (2D bounding radius)
    Z             Toggle forward (-Z) arrow
    F             Frame model (auto-fit camera distance)
    L             Reload models from disk (hot reload after a hull edit)
    R             Reset camera
    Q / Esc       Quit

On Linux with a discrete Nvidia GPU:
    __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia \
        python -m az.tools.vehicle_viewer
"""

from __future__ import annotations

import importlib
import math
import sys
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication

from OpenGL.GL import (
    glBegin, glClear, glClearColor, glClearDepth, glColor3f, glDepthFunc,
    glEnable, glEnd, glLineWidth, glLoadIdentity, glMatrixMode, glPopMatrix,
    glPushMatrix, glRotatef, glTranslatef, glVertex3f, glViewport,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
    GL_LESS, GL_LINES, GL_MODELVIEW, GL_PROJECTION,
)
from OpenGL.GLU import gluPerspective

from az.outerworld_engine.obstacle import model_radius_2d


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Blue-first: Auto Warfare is cyberblue-phosphor, so default to the game's look
# rather than Battlezone green. Same hex set as the BZ/Bane viewers so a model
# reads identically across all three.
COLOR_SCHEMES: dict[str, str] = {
    'blue':   '#35E0FF',
    'green':  '#00FFAA',
    'amber':  '#FFB000',
    'white':  '#FFFFFF',
}
DEFAULT_COLOR_NAME = 'blue'


# ---------------------------------------------------------------------------
# Model acquisition — the real game dicts, by reference
# ---------------------------------------------------------------------------

# (import_path, attr_name, display_name). The viewer imports these modules and
# pulls the dict attrs, so it shows exactly what the game spawns. Add a row to
# inspect another hull (e.g. the projectiles or buildings).
_MODEL_SOURCES = [
    ('az.outerworld_engine.models.tank_model', 'TANK_MODEL', 'TANK (reference)'),
    ('az.outdoor.models.vehicles', 'SEDAN_MODEL', 'SEDAN'),
    ('az.outdoor.models.vehicles', 'PICKUP_MODEL', 'PICKUP'),
    ('az.outdoor.models.vehicles', 'FLATBED_MODEL', 'FLATBED'),
]


def _build_models(reload: bool = False) -> list[tuple[str, dict, str]]:
    """Import (or reload) the source modules and return
    [(display_name, model_dict, 'module.py'), ...] in declared order.

    ``reload=True`` re-imports from disk so an edit to a hull file shows live
    (the L key) — the same hot-reload affordance the BZ viewer had, but scoped
    to the exact modules instead of a directory walk.
    """
    entries: list[tuple[str, dict, str]] = []
    reloaded: set[str] = set()
    for mod_path, attr, display in _MODEL_SOURCES:
        module = importlib.import_module(mod_path)
        if reload and mod_path not in reloaded:
            module = importlib.reload(module)
            reloaded.add(mod_path)
        model = getattr(module, attr)
        # Backfill the optional scalar keys so render never KeyErrors.
        model.setdefault('scale', 1.0)
        model.setdefault('bob_speed', 0.0)
        model.setdefault('bob_amount', 0.0)
        src = mod_path.rsplit('.', 1)[-1] + '.py'
        entries.append((display, model, src))
    return entries


# ---------------------------------------------------------------------------
# Bounds helpers
# ---------------------------------------------------------------------------

def _model_bounds(model: dict) -> tuple[tuple[float, float], ...]:
    """Return ((xmin,xmax), (ymin,ymax), (zmin,zmax)) for the model's vertices."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for (a, b) in model['lines']:
        xs.extend((a[0], b[0]))
        ys.extend((a[1], b[1]))
        zs.extend((a[2], b[2]))
    if not xs:
        return ((-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0))
    return ((min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs)))


def _model_radius(model: dict) -> float:
    """Worst-case distance from origin to any vertex (camera framing)."""
    r = 0.0
    for (a, b) in model['lines']:
        for p in (a, b):
            d = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
            if d > r:
                r = d
    return r


def _frame_distance(model: dict, fov_deg: float = 60.0,
                    margin: float = 1.5) -> float:
    """Camera distance that comfortably frames a model of the given radius."""
    radius = _model_radius(model)
    if radius < 1.0:
        return 50.0
    half_fov = math.radians(fov_deg / 2.0)
    return (radius * margin) / math.tan(half_fov)


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------

class VehicleViewer(QOpenGLWidget):
    """Orbital wireframe viewer for the AW vehicle hulls."""

    FOV_DEG = 60.0

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Auto Warfare — Vehicle Viewer')
        self.resize(1100, 850)

        # MSAA so wireframe lines read smooth, like a real vector display.
        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)

        self.models = _build_models()
        if not self.models:
            print('WARNING: no vehicle models built', file=sys.stderr)

        # Orbital camera — a gentle 3/4 down-look by default.
        self.azimuth = 35.0
        self.elevation = -16.0
        self.distance = 130.0
        self.target_y = 0.0

        self.model_index = 0
        self._frame_current_model()

        # Display state
        self.color_name = DEFAULT_COLOR_NAME
        self.show_grid = True
        self.show_hit_circle = True      # AW: the 2D bounding radius
        self.show_forward = True         # AW: the -Z forward arrow
        self.animate = True
        self.paused = False

        self.entity_timer = 0.0
        self.last_tick = time.time()
        self._last_mouse = None
        self.status_text = ''
        self.status_decay = 0.0

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # --- Selection helpers ---------------------------------------------------

    @property
    def color(self) -> QColor:
        return QColor(COLOR_SCHEMES[self.color_name])

    @property
    def current(self) -> tuple[str, dict, str] | None:
        if not self.models:
            return None
        return self.models[self.model_index]

    def _frame_current_model(self) -> None:
        cur = self.current
        if cur is None:
            self.target_y = 0.0
            return
        _, model, _ = cur
        (_, _), (y_min, y_max), (_, _) = _model_bounds(model)
        self.target_y = (y_min + y_max) / 2.0
        self.distance = max(40.0, min(800.0, _frame_distance(model, self.FOV_DEG)))

    def _set_status(self, text: str, duration: float = 2.5) -> None:
        self.status_text = text
        self.status_decay = duration

    def reload_models(self) -> None:
        """Re-import the hull modules from disk so edits take effect live."""
        try:
            self.models = _build_models(reload=True)
        except Exception as exc:
            self._set_status(f'Reload FAILED — {type(exc).__name__}: {exc}',
                             duration=5.0)
            return
        if self.model_index >= len(self.models):
            self.model_index = max(0, len(self.models) - 1)
        self._frame_current_model()
        self._set_status(f'Reloaded ✓  ({len(self.models)} models)')

    # --- Tick ----------------------------------------------------------------

    def _tick(self) -> None:
        now = time.time()
        dt = now - self.last_tick
        self.last_tick = now
        if self.animate and not self.paused:
            self.entity_timer += dt
        if self.status_decay > 0:
            self.status_decay = max(0.0, self.status_decay - dt)
            if self.status_decay == 0.0:
                self.status_text = ''
        self.update()

    # --- OpenGL --------------------------------------------------------------

    def initializeGL(self) -> None:
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glClearDepth(1.0)
        glClearColor(0.0, 0.0, 0.0, 1.0)

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
        pass  # viewport set in paintGL with HiDPI ratio applied

    def paintGL(self) -> None:  # noqa: N802
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        ratio = self.devicePixelRatio()
        vp_w = max(1, int(self.width() * ratio))
        vp_h = max(1, int(self.height() * ratio))
        glViewport(0, 0, vp_w, vp_h)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(self.FOV_DEG, vp_w / max(vp_h, 1), 0.5, 4000.0)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glTranslatef(0.0, 0.0, -self.distance)
        glRotatef(self.elevation, 1.0, 0.0, 0.0)
        glRotatef(self.azimuth, 0.0, 1.0, 0.0)
        glTranslatef(0.0, -self.target_y, 0.0)

        c = self.color
        r, g, b = c.redF(), c.greenF(), c.blueF()

        if self.show_grid:
            self._draw_grid(r * 0.25, g * 0.25, b * 0.25)
            self._draw_axes(r * 0.6, g * 0.6, b * 0.6)

        cur = self.current
        if cur is not None:
            _, model, _ = cur
            scale = model.get('scale', 1.0)

            if self.show_hit_circle:
                # The exact gameplay hit circle: model_radius_2d * scale.
                self._draw_hit_circle(model_radius_2d(model) * scale,
                                      r * 0.45, g * 0.45, b * 0.45)
            if self.show_forward:
                # -Z is forward; mark it so barrel/nose orientation is legible.
                (xn, xx), (_, _), (zn, zz) = _model_bounds(model)
                reach = max(abs(zn), abs(zz), abs(xn), abs(xx)) * scale * 1.25
                self._draw_forward_arrow(reach, 1.0, 0.55, 0.2)  # warm arrow

            bob_y = 0.0
            if self.animate and not self.paused and model.get('bob_speed', 0.0) > 0:
                bob_y = math.sin(self.entity_timer * model['bob_speed']) * model['bob_amount']

            glLineWidth(2.0)
            glPushMatrix()
            glTranslatef(0.0, bob_y, 0.0)
            glColor3f(r, g, b)
            glBegin(GL_LINES)
            for (x1, y1, z1), (x2, y2, z2) in model['lines']:
                glVertex3f(x1 * scale, y1 * scale, z1 * scale)
                glVertex3f(x2 * scale, y2 * scale, z2 * scale)
            glEnd()
            glPopMatrix()

        self._draw_hud()

    def _draw_grid(self, r: float, g: float, b: float) -> None:
        glLineWidth(1.0)
        glColor3f(r, g, b)
        size = 200.0
        step = 25.0
        n = int(size / step)
        glBegin(GL_LINES)
        for i in range(-n, n + 1):
            x = i * step
            glVertex3f(x, 0.0, -size); glVertex3f(x, 0.0, size)
            glVertex3f(-size, 0.0, x); glVertex3f(size, 0.0, x)
        glEnd()

    def _draw_axes(self, r: float, g: float, b: float) -> None:
        glLineWidth(1.5)
        glColor3f(r, g, b)
        glBegin(GL_LINES)
        glVertex3f(-25.0, 0.01, 0.0); glVertex3f(25.0, 0.01, 0.0)
        glVertex3f(0.0, 0.01, -25.0); glVertex3f(0.0, 0.01, 25.0)
        glEnd()

    def _draw_hit_circle(self, radius: float, r: float, g: float, b: float) -> None:
        """The 2D bounding circle on the floor — the gameplay hitbox to scale."""
        if radius <= 0.0:
            return
        glLineWidth(1.5)
        glColor3f(r, g, b)
        glBegin(GL_LINES)
        segs = 64
        prev = None
        for i in range(segs + 1):
            a = 2.0 * math.pi * i / segs
            p = (radius * math.cos(a), 0.05, radius * math.sin(a))
            if prev is not None:
                glVertex3f(*prev); glVertex3f(*p)
            prev = p
        glEnd()

    def _draw_forward_arrow(self, reach: float, r: float, g: float, b: float) -> None:
        """An arrow along -Z (forward) so nose/barrel orientation is unambiguous."""
        if reach <= 0.0:
            return
        tip_z = -reach
        head = reach * 0.10
        glLineWidth(2.0)
        glColor3f(r, g, b)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.06, 0.0); glVertex3f(0.0, 0.06, tip_z)        # shaft
        glVertex3f(0.0, 0.06, tip_z); glVertex3f(head, 0.06, tip_z + head)
        glVertex3f(0.0, 0.06, tip_z); glVertex3f(-head, 0.06, tip_z + head)
        glEnd()

    def _draw_hud(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont('monospace', 10))
        painter.setPen(self.color)

        cur = self.current
        anim_state = 'ON' if (self.animate and not self.paused) else 'OFF'

        if cur is None:
            lines = ['No vehicle models built.']
        else:
            name, model, src_file = cur
            (xn, xx), (yn, yx), (zn, zx) = _model_bounds(model)
            scale = model.get('scale', 1.0)
            hit_r = model_radius_2d(model) * scale
            lines = [
                f'[{self.model_index + 1}/{len(self.models)}] {name}  ({src_file})',
                f'Lines:   {len(model["lines"])}     '
                f'Hit circle (2D r): {hit_r:6.2f}',
                f'Bounds:  X[{xn:>7.2f},{xx:>7.2f}]  '
                f'Y[{yn:>7.2f},{yx:>7.2f}]  Z[{zn:>7.2f},{zx:>7.2f}]',
                f'Forward: -Z (toward the arrow)     '
                f'L x W x H: {zx - zn:5.1f} x {xx - xn:5.1f} x {yx - yn:5.1f}',
                f'Camera:  az={self.azimuth:>6.1f}  el={self.elevation:>5.1f}  '
                f'dist={self.distance:>6.1f}',
                f'Color: {self.color_name.title()}   Grid: {"ON" if self.show_grid else "OFF"}   '
                f'Hit: {"ON" if self.show_hit_circle else "OFF"}   '
                f'Fwd: {"ON" if self.show_forward else "OFF"}   Anim: {anim_state}',
            ]
        for i, line in enumerate(lines):
            painter.drawText(12, 22 + i * 16, line)

        help_text = (
            'drag=orbit  wheel=zoom  1-4=model  [/]=prev/next  '
            'C=color  G=grid  H=hit  Z=fwd  F=frame  L=reload  R=reset  Q=quit'
        )
        painter.setPen(QColor('#888888'))
        painter.drawText(12, self.height() - 12, help_text)

        if self.status_text and self.status_decay > 0:
            painter.setFont(QFont('monospace', 12, QFont.Weight.Bold))
            failed = 'FAILED' in self.status_text
            base_color = QColor('#FF5050') if failed else QColor('#FFFFFF')
            alpha = 255 if self.status_decay > 1.0 else int(255 * self.status_decay)
            base_color.setAlpha(alpha)
            painter.setPen(base_color)
            metrics = painter.fontMetrics()
            tw = metrics.horizontalAdvance(self.status_text)
            painter.drawText((self.width() - tw) // 2, 32, self.status_text)

        painter.end()

    # --- Mouse ---------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802
        self._last_mouse = event.position()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._last_mouse is None:
            return
        pos = event.position()
        dx = pos.x() - self._last_mouse.x()
        dy = pos.y() - self._last_mouse.y()
        self._last_mouse = pos
        self.azimuth = (self.azimuth + dx * 0.5) % 360.0
        self.elevation = max(-89.0, min(89.0, self.elevation + dy * 0.5))

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._last_mouse = None

    def wheelEvent(self, event):  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        factor = 0.9 ** steps
        self.distance = max(5.0, min(2000.0, self.distance * factor))

    # --- Keyboard ------------------------------------------------------------

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()

        if key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            self.window().close()
            return

        for i in range(min(9, len(self.models))):
            if key == getattr(Qt.Key, f'Key_{i + 1}'):
                self.model_index = i
                self._frame_current_model()
                return

        if key == Qt.Key.Key_BracketLeft:
            if self.models:
                self.model_index = (self.model_index - 1) % len(self.models)
                self._frame_current_model()
        elif key == Qt.Key.Key_BracketRight:
            if self.models:
                self.model_index = (self.model_index + 1) % len(self.models)
                self._frame_current_model()
        elif key == Qt.Key.Key_C:
            names = list(COLOR_SCHEMES.keys())
            self.color_name = names[(names.index(self.color_name) + 1) % len(names)]
        elif key == Qt.Key.Key_G:
            self.show_grid = not self.show_grid
        elif key == Qt.Key.Key_H:
            self.show_hit_circle = not self.show_hit_circle
        elif key == Qt.Key.Key_Z:
            self.show_forward = not self.show_forward
        elif key == Qt.Key.Key_B:
            self.animate = not self.animate
        elif key == Qt.Key.Key_Space:
            self.paused = not self.paused
        elif key == Qt.Key.Key_F:
            self._frame_current_model()
        elif key == Qt.Key.Key_L:
            self.reload_models()
        elif key == Qt.Key.Key_R:
            self.azimuth = 35.0
            self.elevation = -16.0
            self._frame_current_model()


def main() -> int:
    app = QApplication(sys.argv)
    print('=' * 60)
    print('Auto Warfare — Vehicle Viewer')
    print('=' * 60)
    viewer = VehicleViewer()
    print(f'Loaded {len(viewer.models)} models:')
    for i, (name, model, src) in enumerate(viewer.models):
        hit = model_radius_2d(model) * model.get('scale', 1.0)
        print(f'  {i + 1}. {name:16s} {len(model["lines"]):4d} lines  '
              f'hit_r2d={hit:5.1f}  ({src})')
    print()
    print('drag=orbit  wheel=zoom  1-4=model  H=hit circle  Z=fwd arrow  L=reload')
    print()
    viewer.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())