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

# Grid envelope: footprint (outdoor half-extents) sets the *requested* breadth;
# the per-archetype ``min_grid`` is the floor it clamps up to, and ``MAX_GRID``
# the ceiling. The outdoor footprints are small relative to CELL_SIZE, so most
# buildings still floor to their archetype minimum — the deliberate "bigger
# inside than out" tone call (session 8 open tension). What changed: the floor
# is no longer one global 14 for everything. A skyscraper floors *broad* (a real
# tower plate) while a closet stays tight, so depth and breadth both read off the
# archetype instead of every building sharing one 14x14 plate.
MAX_GRID = 40


@dataclass(frozen=True)
class _Archetype:
    floors: int           # depth — the dive's vertical character
    room_attempts: int    # density — how many rooms the generator tries
    min_room: int         # room-size spread floor (cells) — the closet
    max_room: int         # room-size spread ceiling (cells) — the grand hall
    min_grid: int         # breadth floor — the per-archetype envelope clamp


# Archetype → floor count + density + room-size spread + breadth. These are §7
# balance dials, not law — the one table to tune the curve without touching the
# engine generator. Each row now carries a *texture*, not just a height:
#   warehouse  — 1 broad, sparse floor of big open rooms (cover; fast low check)
#   small      — 1 tight token floor, small rooms
#   large      — 2 mid floors, moderate spread
#   skyscraper — the deep dive: 5 broad floors, widest room spread (halls next
#                to closets), highest reward odds — the tower worth climbing
ARCHETYPES: dict[str, _Archetype] = {
    "warehouse":  _Archetype(floors=1, room_attempts=10, min_room=4, max_room=8, min_grid=22),
    "small":      _Archetype(floors=1, room_attempts=4,  min_room=3, max_room=6, min_grid=14),
    "large":      _Archetype(floors=2, room_attempts=9,  min_room=4, max_room=7, min_grid=18),
    "skyscraper": _Archetype(floors=5, room_attempts=14, min_room=3, max_room=8, min_grid=26),
}
_DEFAULT_ARCHETYPE = ARCHETYPES["large"]

# Stairwell run length (§7 dial): how many consecutive inter-floor links share a
# single stair core before a new core is placed elsewhere on the plate. run=2
# reads as "floors 0-1-2 climb one core, then you cross the floor to a second
# core for 2-3-4." A run >= the floor count collapses to one shared column up
# the whole tower (the pre-segmentation behavior). Buildings with <=2 floors
# have at most one link, so this never affects them — it is the skyscraper dial.
STAIR_RUN = 2


def _spec(archetype: str) -> _Archetype:
    return ARCHETYPES.get(archetype, _DEFAULT_ARCHETYPE)


def _derive(seed: int, index: int) -> int:
    """Stable per-floor seed: deterministic and hash-randomization-proof (no
    str/tuple hashing). Same building seed + floor index -> same grid, every
    dive; different floors differ."""
    return (int(seed) * 2654435761 + index * 40503 + 0x9E3779B9) & 0xFFFFFFFF


def _envelope(footprint: Footprint, min_grid: int) -> tuple[int, int]:
    """Footprint (outdoor half-extents) -> grid width/height in cells. Breadth.
    Clamps up to the archetype's ``min_grid`` floor and down to ``MAX_GRID``."""
    hw, hd = footprint
    width = round(2.0 * hw / CELL_SIZE)
    height = round(2.0 * hd / CELL_SIZE)
    width = max(min_grid, min(MAX_GRID, width))
    height = max(min_grid, min(MAX_GRID, height))
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
        width, height = _envelope(footprint, spec.min_grid)
        n = spec.floors

        # Generate each floor's geometry (breadth + density from the gradient).
        grids = []
        roomsets = []
        for i in range(n):
            d, rooms = generate_dungeon(
                width, height, seed=_derive(seed, i),
                room_attempts=spec.room_attempts,
                min_room=spec.min_room, max_room=spec.max_room)
            grids.append(d)
            roomsets.append(rooms)

        # Inter-floor stair linking (the one net-new subsystem). Stairs are
        # per-link shared cells: between floor i and i+1 there is one landing
        # cell C_i, carved walkable on BOTH floors, so floor i's up-stair and
        # floor i+1's down-stair are the same coordinate — the matching-landing
        # contract holds per link by construction, nothing to reconcile. Links
        # cluster into cores (STAIR_RUN) dispersed across the plate, so a tall
        # tower makes you cross a floor to find the next core rather than ride
        # one chimney.
        floors: list[FloorRuntime] = []
        link_cells = self._choose_cores(grids, roomsets, n, STAIR_RUN)  # len n-1

        for i in range(n):
            d = grids[i]
            rooms = roomsets[i]
            up_cell = link_cells[i] if i < n - 1 else None      # climb from here
            down_cell = link_cells[i - 1] if i > 0 else None    # arrived here

            # Carve each present stair cell into this floor's connected region
            # and stamp its glyph (cosmetic — the runtime reads up_cell/down_cell,
            # not the glyph). A within-run middle floor has up_cell == down_cell
            # (a chimney point): carving twice is harmless, and the single cell
            # is left stamped UP.
            for cell in (down_cell, up_cell):
                if cell is not None:
                    self._carve_column(d, rooms, cell)
            if down_cell is not None and down_cell != up_cell:
                d.set_cell(*down_cell, CellType.STAIRS_DOWN)
            if up_cell is not None:
                d.set_cell(*up_cell, CellType.STAIRS_UP)
            if up_cell is not None or down_cell is not None:
                d.generate_walls()

            if i == 0:
                start = self._entrance(rooms, up_cell)
                floors.append(FloorRuntime(
                    dungeon=d, up_cell=up_cell, down_cell=down_cell,
                    start_cell=start, exit_cell=start))   # enter == leave (§6)
            else:
                # Upper floors default to landing on the down-stair (where you
                # arrive climbing up); a descending arrival repositions onto the
                # up-stair in IndoorWorld._change_floor.
                floors.append(FloorRuntime(
                    dungeon=d, up_cell=up_cell, down_cell=down_cell,
                    start_cell=down_cell))

        self._cache[key] = floors
        return floors

    # --- geometry helpers ------------------------------------------------

    @staticmethod
    def _entrance(rooms: list[Cell], up_cell: Cell | None) -> Cell:
        """Floor-0 spawn / exit: the room centre farthest from the up-stair (so
        you don't spawn on the stairs), deterministic. With no up-stair (a
        single-floor building) just the first room."""
        if up_cell is None or len(rooms) == 1:
            return rooms[0]
        return max(rooms, key=lambda c: abs(c[0] - up_cell[0])
                   + abs(c[1] - up_cell[1]))

    @staticmethod
    def _choose_cores(grids, roomsets, n: int, run: int) -> list[Cell]:
        """Per-link landing cells (length ``n-1``). Links group into cores of
        ``run`` consecutive links sharing one cell; cores are dispersed across
        the plate so a multi-core tower makes you cross the floor to reach the
        next stairwell. Deterministic — pure geometry over the seeded room list,
        no rng.

        Candidate pool is floor 0's room centres: stable, and spread across the
        (now broad) plate. ``_carve_column`` joins whatever is picked into every
        floor, so a pick need not already be walkable above floor 0."""
        if n < 2:
            return []
        num_links = n - 1
        num_cores = (num_links + run - 1) // run            # ceil
        w, h = grids[0].width, grids[0].height
        cx, cz = w // 2, h // 2
        pool: list[Cell] = list(roomsets[0]) or [(cx, cz)]

        cores: list[Cell] = []
        for _ in range(num_cores):
            if not cores:
                # first core nearest the grid centre — the building's main core
                pick = min(pool, key=lambda p: abs(p[0] - cx) + abs(p[1] - cz))
            else:
                # disperse: maximize distance to the nearest core already chosen
                pick = max(pool, key=lambda p: min(
                    abs(p[0] - q[0]) + abs(p[1] - q[1]) for q in cores))
            cores.append(pick)
        return [cores[i // run] for i in range(num_links)]

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