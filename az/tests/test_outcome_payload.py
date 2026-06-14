"""
test_outcome_payload.py — session-8 step 4 pins (headless).

Drives IndoorWorld through on_enter / update without ever calling draw(), so no
GL context is needed. Pins the frozen M3 outcome record, the ledger gate, the
plant/intel placement + walk-over pickup, determinism, and the objective-free
fallback. Run: ``python -m az.tests.test_outcome_payload``.
"""

from __future__ import annotations

from az.indoor.world import IndoorWorld
from az.innerworld_engine import reachable_cells
from az.shell.mode import InputState, NO_INPUT, Transition
from az.shell.player_state import PlayerState

DT = 0.016
ACTION = InputState(action=True)

SKY = {"building": "tower_a", "archetype": "skyscraper",
       "footprint": (200.0, 200.0), "seed": 0xA17A, "holds_plant": True}


def _make(payload):
    w, s = IndoorWorld(), PlayerState()
    w.on_enter(s, payload)
    return w, s


def _objs(w, kind=None):
    return [(fi, e) for fi, fr in enumerate(w.floors) for e in fr.entities
            if kind is None or e.kind == kind]


# --- placement -------------------------------------------------------------

def test_plant_placed_once_deep_and_legal() -> None:
    w, _ = _make(SKY)
    plants = _objs(w, "plant")
    assert len(plants) == 1, "a holds_plant building places exactly one plant"
    fi, ent = plants[0]
    fr = w.floors[fi]
    reserved = {fr.up_cell, fr.down_cell, fr.start_cell, fr.exit_cell} - {None}
    assert fr.dungeon.is_walkable(*ent.cell), "plant must be on a walkable cell"
    assert ent.cell not in reserved, "plant must not sit on a landing/stair"
    print(f"  plant: floor {fi}/{len(w.floors) - 1} at {ent.cell}")


def test_no_plant_when_building_does_not_hold_it() -> None:
    w, s = _make({**SKY, "holds_plant": False})
    assert _objs(w, "plant") == [], "no plant in a building that doesn't hold it"
    t = w.update(DT, ACTION, s)          # spawn is in the exit zone -> bail
    assert isinstance(t, Transition) and t.payload["found"] is False


def test_intel_placed_and_reachable() -> None:
    w, _ = _make(SKY)
    intels = _objs(w, "intel")
    assert len(intels) == 1, "every dived building places one intel"
    fi, ent = intels[0]
    fr = w.floors[fi]
    assert ent.cell in reachable_cells(fr.dungeon, fr.start_cell), \
        "intel must be reachable from its floor's landing"
    print(f"  intel: floor {fi}/{len(w.floors) - 1} at {ent.cell}")


def test_determinism_same_seed_same_cells() -> None:
    a, _ = _make(SKY)
    b, _ = _make(SKY)
    sig = lambda w: [(fi, e.kind, e.cell) for fi, e in _objs(w)]
    assert sig(a) == sig(b), "same (seed, holds_plant) -> identical placement"


# --- pickup ----------------------------------------------------------------

def test_plant_pickup_flips_found_and_inventory() -> None:
    w, s = _make(SKY)
    fi, ent = _objs(w, "plant")[0]
    w._apply_floor(fi, ent.cell)         # stand on the plant cell
    w.update(DT, NO_INPUT, s)            # walk-over pickup, no action key
    assert ent.collected and w._found, "stepping on the plant flips found"
    assert s.has_item("plant"), "plant collection drops it in the inventory"


def test_intel_pickup_flips_hint() -> None:
    w, s = _make(SKY)
    fi, ent = _objs(w, "intel")[0]
    w._apply_floor(fi, ent.cell)
    w.update(DT, NO_INPUT, s)
    assert ent.collected and w._hint, "stepping on the intel flips hint"


# --- the frozen M3 outcome record ------------------------------------------

def test_exit_record_bail() -> None:
    """Bail at the entrance (never climbed): cleared=False, depth=0, ledger
    untouched, record well-formed."""
    w, s = _make(SKY)
    t = w.update(DT, ACTION, s)
    assert isinstance(t, Transition) and t.target == "outdoor"
    assert set(t.payload) == {"from", "cleared", "depth", "found", "hint"}
    assert t.payload["cleared"] is False and t.payload["depth"] == 0
    assert not s.has_cleared("tower_a"), "a bail must not set the ledger"


def test_exit_record_clear_sets_ledger() -> None:
    """Reach the top, return to the ground exit: cleared=True, depth=top, ledger
    set only now."""
    w, s = _make(SKY)
    top = len(w.floors) - 1
    w.max_floor = top                                  # simulate the full climb
    w._apply_floor(0, w.floors[0].exit_cell)           # back on the ground
    t = w.update(DT, ACTION, s)
    assert t.payload["cleared"] is True and t.payload["depth"] == top
    assert s.has_cleared("tower_a"), "a real clear sets the ledger"


def test_fallback_has_no_objectives_and_valid_record() -> None:
    """The bare-payload fallback stack carries no objectives, and its exit still
    returns a well-formed record (found=False, hint=None)."""
    w, s = _make({"building": "tower_a"})
    assert all(fr.entities == [] for fr in w.floors), "fallback is objective-free"
    w._apply_floor(0, w.floors[0].exit_cell)   # fallback spawns away from the exit
    t = w.update(DT, ACTION, s)
    assert isinstance(t, Transition)
    assert t.payload["found"] is False and t.payload["hint"] is None


def test_integration_collect_then_clear() -> None:
    """Collect the plant, reach the top, exit: cleared=True, depth=top, found=True."""
    w, s = _make(SKY)
    fi, ent = _objs(w, "plant")[0]
    w._apply_floor(fi, ent.cell)
    w.update(DT, NO_INPUT, s)
    assert w._found
    top = len(w.floors) - 1
    w.max_floor = top
    w._apply_floor(0, w.floors[0].exit_cell)
    t = w.update(DT, ACTION, s)
    assert t.payload["cleared"] is True
    assert t.payload["depth"] == top
    assert t.payload["found"] is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"\nall {len(tests)} outcome-payload pins passed.")