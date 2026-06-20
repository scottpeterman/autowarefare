"""
tests/test_indoor_escalation.py — dwell-time reinforcement acceptance (headless).

Pins the *intra-dive* escalation: a populated building sends reinforcements onto
your floor, and the longer you linger the faster they come. This is the ramp
that makes a single building tense before the cross-dive ``tier`` ledger (which
needs multi-building play) is exercised — so lingering to sweep gets costlier.

Covered:
  - the wave interval ramps from REINFORCE_BASE down to REINFORCE_FLOOR over
    REINFORCE_RAMP ticks of dwell, then plateaus.
  - dwelling actually adds mobs to the current floor, up to a per-floor cap it
    never exceeds, on legal (walkable, non-reserved) cells.
  - heat is per-dive: a fresh on_enter resets the clock.
  - the bare default stack never reinforces (M2.0 / floor-stack pins stay safe),
    and the waves are deterministic per (seed) dive.

Run:  python -m az.tests.test_indoor_escalation
"""

from __future__ import annotations

from az.indoor.world import (
    IndoorWorld, REINFORCE_BASE, REINFORCE_FLOOR, REINFORCE_RAMP,
)
from az.indoor.enemy_placement import REINFORCE_CAP, RUNTIME_SPAWN_CLEAR, _reserved
from az.shell.mode import InputState
from az.shell.player_state import PlayerState

DT = 1.0 / 60.0
IDLE = InputState()
ARCH = {"building": "tower_a", "archetype": "skyscraper",
        "footprint": (300.0, 300.0), "seed": 7, "holds_plant": True}


def _godmode() -> PlayerState:
    """A player who survives a long dwell, so reinforcements accumulate to be
    counted instead of ending the run."""
    s = PlayerState()
    s.max_health = s.health = 1e9
    s.lives = 10_000
    return s


def _floor0_count(w) -> int:
    return sum(m.alive for m in w.floors[0].enemies)


# --- the ramp -------------------------------------------------------------

def test_interval_ramps_with_dwell() -> None:
    w = IndoorWorld()
    w._dwell = 0
    assert w._reinforce_interval() == REINFORCE_BASE
    w._dwell = REINFORCE_RAMP // 2
    mid = w._reinforce_interval()
    assert REINFORCE_FLOOR < mid < REINFORCE_BASE, "mid-dwell sits between"
    w._dwell = REINFORCE_RAMP * 3
    assert w._reinforce_interval() == REINFORCE_FLOOR, "plateaus at the floor"
    print(f"  wave interval ramps {REINFORCE_BASE} -> {mid} -> {REINFORCE_FLOOR} "
          "ticks with dwell")


# --- reinforcement spawning ----------------------------------------------

def test_dwelling_adds_reinforcements() -> None:
    w, s = IndoorWorld(), _godmode()
    w.on_enter(s, dict(ARCH))
    start = _floor0_count(w)
    for _ in range(REINFORCE_BASE + 200):     # past the first wave
        w.update(DT, IDLE, s)
    assert _floor0_count(w) > start, "dwelling should bring reinforcements"
    print(f"  dwelling reinforces floor 0: {start} -> {_floor0_count(w)} mobs")


def test_reinforcement_respects_cap_and_legality() -> None:
    w, s = IndoorWorld(), _godmode()
    w.on_enter(s, dict(ARCH))
    peak = 0
    for _ in range(6000):                      # a long, lingering dive
        w.update(DT, IDLE, s)
        peak = max(peak, _floor0_count(w))
        assert _floor0_count(w) <= REINFORCE_CAP, "never exceeds the floor cap"
    fr = w.floors[0]
    reserved = _reserved(fr)
    for m in fr.enemies:
        assert fr.dungeon.is_walkable(*m.cell), f"reinforcement off-grid {m.cell}"
        assert m.cell not in reserved, f"reinforcement on reserved {m.cell}"
    assert peak == REINFORCE_CAP, f"a long dwell should fill to the cap ({peak})"
    print(f"  reinforcements fill to cap {REINFORCE_CAP} on legal cells, never past")


def test_heat_resets_each_dive() -> None:
    w, s = IndoorWorld(), _godmode()
    w.on_enter(s, dict(ARCH))
    for _ in range(REINFORCE_BASE + 500):
        w.update(DT, IDLE, s)
    assert w._dwell > 0
    w.on_enter(s, dict(ARCH))                  # a fresh dive
    assert w._dwell == 0 and w._reinforce_cd == REINFORCE_BASE, \
        "a new dive resets the heat clock"
    print("  heat is per-dive: re-entering resets the clock")


def test_bare_stack_never_reinforces() -> None:
    w, s = IndoorWorld(), _godmode()
    w.on_enter(s, {"building": "tower_a"})     # bare payload, enemy-free
    for _ in range(REINFORCE_BASE * 3):
        w.update(DT, IDLE, s)
    assert not any(fr.enemies for fr in w.floors), \
        "the default stack must never reinforce (M2.0 pins)"
    print("  bare default stack stays inert across a long dwell")


def test_reinforcements_are_deterministic() -> None:
    a, b = IndoorWorld(), IndoorWorld()
    sa, sb = _godmode(), _godmode()
    a.on_enter(sa, dict(ARCH))
    b.on_enter(sb, dict(ARCH))
    for _ in range(REINFORCE_BASE * 4):
        a.update(DT, IDLE, sa)
        b.update(DT, IDLE, sb)
    ca = sorted(m.cell for m in a.floors[0].enemies)
    cb = sorted(m.cell for m in b.floors[0].enemies)
    assert ca == cb, "same seed must reinforce identically"
    print(f"  reinforcements deterministic per seed ({len(ca)} mobs match)")


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
        except Exception as e:   # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    if failed == 0:
        print("ESCALATION PASS: dwell-time reinforcement — the wave interval "
              "ramps with dwell, fills a floor to its cap on legal cells, resets "
              "per dive, stays inert on the bare stack, and is deterministic")
    return failed


if __name__ == "__main__":
    raise SystemExit(_run())