"""
innerworld_engine/generate.py — a seeded, solvable rooms-and-corridors
generator on the engine's own carve primitives.

This is `create_test_dungeon` parameterized and seeded — nothing more exotic. It
lives at engine level (the same tier as `create_test_dungeon`) because it is
generic: "a solvable ``DungeonMap``, W×H, from seed S." It knows nothing about
floors, archetypes, stairs, or Auto Warfare — those live one layer up in the
``ProceduralSource`` adapter.

The lesson taken from Castle of Bane is **solvability**, but achieved
*structurally* rather than by Bane's generate-then-BFS-reject loop: rooms are
placed, then connected in placement order so the carved space is one spanning
chain — walkable end-to-end **by construction**. There is no rejection retry and
no BFS at generation time. BFS becomes a *test-time assertion* (see
``reachable_cells``), proving the property the construction already guarantees.

Variety rides *on top of* that guarantee without endangering it. Two of Bane's
moves were dropped in the first native port and are restored here: (1) the
spanning chain is followed by a few **redundant loop links** so a floor reads as
an interconnected space rather than a linear thread of rooms — purely additive
edges over an already-connected graph, so connectivity can only grow, never
break; and (2) corridors carve with a **coin-flipped elbow** (horizontal-first
vs vertical-first) so every bend isn't identical. Room-size spread (``min_room``
/ ``max_room``) is the caller's dial — a wide spread mixes grand halls with
closets, the landmark rooms a floor is navigated *by*.

Deviation from the session-8 primer's pseudocode: it sketched
``generate_dungeon(...) -> DungeonMap``. We return ``(DungeonMap, rooms)`` — the
placed room centres are genuinely useful one layer up (spawn/exit/stairwell
placement want a room, not a random corridor cell), and recomputing them from
the finished grid is lossy. The map stays the generic artifact; the room list
rides alongside it.
"""

from __future__ import annotations

import random
from collections import deque

from .dungeon import CellType, DungeonMap

Cell = tuple[int, int]


def _rects_overlap(a, b, gap: int = 1) -> bool:
    """True if rectangles ``a``/``b`` (x1,z1,x2,z2 inclusive) touch within
    ``gap`` cells — used to keep placed rooms visibly distinct."""
    ax1, az1, ax2, az2 = a
    bx1, bz1, bx2, bz2 = b
    return not (ax2 + gap < bx1 or bx2 + gap < ax1 or
                az2 + gap < bz1 or bz2 + gap < az1)


def _carve_corridor(d: DungeonMap, x1: int, z1: int, x2: int, z2: int,
                    rng: random.Random) -> None:
    """L-corridor between two cells with a **coin-flipped elbow** — horizontal
    leg first half the time, vertical first the other half. The engine's own
    ``DungeonMap.carve_corridor`` is a fixed horizontal-then-vertical bend, so
    every elbow it draws looks the same; this local variant restores Bane's
    randomized bend so corridors don't all turn the same corner. Both legs carve
    FLOOR, so the corridor joins the connected region exactly as the fixed
    primitive would — only the bend direction differs."""
    if rng.random() < 0.5:
        for gx in range(min(x1, x2), max(x1, x2) + 1):
            d.set_cell(gx, z1, CellType.FLOOR)
        for gz in range(min(z1, z2), max(z1, z2) + 1):
            d.set_cell(x2, gz, CellType.FLOOR)
    else:
        for gz in range(min(z1, z2), max(z1, z2) + 1):
            d.set_cell(x1, gz, CellType.FLOOR)
        for gx in range(min(x1, x2), max(x1, x2) + 1):
            d.set_cell(gx, z2, CellType.FLOOR)


def generate_dungeon(width: int, height: int, *, seed: int,
                     room_attempts: int = 12,
                     min_room: int = 3,
                     max_room: int = 6) -> tuple[DungeonMap, list[Cell]]:
    """Carve a solvable rooms-and-corridors ``DungeonMap`` deterministically
    from ``seed``. Returns the map and the list of room centres in placement
    order. Solvable by construction: every placed room is joined to the spanning
    corridor chain, so the walkable space is one connected component."""
    rng = random.Random(seed)
    d = DungeonMap(width=width, height=height)

    rooms: list[Cell] = []
    rects: list[tuple[int, int, int, int]] = []
    for _ in range(room_attempts):
        rw = rng.randint(min_room, max_room)
        rh = rng.randint(min_room, max_room)
        if width - rw - 1 < 1 or height - rh - 1 < 1:
            continue
        x1 = rng.randint(1, width - rw - 1)
        z1 = rng.randint(1, height - rh - 1)
        x2, z2 = x1 + rw, z1 + rh
        rect = (x1, z1, x2, z2)
        if any(_rects_overlap(rect, r) for r in rects):
            continue
        d.carve_room(x1, z1, x2, z2)
        rects.append(rect)
        rooms.append(((x1 + x2) // 2, (z1 + z2) // 2))

    # Degenerate guard: a grid too small/unlucky to place any room still gets
    # one central room so the floor is never empty.
    if not rooms:
        cx, cz = width // 2, height // 2
        d.carve_room(max(1, cx - 1), max(1, cz - 1),
                     min(width - 2, cx + 1), min(height - 2, cz + 1))
        rooms.append((cx, cz))

    # Connect in placement order -> a spanning chain. This is the solvability
    # guarantee: every placed room is joined to the chain, so the union of rooms
    # + corridors is one walkable component.
    for a, b in zip(rooms, rooms[1:]):
        _carve_corridor(d, a[0], a[1], b[0], b[1], rng)

    # Loops: a few redundant links between random room pairs so the floor reads
    # as an interconnected space, not a linear thread. Strictly additive over
    # the spanning chain above — extra edges can only enrich connectivity, never
    # sever it, so solvability-by-construction is untouched. Guarded on >=2
    # rooms (the degenerate single-room floor has nothing to loop).
    if len(rooms) >= 2:
        for _ in range(rng.randint(1, 2)):
            a, b = rng.sample(rooms, 2)
            _carve_corridor(d, a[0], a[1], b[0], b[1], rng)

    d.generate_walls()
    return d, rooms


def reachable_cells(dungeon: DungeonMap, start: Cell) -> set[Cell]:
    """4-connected flood fill over walkable cells from ``start``. Engine-level
    and generic: the adapter uses it to verify a carved stairwell joined the
    connected region; tests use it to assert solvability."""
    seen: set[Cell] = set()
    if not dungeon.is_walkable(*start):
        return seen
    q: deque[Cell] = deque([start])
    seen.add(start)
    while q:
        gx, gz = q.popleft()
        for nx, nz in ((gx + 1, gz), (gx - 1, gz), (gx, gz + 1), (gx, gz - 1)):
            if (nx, nz) not in seen and dungeon.is_walkable(nx, nz):
                seen.add((nx, nz))
                q.append((nx, nz))
    return seen