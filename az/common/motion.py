"""
common/motion.py — the shared heading->forward motion integrator.

The one piece of movement math both worlds agree on (POC design section 2).
It is a helper, not an engine: a heading and a speed in, a position out.

Heading convention (identical in both source engines, and spelled out in
Battlezone's render.py): heading is an angle about +Y, measured so that

    forward = (sin(heading), -cos(heading))

i.e. heading 0 faces -Z, heading +pi/2 faces +X (east), and positive heading
turns clockwise viewed from above. Angles here are **radians**. Castle of Bane
stores its camera angle in degrees internally; a world that does likewise
converts at its own boundary before calling in. Keeping this module
radian-only means there is exactly one source of truth for the convention and
no per-world drift.

No GL, no Qt, no per-world state — pure functions, trivially testable.
"""

from __future__ import annotations

import math


def forward_vector(heading: float) -> tuple[float, float]:
    """Unit forward (dx, dz) on the ground plane for ``heading`` in radians."""
    return (math.sin(heading), -math.cos(heading))


def right_vector(heading: float) -> tuple[float, float]:
    """Unit rightward (dx, dz) — forward rotated +90 deg about +Y. Useful for
    strafing; unused at M0 but part of the shared vocabulary."""
    return (math.cos(heading), math.sin(heading))


def advance(x: float, z: float, heading: float, distance: float
            ) -> tuple[float, float]:
    """Step from (x, z) by ``distance`` along ``heading``. Negative distance
    reverses. Returns the *desired* position; collision is the spatial
    query's job, not this function's (see common/spatial.py)."""
    dx, dz = forward_vector(heading)
    return (x + dx * distance, z + dz * distance)
