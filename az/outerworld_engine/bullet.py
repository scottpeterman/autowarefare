"""
Bullet — active wireframe projectile.

Parallel to ``Obstacle`` (passive scenery), but with velocity and a
finite range. Like obstacles, bullets carry a 2D bounding circle for
collision; unlike obstacles, they advance one step per game tick and
expire when they exhaust their range, leave the world, or hit something.

Lives in ``Battlefield.bullets`` (separate from ``Battlefield.obstacles``)
because the two have different lifecycles — obstacles are added once and
persist; bullets are spawned, advanced, and removed every frame.

Render path is the same as Obstacle (via ``draw_bullet`` in render.py),
which composes the same `glPushMatrix → glTranslatef → glRotatef →
GL_LINES → glPopMatrix` sequence the obstacle renderer uses. The only
difference is the Y offset — bullets fly at gun-level (BULLET_Y in
game.py) rather than sitting on the ground plane.

Canonical Battlezone firing rule (verified against arcade reference):
**one shell on screen at a time**. The next bullet cannot be fired until
the previous one has either hit something or exhausted its range. The
gating is in ``BattlezoneGame._can_fire`` (just `len(bullets) == 0`),
not on the Bullet itself — the Bullet is just data. The crosshair
disappears while the bullet is in flight as a visual cooldown indicator,
matching the original's "crosshair flashes when you fire, returns when
ready to fire again" behavior.

Model: arcade gameplay reference shows a small box-shaped projectile;
spawn site uses CUBE_MODEL with ~0.15 scale. The README's pre-port note
about tetra (citing weapons.js:8) appears to be a JS-port divergence
from the arcade.

Coordinate convention: same as Obstacle — +X right, +Z toward camera at
heading=0. Velocity is in world-units-per-tick to match
``PLAYER_FORWARD_SPEED`` and the rest of the codebase's per-tick speeds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class Bullet:
    """A projectile traveling in a straight line until it hits or expires.

    Attributes:
        model:            Wireframe model dict — typically TETRA_MODEL,
                          per Heminger's `weapons.js:8` reference. Held
                          by reference (shared with all bullets).
        x, z:             World-space position in the XZ plane.
        vx, vz:           Velocity in world units per tick. Constant for
                          the bullet's lifetime — no gravity, no drag.
        range_remaining:  World units of travel left before the bullet
                          fades. Decremented by sqrt(vx² + vz²) per tick.
        heading:          Rotation about Y for rendering (purely cosmetic
                          — collision is the bounding circle).
        y:                World-space Y for rendering. Bullets fly at
                          gun level, not ground level. Default tuned in
                          ``BulletConfig`` in game.py.
        scale:            Per-instance scale of the model wireframe.
                          Decoupled from ``bounding_radius`` so the visual
                          size and the hit radius can be tuned independently.
        bounding_radius:  2D collision radius. Bullets are conceptually
                          point-like; default 1.0 keeps hits tight so the
                          player can dodge by reasonable margins. NOT
                          derived from the model the way Obstacle's is.
    """

    model: dict
    x: float
    z: float
    vx: float
    vz: float
    range_remaining: float
    heading: float = 0.0
    y: float = 6.0
    scale: float = 0.3
    bounding_radius: float = 1.0
    owner: str = 'player'       # 'player' or 'enemy' — governs who
                                # this bullet can hit. Player bullets
                                # hit tanks; enemy bullets hit the player.
                                # Both despawn on obstacles.
    damage: float = 1.0         # HP subtracted from whatever this round hits.
                                # Carried from the firing weapon's ProjectileSpec
                                # (see common.weapon). Default 1.0 = arcade
                                # one-hit kill vs a default-HP target, so a
                                # hand-built Bullet with no damage stays lethal.
    shooter: Any = None         # identity of the firing entity (the camera for
                                # the player, the Tank for an enemy). Distinct
                                # from `owner`: `owner` is the hit-test bucket
                                # ('player'/'enemy'), `shooter` is *which* entity
                                # fired. The ballistic fire-control gates per
                                # shooter on this (common.weapon), so six enemies
                                # each get their own live-round cap instead of
                                # the whole field sharing one. None = ungated by
                                # shooter (hand-built rounds, legacy per-owner).

    def step(self) -> None:
        """Advance one tick: move by (vx, vz), decrement range.

        The Battlefield's ``step_bullets`` calls this and then handles
        removal — out of range, out of world, or obstacle hit. The
        Bullet itself does not own the survivor/expired decision; it
        just integrates its motion.
        """
        self.x += self.vx
        self.z += self.vz
        self.range_remaining -= math.hypot(self.vx, self.vz)