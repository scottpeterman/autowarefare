"""
indoor/enemy_placement.py — the enemy spawn decorator (M2.2).

The combat sibling of ``placement.py``: a pass over the *finished* floor stack
that drops live ``Mob``s onto floors, reading only walkable cells and each
floor's reserved landings — never touching the generator. Same three contracts
``place_objectives`` honours:

  - **Deterministic** from ``(seed, tier)`` via pure-int seeding (hash-randomi-
    zation proof), so a half-fought tower spawns the same roster every dive and a
    re-dive doesn't reshuffle who's where.
  - **Legal & reachable**: walkable, non-reserved cells; reachable by construc-
    tion (one connected component), so no BFS. On the ground floor a spawn-clear
    radius keeps the door breathable — you don't walk into a knife.
  - **Tier-scaled**: the population grows with the dive depth (deeper floors are
    busier) and with the player's escalation ``tier``, so the interior threat
    rises on the same ledger the outdoor war does (vision §6). Plateaued by a
    per-floor cap so a deep tower gets *meaner per mob* (the roster mix), not
    unboundedly crowded.

Roster is ``LIVE_ROSTER`` (thug + knifeman + the now-wired gunman), melee-
weighted so the gunman stays a minority threat. A no-op on an empty stack, and — like objectives —
only the archetype (procedural) branch calls it, so the default test stack stays
enemy-free and the M2.0 / floor-stack pins keep their exact geometry.
"""

from __future__ import annotations

import random

from az.indoor.enemies import LIVE_ROSTER
from az.indoor.mob import Mob

Cell = tuple[int, int]

BASE_PER_FLOOR = 2        # ground-floor baseline (before depth/tier growth)
MAX_PER_FLOOR = 6         # the plateau: a deep floor gets nastier, not denser
SPAWN_CLEAR = 3           # min cell distance from the floor-0 door to a spawn
REINFORCE_CAP = MAX_PER_FLOOR + 1   # per-floor live ceiling for runtime reinforcements
RUNTIME_SPAWN_CLEAR = 4   # min cell distance from the player to a reinforcement


def _enemy_seed(seed: int) -> int:
    """Stable spawn seed from the building seed — pure int, distinct from the
    geometry and objective seeds so threat, layout, and loot don't correlate."""
    return (int(seed) * 40503 + 0x9E3779B1) & 0xFFFFFFFF


def _reserved(fr) -> set[Cell]:
    return {fr.up_cell, fr.down_cell, fr.start_cell, fr.exit_cell} - {None}


def _count(floor_index: int, tier: int) -> int:
    """Population for a floor: baseline + one per floor of depth + one per two
    escalation tiers, capped at the plateau. The ground floor is one lighter so
    the entrance isn't a brawl."""
    n = BASE_PER_FLOOR + floor_index + (tier // 2)
    if floor_index == 0:
        n -= 1
    return max(0, min(MAX_PER_FLOOR, n))


def legal_cells(fr, *, clear_from=None, clear_radius=0) -> list[Cell]:
    """Walkable, non-reserved cells on a floor — optionally excluding a Manhattan
    radius around ``clear_from`` (the player, for runtime spawns; the door, at
    placement). Falls back to the full set if the clear filter empties it, so a
    tiny plate never strands a spawn."""
    d = fr.dungeon
    reserved = _reserved(fr)
    cells = [(x, z) for z in range(d.height) for x in range(d.width)
             if d.is_walkable(x, z) and (x, z) not in reserved]
    if clear_from is not None and clear_radius > 0:
        cx, cz = clear_from
        kept = [c for c in cells
                if abs(c[0] - cx) + abs(c[1] - cz) >= clear_radius]
        cells = kept or cells
    return cells


def spawn_mob(fr, cell: Cell, ddef, rng) -> Mob:
    """Create one live Mob at a floor cell and attach it to that floor."""
    wx, wz = fr.dungeon.grid_to_world(*cell)
    mob = Mob(def_=ddef, x=wx, z=wz, cell=cell, facing_deg=rng.uniform(0.0, 360.0))
    fr.enemies.append(mob)
    return mob


def place_enemies(floors, *, seed: int, tier: int = 0,
                  roster=LIVE_ROSTER) -> None:
    """Decorate ``floors`` in place with live ``Mob``s. Deterministic from
    ``(seed, tier)``. A no-op on an empty stack or an empty roster."""
    if not floors or not roster:
        return
    rng = random.Random(_enemy_seed(seed))
    for f, fr in enumerate(floors):
        clear_from = fr.start_cell if f == 0 else None
        cells = legal_cells(fr, clear_from=clear_from,
                            clear_radius=SPAWN_CLEAR if f == 0 else 0)
        n = min(_count(f, tier), len(cells))
        for cell in rng.sample(cells, n) if n > 0 else []:
            spawn_mob(fr, cell, rng.choice(roster), rng)