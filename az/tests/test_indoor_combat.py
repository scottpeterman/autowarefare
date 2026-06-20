"""
tests/test_indoor_combat.py — Milestone 2.2 acceptance (headless, no GL/Qt).

Pins the indoor melee slice: the clone-mobsters placed, chasing, slashing, and
dying. Proves the *logic* surface without a GL context — the wireframe bodies
render live in the window (the one manual check), everything else is here.

Covered:
  - placement is deterministic per (seed, tier), legal (walkable, non-reserved),
    spawn-clear of the ground door, and tier-scaled; the default test stack stays
    enemy-free so the M2.0 / floor-stack geometry pins are untouched.
  - aggro is LOS-gated: no line, no chase; a clear line within sight engages.
  - a mob closes the distance, then stops inside attack range and slashes on
    cadence; the slash routes into PlayerState (respecting respawn grace), and a
    pool-emptying slash spends a life through the shared economy.
  - the kill path: hit() drops hp and the world culls the dead; the player's
    forward-arc strike damages mobs ahead and spares those behind.

Run:  python -m az.tests.test_indoor_combat
"""

from __future__ import annotations

import math

from az.indoor.world import (
    IndoorWorld, STRIKE_DAMAGE, STRIKE_COOLDOWN, ENEMY_SEPARATION,
)
from az.indoor.enemies import THUG, KNIFEMAN
from az.indoor.enemy_placement import place_enemies, SPAWN_CLEAR, _reserved
from az.indoor.mob import Mob, ENEMY_RADIUS
from az.shell.mode import InputState
from az.shell.player_state import PlayerState

DT = 1.0 / 60.0
FIRE = InputState(fire=True)
ARCH = {"building": "tower_a", "archetype": "skyscraper",
        "footprint": (300.0, 300.0), "seed": 7, "holds_plant": True}


class FakeSpatial:
    """A SpatialQuery stand-in: LOS and free-movement are dials, so the melee
    brain is tested in isolation from any real dungeon."""
    def __init__(self, los: bool = True, blocked: bool = False) -> None:
        self.los = los
        self.blocked = blocked

    def line_of_sight(self, ax, az, bx, bz) -> bool:
        return self.los

    def can_move_to(self, x, z, radius):
        return (not self.blocked, x, z)


def _all_mobs(w):
    return [(f, m) for f, fr in enumerate(w.floors) for m in fr.enemies]


# --- placement ------------------------------------------------------------

def test_placement_deterministic() -> None:
    a, b = IndoorWorld(), IndoorWorld()
    a.on_enter(PlayerState(), dict(ARCH))
    b.on_enter(PlayerState(), dict(ARCH))
    ca = sorted((f, m.cell) for f, m in _all_mobs(a))
    cb = sorted((f, m.cell) for f, m in _all_mobs(b))
    assert ca == cb and ca, "same (seed, tier) must place identical mobs"
    print(f"  deterministic: {len(ca)} mobs placed identically across two dives")


def test_placement_legal_and_spawn_clear() -> None:
    w = IndoorWorld()
    w.on_enter(PlayerState(), dict(ARCH))
    for f, m in _all_mobs(w):
        fr = w.floors[f]
        d = fr.dungeon
        assert d.is_walkable(*m.cell), f"mob on non-walkable {m.cell}"
        assert m.cell not in _reserved(fr), f"mob on reserved cell {m.cell}"
        if f == 0 and fr.start_cell is not None:
            sx, sz = fr.start_cell
            man = abs(m.cell[0] - sx) + abs(m.cell[1] - sz)
            assert man >= SPAWN_CLEAR, f"floor-0 mob too close to door: {man}"
    print("  placement legal: walkable, non-reserved, ground door kept clear")


def test_tier_scales_population() -> None:
    low, high = IndoorWorld(), IndoorWorld()
    s0, s6 = PlayerState(), PlayerState()
    s6.tier = 6
    low.on_enter(s0, dict(ARCH))
    high.on_enter(s6, dict(ARCH))
    n_low, n_high = len(_all_mobs(low)), len(_all_mobs(high))
    assert n_high > n_low, f"tier should grow the roster ({n_low} -> {n_high})"
    print(f"  tier scales population: tier0={n_low}  tier6={n_high}")


def test_default_stack_is_enemy_free() -> None:
    w = IndoorWorld()
    w.on_enter(PlayerState(), {"building": "tower_a"})   # bare payload
    assert not _all_mobs(w), "default stack must stay enemy-free (M2.0 pins)"
    print("  bare-payload default stack carries no enemies (geometry pins safe)")


# --- the melee brain (against a fake spatial) -----------------------------

def test_los_gates_aggro() -> None:
    state = PlayerState()
    # in sight (sight=350), beyond attack range; player 200 north of the mob
    blind = Mob(def_=KNIFEMAN, x=0.0, z=0.0, cell=(0, 0))
    blind.step(0.0, 200.0, FakeSpatial(los=False), state)
    assert (blind.x, blind.z) == (0.0, 0.0), "no LOS must not move the mob"
    assert state.health == state.max_health, "no LOS must not deal damage"

    seer = Mob(def_=KNIFEMAN, x=0.0, z=0.0, cell=(0, 0))
    seer.step(0.0, 200.0, FakeSpatial(los=True), state)
    assert seer.z > 0.0, "clear LOS within sight must close the distance"
    print("  aggro is LOS-gated: blind mob holds, seeing mob advances")


def test_mob_closes_then_holds_at_range() -> None:
    state = PlayerState()
    m = Mob(def_=KNIFEMAN, x=0.0, z=0.0, cell=(0, 0))
    sp = FakeSpatial(los=True)
    prev = 200.0
    for _ in range(120):
        m.step(0.0, 200.0, sp, state)
        dist = math.hypot(0.0 - m.x, 200.0 - m.z)
        assert dist <= prev + 1e-6, "distance must be non-increasing while chasing"
        prev = dist
    assert prev <= KNIFEMAN.attack_range + KNIFEMAN.speed, \
        "mob should settle inside attack range"
    print(f"  approach converges to attack range (final dist {prev:.1f} <= "
          f"{KNIFEMAN.attack_range:.0f})")


def test_slash_cadence_and_damage_routing() -> None:
    state = PlayerState()
    m = Mob(def_=KNIFEMAN, x=0.0, z=0.0, cell=(0, 0))
    sp = FakeSpatial(los=True)
    px, pz = 0.0, 30.0   # inside knifeman attack_range (~46)

    m.step(px, pz, sp, state)                       # first swing lands
    assert state.health == state.max_health - KNIFEMAN.damage
    assert m.cooldown == KNIFEMAN.attack_cooldown
    after_first = state.health

    for _ in range(KNIFEMAN.attack_cooldown - 1):   # cooling down: no new damage
        m.step(px, pz, sp, state)
        assert state.health == after_first, "must not slash during cooldown"
    m.step(px, pz, sp, state)                        # cooldown elapsed: slash again
    assert state.health == after_first - KNIFEMAN.damage
    print(f"  slash cadence: {KNIFEMAN.damage} dmg every "
          f"{KNIFEMAN.attack_cooldown} ticks, routed to PlayerState")


def test_slash_respects_respawn_grace() -> None:
    state = PlayerState()
    state.invuln_ticks = 30
    m = Mob(def_=KNIFEMAN, x=0.0, z=0.0, cell=(0, 0))
    m.step(0.0, 30.0, FakeSpatial(los=True), state)
    assert state.health == state.max_health, "grace must no-op the slash"
    print("  slash whiffs during respawn grace (shared take_damage guard)")


def test_pool_emptying_slash_spends_a_life() -> None:
    state = PlayerState()
    state.health = 10.0                # less than knifeman's 14 dmg
    lives_before = state.lives
    m = Mob(def_=KNIFEMAN, x=0.0, z=0.0, cell=(0, 0))
    m.step(0.0, 30.0, FakeSpatial(los=True), state)
    assert state.lives == lives_before - 1, "emptying the pool spends a life"
    assert state.health == state.max_health, "respawn restores the pool"
    print("  a pool-emptying slash spends a life + respawns (shared economy)")


# --- the kill path (world-level: strike + cull) ---------------------------

def _world_with_mobs(front_def, back_def):
    """Default stack (enemy-free), then drop one mob in front of the player and
    one behind. Player faces heading 0 -> forward is -Z, so 'front' is -Z."""
    w = IndoorWorld()
    state = PlayerState()
    w.on_enter(state, {"building": "tower_a"})
    w.cam_angle_deg = 0.0
    px, pz = w.cam_x, w.cam_z
    front = Mob(def_=front_def, x=px, z=pz - 40.0, cell=(0, 0))   # ahead (-Z)
    back = Mob(def_=back_def, x=px, z=pz + 40.0, cell=(0, 0))     # behind (+Z)
    w.floors[0].enemies = [front, back]
    return w, state, front, back


def test_hit_reduces_hp_and_reports_death() -> None:
    m = Mob(def_=THUG, x=0, z=0, cell=(0, 0))   # 3 hp
    assert m.hit(2) is False and m.hp == 1
    assert m.hit(2) is True and m.hp <= 0
    print("  hit() drops hp and reports the kill")


def test_player_strike_hits_front_spares_back() -> None:
    w, state, front, back = _world_with_mobs(THUG, THUG)   # both 3 hp survive a hit
    w.update(DT, FIRE, state)
    assert front.hp == THUG.hp - STRIKE_DAMAGE, "front mob takes the strike"
    assert back.hp == THUG.hp, "mob behind the player is spared"
    print(f"  strike: front -{STRIKE_DAMAGE} hp, back untouched (forward arc)")


def test_strike_culls_the_dead() -> None:
    w, state, front, back = _world_with_mobs(KNIFEMAN, THUG)   # knifeman = 1 hp
    w.update(DT, FIRE, state)
    live = w.floors[0].enemies
    assert front not in live, "a killed mob is culled from the floor"
    assert back in live, "a survivor stays"
    print("  the strike culls a killed mob from the active floor")


def test_strike_is_cadence_gated() -> None:
    w, state, front, _ = _world_with_mobs(THUG, THUG)
    w.update(DT, FIRE, state)
    hp_after_one = front.hp
    w.update(DT, FIRE, state)   # immediate second fire is on cooldown
    assert front.hp == hp_after_one, "strike must respect its cooldown"
    assert w._strike_cd <= STRIKE_COOLDOWN
    print("  player strike is cadence-gated (no machine-gun melee)")


def test_stacked_mobs_separate() -> None:
    w = IndoorWorld()
    s = PlayerState()
    w.on_enter(s, {"building": "tower_a"})            # open, walkable start cell
    px, pz = w.cam_x, w.cam_z
    a = Mob(def_=THUG, x=px, z=pz, cell=(0, 0))        # exact overlap
    b = Mob(def_=THUG, x=px, z=pz, cell=(0, 0))
    for _ in range(20):
        w._separate_mobs([a, b])
    d = math.hypot(a.x - b.x, a.z - b.z)
    assert d >= ENEMY_RADIUS, f"stacked mobs must jostle apart (got {d:.1f})"
    print(f"  two stacked mobs fan apart to {d:.0f}u (no more fused blob)")


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
        except Exception as e:   # noqa: BLE001 — surface setup errors too
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    if failed == 0:
        print("M2.2 PASS: indoor melee — clone-mobsters placed (deterministic, "
              "legal, tier-scaled), LOS-gated chase, cadence slash into "
              "PlayerState, and the strike/cull kill path all green")
    return failed


if __name__ == "__main__":
    raise SystemExit(_run())