"""
Tank — destructible enemy entity on the battlefield.

Third entity type alongside ``Obstacle`` (passive scenery) and ``Bullet``
(active projectile). Like obstacles, tanks sit on the ground plane and
carry a 2D bounding circle for collision/hit-test. Unlike obstacles,
they're destructible (one-hit kill, per arcade rules) and will eventually
have AI state driving per-tick motion (milestone 4: ``enemytank.js``
state-machine port — patrol / patrolrotate / chase / lookchase / evade,
plus ``setavoid()`` cone-projection avoidance).

Lives in ``Battlefield.tanks`` (separate from ``obstacles`` and
``bullets``). The split lets ``Battlefield.step_bullets`` cleanly
prioritize tank hits over obstacle hits (a bullet that overlaps both
should kill the tank, not get absorbed by cover behind it), and lets
the eventual AI tick (``Battlefield.step_tanks``, milestone 4) iterate
just the tanks list without strolling past 13 obstacles plus N bullets.

Render path: ``draw_tank`` in render.py — same model/translate/rotate
sequence as obstacle, no Y offset (tanks sit on the ground), no bob.
The tank's intrinsic forward axis is -Z, baked into the asset (see
tank_model.py docstring), so ``heading`` semantics match Camera and
Obstacle: 0 = facing -Z, positive = clockwise from above.

Kill model (milestone 5b, partly here): a single bullet hit removes the
tank from the world. Currently this just despawns the tank silently in
``Battlefield.step_bullets``. The texplode1..6 fragment cascade comes
later — the kill loop is already wired, the explosion is purely visual.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .obstacle import model_radius_2d


@dataclass
class Tank:
    """An enemy tank — destructible, mobile (eventually), aimable.

    Attributes:
        model:    Wireframe model dict (typically TANK_MODEL). Held by
                  reference; all tanks share the same dict.
        x, z:     World-space position in the XZ plane.
        heading:  Rotation about +Y. ``0`` = facing -Z (matches Camera
                  and Obstacle convention; tank model is baked -Z forward).
        scale:    Per-instance scale. The native tank is 48u long, 24u
                  wide, 16u tall — already correctly sized against the
                  player's tank, so default 1.0.

        ai_mode:  AI state-machine label. Stubbed to 'idle' until the
                  ``enemytank.js`` port lands in milestone 4. Reserved
                  values per JS source: 'patrol', 'patrolrotate',
                  'chase', 'lookchase', 'evade'.

    Tanks are one-hit kills (arcade rule). There's no health, no shields,
    no damage state. If a bullet's bounding circle overlaps a tank's,
    the tank is removed from ``Battlefield.tanks`` on that tick.
    """

    model: dict
    x: float
    z: float
    heading: float = 0.0
    scale: float = 1.0

    # AI state — slice 1 of the enemytank.js port lands the FSM in
    # bz/battlefield_engine/tank_ai.py. Reserved values per JS source
    # (enemytank.js:283-322): 'idle', 'patrol', 'patrolrotate',
    # 'chase', 'lookchase', 'evade'. Spawn 'idle' and let
    # ``tank_ai.tick_tank`` bootstrap into 'patrol' on first tick.
    ai_mode: str = 'idle'

    # FSM bookkeeping. Mutated only by ``tank_ai.tick_tank``; kept
    # here on the dataclass for visibility in the debugger and so a
    # future serializer can dump them.
    #
    #   ai_state_ticks    — countdown of ticks remaining in the
    #                       current state. Some states use it as a
    #                       duration (patrol, lookchase), others as a
    #                       safety cap (patrolrotate), chase ignores it.
    #   ai_target_heading — target rotation for ``patrolrotate``.
    #                       Unused in other states; left set across
    #                       transitions as a harmless "last target" trail.
    #   ai_seed           — per-tank RNG seed. ``None`` = system entropy
    #                       (test scenes pass a fixed int for repeatability).
    ai_state_ticks: int = 0
    ai_target_heading: float = 0.0
    ai_seed: int | None = None

    # Firing flag — set by ``tank_ai.tick_tank`` when the tank wants
    # to fire this tick. Read and cleared by ``game.py._tick`` after
    # ``step_tanks()``. Keeps bullet creation in game.py (where model
    # imports and config constants live) and the fire *decision* in the
    # AI module.
    ai_wants_fire: bool = False

    def __post_init__(self) -> None:
        # Per-tank Random so two tanks in the same scene don't share
        # decision state — sharing the global ``random`` would make
        # multiple tanks roll patrol/chase decisions in lockstep on
        # the same tick, which reads on screen as duplicated behavior.
        # Carried as a non-dataclass attribute so dataclass __eq__ /
        # __repr__ ignore it.
        self._rng = random.Random(self.ai_seed)

    @property
    def bounding_radius(self) -> float:
        """Effective 2D collision radius in world units.

        Same composition order as Obstacle:
          model_radius_2d * model['scale'] * tank.scale

        For the canonical TANK_MODEL with default scale this is ~27 — the
        tank is 48u × 24u, so the bounding circle (corner-to-origin) is
        sqrt(24² + 12²) ≈ 26.8. Generous for hit-detection but tight
        enough that bullets at flank range still need real aim.
        """
        intrinsic = self.model.get('scale', 1.0)
        return model_radius_2d(self.model) * intrinsic * self.scale
