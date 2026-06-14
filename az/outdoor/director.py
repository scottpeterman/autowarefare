"""
outdoor/director.py — the spawn director (M1 increment 4).

One input drives everything: ``tier``, the escalation ledger on PlayerState that
bumps when the player returns from a building dive (the Milestone-3 ratchet —
not a wall clock). From that single integer the director computes two outputs,
exactly the two the chart showed:

  * population_target(tier) — HOW MANY enemies hold the field at once. Rises in
    steps and PLATEAUS at a ceiling. The plateau is this module's share of the
    §7 balance problem: a deep battlefield gets nastier per enemy (the mix
    shifts) but not more numerous, so a thorough-but-unlucky player meets a
    hard-but-bounded field rather than an unbounded swarm.

  * mix_weights(tier) — WHO spawns. A gated, shifting weight table: Sedans only
    early, Pickups unlock mid, Flatbeds gate late and stay rare. Sedans never
    fall to zero (a floor), so the swarm stays a threat even at the top.

The director also REFILLS to the population target within a tier — kill two and
the war sends two more of the current mix, on a cooldown. That is persistence,
not escalation: it keeps the field from going quiet and farmable after a clear,
and it never moves the tier. Escalation only happens when ``tier`` changes.

Nothing here runs a clock or reads score. Tier in, roster out.
"""

from __future__ import annotations

import math
import random

from az.outdoor.vehicles import (
    FLATBED, PICKUP, SEDAN, VehicleDef, spawn_vehicle,
)

# --- population: rises in steps, plateaus at a ceiling ---------------------
BASE_POPULATION = 2            # tier 0 — a two-Sedan skirmish
POPULATION_PER_TIER = 1 / 3.0  # +1 enemy every 3 tiers
MAX_POPULATION = 6             # the plateau (the §7 anti-unwinnable ceiling)

# --- mix: gated, shifting weights ------------------------------------------
# Sedan: starts dominant, decays, but never below its floor (the swarm endures).
SEDAN_TOP = 6.0
SEDAN_DECAY = 0.45             # weight lost per tier
SEDAN_FLOOR = 1.5
# Pickup: hard-gated, then ramps to a cap (the mid-game bruiser fight).
PICKUP_TIER = 2
PICKUP_RAMP = 1.0             # weight gained per tier past the gate
PICKUP_MAX = 5.0
# Flatbed: gated late, ramps slowly to a low cap (the rare elite).
FLATBED_TIER = 6
FLATBED_RAMP = 0.4
FLATBED_MAX = 1.5

# --- refill cadence + spawn geometry ---------------------------------------
SPAWN_INTERVAL_TICKS = 90      # ~1.5 s between reinforcement spawns @ 60 Hz
SPAWN_RING = 850.0             # spawn this far from the player — they drive in
SPAWN_MARGIN = 60.0            # keep spawns inside the world square


def population_target(tier: int) -> int:
    """How many enemies should hold the field at this tier (capped)."""
    n = BASE_POPULATION + int(math.floor(max(0, tier) * POPULATION_PER_TIER))
    return max(BASE_POPULATION, min(MAX_POPULATION, n))


def mix_weights(tier: int) -> list[tuple[VehicleDef, float]]:
    """The spawn weight table at this tier — only entries with weight > 0
    (i.e. unlocked). Sedan is always present; Pickup/Flatbed gate in."""
    tier = max(0, tier)
    out: list[tuple[VehicleDef, float]] = []

    sedan_w = max(SEDAN_FLOOR, SEDAN_TOP - SEDAN_DECAY * tier)
    out.append((SEDAN, sedan_w))

    if tier >= PICKUP_TIER:
        pickup_w = min(PICKUP_MAX, PICKUP_RAMP * (tier - PICKUP_TIER + 1))
        if pickup_w > 0:
            out.append((PICKUP, pickup_w))

    if tier >= FLATBED_TIER:
        flatbed_w = min(FLATBED_MAX, FLATBED_RAMP * (tier - FLATBED_TIER + 1))
        if flatbed_w > 0:
            out.append((FLATBED, flatbed_w))

    return out


class Director:
    """Holds the field at the tier's population target, spawning the tier's mix
    on a cooldown. Stateless w.r.t. difficulty — it's handed ``tier`` each call
    and owns no clock."""

    def __init__(self, seed: int | None = 0) -> None:
        self._rng = random.Random(seed)
        self._cooldown = 0

    # --- queries (pure) ---
    def population_target(self, tier: int) -> int:
        return population_target(tier)

    def mix_weights(self, tier: int) -> list[tuple[VehicleDef, float]]:
        return mix_weights(tier)

    # --- spawning ---
    def _roll(self, tier: int) -> VehicleDef:
        table = mix_weights(tier)
        vdefs = [v for v, _ in table]
        weights = [w for _, w in table]
        return self._rng.choices(vdefs, weights=weights, k=1)[0]

    def _spawn_point(self, battlefield, player_x: float, player_z: float
                     ) -> tuple[float, float]:
        ang = self._rng.uniform(0.0, 2.0 * math.pi)
        x = player_x + math.sin(ang) * SPAWN_RING
        z = player_z - math.cos(ang) * SPAWN_RING
        half = battlefield.half_size - SPAWN_MARGIN
        return (max(-half, min(half, x)), max(-half, min(half, z)))

    def _spawn_one(self, battlefield, tier: int,
                   player_x: float, player_z: float) -> None:
        vdef = self._roll(tier)
        x, z = self._spawn_point(battlefield, player_x, player_z)
        # face roughly toward the player so it engages on arrival
        heading = math.atan2(player_x - x, -(player_z - z))
        battlefield.add_tank(spawn_vehicle(
            vdef, x, z, heading=heading,
            ai_seed=self._rng.randint(0, 2**31 - 1),
        ))

    def fill(self, battlefield, tier: int,
             player_x: float, player_z: float) -> None:
        """Top the field up to the tier's population target immediately (world
        start, and each return-from-dive: the persistent field reinforced back
        to strength). Does nothing if already at/over target."""
        while len(battlefield.tanks) < population_target(tier):
            self._spawn_one(battlefield, tier, player_x, player_z)
        self._cooldown = SPAWN_INTERVAL_TICKS

    def update(self, battlefield, tier: int,
               player_x: float, player_z: float) -> None:
        """One tick of within-tier persistence: if the field is below target and
        the reinforcement cooldown has elapsed, drive one replacement in. One at
        a time — losses are felt before the war answers."""
        if self._cooldown > 0:
            self._cooldown -= 1
        if (len(battlefield.tanks) < population_target(tier)
                and self._cooldown <= 0):
            self._spawn_one(battlefield, tier, player_x, player_z)
            self._cooldown = SPAWN_INTERVAL_TICKS