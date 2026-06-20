"""
indoor/floor.py — one level of a building, as the indoor world consumes it.

Question 1 of session 8: *a building is a stack of floors; a floor is a
``DungeonMap``*, and moving between floors is internal to ``IndoorWorld`` — it
is NOT a portal transition. ``FloorRuntime`` is what the stack is made of: the
``DungeonMap`` for the floor, its lazily-built ``BSPTree`` (draw order, cached on
first visit), the **stairwell column** cell, the floor's **start** landing, and —
for floor 0 only — the building **exit** cell. Entities are reserved for step 4
(the plant / intel placement) and ride along here so the slot is stable now.

The stairwell is **per-link, not one global column**: between floor i and
floor i+1 there is a single shared landing cell C_i, carved walkable on *both*
floors. Floor i's ``up_cell`` and floor i+1's ``down_cell`` are that same
coordinate, so the "matching landing" contract (floor i's up-stair == floor
i+1's down-stair) still holds *by construction* — there is simply nothing to
reconcile, per link. A middle floor therefore carries two stairs at (usually)
different cells: a ``down_cell`` where you arrived from below, and an ``up_cell``
you have to cross the floor to reach. Consecutive links can be clustered to
share a core (the ``STAIR_RUN`` dial in ``floor_source``), so a tall tower reads
as a few distinct stair cores rather than one chimney; set the run >= the floor
count and it collapses back to a single shared column. Floor 0 has no
``down_cell``; the roof has no ``up_cell``. Which key is offered is read from
which stair cell the player stands on, not from the cell's glyph.

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
    up_cell: Cell | None = None        # this floor's up-stair (None on the roof)
    down_cell: Cell | None = None      # this floor's down-stair (None on floor 0)
    start_cell: Cell | None = None     # spawn / arrival landing for this floor
    exit_cell: Cell | None = None      # building exit — floor 0 only
    entities: list[Any] = field(default_factory=list)   # objectives (plant/intel)
    enemies: list[Any] = field(default_factory=list)     # live Mobs on this floor

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