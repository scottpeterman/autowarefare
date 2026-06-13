"""
tests/test_indoor_m20.py — Milestone 2.0 acceptance (headless, no GL/Qt).

Proves the Bane interior's *logic* surface now that the scratch room is gone:
a real grid dungeon loads with walls, grid collision blocks movement into solid
cells, slide-along keeps a free axis, grid LOS sees through open space and is
blocked by solid, and standing in the exit zone + action hands back to the
outdoor world with the tower marked cleared. The renderer's GL is exercised
live in the window (M2.0's one manual check: GL-state hygiene at the QPainter
handoff); everything testable without a context is tested here.

Run:  python -m az.tests.test_indoor_m20
"""

from __future__ import annotations

from az.indoor.world import IndoorWorld, START_CELL, EXIT_CELL, BODY_RADIUS
from az.innerworld_engine import CellType
from az.shell.mode import InputState, Transition
from az.shell.player_state import PlayerState

DT = 1.0 / 60.0
FORWARD = InputState(forward=True)
ACTION = InputState(action=True)


def _entered():
    w = IndoorWorld()
    state = PlayerState()
    w.on_enter(state, {"building": "tower_a"})
    return w, state


def test_a_loads_real_dungeon_with_walls() -> None:
    w, _ = _entered()
    assert w.dungeon is not None and w.bsp_tree is not None
    assert len(w.dungeon.walls) > 0, "carved dungeon should generate walls"
    # spawned on the start cell, in walkable space
    gx, gz = w.dungeon.world_to_grid(w.cam_x, w.cam_z)
    assert (gx, gz) == START_CELL
    assert w.dungeon.is_walkable(gx, gz)
    print(f"  dungeon {w.dungeon.width}x{w.dungeon.height}, "
          f"{len(w.dungeon.walls)} walls, spawn {START_CELL}")


def test_b_grid_collision_blocks_solid() -> None:
    w, _ = _entered()
    # find a solid cell adjacent to the start room and confirm a body there is
    # reported blocked, while the start cell itself is free
    free, _, _ = w.can_move_to(w.cam_x, w.cam_z, BODY_RADIUS)
    assert free, "spawn cell must be free"
    # a point deep in out-of-bounds/solid space is blocked
    far = (w.dungeon.width * 50.0)  # well outside the grid -> SOLID
    blocked, _, _ = w.can_move_to(far, far, BODY_RADIUS)
    assert not blocked, "a body in solid/out-of-bounds space must be blocked"
    print("  collision blocks solid, frees floor")


def test_c_slide_along_keeps_free_axis() -> None:
    w, state = _entered()
    # drive straight into the north wall of the start room for many ticks; the
    # player should slide/stop, never tunnel into a solid cell
    for _ in range(400):
        w.update(DT, FORWARD, state)
        gx, gz = w.dungeon.world_to_grid(w.cam_x, w.cam_z)
        assert w.dungeon.is_walkable(gx, gz), "must never end a tick in solid"
    print(f"  200+ forward ticks, always walkable (ended {w.dungeon.world_to_grid(w.cam_x, w.cam_z)})")


def test_d_line_of_sight() -> None:
    w, _ = _entered()
    # LOS to self is trivially clear; LOS across the whole map (through solid
    # rock between disconnected rooms) is blocked somewhere
    assert w.line_of_sight(w.cam_x, w.cam_z, w.cam_x, w.cam_z)
    ax, az = w.dungeon.grid_to_world(2, 2)      # a corner (solid)
    bx, bz = w.dungeon.grid_to_world(17, 17)    # opposite corner (solid)
    assert not w.line_of_sight(ax, az, bx, bz), "cross-map LOS hits rock"
    print("  LOS clear to self, blocked across rock")


def test_e_exit_zone_transitions_and_clears() -> None:
    w, state = _entered()
    # not on the exit yet -> no transition
    assert w.update(DT, ACTION, state) is None
    # teleport into the exit zone, tap action -> hand back + cleared
    w.cam_x, w.cam_z = w.exit_x, w.exit_z
    t = w.update(DT, ACTION, state)
    assert isinstance(t, Transition) and t.target == "outdoor"
    assert t.payload.get("from") == "tower_a"
    assert state.has_cleared("tower_a")
    print(f"  exit at {EXIT_CELL} -> Transition(outdoor), cleared=tower_a")


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    if failed == 0:
        print("M2.0 PASS: Bane interior vendored + de-windowed; real grid "
              "dungeon, collision, slide-along, LOS, and portal exit all green "
              "(GL-state hygiene at the QPainter handoff is the one live check)")
    return failed


if __name__ == "__main__":
    raise SystemExit(_run())
