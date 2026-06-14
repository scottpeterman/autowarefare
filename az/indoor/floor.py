"""
indoor/floor.py — one level of a building, as the indoor world consumes it.

Question 1 of session 8: *a building is a stack of floors; a floor is a
``DungeonMap``*, and moving between floors is internal to ``IndoorWorld`` — it
is NOT a portal transition. ``FloorRuntime`` is what the stack is made of: the
``DungeonMap`` for the floor, its lazily-built ``BSPTree`` (draw order, cached on
first visit), the **stairwell column** cell, the floor's **start** landing, and —
for floor 0 only — the building **exit** cell. Entities are reserved for step 4
(the plant / intel placement) and ride along here so the slot is stable now.

The stairwell is a **single shared column**: the same ``(gx, gz)`` cell is
walkable on every floor of the stack, carved STAIRS on each. That choice is what
makes the prompt-gated swap (press E, then push the way you want to go) cheap:
the player always arrives at the same column on the floor they move to, so the
"matching landing" contract from the design (floor i's up-stair == floor i+1's
down-stair) is satisfied *by construction* — there is nothing to reconcile,
because it is literally one cell coordinate shared up the whole tower. Which
directions are offered is read from the floor's position in the stack, not from
the cell's glyph, so a mid-floor offers both and an endpoint offers one.

Pure data + a lazy BSP cache. No GL, no Qt, no shell coupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from az.innerworld_engine import (
    BSPTree, CellType, DungeonMap, build_bsp_from_dungeon,
)

Cell = tuple[int, int]


@dataclass
class FloorRuntime:
    """One level of a building: the (DungeonMap, lazy BSPTree) pair plus the
    landings the indoor world repositions the camera against."""

    dungeon: DungeonMap
    stair_cell: Cell | None = None     # the shared stairwell column on this floor
    start_cell: Cell | None = None     # spawn / arrival landing for this floor
    exit_cell: Cell | None = None      # building exit — floor 0 only
    entities: list[Any] = field(default_factory=list)   # reserved for step 4

    _bsp: BSPTree | None = field(default=None, repr=False)

    def bsp(self) -> BSPTree:
        """The floor's BSP tree, built on first visit and cached. Grids are
        cheap to build eagerly (the source stamps them all up front); the BSP
        stays lazy so an undived upper floor never pays for a tree it never
        draws."""
        if self._bsp is None:
            self._bsp = build_bsp_from_dungeon(self.dungeon)
        return self._bsp


def find_stair_cell(dungeon: DungeonMap) -> Cell | None:
    """Scan a grid for its stairwell cell (STAIRS_UP or STAIRS_DOWN). The
    shared-column design stamps exactly one per floor, so the first match is the
    column. Used by sources that stamp stairs into geometry and want the runtime
    to discover the landing rather than be told it twice."""
    for gz in range(dungeon.height):
        for gx in range(dungeon.width):
            if dungeon.get_cell(gx, gz) in (CellType.STAIRS_UP,
                                            CellType.STAIRS_DOWN):
                return (gx, gz)
    return None