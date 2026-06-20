"""
indoor/mob.py — an indoor enemy instance and its melee AI step.

A ``Mob`` is the runtime an ``EnemyDef`` drives: a continuous (x, z) position, a
facing, current hp, and an attack cooldown. ``step`` is one tick of the melee
brain, written against the ``SpatialQuery`` contract (``can_move_to`` /
``line_of_sight``) so it runs identically on the real indoor world or a fake in
tests, and against the shared ``PlayerState`` so a slash routes into the same
pool a tank shell does outdoors.

The melee loop is deliberately small and is the whole of M2.2's enemy brain:

  1. **Aggro is LOS-gated.** A mob engages only while the player is within
     ``sight`` *and* visible (``line_of_sight``) — a wall breaks the chase. No
     omniscient pathing; the dungeon's corridors do the gating.
  2. **Face, then close.** It slews its facing toward the player at
     ``turn_per_tick`` and steps straight at them at ``speed``, resolving the
     move through the world's collision with the same trial-revert slide the
     player uses, so a mob hugs a wall around a corner instead of stopping dead.
  3. **Contact is cadence-gated.** Inside ``attack_range`` it stops and slashes
     every ``attack_cooldown`` ticks for ``damage`` — ``take_damage`` already
     no-ops during the player's respawn grace, and a hit that empties the pool
     spends a life, mirroring the outdoor damage economy exactly.

``hp`` and ``hit`` are wired now though no in-world player weapon drives them
this round (the first-person strike is M2.3): the world culls a mob whose hp
reaches 0, and tests exercise ``hit`` directly, so the kill path is real and
pinned ahead of the weapon that will feed it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from az.indoor.enemies import EnemyDef
from az.indoor.projectile import spawn_bolt

# Movement collision radius — a mob navigates corridors like the player does
# (the player's BODY_RADIUS), not at its slim torso footprint, so it doesn't
# clip wall corners. The torso radius (def.body_radius) is for contact/visual.
ENEMY_RADIUS = 12.0

# Ranged kiting: a gunman holds the band [STANDOFF_MIN, attack_range] — it backs
# off if the player closes inside this, so it stays a ranged problem rather than
# wandering into melee range and standing there.
STANDOFF_MIN = 100.0


def _slew(cur_deg: float, target_deg: float, max_step: float) -> float:
    """Rotate ``cur`` toward ``target`` by at most ``max_step`` degrees, taking
    the shortest signed path (wrap-safe)."""
    d = (target_deg - cur_deg + 180.0) % 360.0 - 180.0
    if abs(d) <= max_step:
        return target_deg % 360.0
    return (cur_deg + math.copysign(max_step, d)) % 360.0


@dataclass
class Mob:
    """One live enemy on a floor. ``cell`` is its spawn grid cell (placement
    metadata); position is continuous from there on."""
    def_: EnemyDef
    x: float
    z: float
    cell: tuple[int, int]
    facing_deg: float = 0.0
    hp: int = 0
    cooldown: int = 0          # ticks until the next attack is allowed

    def __post_init__(self) -> None:
        if self.hp <= 0:
            self.hp = self.def_.hp

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def hit(self, amount: int) -> bool:
        """Take ``amount`` damage; return True if this killed the mob. The path
        the player's indoor weapon will drive (M2.3); pinned now."""
        self.hp -= int(amount)
        return self.hp <= 0

    def step(self, player_x: float, player_z: float, spatial, state):
        """One tick of brain. Shared front half — cooldown, LOS-gated aggro,
        facing — then dispatch on behavior. Melee deals contact damage in place
        and returns ``None``; ranged returns a fired ``Bolt`` (or ``None``) for
        the world to track. Mutates position, facing, and cooldown."""
        if self.cooldown > 0:
            self.cooldown -= 1

        dx, dz = player_x - self.x, player_z - self.z
        dist = math.hypot(dx, dz)

        # LOS-gated aggro — within sight AND a clear line. Breaks the chase and
        # holds the gunman's fire the instant a wall cuts the sightline.
        if dist > self.def_.sight or not spatial.line_of_sight(
                self.x, self.z, player_x, player_z):
            return None

        # face the player
        if dist > 1e-6:
            desired = math.degrees(math.atan2(dx, -dz))
            self.facing_deg = _slew(self.facing_deg, desired,
                                    self.def_.turn_per_tick)

        if self.def_.behavior == "ranged":
            return self._ranged(player_x, player_z, dx, dz, dist, spatial)
        self._melee(dx, dz, dist, spatial, state)
        return None

    def _melee(self, dx, dz, dist, spatial, state) -> None:
        """In range, slash on cadence (damage -> PlayerState); else close in."""
        if dist <= self.def_.attack_range:
            if self.cooldown <= 0:
                state.take_damage(self.def_.damage)
                if state.is_dead:
                    state.lose_life()
                self.cooldown = self.def_.attack_cooldown
            return
        self._move(dx, dz, dist, spatial, +1.0)

    def _ranged(self, px, pz, dx, dz, dist, spatial):
        """Hold a standoff band — close if out of reach, back-pedal if crowded —
        and fire a bolt on cadence while in reach (LOS already confirmed). The
        bolt is returned for the world to fly; the gunman never touches the
        player directly."""
        if dist > self.def_.attack_range:
            self._move(dx, dz, dist, spatial, +1.0)        # close to range
        elif dist < STANDOFF_MIN:
            self._move(dx, dz, dist, spatial, -1.0)        # kite back

        if dist <= self.def_.attack_range and self.cooldown <= 0:
            self.cooldown = self.def_.attack_cooldown
            return spawn_bolt(self.x, self.z, px, pz, self.def_.damage)
        return None

    def _move(self, dx, dz, dist, spatial, sign: float) -> None:
        """Step ``speed`` toward (sign +1) or away from (sign -1) the player,
        resolved with the player's trial-revert slide so a glancing wall slides
        the mob along it instead of halting it."""
        if dist < 1e-6:
            return
        ux, uz = sign * dx / dist, sign * dz / dist
        step = self.def_.speed
        nx, nz = self.x + ux * step, self.z + uz * step
        free, rx, rz = spatial.can_move_to(nx, nz, ENEMY_RADIUS)
        if free:
            self.x, self.z = rx, rz
            return
        fx, ax, _ = spatial.can_move_to(nx, self.z, ENEMY_RADIUS)
        if fx:
            self.x = ax
        else:
            fz, _, bz = spatial.can_move_to(self.x, nz, ENEMY_RADIUS)
            if fz:
                self.z = bz