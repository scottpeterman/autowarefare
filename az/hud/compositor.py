"""
hud/compositor.py — the shared HUD, drawn from PlayerState (POC design sec 10).

One HUD for both worlds, because the player's health/lives/score are one
shared thing regardless of which world is live. It is a QPainter overlay drawn
*after* the active world's GL, mirroring the ordering validated in
bz_model_viewer.py (raw GL first, then a QPainter on the same widget). It reads
PlayerState and the active world; it never mutates either.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from az.shell.player_state import PlayerState

_CYAN = QColor(0, 191, 255)
_DIM = QColor(120, 140, 150)
_BAR_BG = QColor(0, 40, 55)
_BAR_FG = QColor(0, 220, 140)
_BAR_LOW = QColor(230, 70, 50)
_RETICLE = QColor(90, 215, 255)        # bright targeting cyan
_RETICLE_DIM = QColor(0, 140, 200)     # recessed ring/ticks


class Hud:
    def __init__(self) -> None:
        self._frame = 0       # drives the reticle's slow ring rotation

    def draw(self, painter: QPainter, state: PlayerState,
             world_name: str, status: str, w: int, h: int,
             weapon: dict | None = None) -> None:
        self._frame += 1
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # damage flash: red edge vignette while the timer is live
        if state.damage_flash_ticks > 0:
            self._draw_damage_edge(painter, state, w, h)

        # health bar (top-left)
        self._draw_health(painter, state, 16, 16)

        # active weapon + heat gauge, under the health bar (top-left)
        if weapon is not None:
            self._draw_weapon(painter, weapon, 16, 40)

        # lives + score (top-right)
        painter.setFont(QFont("monospace", 11, QFont.Weight.Bold))
        painter.setPen(_CYAN)
        right = self._line_right(painter, f"LIVES {state.lives}", w - 16, 30)
        self._line_right(painter, f"SCORE {state.score:06d}", w - 16, 30 + 18)

        # world tag (top-center)
        painter.setFont(QFont("monospace", 10))
        painter.setPen(_DIM)
        self._line_center(painter, world_name.upper(), w, 22)

        # reticle (center)
        self._draw_reticle(painter, w, h)

        # status prompt (bottom-center)
        painter.setFont(QFont("monospace", 11))
        painter.setPen(_CYAN)
        self._line_center(painter, status, w, h - 18)

    # --- pieces ----------------------------------------------------------

    def _draw_health(self, painter: QPainter, state: PlayerState,
                     x: int, y: int) -> None:
        bw, bh = 220, 16
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_BAR_BG)
        painter.drawRect(x, y, bw, bh)
        frac = state.hp_fraction
        painter.setBrush(_BAR_LOW if frac <= 0.3 else _BAR_FG)
        painter.drawRect(x, y, int(bw * frac), bh)
        painter.setPen(QPen(_CYAN, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(x, y, bw, bh)
        painter.setFont(QFont("monospace", 10, QFont.Weight.Bold))
        painter.drawText(x + 6, y + bh - 3,
                         f"HP {int(state.health):3d}/{int(state.max_health)}")

    def _draw_weapon(self, painter: QPainter, weapon: dict,
                     x: int, y: int) -> None:
        """Active weapon name + (for heat weapons) a heat gauge that reddens as
        it climbs and reads OVERHEAT while locked out. Weapons without heat
        (the ballistic shell) show just the name."""
        name = str(weapon.get("name", "")).upper()
        heat = weapon.get("heat")
        overheated = bool(weapon.get("overheated"))

        painter.setFont(QFont("monospace", 10, QFont.Weight.Bold))
        painter.setPen(_BAR_LOW if overheated else _CYAN)
        painter.drawText(x, y + 12, f"WPN {name}")

        if heat is None:
            return

        bx, by, bw, bh = x + 92, y + 1, 110, 12
        frac = max(0.0, min(1.0, float(heat)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_BAR_BG)
        painter.drawRect(bx, by, bw, bh)
        if overheated:
            fg = _BAR_LOW
        elif frac > 0.7:
            fg = QColor(240, 150, 40)       # amber as it climbs
        else:
            fg = QColor(60, 190, 230)       # cool cyan
        painter.setBrush(fg)
        painter.drawRect(bx, by, int(bw * frac), bh)
        painter.setPen(QPen(_CYAN, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bx, by, bw, bh)
        if overheated:
            painter.setFont(QFont("monospace", 8, QFont.Weight.Bold))
            painter.setPen(_BAR_LOW)
            painter.drawText(bx + 28, by + bh - 2, "OVERHEAT")

    def _draw_reticle(self, painter: QPainter, w: int, h: int) -> None:
        cx, cy = w / 2.0, h / 2.0
        painter.save()
        painter.translate(cx, cy)

        # --- center: fine cross with a gap + a dot --------------------------
        painter.setPen(QPen(_RETICLE, 1.4))
        gap, arm = 4, 11
        painter.drawLine(QPointF(-arm, 0), QPointF(-gap, 0))
        painter.drawLine(QPointF(gap, 0), QPointF(arm, 0))
        painter.drawLine(QPointF(0, -arm), QPointF(0, -gap))
        painter.drawLine(QPointF(0, gap), QPointF(0, arm))
        painter.setBrush(_RETICLE)
        painter.drawEllipse(QPointF(0, 0), 1.2, 1.2)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # --- inner ring + radial ticks every 30 deg ------------------------
        r1 = 26.0
        painter.setPen(QPen(_RETICLE_DIM, 1.0))
        painter.drawEllipse(QRectF(-r1, -r1, 2 * r1, 2 * r1))
        for deg in range(0, 360, 30):
            a = math.radians(deg)
            ca, sa = math.cos(a), math.sin(a)
            painter.drawLine(QPointF(r1 * ca, r1 * sa),
                             QPointF((r1 + 5) * ca, (r1 + 5) * sa))

        # --- four cardinal markers (longer ticks N/E/S/W) ------------------
        painter.setPen(QPen(_RETICLE, 1.6))
        for ca, sa in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            painter.drawLine(QPointF((r1 + 3) * ca, (r1 + 3) * sa),
                             QPointF((r1 + 11) * ca, (r1 + 11) * sa))

        # --- rotating segmented outer ring ---------------------------------
        r2 = 46.0
        painter.save()
        painter.rotate(self._frame * 0.55)          # slow CW spin
        painter.setPen(QPen(_RETICLE, 1.7))
        rect = QRectF(-r2, -r2, 2 * r2, 2 * r2)
        for base in (0, 90, 180, 270):              # four arcs, gaps between
            painter.drawArc(rect, (base + 10) * 16, 34 * 16)
        painter.restore()

        # --- corner brackets framing the targeting box ----------------------
        box, ln = 54.0, 13.0
        painter.setPen(QPen(_RETICLE, 1.4))
        for sx in (-1, 1):
            for sy in (-1, 1):
                px, py = sx * box, sy * box
                painter.drawLine(QPointF(px, py), QPointF(px - sx * ln, py))
                painter.drawLine(QPointF(px, py), QPointF(px, py - sy * ln))

        painter.restore()

    def _draw_damage_edge(self, painter: QPainter, state: PlayerState,
                          w: int, h: int) -> None:
        from az.shell.player_state import DAMAGE_FLASH_TICKS
        a = int(150 * state.damage_flash_ticks / DAMAGE_FLASH_TICKS)
        pen = QPen(QColor(230, 40, 30, a), 10)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(5, 5, w - 10, h - 10)

    # --- text helpers ----------------------------------------------------

    def _line_center(self, painter: QPainter, text: str, w: int, y: int) -> None:
        tw = painter.fontMetrics().horizontalAdvance(text)
        painter.drawText((w - tw) // 2, y, text)

    def _line_right(self, painter: QPainter, text: str, x: int, y: int) -> int:
        tw = painter.fontMetrics().horizontalAdvance(text)
        painter.drawText(x - tw, y, text)
        return x - tw
