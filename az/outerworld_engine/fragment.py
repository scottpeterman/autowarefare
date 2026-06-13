"""
Fragment — short-lived explosion debris.

When an enemy tank is killed, it's replaced by 8–10 fragments chosen
randomly from the ``texplode1..6`` models. Each fragment flies outward
from the kill position with a random velocity, arcs upward under
gravity, and tumbles (spins on two axes). Fragments despawn after a
fixed lifetime — they're purely visual, no collision.

The arcade effect is distinctive: the tank doesn't just disappear, it
*shatters* into tumbling wireframe shards that arc up and rain down.
It's one of the most memorable visual effects in a 1980 game.

Coordinate convention: same as everything else — +Y up, heading 0
faces -Z, positive heading clockwise from above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# --- Fragment constants (tunables) ------------------------------------------

FRAGMENT_GRAVITY = -0.04        # Y acceleration per tick (negative = down)
FRAGMENT_LIFETIME_TICKS = 90    # ~1.5 sec at 62.5 Hz
FRAGMENT_SCALE = 0.8            # slightly smaller than native tank pieces


@dataclass
class Fragment:
    """A tumbling piece of a destroyed tank.

    Attributes:
        model:      Wireframe model dict (one of TEXPLODE1..6_MODEL).
        x, y, z:    World-space position. Y starts at 0 (ground) and
                    arcs up then down under gravity.
        vx, vy, vz: Velocity in world units per tick.
        heading:    Y-axis rotation (radians). Advances by spin_y per tick.
        tumble:     X-axis rotation (radians). Advances by spin_x per tick.
                    Combined with heading gives a convincing tumble.
        spin_y:     Angular velocity about Y (radians/tick).
        spin_x:     Angular velocity about X (radians/tick).
        scale:      Per-instance scale.
        lifetime:   Ticks remaining before despawn.
    """

    model: dict
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    heading: float = 0.0
    tumble: float = 0.0
    spin_y: float = 0.0
    spin_x: float = 0.0
    scale: float = FRAGMENT_SCALE
    lifetime: int = FRAGMENT_LIFETIME_TICKS

    def step(self) -> None:
        """Advance one tick: move, apply gravity, spin, age."""
        self.x += self.vx
        self.y += self.vy
        self.z += self.vz
        self.vy += FRAGMENT_GRAVITY

        # Clamp to ground — fragments don't go below the terrain.
        if self.y < 0.0:
            self.y = 0.0
            self.vy = 0.0
            # Dampen horizontal velocity on ground contact so fragments
            # skid to a stop rather than sliding forever.
            self.vx *= 0.85
            self.vz *= 0.85

        self.heading += self.spin_y
        self.tumble += self.spin_x
        self.lifetime -= 1

    @property
    def alive(self) -> bool:
        return self.lifetime > 0
