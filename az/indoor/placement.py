"""
indoor/placement.py — the win/hint placement decorator (session-8 step 4).

A pass over the *finished* floor stack that drops objectives onto floors. It is
deliberately separate from geometry (``generate.py`` / ``ProceduralSource``): it
reads only walkable cells and each floor's reserved landings (start / exit / the
two stair cells), so the §7 balance dials — how deep the plant sits, how early
the intel is reachable — live here, in one place, tunable without touching the
generator.

Two objectives:
  - the **plant** (the MicroNuke Power Plant, vision §2): the win object, placed
    only in the building that *holds* it, biased DEEP so the full climb is what
    earns it.
  - the **intel** (vision §4): an information pickup, placed in every dived
    building, biased EARLY so a shallow dive can still learn something and a
    blind search stays winnable.

Reachability is free: every floor is one connected component by construction
(the generator's spanning chain + loops), so any walkable non-reserved cell is
reachable from that floor's landing — no BFS here.

Determinism is the contract the persistent world needs: the same
``(seed, holds_plant)`` drops objectives on identical cells every dive, so a
half-searched tower never reshuffles its loot. The placement seed is derived
from the building seed with pure integer arithmetic (no str/tuple hashing) so it
is immune to ``PYTHONHASHSEED`` randomization — the same trick ``floor_source``
uses for its per-floor seeds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

Cell = tuple[int, int]


@dataclass
class Objective:
    """A placed interior objective. ``kind`` is ``"plant"`` | ``"intel"``;
    ``cell`` is its grid cell on its floor; ``collected`` flips on walk-over
    pickup and the renderer stops drawing it."""
    kind: str
    cell: Cell
    collected: bool = False


def _place_seed(seed: int) -> int:
    """Stable placement seed from the building seed — pure int, hash-randomization
    proof, distinct from the per-floor geometry seeds so loot and layout don't
    correlate."""
    return (int(seed) * 2654435761 + 0x517CC1B7) & 0xFFFFFFFF


def _reserved(fr) -> set[Cell]:
    """Cells an objective must not land on: the floor's landings and both stair
    cells, so a pickup is never stranded on the door or sitting on the stairs."""
    return {fr.up_cell, fr.down_cell, fr.start_cell, fr.exit_cell} - {None}


def _pick(floors, *, deep: bool, rng: random.Random) -> tuple[int, Cell]:
    """Choose ``(floor_index, cell)`` for one objective. The floor is chosen with
    a linear depth bias — toward the top of the stack when ``deep`` (the plant),
    toward the bottom otherwise (the intel) — and the cell is any walkable
    non-reserved cell on that floor (reachable by construction). The linear
    weights are the §7 dial: steepen them to push the plant deeper or pull the
    intel shallower once the ratchet consumes the payload and there are several
    buildings to tune against."""
    n = len(floors)
    weights = [(i + 1) if deep else (n - i) for i in range(n)]
    f = rng.choices(range(n), weights=weights, k=1)[0]
    fr = floors[f]
    d = fr.dungeon
    reserved = _reserved(fr)
    cells = [(x, z) for z in range(d.height) for x in range(d.width)
             if d.is_walkable(x, z) and (x, z) not in reserved]
    # Degenerate guard: a floor with no free cell (never seen on the broad
    # generated plates) falls back to its start landing so placement can't crash.
    cell = rng.choice(cells) if cells else fr.start_cell
    return f, cell


def place_objectives(floors, *, holds_plant: bool, seed: int) -> None:
    """Decorate ``floors`` in place with objectives. The plant lands only when
    this building ``holds_plant`` (a game-level fact carried across the enter
    seam), biased deep; the intel lands in every dived building, biased early.
    Deterministic from ``seed``. A no-op on an empty stack."""
    if not floors:
        return
    rng = random.Random(_place_seed(seed))
    if holds_plant:
        f, cell = _pick(floors, deep=True, rng=rng)
        floors[f].entities.append(Objective(kind="plant", cell=cell))
    f, cell = _pick(floors, deep=False, rng=rng)
    floors[f].entities.append(Objective(kind="intel", cell=cell))