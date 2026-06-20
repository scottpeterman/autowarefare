#!/usr/bin/env python3
"""
tools/bake_mobsters.py — freeze the design-time mobster bodies into the runtime.

The viewer renders the *generated* (numpy) humanoids live so they can be tuned.
The game must not import numpy, so once the bodies are signed off this baker runs
the generator one last time and writes static ``{'lines'}`` dicts into
``az/indoor/models/mobsters.py`` — the same "extract to a flat model file" move
that produced Bane's ``GHOST_MODEL``. After this, the runtime reads plain tuples.

It also performs the one coordinate reconciliation the integration owes: the
generator authors **+Y up, +Z forward** at a 48-unit head height; the indoor
world is **-Y up** (up is negative y, floor y=0) at human scale. So each vertex
is scaled to ``INDOOR_HEIGHT`` and its Y negated. +Z stays forward; the renderer
rotates per-enemy facing. This is the single documented place that flip happens.

    python -m az.tools.bake_mobsters        # rewrites az/indoor/models/mobsters.py
"""

from __future__ import annotations

import math
import os

from az.tools.humanoid import lines_from_params
from az.tools.mobsters import MOBSTERS, ORDER

# Head height in indoor world units (-Y-up). Player eye sits at y=-15, so a head
# near -28 reads as a person looming a little over eye line without being a giant.
INDOOR_HEIGHT = 28.0
SRC_HEIGHT = 48.0                       # the generator's authored head height


def _bake_one(name: str):
    """Return (lines, body_radius) in indoor space: feet at y=0, head at
    y=-INDOOR_HEIGHT (-Y up), +Z forward. body_radius is the torso XZ footprint
    (the weapon/forward arm excluded) for collision — a knife tip must not block."""
    raw = lines_from_params(MOBSTERS[name]["geom"], target_height=SRC_HEIGHT)
    s = INDOOR_HEIGHT / SRC_HEIGHT
    out = []
    torso_r2 = 0.0
    for a, b in raw:
        pa = (a[0] * s, -(a[1] * s), a[2] * s)     # scale + Y flip (+Y -> -Y up)
        pb = (b[0] * s, -(b[1] * s), b[2] * s)
        out.append((pa, pb))
        # torso footprint: ignore points reaching forward (the blade/gun/arm),
        # i.e. only count verts whose forward-z is within the body core.
        for p in (pa, pb):
            if abs(p[2]) < 0.18 * INDOOR_HEIGHT:
                torso_r2 = max(torso_r2, p[0] * p[0] + p[2] * p[2])
    return out, round(math.sqrt(torso_r2), 2)


def _fmt_lines(lines) -> str:
    rows = []
    for a, b in lines:
        rows.append(f"        (({a[0]:.3f}, {a[1]:.3f}, {a[2]:.3f}), "
                    f"({b[0]:.3f}, {b[1]:.3f}, {b[2]:.3f})),")
    return "\n".join(rows)


def _header() -> str:
    return (
        '"""\n'
        "indoor/models/mobsters.py — BAKED. Do not edit by hand.\n\n"
        "Static wireframe bodies for the indoor clone-mobsters, frozen from the\n"
        "design tool by ``python -m az.tools.bake_mobsters``. Plain {'lines'} dicts\n"
        "in the indoor coordinate convention — -Y up (head at negative y), feet at\n"
        f"y=0, +Z forward — at a {INDOOR_HEIGHT:.0f}-unit head height. No numpy at\n"
        "runtime: these are plain tuples. ``body_radius`` is the torso XZ footprint\n"
        "(weapon excluded) for grid collision. Re-bake after a body edit.\n"
        '"""\n\n'
        "MODELS = {\n"
    )


def main() -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = os.path.join(here, "indoor", "models", "mobsters.py")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    chunks = [_header()]
    for name in ORDER:
        lines, body_r = _bake_one(name)
        chunks.append(f'    "{name}": {{\n')
        chunks.append(f'        "body_radius": {body_r},\n')
        chunks.append('        "lines": [\n')
        chunks.append(_fmt_lines(lines) + "\n")
        chunks.append("        ],\n    },\n")
        print(f"baked {name:9s} {len(lines):4d} lines  body_radius={body_r}")
    chunks.append("}\n")

    with open(out_path, "w") as fh:
        fh.write("".join(chunks))
    print(f"-> wrote {out_path}")
    # ensure the package marker exists
    init_path = os.path.join(os.path.dirname(out_path), "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w") as fh:
            fh.write('"""Baked static models for the indoor world."""\n')
        print(f"-> wrote {init_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())