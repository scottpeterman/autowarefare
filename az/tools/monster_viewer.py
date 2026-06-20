#!/usr/bin/env python3
"""
Auto Warfare — Monster / Character Viewer
=========================================
An orbital wireframe inspector for the indoor clone-mobsters, so they can be
*designed before integration*: tune a body or a stat in ``tools/mobsters.py``
(and the generator in ``tools/humanoid.py``), press **L**, and the change is
live in the seat — the same hot-reload design loop ``vehicle_viewer.py`` gives
the hulls. Re-adopted from that viewer (PyQt6 + QOpenGLWidget, orbital camera,
QPainter HUD, AW cyberblue phosphor) and the standalone castleofbane
``model_viewer_pro.py`` it descends from.

What it shows that the vehicle viewer doesn't: the **character is body + stats**,
so the HUD carries the draft ``EnemyDef`` (Bane's shipped schema — hp / damage /
speed / sight / attack range + interval / turn / behavior) right beside the
geometry. You dial the look and the feel together.

Acquisition: the bodies are *generated*, not loaded — ``mobsters.build_model``
bakes ``humanoid.build_humanoid`` to a ``{'lines'}`` dict each reload, so what
you orbit is exactly the geometry that will be baked into ``indoor/models/`` at
integration. numpy lives here in the tool; the runtime game never imports it.

Orientation note: humanoids are authored **+Y up, +Z forward** (the arrow marks
+Z — the way a mobster faces). The indoor integration flips +Z->-Z to match the
game's forward and rides the renderer's documented -Y flip; that reconciliation
is an integration step, not something to eyeball here.

Run from the project root (so ``az`` is importable):

    python -m az.tools.monster_viewer

Controls:
    Mouse drag    Orbit camera
    Mouse wheel   Zoom
    1-3           Jump to mobster (Thug / Knifeman / Gunman)
    [ / ]         Prev / next mobster
    C             Cycle color scheme (blue default — AW phosphor)
    G             Toggle floor grid
    H             Toggle footprint circle (2D XZ radius, incl. held weapon)
    Z             Toggle forward (+Z) arrow
    B             Toggle idle bob
    Space         Pause animation
    F             Frame model (auto-fit camera distance)
    L             Reload bodies + stats from disk (after an edit)
    R             Reset camera
    Q / Esc       Quit
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

from az.tools import humanoid as _humanoid_mod
from az.tools import mobsters as _mobsters_mod


# ---------------------------------------------------------------------------
# Constants — same phosphor hex set as the vehicle/BZ/Bane viewers
# ---------------------------------------------------------------------------

COLOR_SCHEMES: dict[str, str] = {
    'blue':   '#35E0FF',
    'green':  '#00FFAA',
    'amber':  '#FFB000',
    'white':  '#FFFFFF',
}
DEFAULT_COLOR_NAME = 'blue'


# ---------------------------------------------------------------------------
# Model acquisition — generated bodies + their draft stats, by reference
# ---------------------------------------------------------------------------

def _build_mobsters(reload: bool = False) -> list[tuple[str, dict, dict]]:
    """Bake each registered mobster to (display_name, model_dict, stats_dict).

    ``reload=True`` re-imports the generator and the registry from disk so an
    edit to either shows live (the L key). The registry's ``build_model`` does a
    lazy import of the generator, so reloading ``humanoid`` first means the bake
    uses the edited geometry.
    """
    if reload:
        importlib.reload(_humanoid_mod)
        importlib.reload(_mobsters_mod)
    out: list[tuple[str, dict, dict]] = []
    for name in _mobsters_mod.ORDER:
        model = _mobsters_mod.build_model(name)
        stats = _mobsters_mod.MOBSTERS[name]['stats']
        out.append((name.title(), model, stats))
    return out


# ---------------------------------------------------------------------------
# Bounds helpers (shared shape with vehicle_viewer)
# ---------------------------------------------------------------------------

def _model_bounds(model: dict) -> tuple[tuple[float, float], ...]:
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
    r = 0.0
    for (a, b) in model['lines']:
        for p in (a, b):
            d = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
            if d > r:
                r = d
    return r


def _frame_distance(model: dict, fov_deg: float = 60.0,
                    margin: float = 1.5) -> float:
    radius = _model_radius(model)
    if radius < 1.0:
        return 50.0
    half_fov = math.radians(fov_deg / 2.0)
    return (radius * margin) / math.tan(half_fov)


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------

class MonsterViewer(QOpenGLWidget):
    """Orbital wireframe viewer for the AW clone-mobsters."""

    FOV_DEG = 60.0

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('Auto Warfare — Monster Viewer')
        self.resize(1100, 900)

        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)

        self.models = _build_mobsters()
        if not self.models:
            print('WARNING: no mobsters built', file=sys.stderr)

        # Orbital camera — a near-level look at a standing figure.
        self.azimuth = 20.0
        self.elevation = -10.0
        self.distance = 130.0
        self.target_y = 24.0

        self.model_index = 0
        self._frame_current_model()

        self.color_name = DEFAULT_COLOR_NAME
        self.show_grid = True
        self.show_footprint = True       # 2D XZ radius (includes held weapon)
        self.show_forward = True         # +Z forward arrow (humanoid facing)
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
    def current(self) -> tuple[str, dict, dict] | None:
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
        """Re-import the generator + registry so body/stat edits take effect."""
        try:
            self.models = _build_mobsters(reload=True)
        except Exception as exc:
            self._set_status(f'Reload FAILED — {type(exc).__name__}: {exc}',
                             duration=6.0)
            return
        if self.model_index >= len(self.models):
            self.model_index = max(0, len(self.models) - 1)
        self._frame_current_model()
        self._set_status(f'Reloaded ✓  ({len(self.models)} mobsters)')

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

            if self.show_footprint:
                self._draw_footprint(model_radius_2d(model) * scale,
                                     r * 0.45, g * 0.45, b * 0.45)
            if self.show_forward:
                # +Z is forward for humanoids — mark the facing.
                (xn, xx), (_, _), (zn, zz) = _model_bounds(model)
                reach = max(abs(zn), abs(zz), abs(xn), abs(xx)) * scale * 1.25
                self._draw_forward_arrow(reach, 1.0, 0.55, 0.2)

            bob_y = 0.0
            if self.animate and not self.paused and model.get('bob_speed', 0.0) > 0:
                bob_y = math.sin(self.entity_timer * model['bob_speed']) * model['bob_amount']

            glLineWidth(1.6)
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
        size = 120.0
        step = 12.0
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
        glVertex3f(-15.0, 0.01, 0.0); glVertex3f(15.0, 0.01, 0.0)
        glVertex3f(0.0, 0.01, -15.0); glVertex3f(0.0, 0.01, 15.0)
        glEnd()

    def _draw_footprint(self, radius: float, r: float, g: float, b: float) -> None:
        """The 2D XZ bounding circle on the floor — the design read of how much
        ground the figure (and its held weapon) covers."""
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
        """An arrow along +Z (the way the mobster faces)."""
        if reach <= 0.0:
            return
        tip_z = reach
        head = reach * 0.10
        glLineWidth(2.0)
        glColor3f(r, g, b)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.06, 0.0); glVertex3f(0.0, 0.06, tip_z)
        glVertex3f(0.0, 0.06, tip_z); glVertex3f(head, 0.06, tip_z - head)
        glVertex3f(0.0, 0.06, tip_z); glVertex3f(-head, 0.06, tip_z - head)
        glEnd()

    def _draw_hud(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont('monospace', 10))
        painter.setPen(self.color)

        cur = self.current
        anim_state = 'ON' if (self.animate and not self.paused) else 'OFF'

        if cur is None:
            lines = ['No mobsters built.']
        else:
            name, model, stats = cur
            (xn, xx), (yn, yx), (zn, zx) = _model_bounds(model)
            scale = model.get('scale', 1.0)
            foot_r = model_radius_2d(model) * scale
            lines = [
                f'[{self.model_index + 1}/{len(self.models)}] {name}'
                f'    behavior: {stats["behavior"].upper()}',
                f'Lines: {len(model["lines"])}    Footprint r(XZ): {foot_r:5.1f}'
                f'    H x W x D: {yx - yn:4.1f} x {xx - xn:4.1f} x {zx - zn:4.1f}',
                f'STATS  hp {stats["hp"]}   dmg {stats["damage"]}   '
                f'speed {stats["speed"]}   turn {stats["turn_speed"]:.0f}/s',
                f'       sight {stats["sight_range"]}   '
                f'attack: range {stats["attack_range"]} / '
                f'every {stats["attack_interval"]}s',
                f'Camera az={self.azimuth:>6.1f} el={self.elevation:>5.1f} '
                f'dist={self.distance:>6.1f}    Forward +Z (arrow)',
                f'Color {self.color_name.title()}  Grid {"ON" if self.show_grid else "OFF"}  '
                f'Foot {"ON" if self.show_footprint else "OFF"}  '
                f'Fwd {"ON" if self.show_forward else "OFF"}  Bob {anim_state}',
            ]
        for i, line in enumerate(lines):
            painter.drawText(12, 22 + i * 16, line)

        help_text = (
            'drag=orbit  wheel=zoom  1-3=mobster  [/]=prev/next  '
            'C=color  G=grid  H=foot  Z=fwd  B=bob  F=frame  L=reload  R=reset  Q=quit'
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
            self.show_footprint = not self.show_footprint
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
            self.azimuth = 20.0
            self.elevation = -10.0
            self._frame_current_model()


def main() -> int:
    app = QApplication(sys.argv)
    print('=' * 60)
    print('Auto Warfare — Monster / Character Viewer')
    print('=' * 60)
    viewer = MonsterViewer()
    print(f'Loaded {len(viewer.models)} mobsters:')
    for i, (name, model, stats) in enumerate(viewer.models):
        foot = model_radius_2d(model) * model.get('scale', 1.0)
        print(f'  {i + 1}. {name:10s} {len(model["lines"]):4d} lines  '
              f'foot_r={foot:4.1f}  hp={stats["hp"]} dmg={stats["damage"]} '
              f'({stats["behavior"]})')
    print()
    print('drag=orbit  1-3=mobster  C=color  H=footprint  Z=fwd  L=reload  Q=quit')
    print()
    viewer.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())