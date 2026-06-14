"""
shell/app.py — the host (POC design sections 2-3, 10).

A single QOpenGLWidget owns the process spine: the GL context, one QTimer
loop, the shared PlayerState, the registered worlds, and the portal between
them. This is the viewer's widget type (bz_model_viewer.py is a QOpenGLWidget
with paintGL + a QPainter HUD) running the games' loop shape — neither source
codebase had to invent a new host; the shell recombines parts both already
ship. Using QOpenGLWidget rather than the games' QGraphicsView drops the
scene/invalidate indirection and lets the shared HUD paint straight over GL.

Per frame:
    _tick   -> build InputState, active.update(dt, input, state), maybe portal
               handoff, state.tick(), schedule a repaint.
    paintGL -> active.draw(viewport) into the current context, then a QPainter
               pass for the shared HUD (GL first, painter second).

Physical keys are mapped to semantic InputState here so worlds never see Qt.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import GL_TRUE, glColorMask

from az.hud.compositor import Hud
from az.indoor.world import IndoorWorld
from az.outdoor.world import OutdoorWorld
from az.shell.mode import InputState
from az.shell.player_state import PlayerState
from az.shell.portal import Portal

TICK_MS = 16   # ~60 Hz, matches both source engines

_MOVE_KEYS = {
    Qt.Key.Key_W: "forward", Qt.Key.Key_Up: "forward",
    Qt.Key.Key_S: "back", Qt.Key.Key_Down: "back",
    Qt.Key.Key_A: "left", Qt.Key.Key_Left: "left",
    Qt.Key.Key_D: "right", Qt.Key.Key_Right: "right",
}
_ACTION_KEYS = {Qt.Key.Key_E, Qt.Key.Key_Return}      # edge: enter/interact
_FIRE_KEYS = {Qt.Key.Key_Space, Qt.Key.Key_F, Qt.Key.Key_Control}  # held: fire
# edge: cycle weapon. Q stays bound to quit, so the cycle key is Tab; change
# this set to rebind (e.g. swap quit off Q and add Qt.Key.Key_Q here).
_CYCLE_KEYS = {Qt.Key.Key_Tab}
# edge: take the stairs up / down (indoor only). Dedicated keys so signalling a
# direction never also walks the player off the single stairwell cell the way a
# movement key (W/S) would. Free of every other binding below.
_STAIR_UP_KEYS = {Qt.Key.Key_U}
_STAIR_DOWN_KEYS = {Qt.Key.Key_I}
# edge: grab a screenshot of the exact GL backbuffer (HUD included). 'S' is the
# reverse key, so screenshots live on P (easy reach) and F12 (muscle memory).
# Saved to $AWF_SHOT_DIR (default ./screenshots) as a millisecond-stamped PNG.
_SHOT_KEYS = {Qt.Key.Key_P, Qt.Key.Key_F12}


class ShellApp(QOpenGLWidget):
    def __init__(self, width: int = 1024, height: int = 768) -> None:
        super().__init__()
        self.setWindowTitle("Auto Warfare — M0 walking skeleton")
        self.resize(width, height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setDepthBufferSize(24)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)

        # shared state + worlds + portal (the spine)
        self.state = PlayerState()
        self.worlds = {"outdoor": OutdoorWorld(), "indoor": IndoorWorld()}
        self.portal = Portal(self.worlds)
        self.hud = Hud()

        self.active = self.worlds["outdoor"]
        self.active.on_enter(self.state, {})

        # input: held keys (level) + edge keys consumed once per frame
        self._held: set[int] = set()
        self._edge: set[int] = set()

        self._last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)

    # --- loop ------------------------------------------------------------

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        # clamp dt so an alt-tab stall can't teleport the player
        dt = min(dt, 0.05)

        inp = self._input_snapshot()
        self._edge.clear()  # edges are consumed by this frame only

        transition = self.active.update(dt, inp, self.state)
        if transition is not None:
            self.active = self.portal.transit(self.active, transition, self.state)

        self.state.tick()
        self.update()  # schedule paintGL

    def _input_snapshot(self) -> InputState:
        held, edge = self._held, self._edge
        intents = {_MOVE_KEYS[k] for k in held if k in _MOVE_KEYS}
        return InputState(
            forward="forward" in intents,
            back="back" in intents,
            left="left" in intents,
            right="right" in intents,
            action=any(k in _ACTION_KEYS for k in edge),   # edge-triggered
            fire=any(k in _FIRE_KEYS for k in held),        # held (gated downstream)
            cycle=any(k in _CYCLE_KEYS for k in edge),      # edge-triggered
            stair_up=any(k in _STAIR_UP_KEYS for k in edge),     # edge
            stair_down=any(k in _STAIR_DOWN_KEYS for k in edge), # edge
        )

    # --- input -----------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.isAutoRepeat():
            return
        key = event.key()
        if key in (Qt.Key.Key_Q, Qt.Key.Key_Escape):
            self.window().close()
            return
        if key in _SHOT_KEYS:
            self._save_screenshot()
            return
        self._held.add(key)
        self._edge.add(key)   # also an edge event this frame

    def keyReleaseEvent(self, event) -> None:
        if event.isAutoRepeat():
            return
        self._held.discard(event.key())

    def focusNextPrevChild(self, next: bool) -> bool:
        # Keep Tab as a game key (weapon cycle) instead of letting Qt consume it
        # for focus traversal — this is the only focusable widget anyway.
        return False

    def focusOutEvent(self, event) -> None:
        self._held.clear()
        self._edge.clear()
        super().focusOutEvent(event)

    # --- screenshot ------------------------------------------------------

    def _save_screenshot(self) -> None:
        """Grab the exact GL backbuffer (HUD included) to a timestamped PNG.

        ``grabFramebuffer`` re-renders through ``paintGL`` into an offscreen FBO
        and returns it, so the capture is the precise backbuffer — no compositor
        scaling, no capture-source guessing, and the QPainter HUD pass is part of
        paintGL so it's in the shot too. The millisecond stamp lets rapid grabs
        during motion land in distinct files. Console feedback (not a HUD flash)
        keeps it out of the captured frame and matches the viewer's style.
        """
        try:
            img = self.grabFramebuffer()
        except Exception as exc:  # pragma: no cover - needs a live GL context
            print(f"[screenshot] FAILED to grab framebuffer: "
                  f"{type(exc).__name__}: {exc}")
            return
        shot_dir = os.environ.get("AWF_SHOT_DIR", "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]   # ms precision
        path = os.path.join(shot_dir, f"aw_{stamp}.png")
        if img.save(path):
            print(f"[screenshot] {path}  ({img.width()}x{img.height()})")
        else:
            print(f"[screenshot] FAILED to write {path}")

    # --- GL --------------------------------------------------------------

    def initializeGL(self) -> None:
        # Each world sets its own frame state in draw(); nothing global needed.
        pass

    def resizeGL(self, w: int, h: int) -> None:
        # Viewport is set per-frame in the active world's draw() with the
        # HiDPI ratio applied, matching bz_model_viewer.py.
        pass

    def paintGL(self) -> None:
        ratio = self.devicePixelRatio()
        vp_w = max(1, int(self.width() * ratio))
        vp_h = max(1, int(self.height() * ratio))

        # The QPainter HUD pass (below) leaves GL state dirty for the next frame:
        # Qt's paint engine masks the red channel during compositing, and the
        # de-windowed renderers shed Bane's beginNativePainting bracket that used
        # to save/restore GL state around raw GL. Without that, last frame's
        # masked red bleeds into this one and every high-red draw loses its red
        # (amber stairs -> green, gold flag -> green, magenta -> blue). Re-enable
        # all channels before handing raw GL to the world — covers both worlds at
        # the one seam where the leak actually happens.
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)

        self.active.draw(vp_w, vp_h)

        # HUD: open a QPainter on this widget AFTER raw GL (the validated order)
        status = ""
        fn = getattr(self.active, "status_text", None)
        if callable(fn):
            status = fn(self.state)
        wfn = getattr(self.active, "weapon_status", None)
        weapon = wfn() if callable(wfn) else None
        painter = QPainter(self)
        self.hud.draw(painter, self.state, self.active.name, status,
                      self.width(), self.height(), weapon)
        painter.end()