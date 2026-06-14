"""
test_director — the spawn director (M1 increment 4).

Pins the contract the difficulty curve hangs on: difficulty is the player's
search (the tier ledger), expressed as HOW MANY (population, stepped + plateaued)
and WHO (the gated, shifting mix), plus within-tier persistence (refill to the
target, never past it). No clock, no score — tier in, roster out.
"""

from __future__ import annotations

from az.outerworld_engine.battlefield import Battlefield
from az.outdoor.director import (
    Director, population_target, mix_weights,
    BASE_POPULATION, MAX_POPULATION, SEDAN_FLOOR,
    PICKUP_TIER, FLATBED_TIER, SPAWN_INTERVAL_TICKS,
)
from az.outdoor.vehicles import SEDAN, PICKUP, FLATBED, spawn_vehicle


# --- helpers ---------------------------------------------------------------

def _field() -> Battlefield:
    return Battlefield(half_size=1000.0)


def _names(table):
    return {v.name for v, w in table}


def _weight(table, vdef) -> float:
    for v, w in table:
        if v is vdef:
            return w
    return 0.0


# --- population: steps, then plateaus --------------------------------------

def test_population_steps_and_plateau():
    # +1 every 3 tiers from a base of 2, capped at the ceiling.
    assert population_target(0) == BASE_POPULATION == 2
    assert population_target(1) == 2
    assert population_target(2) == 2
    assert population_target(3) == 3
    assert population_target(6) == 4
    assert population_target(9) == 5
    assert population_target(12) == 6
    # plateau — the §7 anti-unwinnable ceiling holds no matter how deep
    assert population_target(50) == MAX_POPULATION == 6
    assert population_target(1000) == 6


def test_population_monotonic_nondecreasing():
    prev = 0
    for tier in range(0, 60):
        p = population_target(tier)
        assert p >= prev
        assert p <= MAX_POPULATION
        prev = p


# --- mix: gated and shifting -----------------------------------------------

def test_sedan_always_present_with_a_floor():
    # The swarm never disappears — sedan weight is > 0 at every tier and
    # bottoms out at exactly its floor when the decay would push it lower.
    for tier in range(0, 60):
        w = _weight(mix_weights(tier), SEDAN)
        assert w > 0.0
        assert w >= SEDAN_FLOOR
    assert _weight(mix_weights(50), SEDAN) == SEDAN_FLOOR


def test_pickup_gate():
    for tier in range(0, PICKUP_TIER):           # 0, 1
        assert _weight(mix_weights(tier), PICKUP) == 0.0
        assert "pickup" not in _names(mix_weights(tier))
    for tier in (PICKUP_TIER, PICKUP_TIER + 1, 12):
        assert _weight(mix_weights(tier), PICKUP) > 0.0


def test_flatbed_gate():
    for tier in range(0, FLATBED_TIER):          # 0..5
        assert _weight(mix_weights(tier), FLATBED) == 0.0
        assert "flatbed" not in _names(mix_weights(tier))
    for tier in (FLATBED_TIER, FLATBED_TIER + 4, 30):
        assert _weight(mix_weights(tier), FLATBED) > 0.0


def test_mix_composition_by_tier():
    assert _names(mix_weights(0)) == {"sedan"}
    assert _names(mix_weights(1)) == {"sedan"}
    assert _names(mix_weights(2)) == {"sedan", "pickup"}
    assert _names(mix_weights(5)) == {"sedan", "pickup"}
    assert _names(mix_weights(6)) == {"sedan", "pickup", "flatbed"}


def test_roll_only_returns_unlocked():
    d = Director(seed=1)
    # tier 0: sedan-only gate -> every roll is a sedan, regardless of rng
    assert all(d._roll(0) is SEDAN for _ in range(100))
    # tier 1: still sedan-only
    assert all(d._roll(1) is SEDAN for _ in range(100))
    # tier 5: sedan or pickup, never flatbed
    rolls5 = {d._roll(5).name for _ in range(300)}
    assert rolls5 <= {"sedan", "pickup"}
    assert "flatbed" not in rolls5
    # tier 10: all three reachable
    rolls10 = {d._roll(10).name for _ in range(500)}
    assert rolls10 == {"sedan", "pickup", "flatbed"}


# --- per-chassis spawn -----------------------------------------------------

def test_spawn_vehicle_carries_chassis_stats():
    s = spawn_vehicle(SEDAN, 10.0, -20.0, heading=0.3, ai_seed=7)
    assert (s.hp, s.max_hp) == (40.0, 40.0)
    assert s.move_speed == 0.52 and s.turn_speed_deg == 0.95
    assert s.engage_distance == 650.0
    assert s.score_value == 1000
    assert len(s.loadout.weapons) == 1            # pulse MG only

    p = spawn_vehicle(PICKUP, 0.0, 0.0)
    assert p.max_hp == 120.0 and p.score_value == 2500
    assert len(p.loadout.weapons) == 1            # shell cannon only

    f = spawn_vehicle(FLATBED, 0.0, 0.0)
    assert f.max_hp == 80.0 and f.score_value == 4000
    assert len(f.loadout.weapons) == 2            # shell + pulse


def test_each_spawn_gets_its_own_loadout():
    a = spawn_vehicle(PICKUP, 0.0, 0.0)
    b = spawn_vehicle(PICKUP, 0.0, 0.0)
    assert a.loadout is not b.loadout
    assert a.loadout.active is not b.loadout.active


# --- fill: top up to the target immediately --------------------------------

def test_fill_reaches_population_target():
    for tier in (0, 3, 6, 12, 50):
        bf = _field()
        Director(seed=2).fill(bf, tier, 0.0, 600.0)
        assert len(bf.tanks) == population_target(tier)


def test_fill_at_tier_zero_is_all_sedans():
    bf = _field()
    Director(seed=3).fill(bf, 0, 0.0, 600.0)
    assert len(bf.tanks) == 2
    for t in bf.tanks:
        assert t.max_hp == SEDAN.max_hp and t.score_value == SEDAN.score


def test_fill_is_idempotent_at_target():
    bf = _field()
    d = Director(seed=4)
    d.fill(bf, 3, 0.0, 600.0)
    n = len(bf.tanks)
    d.fill(bf, 3, 0.0, 600.0)          # already full -> no change
    assert len(bf.tanks) == n


def test_spawns_land_in_bounds():
    bf = _field()
    Director(seed=5).fill(bf, 12, 900.0, 900.0)   # player near a corner
    half = bf.half_size
    for t in bf.tanks:
        assert -half <= t.x <= half and -half <= t.z <= half


# --- update: refill to target within a tier, never past it -----------------

def test_update_refills_after_a_loss():
    bf = _field()
    d = Director(seed=6)
    tier = 3
    d.fill(bf, tier, 0.0, 600.0)
    target = population_target(tier)
    assert len(bf.tanks) == target

    # a loss drops the field below target
    bf.tanks.pop()
    assert len(bf.tanks) == target - 1

    # the war answers — but on a cooldown (not instantly), one at a time,
    # and never past the target.
    for _ in range(SPAWN_INTERVAL_TICKS + 5):
        d.update(bf, tier, 0.0, 600.0)
        assert len(bf.tanks) <= target
    assert len(bf.tanks) == target


def test_update_holds_steady_at_target():
    bf = _field()
    d = Director(seed=7)
    tier = 6
    d.fill(bf, tier, 0.0, 600.0)
    target = population_target(tier)
    for _ in range(500):
        d.update(bf, tier, 0.0, 600.0)
        assert len(bf.tanks) == target      # full field stays exactly full


def test_update_climbs_to_a_raised_target():
    # tier bumps (return-from-dive): the same director, handed a higher tier,
    # fills the extra slots over time without ever overshooting.
    bf = _field()
    d = Director(seed=8)
    d.fill(bf, 0, 0.0, 600.0)               # target 2
    assert len(bf.tanks) == 2
    higher = 9                              # target 5
    target = population_target(higher)
    for _ in range(SPAWN_INTERVAL_TICKS * (target - 2) + 10):
        d.update(bf, higher, 0.0, 600.0)
        assert len(bf.tanks) <= target
    assert len(bf.tanks) == target


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_director: {len(fns)} passed")


if __name__ == "__main__":
    _run()
