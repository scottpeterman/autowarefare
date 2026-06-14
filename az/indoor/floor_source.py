"""
indoor/floor_source.py — the FloorSource seam (one contract, two drivers) and
its default ``ProceduralSource``.

Session 8's one-engine-two-drivers move: the indoor world turns
``(archetype, footprint, seed)`` into a stack of floors, and *where floors come
from* sits behind a seam. ``ProceduralSource`` (here) generates them on the
engine's own ``generate_dungeon``; ``MapFileSource`` (later, nearly free given
``level.py``) will load hand-authored ``.map`` set-pieces. Win/hint placement is
a decorator over whichever source produced the geometry — not baked into either
— and stays parked for step 4.

The §3 premise correction is honored: **nothing from Castle of Bane is vendored
here.** The engine generator is native (`innerworld_engine/generate.py`); this
adapter is the AW-specific gradient the engine generator stays innocent of —
footprint → breadth, archetype → depth + density — plus the one genuinely new
subsystem, inter-floor stair linking.

Determinism is the contract the persistent world needs: the same building seed
yields the same stack every dive, so a half-cleared tower never reshuffles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from az.innerworld_engine import (
    CELL_SIZE, CellType, generate_dungeon, reachable_cells,
)
from az.indoor.floor import FloorRuntime

Cell = tuple[int, int]
Footprint = tuple[float, float]

# Grid envelope clamp (cells). The outdoor footprints are small relative to
# CELL_SIZE, so most buildings floor to the minimum — the deliberate "bigger
# inside than out" tone call (session 8 open tension). Footprint still modulates
# breadth above the floor, which is the dimension the test pins.
MIN_GRID = 14
MAX_GRID = 40


@dataclass(frozen=True)
class _Archetype:
    floors: int           # depth — the dive's vertical character
    room_attempts: int    # density — how many rooms the generator tries


# Archetype → floor count + density. These are §7 balance dials, not law — the
# one table to tune the curve without touching the engine generator.
#   warehouse  — 1 wide, sparse floor (cover; a fast low-value check)
#   small      — 1 token floor
#   large      — 2 floors, quick clear
#   skyscraper — the deep dive, the highest reward odds
ARCHETYPES: dict[str, _Archetype] = {
    "warehouse":  _Archetype(floors=1, room_attempts=5),
    "small":      _Archetype(floors=1, room_attempts=4),
    "large":      _Archetype(floors=2, room_attempts=9),
    "skyscraper": _Archetype(floors=5, room_attempts=12),
}
_DEFAULT_ARCHETYPE = ARCHETYPES["large"]


def _spec(archetype: str) -> _Archetype:
    return ARCHETYPES.get(archetype, _DEFAULT_ARCHETYPE)


def _derive(seed: int, index: int) -> int:
    """Stable per-floor seed: deterministic and hash-randomization-proof (no
    str/tuple hashing). Same building seed + floor index -> same grid, every
    dive; different floors differ."""
    return (int(seed) * 2654435761 + index * 40503 + 0x9E3779B9) & 0xFFFFFFFF


def _envelope(footprint: Footprint) -> tuple[int, int]:
    """Footprint (outdoor half-extents) -> grid width/height in cells. Breadth."""
    hw, hd = footprint
    width = round(2.0 * hw / CELL_SIZE)
    height = round(2.0 * hd / CELL_SIZE)
    width = max(MIN_GRID, min(MAX_GRID, width))
    height = max(MIN_GRID, min(MAX_GRID, height))
    return width, height


@runtime_checkable
class FloorSource(Protocol):
    """One contract, two drivers. The two-method protocol is the public seam;
    how an adapter satisfies it (eager stack, lazy, file-backed) is private."""

    def floor_count(self, archetype: str, footprint: Footprint,
                    seed: int) -> int: ...

    def build_floor(self, archetype: str, footprint: Footprint,
                    seed: int, index: int) -> FloorRuntime: ...


class ProceduralSource:
    """Generates a deterministic, solvable floor stack from
    ``(archetype, footprint, seed)``.

    Stair alignment is cross-floor knowledge (a per-floor ``build_floor`` can't
    place a shared stairwell in isolation), so the adapter builds the **whole
    stack once**, deterministic from ``seed``, caches it, and serves
    ``build_floor(index)`` from the cache. The two-method protocol stays the
    public contract; the eager build is private business."""

    def __init__(self) -> None:
        self._cache: dict[tuple, list[FloorRuntime]] = {}

    # --- FloorSource -----------------------------------------------------

    def floor_count(self, archetype: str, footprint: Footprint,
                    seed: int) -> int:
        return _spec(archetype).floors

    def build_floor(self, archetype: str, footprint: Footprint,
                    seed: int, index: int) -> FloorRuntime:
        return self._stack(archetype, footprint, seed)[index]

    # --- the eager stack build (private) ---------------------------------

    def _stack(self, archetype: str, footprint: Footprint,
               seed: int) -> list[FloorRuntime]:
        key = (archetype, footprint, int(seed))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        spec = _spec(archetype)
        width, height = _envelope(footprint)
        n = spec.floors

        # Generate each floor's geometry (breadth + density from the gradient).
        grids = []
        roomsets = []
        for i in range(n):
            d, rooms = generate_dungeon(
                width, height, seed=_derive(seed, i),
                room_attempts=spec.room_attempts)
            grids.append(d)
            roomsets.append(rooms)

        # Inter-floor stair linking (the one net-new subsystem). A single shared
        # stairwell column, the same (gx, gz) on every floor, carved into each
        # floor's connected region. Because it is one cell coordinate shared up
        # the stack, the matching-landing contract (floor i's stair == floor
        # i+1's stair) holds by construction — there is nothing to reconcile.
        floors: list[FloorRuntime] = []
        column: Cell | None = None
        if n > 1:
            column = self._choose_column(grids, roomsets, seed)

        for i in range(n):
            d = grids[i]
            rooms = roomsets[i]
            stair_cell = None
            if column is not None:
                # Carve the column into this floor's connected region: join it
                # to the nearest room so the stairwell is never stranded, then
                # stamp the glyph (cosmetic — direction is read from the floor
                # index, not the glyph).
                self._carve_column(d, rooms, column)
                d.set_cell(*column, CellType.STAIRS_UP if i < n - 1
                           else CellType.STAIRS_DOWN)
                d.generate_walls()
                stair_cell = column

            if i == 0:
                start = self._entrance(rooms, column)
                floors.append(FloorRuntime(
                    dungeon=d, stair_cell=stair_cell,
                    start_cell=start, exit_cell=start))   # enter == leave (§6)
            else:
                # Upper floors: you arrive at the column.
                floors.append(FloorRuntime(
                    dungeon=d, stair_cell=stair_cell, start_cell=column))

        self._cache[key] = floors
        return floors

    # --- geometry helpers ------------------------------------------------

    @staticmethod
    def _entrance(rooms: list[Cell], column: Cell | None) -> Cell:
        """Floor-0 spawn / exit: the room centre farthest from the stairwell
        column (so you don't spawn on the stairs), deterministic. With no column
        (single-floor building) just the first room."""
        if column is None or len(rooms) == 1:
            return rooms[0]
        return max(rooms, key=lambda c: abs(c[0] - column[0])
                   + abs(c[1] - column[1]))

    @staticmethod
    def _choose_column(grids, roomsets, seed: int) -> Cell:
        """Pick the shared stairwell column deterministically: a room centre
        present on floor 0, biased toward the grid interior. It need not be
        walkable on the other floors yet — ``_carve_column`` joins it in."""
        rooms = roomsets[0]
        # the room nearest the grid centre reads as a natural stairwell hall
        w, h = grids[0].width, grids[0].height
        cx, cz = w // 2, h // 2
        return min(rooms, key=lambda c: abs(c[0] - cx) + abs(c[1] - cz))

    @staticmethod
    def _carve_column(dungeon, rooms: list[Cell], column: Cell) -> None:
        """Ensure ``column`` is walkable and reachable on this floor: set it
        FLOOR and corridor-connect it to the nearest room centre (which is in
        this floor's spanning chain), so the stairwell joins the connected
        region. Idempotent if the column already sits in a room."""
        dungeon.set_cell(*column, CellType.FLOOR)
        target = min(rooms, key=lambda c: abs(c[0] - column[0])
                     + abs(c[1] - column[1]))
        dungeon.carve_corridor(column[0], column[1], target[0], target[1])