"""
Free-floating wireframe object on the battlefield.

Covers the passive scenery: cubes, tetras, platforms, mountains, volcanos.
Tanks are NOT obstacles — they have their own AI/state and live in their
own type (to come in a later milestone).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def model_radius_2d(model: dict) -> float:
    """Compute (and cache) the 2D bounding-circle radius of a model.

    Walks all line endpoints, returns max sqrt(x² + z²) — the maximum
    horizontal distance from the model's local origin to any vertex.
    Y is ignored: collision happens on the ground plane.

    Cached on the dict under ``_bounding_radius_2d`` (underscore-prefixed
    to mark it as derived). Models are shared across instances (many
    obstacles point at the same dict), so this amortizes to one walk
    per model regardless of how many obstacles use it.

    The model's own intrinsic ``scale`` field is NOT applied here — it
    multiplies in at the per-instance level via ``Obstacle.bounding_radius``,
    same composition order as the renderer uses.

    Shared helper — Tank's bounding_radius uses this too. Bullets do
    NOT (they keep collision decoupled from visual scale).
    """
    cached = model.get('_bounding_radius_2d')
    if cached is not None:
        return cached

    r2_max = 0.0
    for (a, b) in model['lines']:
        for (x, _y, z) in (a, b):
            r2 = x * x + z * z
            if r2 > r2_max:
                r2_max = r2
    radius = math.sqrt(r2_max)
    model['_bounding_radius_2d'] = radius
    return radius


@dataclass
class Obstacle:
    """A static or near-static wireframe entity placed in world space.

    Attributes:
        model:    Wireframe model dict — the canonical
                  ``{'lines': [...], 'scale': float, 'bob_speed': float, 'bob_amount': float}``
                  shape produced by ``an8_to_wireframe.py``. Held by reference;
                  many obstacles share the same dict.
        x, z:     World-space position. +X right, +Z forward (away from the
                  default camera). Y is implied by the model's own geometry.
        heading:  Rotation about the Y axis, in radians. Applied at render
                  time via ``glRotatef``. 0 = model's authored facing.
        scale:    Per-instance scale multiplier. Composed with the model
                  dict's intrinsic ``scale`` field at render time.
        destructible: True for things that can be destroyed (none in v1 —
                  tanks are separate). Reserved for later (e.g. shootable
                  cube props if we ever want them).
    """

    model: dict
    x: float
    z: float
    heading: float = 0.0
    scale: float = 1.0
    destructible: bool = False

    @property
    def bounding_radius(self) -> float:
        """Effective 2D collision radius in world units.

        Composes (in the same order as the renderer):
          model_radius_2d * model['scale'] * obstacle.scale

        Bullets in milestone 5 will reuse this same field for hit
        detection — the abstraction is "every spatial entity has a
        2D bounding circle." Tanks (when they arrive) will publish
        their own ``bounding_radius`` so AI / projectile code can
        treat them uniformly with obstacles.
        """
        intrinsic = self.model.get('scale', 1.0)
        return model_radius_2d(self.model) * intrinsic * self.scale
