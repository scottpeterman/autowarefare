"""
indoor/projectile.py — the gunman's bolt (M2.3).

The interior's one ranged hazard: a slow, *visible* slug, not a hitscan. The
choice is deliberate. A hitscan gunman is just a melee mob with a long reach —
you can't react to it, so its only counter is geometry you already had to use.
A travelling bolt you can see coming makes the gunman a distinct threat with a
distinct answer: it's slow enough to sidestep at range and to outrun a corner,
so the player reads the sightline, breaks it or strafes, and the LOS gating that
governs aggro now also governs whether a shot ever leaves the barrel. That's the
Battlezone read — a glowing tracer you dodge — and it keeps melee and ranged
feeling like different problems.

A ``Bolt`` is intentionally dumb: it only knows how to move and to age. The
world owns the consequences — wall stops, the player hit, expiry — because the
world is what holds the dungeon and the player position, exactly as it owns the
melee contact check. Bolts are transient and active-floor-only; the world drops
them on any floor swap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

BOLT_SPEED = 6.0          # u/tick — 2x the player; fast enough to punish a held
                          # sightline, slow enough to read and sidestep at range
BOLT_LIFE = 110           # ticks (~1.8s) — outranges the gunman's reach at 6 u/tick
BOLT_HIT_RADIUS = 16.0    # centre-to-centre player hit (player body ~12 + slug)
BOLT_Y = -14.0            # render height in -Y-up space (chest/eye line)


@dataclass
class Bolt:
    """A single in-flight slug. ``advance`` is one tick of travel + aging; the
    world tests it against walls and the player after."""
    x: float
    z: float
    vx: float
    vz: float
    damage: float
    life: int = BOLT_LIFE

    def advance(self) -> None:
        self.x += self.vx
        self.z += self.vz
        self.life -= 1

    @property
    def expired(self) -> bool:
        return self.life <= 0


def spawn_bolt(x: float, z: float, tx: float, tz: float, damage: float) -> Bolt:
    """A bolt from (x, z) aimed at (tx, tz) at ``BOLT_SPEED``. Aimed at the
    player's position *now* — a lead-free shot the player can sidestep."""
    dx, dz = tx - x, tz - z
    d = math.hypot(dx, dz)
    if d < 1e-6:
        dx, dz, d = 0.0, 1.0, 1.0          # degenerate: fire +Z, never divide by 0
    s = BOLT_SPEED / d
    return Bolt(x=x, z=z, vx=dx * s, vz=dz * s, damage=damage)