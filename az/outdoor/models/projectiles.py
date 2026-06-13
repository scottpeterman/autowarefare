"""
outdoor/models/projectiles.py — the player's shell projectile (game-layer look).

Replaces the placeholder cube the player was firing. A shell is an octagonal
(rounded-reading) body that tapers to a point at the **nose**, authored along
local **−Z** so it points in the direction of travel: the camera's forward at
heading 0 is (0, −1) → −Z, the bullet inherits ``camera.heading``, and
``render.draw_bullet`` rotates the model by ``−heading`` about Y — which carries
local −Z onto the world travel vector for every heading (verified against
``Camera.forward``). Authored in world units (≈16 long, ≈2.5 radius — same girth
as the old cube bullet, just elongated), so it is fired at ``scale = 1.0``.

Plain ``{'lines'}`` model dict (the §4a asset contract): draws through the
unmodified ``render.draw_bullet`` and needs no engine change.
"""

from __future__ import annotations

import math

from az.common import model as model_mod

_SIDES = 8                  # octagon cross-section: rounded without being heavy
_R = 2.5                    # body radius
_TAIL_Z = 6.0               # tail plane (+Z, trailing)
_SHOULDER_Z = -3.0          # where the body meets the nose cone
_TIP_Z = -12.0             # nose point (−Z, leading)


def _ring(z: float, r: float) -> list[tuple[float, float, float]]:
    """A ring of points in the XY plane at depth z (axis = Z)."""
    return [(r * math.cos(2 * math.pi * i / _SIDES),
             r * math.sin(2 * math.pi * i / _SIDES), z)
            for i in range(_SIDES)]


def _shell_model() -> dict:
    tail = _ring(_TAIL_Z, _R)
    shoulder = _ring(_SHOULDER_Z, _R)
    tip = (0.0, 0.0, _TIP_Z)

    lines: list[tuple] = []
    # the two body rings (the rounded cross-sections)
    for ring in (tail, shoulder):
        for i in range(_SIDES):
            lines.append((ring[i], ring[(i + 1) % _SIDES]))
    # body: longitudinal edges tail → shoulder
    for i in range(_SIDES):
        lines.append((tail[i], shoulder[i]))
    # nose cone: shoulder → tip
    for i in range(_SIDES):
        lines.append((shoulder[i], tip))

    m = {'lines': lines}
    model_mod.validate(m)
    return m


SHELL_MODEL = _shell_model()
SHELL_SCALE = 1.0           # authored at final world size


# --- the pulse-rifle tracer (M1 inc 2, rapid-fire weapon) ------------------
# A short, thin bright needle — reads as a fast streak rather than a heavy
# shell. Same -Z authoring convention as the shell (points along travel under
# render.draw_bullet's -heading rotation). Smaller and shorter than the shell:
# the heat-gated pulse rifle sprays many of these, fast.

_TR_R = 0.7                 # tracer body radius (thin)
_TR_SIDES = 4               # square section — cheapest, still reads round-ish
_TR_TAIL_Z = 4.0            # short tail
_TR_TIP_Z = -5.0            # short nose


def _tracer_model() -> dict:
    def ring(z: float) -> list[tuple[float, float, float]]:
        return [(_TR_R * math.cos(2 * math.pi * i / _TR_SIDES),
                 _TR_R * math.sin(2 * math.pi * i / _TR_SIDES), z)
                for i in range(_TR_SIDES)]

    tail = ring(_TR_TAIL_Z)
    tip = (0.0, 0.0, _TR_TIP_Z)
    lines: list[tuple] = []
    for i in range(_TR_SIDES):                       # tail square
        lines.append((tail[i], tail[(i + 1) % _TR_SIDES]))
    for i in range(_TR_SIDES):                       # taper tail -> tip
        lines.append((tail[i], tip))

    m = {'lines': lines}
    model_mod.validate(m)
    return m


TRACER_MODEL = _tracer_model()
TRACER_SCALE = 1.0          # authored at final world size
