"""
outdoor/vehicles.py — the three Auto Warfare chassis, as data (M1 increment 4).

A ``VehicleDef`` is the shared definition vision §6 calls for — "a vehicle is
model + hp + drive knobs + loadout" — meant to be consumed two ways: the player
is a vehicle + input, an enemy is the same vehicle + AI. Today only the enemy
embodiment exists (``spawn_vehicle`` builds a Tank the AI drives); the player
embodiment (the camera adopting a def's hp/handling, and the player choosing
Sedan / Pickup / Flatbed off the concept sheet) is the same data when it lands.

The three mirror the concept sheet:

  Sedan   — fast, fragile, pulse MG. The swarm. Dies to one player shell;
            falls to ~4 pulse hits. Cheap. Comes in numbers.
  Pickup   — slow, tough, shell cannon. The bruiser. Two player shells to drop;
            a long, wrong-tool burn for the pulse. Hits hard, telegraphs slow.
  Flatbed — medium, both weapons. The elite. Two shells; rare and late, the
            chassis that forces the player's full kit.

HP is the increment-3 tuning you signed off in the seat; handling is derived
from each chassis's identity against the reference (move 0.35 / turn 0.65 /
engage 600). All are starting points to tune in the window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from az.common.weapon import Loadout
from az.outerworld_engine.tank import Tank
from az.outdoor.models.vehicles import SEDAN_MODEL, PICKUP_MODEL, FLATBED_MODEL
from az.outdoor.weapons import (
    make_enemy_pulse_weapon, make_enemy_shell_weapon,
)


@dataclass(frozen=True, eq=False)
class VehicleDef:
    """A chassis as pure data. ``make_loadout`` is a factory (not a Loadout
    instance) so every spawn gets its own fire-control state — two Pickups must
    not share one cooldown.

    ``eq=False`` (identity equality/hash): the defs are module singletons
    (SEDAN/PICKUP/FLATBED), identity is the right comparison, and it keeps them
    hashable despite the unhashable ``model`` dict — so they work as set members
    and dict keys (the director's weight table, test assertions)."""

    name: str
    model: dict
    max_hp: float
    move_speed: float           # u/tick top (chase) speed   -> Tank.move_speed
    turn_speed_deg: float       # deg/tick                    -> Tank.turn_speed_deg
    engage_distance: float      # world units                 -> Tank.engage_distance
    make_loadout: Callable[[], Loadout]
    score: int


# Each chassis now wears its own faceless wireframe (authored from the concept
# silhouettes in ``outdoor/models/vehicles.py``): the Sedan is the smallest hull
# (smallest hit circle, suits the darting swarm), the Pickup reads heavy through
# height, the Flatbed is the long elite carrier. Identity still *rides* hp +
# handling + loadout + score — the model is the look the dynamics already earned.
SEDAN = VehicleDef(
    name="sedan", model=SEDAN_MODEL, max_hp=40.0,
    move_speed=0.52, turn_speed_deg=0.95, engage_distance=650.0,
    make_loadout=lambda: Loadout([make_enemy_pulse_weapon()]),
    score=1000,
)

PICKUP = VehicleDef(
    name="pickup", model=PICKUP_MODEL, max_hp=120.0,
    move_speed=0.24, turn_speed_deg=0.45, engage_distance=600.0,
    make_loadout=lambda: Loadout([make_enemy_shell_weapon()]),
    score=2500,
)

FLATBED = VehicleDef(
    name="flatbed", model=FLATBED_MODEL, max_hp=80.0,
    move_speed=0.35, turn_speed_deg=0.65, engage_distance=700.0,
    # slot 0 shell (range), slot 1 pulse (close). The world's interim
    # range-based selector picks between them each tick; the real two-weapon
    # choice AI is the deferred enemy-fire pass (vision §7).
    make_loadout=lambda: Loadout([make_enemy_shell_weapon(),
                                  make_enemy_pulse_weapon()]),
    score=4000,
)

ALL_VEHICLES = (SEDAN, PICKUP, FLATBED)


def spawn_vehicle(vdef: VehicleDef, x: float, z: float, *,
                  heading: float = 0.0, ai_seed: int | None = None) -> Tank:
    """Build an enemy Tank embodiment of a VehicleDef: hp, drive knobs, a fresh
    loadout, and the score it's worth, all read off the def. (The player
    embodiment of the same def is future work — see the module docstring.)"""
    return Tank(
        model=vdef.model, x=x, z=z, heading=heading,
        max_hp=vdef.max_hp, hp=vdef.max_hp,
        move_speed=vdef.move_speed, turn_speed_deg=vdef.turn_speed_deg,
        engage_distance=vdef.engage_distance,
        loadout=vdef.make_loadout(),
        score_value=vdef.score,
        ai_seed=ai_seed,
    )