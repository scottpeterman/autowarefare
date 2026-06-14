"""
tests/test_spine.py — headless acceptance test for the integration spine.

Runs with no GL and no Qt. Covers, against the REAL battlefield engine:
  A. the outdoor world is drivable and stays in bounds,
  B. the one-shell-at-a-time fire rule holds,
  C. a player bullet killing an enemy routes score through shell PlayerState,
  D. the portal hands off both ways; health taken indoors and a cleared flag
     both persist across the seam, and the outdoor pose is restored on return.

Run:  python -m az.tests.test_spine   (or: pytest az/tests/test_spine.py)
"""

from __future__ import annotations

from az.outerworld_engine.bullet import Bullet
from az.outerworld_engine.tank import Tank
from az.outerworld_engine.models.cube_model import CUBE_MODEL
from az.outerworld_engine.models.tank_model import TANK_MODEL

from az.indoor.world import IndoorWorld
from az.outdoor.world import OutdoorWorld, TANK_SCORE, TOWER_ID
from az.shell.mode import NO_INPUT, InputState, Transition
from az.shell.player_state import PlayerState
from az.shell.portal import Portal
from az.common.weapon import (
    BallisticFireControl, HeatFireControl, Loadout, ProjectileSpec, Weapon,
)

DT = 1.0 / 60.0
FORWARD = InputState(forward=True)
FIRE = InputState(fire=True)
ACTION = InputState(action=True)


def _fresh():
    state = PlayerState()
    worlds = {"outdoor": OutdoorWorld(), "indoor": IndoorWorld()}
    portal = Portal(worlds)
    worlds["outdoor"].on_enter(state, {})
    return state, worlds, portal


def test_a_drivable() -> None:
    state, worlds, _ = _fresh()
    ow = worlds["outdoor"]
    z0 = ow.camera.z
    for _ in range(120):
        ow.update(DT, FORWARD, state)
    assert ow.camera.z < z0, "holding forward should move along -Z"
    assert ow.battlefield.in_bounds(ow.camera.x, ow.camera.z), "must stay in bounds"


def test_b_one_shell_rule() -> None:
    state, worlds, _ = _fresh()
    ow = worlds["outdoor"]
    ow.update(DT, FIRE, state)
    assert len(ow.battlefield.bullets) == 1, "fire should spawn exactly one shell"
    assert not ow._can_fire(), "second shell blocked while first is in flight"
    ow.update(DT, FIRE, state)
    assert len(ow.battlefield.bullets) == 1, "no second shell until the first clears"


def test_c_kill_routes_score_to_playerstate() -> None:
    state, worlds, _ = _fresh()
    ow = worlds["outdoor"]
    ow.battlefield.tanks.clear()
    ow.battlefield.bullets.clear()
    cx, cz = ow.camera.x, ow.camera.z
    ow.battlefield.add_tank(Tank(model=TANK_MODEL, x=cx, z=cz - 100.0, ai_seed=7))
    ow.battlefield.add_bullet(Bullet(model=CUBE_MODEL, x=cx, z=cz - 100.0,
                                     vx=0.0, vz=0.0, range_remaining=100.0,
                                     bounding_radius=1.0, owner="player"))
    score0 = state.score
    ow._sim_tick(NO_INPUT, state)
    assert len(ow.battlefield.tanks) == 0, "player bullet should kill the tank"
    assert state.score == score0 + TANK_SCORE, "kill must score through PlayerState"


def test_d_portal_roundtrip_persists_state() -> None:
    state, worlds, portal = _fresh()
    ow = worlds["outdoor"]
    # park the auto at the tower lobby (driving the full ~1km is a separate concern)
    ow.camera.x, ow.camera.z = ow._lobby.x, ow._lobby.z
    saved = ow.save_pose()

    t = ow.update(DT, ACTION, state)
    assert t is not None and t.target == "indoor"
    active = portal.transit(ow, t, state)
    assert active.name == "indoor"

    # M2.0: no indoor hazard yet (combat lands in M2.2). Prove the round-trip
    # *mechanics*: reach the exit, hand back, cleared flag set, pose restored,
    # PlayerState carried through intact. Teleport to the exit cell rather than
    # navigate the dungeon, mirroring the outdoor lobby teleport above.
    hp_before = state.health
    # Step 4 changed the clear gate: mark_cleared fires only on a top-reached
    # exit. Simulate the full climb so this round-trip exit is a genuine clear
    # (the round-trip mechanics are what this test pins, not the navigation).
    active.max_floor = len(active.floors) - 1
    active.cam_x, active.cam_z = active.exit_x, active.exit_z
    t = active.update(DT, ACTION, state)
    assert t is not None and t.target == "outdoor"

    active = portal.transit(active, t, state)
    assert active.name == "outdoor"
    assert state.has_cleared(TOWER_ID)
    assert abs(state.health - hp_before) < 1e-6, "HP must persist across the seam"
    assert abs(active.camera.x - saved[0]) < 1e-6 and abs(active.camera.z - saved[1]) < 1e-6


def test_e_weapon_loadout_and_ballistic_gate() -> None:
    """The M1-inc2 foundation: firing now routes through the active weapon's
    fire-control (the one-shell gate is a property of BallisticFireControl, not
    the world), and the Loadout switch mechanism works. Economy-independent —
    no rapid-fire decisions baked in."""
    state, worlds, _ = _fresh()
    ow = worlds["outdoor"]

    # the active weapon is the ballistic shell, gated one-on-screen-at-a-time
    assert ow.loadout.active.name == "shell"
    assert ow.loadout.active.can_fire(ow.battlefield, "player")
    ow.update(DT, FIRE, state)
    assert len(ow.battlefield.bullets) == 1, "weapon emits exactly one round"
    assert not ow.loadout.active.can_fire(ow.battlefield, "player"), \
        "ballistic gate closes while a player round is live"

    # the Loadout switch mechanism (binding keys to it is a deferred decision).
    # A stub weapon stands in purely to exercise select/cycle without assuming
    # how many weapons ship by default.
    n0 = len(ow.loadout.weapons)
    stub = Weapon(name="stub", spec=ow.loadout.active.spec,
                  control=BallisticFireControl(),
                  make_projectile=ow.loadout.active.make_projectile)
    ow.loadout.weapons.append(stub)
    assert ow.loadout.select(n0) and ow.loadout.active.name == "stub"
    ow.loadout.cycle()
    assert ow.loadout.active is ow.loadout.weapons[0], "cycle wraps to slot 0"
    assert not ow.loadout.select(99), "out-of-range select is inert"


def test_f_pulse_heat_overheat_and_cycle() -> None:
    """The rapid-fire weapon: the heat fire-control builds heat, trips an
    overheat lockout, and re-engages only after cooling past the hysteresis
    threshold — and the outdoor loadout cycles shell <-> pulse."""
    # heat economy, exercised directly and deterministically
    hc = HeatFireControl(cadence_ticks=2, heat_per_shot=0.5,
                         cool_per_tick=0.01, reengage=0.5)
    shots = 0
    for _ in range(6):              # hold the trigger across several ticks
        if hc.update(True, None, "player"):
            shots += 1
        hc.tick()
    assert shots >= 2, "should land multiple rounds before overheating"
    assert hc.overheated, "sustained fire must overheat"
    assert not hc.can_fire(None, "player"), "locked out while overheated"

    cooled = 0
    while hc.overheated and cooled < 1000:   # cool back down past reengage
        hc.tick()
        cooled += 1
    assert not hc.overheated, "overheat clears after cooling to reengage"
    assert hc.can_fire(None, "player"), "weapon usable again once re-engaged"

    # cycle in the live world: shell -> pulse -> shell
    state, worlds, _ = _fresh()
    ow = worlds["outdoor"]
    assert ow.loadout.active.name == "shell"
    assert ow.weapon_status()["heat"] is None, "shell has no heat gauge"
    ow.update(DT, InputState(cycle=True), state)
    assert ow.loadout.active.name == "pulse"
    assert isinstance(ow.weapon_status()["heat"], float), "pulse shows heat"
    ow.update(DT, InputState(cycle=True), state)
    assert ow.loadout.active.name == "shell", "cycle wraps back to the shell"


def _run_all() -> None:
    for fn in (test_a_drivable, test_b_one_shell_rule,
               test_c_kill_routes_score_to_playerstate,
               test_d_portal_roundtrip_persists_state,
               test_e_weapon_loadout_and_ballistic_gate,
               test_f_pulse_heat_overheat_and_cycle):
        fn()
        print(f"  PASS  {fn.__name__}")


if __name__ == "__main__":
    _run_all()
    print("M1 increment-2 PASS: shared Weapon/Loadout abstraction (engine-"
          "neutral common.weapon) — ballistic shell + heat-gated pulse rifle, "
          "cycle switching; spine (drive/fire/kill->score/portal) still green")