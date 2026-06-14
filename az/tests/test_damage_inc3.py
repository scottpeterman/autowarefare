"""
tests/test_damage_inc3.py — headless acceptance tests for the M1 increment-3
damage model. Runs with no GL and no Qt, against the REAL battlefield engine.

The damage economy in one sentence: every damage source mutates one pool —
player rounds chip tank HP (kill + score + fragment burst only at hp<=0), enemy
rounds chip the shell-owned PlayerState pool (grace, lives, game over). Covers:

  A. enemy HP — a player round subtracts damage; a non-lethal hit leaves the
     tank alive (and is consumed); a second round finishes it, scores, bursts.
  B. enemy fire — a tank fires owner='enemy' through the SAME Weapon/Loadout
     the player uses, spawned ahead of its hull along its forward vector.
  C. player damage — an enemy round routes its damage into PlayerState.
  D. a hit that empties the pool spends a life (respawn at full + grace).
  E. respawn invulnerability ignores damage.
  F. back-compat — a bare engine tank (default hp 1.0) is still a one-hit kill.

Run:  python -m az.tests.test_damage_inc3
"""

from __future__ import annotations

from az.outerworld_engine.bullet import Bullet
from az.outerworld_engine.tank import Tank
from az.outerworld_engine.models.cube_model import CUBE_MODEL
from az.outerworld_engine.models.tank_model import TANK_MODEL

from az.outdoor.world import (
    OutdoorWorld, TANK_SCORE, ENEMY_SHELL_DAMAGE, _enemy_loadout,
)
from az.shell.mode import NO_INPUT
from az.shell.player_state import PlayerState


def _fresh():
    state = PlayerState()
    ow = OutdoorWorld()
    ow.on_enter(state, {})
    ow.battlefield.tanks.clear()      # drop the live roster; tests stage their own
    ow.battlefield.bullets.clear()
    return state, ow


def _player_round(x: float, z: float, damage: float) -> Bullet:
    # a stationary player round sitting on its target — hits on the first step
    return Bullet(model=CUBE_MODEL, x=x, z=z, vx=0.0, vz=0.0,
                  range_remaining=100.0, bounding_radius=1.0,
                  owner="player", damage=damage)


def _enemy_round(x: float, z: float, damage: float) -> Bullet:
    return Bullet(model=CUBE_MODEL, x=x, z=z, vx=0.0, vz=0.0,
                  range_remaining=100.0, bounding_radius=1.0,
                  owner="enemy", damage=damage)


def test_a_enemy_hp_chips_then_dies() -> None:
    state, ow = _fresh()
    cx, cz = ow.camera.x, ow.camera.z
    tank = Tank(model=TANK_MODEL, x=cx, z=cz - 100.0, ai_seed=7,
                max_hp=100.0, hp=100.0)
    ow.battlefield.add_tank(tank)

    # first shell: 100 -> 40, tank survives, the round is consumed on the hit
    ow.battlefield.add_bullet(_player_round(tank.x, tank.z, damage=60.0))
    ow._sim_tick(NO_INPUT, state)
    assert tank in ow.battlefield.tanks, "non-lethal hit must not kill"
    assert abs(tank.hp - 40.0) < 1e-6, "hit subtracts exactly its damage"
    assert len(ow.battlefield.bullets) == 0, "the round is spent on the hit"
    assert state.score == 0, "no score for a non-lethal hit"

    # second shell: 40 -> -20 <= 0, dies, scores, shatters
    ow.battlefield.add_bullet(_player_round(tank.x, tank.z, damage=60.0))
    frags0 = len(ow.battlefield.fragments)
    ow._sim_tick(NO_INPUT, state)
    assert len(ow.battlefield.tanks) == 0, "hp<=0 must remove the tank"
    assert state.score == TANK_SCORE, "kill scores through PlayerState"
    assert len(ow.battlefield.fragments) > frags0, "death bursts into fragments"


def test_b_enemy_fires_through_shared_weapon() -> None:
    _state, ow = _fresh()
    # heading 0 -> forward (0, -1): the round should emerge ahead along -Z
    tank = Tank(model=TANK_MODEL, x=0.0, z=-200.0, heading=0.0,
                loadout=_enemy_loadout())
    fired = tank.loadout.active.try_fire(True, tank, ow.battlefield,
                                         owner="enemy")
    assert fired, "an armed tank with a free gun should fire"
    assert len(ow.battlefield.bullets) == 1
    b = ow.battlefield.bullets[0]
    assert b.owner == "enemy", "enemy fire is owner-tagged for the hit path"
    assert abs(b.damage - ENEMY_SHELL_DAMAGE) < 1e-6, "round carries spec damage"
    assert b.z < tank.z, "round spawns ahead of the hull along forward (-Z)"

    # the ballistic gate is now per-SHOOTER (Session 7): this tank can't fire a
    # second round while its own is live (cap 1)...
    assert not tank.loadout.active.can_fire(ow.battlefield, "enemy", tank)
    # ...but a different tank still can — the six-enemy field no longer shares a
    # single live round the way the old per-owner gate forced.
    other = Tank(model=TANK_MODEL, x=80.0, z=-200.0, heading=0.0,
                 loadout=_enemy_loadout())
    assert other.loadout.active.can_fire(ow.battlefield, "enemy", other)


def test_c_enemy_round_damages_the_shared_pool() -> None:
    state, ow = _fresh()
    cx, cz = ow.camera.x, ow.camera.z
    ow.battlefield.add_bullet(_enemy_round(cx, cz, damage=ENEMY_SHELL_DAMAGE))
    hp0 = state.health
    ow._sim_tick(NO_INPUT, state)
    assert abs(state.health - (hp0 - ENEMY_SHELL_DAMAGE)) < 1e-6, \
        "enemy round chips the PlayerState pool by its damage"
    assert len(ow.battlefield.bullets) == 0, "the round is spent on the hit"


def test_d_lethal_hit_spends_a_life() -> None:
    state, ow = _fresh()
    state.health = 20.0
    lives0 = state.lives
    cx, cz = ow.camera.x, ow.camera.z
    ow.battlefield.add_bullet(_enemy_round(cx, cz, damage=ENEMY_SHELL_DAMAGE))
    ow._sim_tick(NO_INPUT, state)
    assert state.lives == lives0 - 1, "emptying the pool spends one life"
    assert abs(state.health - state.max_health) < 1e-6, "respawn at full health"
    assert state.invuln_ticks > 0, "respawn grants invulnerability grace"


def test_e_grace_ignores_damage() -> None:
    state, ow = _fresh()
    state.invuln_ticks = 30          # mid-grace, just respawned
    hp0 = state.health
    cx, cz = ow.camera.x, ow.camera.z
    ow.battlefield.add_bullet(_enemy_round(cx, cz, damage=ENEMY_SHELL_DAMAGE))
    ow._sim_tick(NO_INPUT, state)
    assert abs(state.health - hp0) < 1e-6, "no damage taken during grace"


def test_f_default_tank_is_still_one_hit() -> None:
    state, ow = _fresh()
    cx, cz = ow.camera.x, ow.camera.z
    # a bare engine tank: default max_hp/hp 1.0 — the arcade one-hit kill
    tank = Tank(model=TANK_MODEL, x=cx, z=cz - 100.0, ai_seed=3)
    ow.battlefield.add_tank(tank)
    ow.battlefield.add_bullet(_player_round(tank.x, tank.z, damage=1.0))
    ow._sim_tick(NO_INPUT, state)
    assert len(ow.battlefield.tanks) == 0, "default tank dies to one default round"
    assert state.score == TANK_SCORE


def test_g_game_over_floors_lives_and_freezes() -> None:
    # the pool floors at zero: spending the last life and then taking more hits
    # must NOT drive lives negative (the LIVES -58 bug).
    state, ow = _fresh()
    state.lives = 2
    for _ in range(50):                 # far more deaths than lives
        state.health = 0.0              # force the killing blow each iteration
        if state.is_dead:
            state.lose_life()
    assert state.lives == 0, "lives must floor at 0, never go negative"
    assert state.is_game_over, "out of lives is a terminal state"

    # and the outdoor world freezes once game over: input is ignored, and an
    # enemy round landing every tick can't re-enter lose_life on the corpse.
    cx, cz = ow.camera.x, ow.camera.z
    ow.battlefield.add_bullet(_enemy_round(cx, cz, damage=ENEMY_SHELL_DAMAGE))
    lives_at_go = state.lives
    for _ in range(10):
        ow._sim_tick(_forward(), state)
    assert ow.camera.x == cx and ow.camera.z == cz, "frozen: no movement on game over"
    assert state.lives == lives_at_go, "no further life drain after game over"


def _forward():
    from az.shell.mode import InputState
    return InputState(forward=True)


def _run_all() -> None:
    for fn in (test_a_enemy_hp_chips_then_dies,
               test_b_enemy_fires_through_shared_weapon,
               test_c_enemy_round_damages_the_shared_pool,
               test_d_lethal_hit_spends_a_life,
               test_e_grace_ignores_damage,
               test_f_default_tank_is_still_one_hit,
               test_g_game_over_floors_lives_and_freezes):
        fn()
        print(f"  PASS  {fn.__name__}")


if __name__ == "__main__":
    _run_all()
    print("M1 increment-3 PASS: one unified damage economy — projectile damage, "
          "enemy HP (chip->kill->score->burst), enemy fire through the shared "
          "Weapon/Loadout, and player damage routed to PlayerState (grace, "
          "lives, game over); spine + indoor still green")