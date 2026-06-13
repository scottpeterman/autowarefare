"""
Horizon descriptor.

Per the transition doc's "Decisions still to make" #6, we're going with
option (a): render the horizon as a 2D line in the QPainter HUD overlay
at ``viewport_height / 2`` (modulated only by an optional tilt). The
original Battlezone camera doesn't pitch, so this is sufficient and
keeps the GL renderer free of a giant ground-plane quad.

Stub. To be filled when the HUD layer goes in (milestone 3, after
the camera and basic obstacle rendering work).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Horizon:
    """Visual horizon line — pure HUD descriptor, no 3D geometry.

    Attributes:
        y_offset:   Pixel offset from viewport vertical center. Negative
                    pushes horizon up, positive down. Default 0 = centered.
        thickness:  Line thickness in pixels.
    """

    y_offset: int = 0
    thickness: int = 1
