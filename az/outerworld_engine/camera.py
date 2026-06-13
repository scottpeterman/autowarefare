"""
First-person tank camera.

Battlezone-style: 2D motion in the XZ plane, rotation about Y only.
No pitch, no roll. Eye height is fixed.

Coordinate convention (right-handed, OpenGL default):
  +X right, +Y up, +Z toward the camera.
  ``heading = 0``  → looking down -Z (the conventional "into the screen").
  ``heading = π/2`` → looking down +X (right turn from the spawn facing).
  Positive heading = camera right turn (clockwise when viewed from
  above, looking down +Y). This is because ``apply_camera`` issues
  ``glRotatef(degrees(heading), 0, 1, 0)`` on the modelview, rotating
  the *world* CCW about +Y — which is equivalent to rotating the
  *camera* CW.

Note: the Battlezone JS source has the player spawn "facing 180°" in
``z_game.js``. That's a JS/canvas convention with Y-down — when we wire
up scene composition we'll set ``heading = 0`` (looking down -Z) as the
spawn default and adjust if anything looks backward on first render.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Camera:
    """Tank-driver eye position + heading.

    Attributes:
        x, z:        World-space position in the XZ plane.
        heading:     Rotation about +Y, in radians.
        eye_height:  Y offset from ground plane (camera Y in world space).
                     Loosely tuned for Battlezone's "sitting in a tank"
                     framing — taller than a person, shorter than a
                     standing observer.
    """

    x: float = 0.0
    z: float = 0.0
    heading: float = 0.0
    eye_height: float = 12.0

    @property
    def forward(self) -> tuple[float, float]:
        """Unit forward vector in world XZ.

        At ``heading = 0`` this is ``(0, -1)``: looking down -Z.
        """
        return (math.sin(self.heading), -math.cos(self.heading))

    @property
    def right(self) -> tuple[float, float]:
        """Unit right vector in world XZ.

        At ``heading = 0`` this is ``(1, 0)``: +X.
        """
        return (math.cos(self.heading), math.sin(self.heading))

    def move_forward(self, distance: float) -> None:
        fx, fz = self.forward
        self.x += fx * distance
        self.z += fz * distance

    def move_right(self, distance: float) -> None:
        """Strafe — not used by Battlezone tanks (no strafe in the original),
        but cheap to keep around for debug fly-through."""
        rx, rz = self.right
        self.x += rx * distance
        self.z += rz * distance

    def turn(self, radians: float) -> None:
        """Rotate the camera by ``radians`` about Y.

        Positive value = clockwise as seen from above (right turn in our
        convention — see module docstring for why). The tank input layer
        in ``bz/game.py`` maps Key_D / Key_Right to positive turns and
        Key_A / Key_Left to negative.
        """
        self.heading = (self.heading + radians) % (2.0 * math.pi)