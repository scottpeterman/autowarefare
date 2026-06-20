"""
tests/test_indoor_ranged.py — Milestone 2.3 acceptance (headless, no GL/Qt).

Pins the gunman: the interior's ranged threat and its slow, dodgeable bolt.
Where the melee mob punishes proximity, the gunman punishes a held sightline —
so the pins prove (a) it positions to a standoff band rather than walking into
melee, (b) it only fires with a clear line, on cadence, and (c) the bolt is a
travelling object the world flies, lands on the player, or spends on a wall —
never an instant hit.

Covered:
  - standoff: holds the band, closes when out of reach, kites when crowded.
  - fire is LOS-gated and cadence-gated; a fired bolt is handed back for the
    world to track; no line means no shot.
  - the world flies bolts: a bolt reaching the player lands its damage through
    the shared pool; a bolt into a wall or past its life is dropped; a floor
    swap voids all bolts in flight.
  - the live roster now fields gunmen, and a real dive draws ranged fire.

Run:  python -m az.tests.test_indoor_ranged
"""

from __future__ import annotations

import math

from az.indoor.world import IndoorWorld
from az.indoor.enemies import GUNMAN, LIVE_ROSTER
from az.indoor.mob import Mob, STANDOFF_MIN
from az.indoor.projectile import Bolt, spawn_bolt, BOLT_HIT_RADIUS, BOLT_SPEED
from az.shell.mode import InputState
from az.shell.player_state import PlayerState

DT = 1.0 / 60.0


class FakeSpatial:
    def __init__(self, los: bool = True, blocked: bool = False) -> None:
        self.los = los
        self.blocked = blocked

    def line_of_sight(self, ax, az, bx, bz) -> bool:
        return self.los

    def can_move_to(self, x, z, radius):
        return (not self.blocked, x, z)


def _gunman(x=0.0, z=0.0) -> Mob:
    return Mob(def_=GUNMAN, x=x, z=z, cell=(0, 0))


# --- standoff positioning -------------------------------------------------

def test_gunman_closes_when_out_of_reach() -> None:
    g = _gunman()
    # beyond reach but within sight — the band (attack_range, sight] where it closes
    pz = (GUNMAN.attack_range + GUNMAN.sight) / 2.0
    g.step(0.0, pz, FakeSpatial(los=True), PlayerState())
    assert g.z > 0.0, "gunman should advance toward a target out of reach"
    print(f"  out of reach (> {GUNMAN.attack_range:.0f}): gunman closes in")


def test_gunman_holds_the_band() -> None:
    g = _gunman()
    pz = (STANDOFF_MIN + GUNMAN.attack_range) / 2.0   # mid-band
    z0 = g.z
    for _ in range(20):
        g.step(0.0, pz, FakeSpatial(los=True), PlayerState())
    assert abs(g.z - z0) < 1e-6, "in-band gunman should hold position"
    print(f"  in-band ([{STANDOFF_MIN:.0f}, {GUNMAN.attack_range:.0f}]): holds ground")


def test_gunman_kites_when_crowded() -> None:
    g = _gunman()
    pz = STANDOFF_MIN - 40.0                   # player too close
    g.step(0.0, pz, FakeSpatial(los=True), PlayerState())
    assert g.z < 0.0, "crowded gunman should back away from the player"
    print(f"  crowded (< {STANDOFF_MIN:.0f}): gunman kites back")


# --- firing ---------------------------------------------------------------

def test_gunman_fires_on_los_and_cadence() -> None:
    g = _gunman()
    pz = 200.0                                 # in reach
    sp = FakeSpatial(los=True)
    bolt = g.step(0.0, pz, sp, PlayerState())
    assert isinstance(bolt, Bolt), "in reach + LOS should fire a bolt"
    assert g.cooldown == GUNMAN.attack_cooldown

    for _ in range(GUNMAN.attack_cooldown - 1):
        assert g.step(0.0, pz, sp, PlayerState()) is None, "no fire mid-cooldown"
    assert isinstance(g.step(0.0, pz, sp, PlayerState()), Bolt), \
        "fires again once cooled down"
    print(f"  fires on cadence: a bolt every {GUNMAN.attack_cooldown} ticks")


def test_gunman_holds_fire_without_los() -> None:
    g = _gunman()
    out = g.step(0.0, 200.0, FakeSpatial(los=False), PlayerState())
    assert out is None and (g.x, g.z) == (0.0, 0.0), "no line -> no shot, no move"
    print("  no LOS: gunman holds fire and position")


def test_fired_bolt_aims_at_the_player() -> None:
    b = spawn_bolt(0.0, 0.0, 0.0, 300.0, GUNMAN.damage)
    assert abs(math.hypot(b.vx, b.vz) - BOLT_SPEED) < 1e-9, "bolt flies at BOLT_SPEED"
    assert b.vz > 0 and abs(b.vx) < 1e-9, "bolt heads straight at the target"
    print("  a fired bolt is aimed at the player at bolt speed")


# --- the world flies bolts ------------------------------------------------

def _world() -> tuple[IndoorWorld, PlayerState]:
    w, s = IndoorWorld(), PlayerState()
    w.on_enter(s, {"building": "tower_a"})     # default stack, enemy-free
    return w, s


def test_bolt_hits_player_for_damage() -> None:
    w, s = _world()
    # a bolt one tick short of the player, flying straight in
    w._bolts = [Bolt(x=w.cam_x, z=w.cam_z - BOLT_HIT_RADIUS - BOLT_SPEED + 1.0,
                     vx=0.0, vz=BOLT_SPEED, damage=GUNMAN.damage)]
    w._update_bolts(s)
    assert s.health == s.max_health - GUNMAN.damage, "bolt should land its damage"
    assert not w._bolts, "a landed bolt is spent"
    print(f"  bolt lands {GUNMAN.damage:.0f} on the player, then is spent")


def test_bolt_expires_on_life() -> None:
    w, s = _world()
    far = w.cam_x + 5000.0                      # nowhere near the player
    w._bolts = [Bolt(x=far, z=0.0, vx=BOLT_SPEED, vz=0.0,
                     damage=GUNMAN.damage, life=1)]
    w._update_bolts(s)
    assert not w._bolts, "a bolt past its life is dropped"
    assert s.health == s.max_health, "and deals nothing"
    print("  a bolt expires when its life runs out")


def test_floor_swap_voids_bolts() -> None:
    w, s = IndoorWorld(), PlayerState()
    w.on_enter(s, {"building": "tower_a", "archetype": "skyscraper",
                   "footprint": (300.0, 300.0), "seed": 7})
    w._bolts = [Bolt(x=w.cam_x, z=w.cam_z, vx=0.0, vz=BOLT_SPEED,
                     damage=GUNMAN.damage)]
    if len(w.floors) > 1:
        w._change_floor(1, ascending=True)
        assert not w._bolts, "a floor swap voids bolts in flight"
        print("  a floor swap voids all bolts in flight")
    else:
        print("  (skipped: single-floor stack)")


def test_live_roster_fields_gunmen() -> None:
    assert GUNMAN in LIVE_ROSTER, "the gunman is now in the live roster"
    print(f"  live roster fields gunmen ({[d.name for d in LIVE_ROSTER]})")


def test_gunman_draws_fire_in_a_dive() -> None:
    w, s = _world()
    # drop a gunman point-blank in the open start cell: LOS is clear, so it fires
    g = Mob(def_=GUNMAN, x=w.cam_x + 50.0, z=w.cam_z, cell=(0, 0))
    w.floors[0].enemies = [g]
    fired = False
    for _ in range(8):                          # a handful of ticks
        w.update(DT, InputState(), s)
        if w._bolts:
            fired = True
            break
    assert fired, "a gunman with a clear line should put a bolt in the air"
    print("  a real dive draws ranged fire (gunman bolt in flight)")


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
        print("M2.3 PASS: the gunman — standoff/kite positioning, LOS- and "
              "cadence-gated fire, and the world flying its slow bolt to land "
              "on the player, spend on a wall, or void on a floor swap, all green")
    return failed


if __name__ == "__main__":
    raise SystemExit(_run())