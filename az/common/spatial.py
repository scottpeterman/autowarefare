"""
common/spatial.py — the spatial-query interface (POC design section 4b).

The motion integrator is shared, but the *collision query* is welded to how
each world represents space: the outdoor world is continuous (circle-vs-circle
against obstacle radii, hard boundary clamp); the indoor world is a grid
(walkable cells, closed-door blocking). This Protocol hides that difference so
shared movement and AI code can ask "can I be here?" / "can A see B?" without
knowing which world answers.

A ``SpatialQuery`` is a structural contract, not a base class — outdoor/world.py
and indoor/world.py each implement it directly. ``can_move_to`` takes a
*desired* position and returns whether it was already free plus a *resolved*
position (pushed out of geometry and/or clamped to bounds), so a caller can
move in one call and let the world decide how to slide.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpatialQuery(Protocol):
    def can_move_to(self, x: float, z: float, radius: float
                    ) -> tuple[bool, float, float]:
        """Resolve a desired position against this world's geometry.

        Returns ``(was_free, resolved_x, resolved_z)``:
          - ``was_free`` is True if (x, z) needed no correction.
          - ``resolved_x/z`` is a legal position — the input when free, else
            pushed out of obstacles and/or clamped to the world boundary.
        Supports a slide-along feel: a glancing move keeps its tangential
        component instead of stopping dead.
        """
        ...

    def line_of_sight(self, ax: float, az: float,
                      bx: float, bz: float) -> bool:
        """True if nothing blocks the segment from (ax, az) to (bx, bz).
        Used by ranged-enemy AI (the gunman at Milestone 2); present now so
        the interface is complete and worlds implement it from the start."""
        ...
