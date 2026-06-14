"""
tests/test_enemy_fire.py — the Session 7 enemy-fire-AI pass.

Headless, no GL/Qt, against the REAL battlefield engine. Behavior (1) of three:
**per-shooter bullet attribution**. The old ballistic gate was per *owner*, so
the whole enemy field shared a single live round — six tanks, one bullet between
them, which badly undersells "the war kept coming" (vision §3, §7). The gate is
now per *shooter*: each Bullet carries the entity that fired it, and the cap is
counted per shooter. The player is a single shooter, so its one-shell rule is
unchanged; each enemy tank is its own shooter, so the field can put one round
per tank in flight at once — while the per-shooter cap keeps it fair (no
unwinnable wall of bullets, §7).

(Behaviors (2) rapid enemy pulse and (3) Flatbed two-weapon select build on
this and land next.)

Run:  python -m az.tests.test_enemy_fire
"""

from __future__ import annotations

from az.outerworld_engine.tank import Tank
from az.outerworld_engine.models.tank_model import TANK_MODEL

from az.outdoor.world import OutdoorWorld, _enemy_loadout
from az.shell.player_state import PlayerState


def _fresh():
    state = PlayerState()
    ow = OutdoorWorld()
    ow.on_enter(state, {})
    ow.battlefield.tanks.clear()
    ow.battlefield.bullets.clear()
    return state, ow


def _armed_tank(x: float, z: float) -> Tank:
    # each tank gets its OWN loadout (the factory), so its fire-control state
    # (and thus its per-shooter gate) is independent of every other tank's.
    return Tank(model=TANK_MODEL, x=x, z=z, heading=0.0, loadout=_enemy_loadout())


def test_each_shooter_gets_its_own_round() -> None:
    """Six staged enemies can each have a ballistic round in flight at once —
    the core of behavior (1). The old per-owner gate would have stopped at one."""
    _state, ow = _fresh()
    tanks = [_armed_tank(x=-250.0 + i * 100.0, z=-220.0) for i in range(6)]
    for t in tanks:
        ow.battlefield.add_tank(t)
        fired = t.loadout.active.try_fire(True, t, ow.battlefield, owner="enemy")
        assert fired, "an armed tank with a free gun should fire"

    assert len(ow.battlefield.bullets) == 6, \
        "six shooters -> six concurrent enemy rounds (per-shooter, not per-owner)"
    # every round is owner-tagged 'enemy' (hit path) AND shooter-tagged (gate)
    for t in tanks:
        mine = [b for b in ow.battlefield.bullets if b.shooter is t]
        assert len(mine) == 1, "exactly one live round attributed to each shooter"
        assert mine[0].owner == "enemy", "still owner-tagged for the hit path"


def test_a_shooter_is_capped_at_one() -> None:
    """Per-shooter, not ungated: a tank with a live round can't fire a second,
    and can fire again only once its own round clears (cap defaults to 1)."""
    _state, ow = _fresh()
    t = _armed_tank(x=0.0, z=-220.0)
    ow.battlefield.add_tank(t)

    assert t.loadout.active.can_fire(ow.battlefield, "enemy", t), "free gun first"
    assert t.loadout.active.try_fire(True, t, ow.battlefield, owner="enemy")
    assert not t.loadout.active.can_fire(ow.battlefield, "enemy", t), \
        "its own live round blocks a second (the cap held)"
    assert not t.loadout.active.try_fire(True, t, ow.battlefield, owner="enemy"), \
        "try_fire respects the per-shooter cap too"
    assert len(ow.battlefield.bullets) == 1, "no second round leaked past the cap"

    # round clears -> the same shooter may fire again
    ow.battlefield.bullets.clear()
    assert t.loadout.active.can_fire(ow.battlefield, "enemy", t), \
        "gun frees once the shooter's round is gone"


def test_distinct_shooters_are_independent() -> None:
    """One tank firing must not gate another — the failure the old per-owner
    bucket caused."""
    _state, ow = _fresh()
    a, b = _armed_tank(-80.0, -220.0), _armed_tank(80.0, -220.0)
    for t in (a, b):
        ow.battlefield.add_tank(t)
    a.loadout.active.try_fire(True, a, ow.battlefield, owner="enemy")
    assert not a.loadout.active.can_fire(ow.battlefield, "enemy", a), "A is spent"
    assert b.loadout.active.can_fire(ow.battlefield, "enemy", b), \
        "B is untouched by A's shot"


def test_player_one_shell_rule_survives_a_busy_field() -> None:
    """The player's single-round gate is independent of how much the enemy field
    is firing — five live enemy rounds don't free or block the player's gate,
    and the player still can't double-fire."""
    state, ow = _fresh()
    # five enemies each put a round downrange
    for i in range(5):
        t = _armed_tank(x=-200.0 + i * 100.0, z=-220.0)
        ow.battlefield.add_tank(t)
        t.loadout.active.try_fire(True, t, ow.battlefield, owner="enemy")
    assert len(ow.battlefield.bullets) == 5

    cam = ow.camera
    shell = ow.loadout.active  # active[0] is the ballistic shell
    assert shell.can_fire(ow.battlefield, "player", cam), \
        "a busy enemy field doesn't block the player's own gate"
    assert shell.try_fire(True, cam, ow.battlefield, owner="player")
    assert not shell.can_fire(ow.battlefield, "player", cam), \
        "player still capped at one live shell despite five enemy rounds"
    # legacy no-shooter read (HUD crosshair cue) agrees for the lone player
    assert not ow._can_fire(), "the HUD's per-owner read still sees the player gated"


def _run_all() -> None:
    for fn in (test_each_shooter_gets_its_own_round,
               test_a_shooter_is_capped_at_one,
               test_distinct_shooters_are_independent,
               test_player_one_shell_rule_survives_a_busy_field):
        fn()
        print(f"  PASS  {fn.__name__}")


if __name__ == "__main__":
    _run_all()
    print("Session 7 behavior (1) PASS: per-shooter bullet attribution — six "
          "enemies each fire concurrently, each capped at one; player one-shell "
          "rule intact under a busy field")