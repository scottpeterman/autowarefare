"""
common/weapon.py — the one weapon concept both worlds share (POC design sec 9).

POC §9 left an open question: "Bane's ``StaffState`` becomes a gun; outdoor
already has bullet logic. Reconcile into one weapon concept or keep per-world."
This module is the reconciliation. A **weapon** is a *projectile spec* plus a
*fire-control*, and a player carries a *loadout* of them. The outdoor shell
cannon and (later) the interior's staff-as-gun are then the SAME concept with
different specs and controls — not two firing code paths.

What a weapon is
----------------
  - ``ProjectileSpec`` — the round's shape and physics: model, speed, range,
    scale, hit radius, spawn offset, fly height. Pure data; no engine type.
  - ``FireControl`` — the *gate*: given the trigger and the live battlefield,
    decide whether a round is emitted this tick, and own any cooldown clock.
    ``BallisticFireControl`` is the canonical Battlezone gate (one live round
    of your own on screen at a time). A cadence/heat control for a rapid-fire
    weapon is a second implementation that slots in beside it — its economy
    (unlimited / finite ammo / heat) is a gameplay decision, deferred here.
  - ``Weapon`` — binds a spec to a control and knows the firing *geometry*
    (spawn ahead of the shooter along its forward vector, inherit heading).
  - ``Loadout`` — the list of weapons + the active index, with select/cycle.
    Input *binding* (number keys vs a cycle key) is a shell concern and is
    intentionally NOT wired here.

Why this lives in ``common/`` and stays engine-neutral
------------------------------------------------------
Like ``model``, ``motion``, and ``spatial``, this module imports nothing from
either engine, so both worlds can depend on it without either depending on the
other. It never constructs an engine-specific projectile itself; instead each
world injects a ``ProjectileFactory`` that builds its own projectile type (the
outdoor world supplies a BZ ``Bullet`` factory; a future indoor weapon supplies
a Bane ``Projectile`` factory). The ``battlefield`` and ``shooter`` arguments
are duck-typed — the control reads ``battlefield.bullets`` (each with an
``owner``) and the geometry reads ``shooter.forward`` / ``.x`` / ``.z`` /
``.heading`` — so no concrete class crosses the seam.

Pure logic + small dataclasses. No GL, no Qt, no engine imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


# --- the projectile a weapon emits -----------------------------------------

@dataclass(frozen=True)
class ProjectileSpec:
    """Everything about a round except *when* it is allowed to fire.

    Decoupled exactly the way the engine ``Bullet`` already decouples them:
    ``scale`` (visual size of the model) is independent of ``radius`` (the 2D
    hit circle), so a big-looking shell and a tiny tracer can both keep tight,
    fair collision. Speed/range are in the host world's native units (per-tick
    for the BZ sim); the factory is what turns this spec into a live round.
    """
    model: dict
    speed: float            # world units per tick (matches PLAYER_FORWARD_SPEED)
    max_range: float        # world units of travel before the round fades
    scale: float = 1.0      # per-instance model scale (visual only)
    radius: float = 1.0     # 2D collision radius (independent of scale)
    spawn_offset: float = 12.0   # spawned this far ahead of the shooter
    fly_height: float = 6.0      # world Y the round flies at (gun level)


# A world hands the weapon a factory that builds *its* projectile type from a
# spec + resolved spawn state, keeping this module free of any engine import.
#   (spec, x, z, y, vx, vz, heading, owner) -> projectile object
ProjectileFactory = Callable[
    [ProjectileSpec, float, float, float, float, float, float, str], Any]


# --- the fire-control: the gate + its clock --------------------------------

@runtime_checkable
class FireControl(Protocol):
    """Decides whether a weapon emits a round this tick, and owns any cooldown.

    ``update`` is called once per sim tick with the *held* trigger state; it
    advances any internal clock and returns True on the ticks a round should be
    emitted. ``can_fire`` is a side-effect-free predicate (for the HUD's
    crosshair-while-ready cue and for tests) — it answers "would a fire attempt
    succeed right now?" without consuming anything.
    """

    def update(self, trigger_held: bool, battlefield: Any, owner: str) -> bool:
        ...

    def can_fire(self, battlefield: Any, owner: str) -> bool:
        ...

    def tick(self) -> None:
        """Per-tick maintenance, called for EVERY weapon in the loadout each
        sim tick — active or holstered — so cooldowns and heat keep advancing
        even while a weapon is put away. Stateless controls make this a no-op."""
        ...


@dataclass
class BallisticFireControl:
    """The canonical Battlezone gate: one live round of your own on screen at a
    time. The next round cannot fire until the previous one has hit something
    or exhausted its range — the exact rule the arcade enforced and the reason
    the crosshair blinks out while a shell is in flight. Stateless: the gate is
    read entirely from the live ``battlefield.bullets``, so it needs no clock.
    """

    def can_fire(self, battlefield: Any, owner: str) -> bool:
        return not any(b.owner == owner for b in battlefield.bullets)

    def update(self, trigger_held: bool, battlefield: Any, owner: str) -> bool:
        return trigger_held and self.can_fire(battlefield, owner)

    def tick(self) -> None:
        return  # stateless — the gate is read live from the battlefield


@dataclass
class HeatFireControl:
    """A pulse-rifle gate: rapid cadence with a heat budget that overheats.

    Each shot adds ``heat_per_shot`` and starts a ``cadence_ticks`` cooldown;
    every tick bleeds ``cool_per_tick`` of heat off. Reaching ``max_heat`` trips
    an overheat lockout that does not clear until heat falls back to
    ``reengage`` * max — hysteresis, so the weapon doesn't stutter on/off right
    at the cap. ``can_fire`` is False while overheated or mid-cadence.

    All fields are tunable feel knobs (per-tick units at 60 Hz, like the drive
    knobs); the pulse rifle sets them at its build site in outdoor/world.py.
    Engine-neutral: it reads nothing from the battlefield, only its own clock.
    """
    cadence_ticks: int = 5        # ticks between rounds (5 @ 60 Hz = 12 rps)
    heat_per_shot: float = 0.06   # heat added per round (max_heat = 1.0)
    cool_per_tick: float = 0.006  # heat bled off each tick
    reengage: float = 0.35        # clear overheat once heat <= reengage * max
    max_heat: float = 1.0

    heat: float = 0.0             # state: current heat (0..max_heat)
    cooldown: int = 0             # state: ticks until the next round is allowed
    overheated: bool = False      # state: locked out until heat cools to reengage

    @property
    def heat_fraction(self) -> float:
        """0.0–1.0 for the HUD heat gauge."""
        if self.max_heat <= 0:
            return 0.0
        return max(0.0, min(1.0, self.heat / self.max_heat))

    def can_fire(self, battlefield: Any, owner: str) -> bool:
        return (not self.overheated) and self.cooldown <= 0

    def update(self, trigger_held: bool, battlefield: Any, owner: str) -> bool:
        if not (trigger_held and self.can_fire(battlefield, owner)):
            return False
        self.heat += self.heat_per_shot
        self.cooldown = self.cadence_ticks
        if self.heat >= self.max_heat:
            self.heat = self.max_heat
            self.overheated = True
        return True

    def tick(self) -> None:
        if self.cooldown > 0:
            self.cooldown -= 1
        if self.heat > 0.0:
            self.heat = max(0.0, self.heat - self.cool_per_tick)
        if self.overheated and self.heat <= self.reengage * self.max_heat:
            self.overheated = False


# --- the weapon: spec + control + firing geometry --------------------------

@dataclass
class Weapon:
    """A named weapon = projectile spec + fire-control + a projectile factory.

    ``try_fire`` is the per-tick entry point the world calls. It asks the
    control whether to emit (passing the held trigger and the live
    battlefield), and on a yes it spawns one round ahead of the shooter along
    its forward vector, inheriting the shooter's heading, with velocity =
    forward * spec.speed. Returns True iff a round was emitted this tick.
    """
    name: str
    spec: ProjectileSpec
    control: FireControl
    make_projectile: ProjectileFactory

    def can_fire(self, battlefield: Any, owner: str = "player") -> bool:
        return self.control.can_fire(battlefield, owner)

    def try_fire(self, trigger_held: bool, shooter: Any, battlefield: Any,
                 owner: str = "player") -> bool:
        if not self.control.update(trigger_held, battlefield, owner):
            return False
        fx, fz = shooter.forward
        s = self.spec
        round_ = self.make_projectile(
            s,
            shooter.x + fx * s.spawn_offset,
            shooter.z + fz * s.spawn_offset,
            s.fly_height,
            fx * s.speed,
            fz * s.speed,
            shooter.heading,
            owner,
        )
        battlefield.add_bullet(round_)
        return True


# --- the loadout: what the player is carrying ------------------------------

@dataclass
class Loadout:
    """The player's weapons and which one is active. The mechanism only —
    binding keys to ``select``/``cycle`` is a shell decision (number keys vs a
    cycle key) and is deliberately left to the input layer.
    """
    weapons: list[Weapon] = field(default_factory=list)
    active_index: int = 0

    @property
    def active(self) -> Weapon:
        return self.weapons[self.active_index]

    def select(self, index: int) -> bool:
        """Make weapon ``index`` active. Returns False (no change) if out of
        range, so a bound key for a slot that isn't filled is simply inert."""
        if 0 <= index < len(self.weapons):
            self.active_index = index
            return True
        return False

    def cycle(self, step: int = 1) -> None:
        """Advance the active weapon, wrapping. ``step=-1`` cycles backward."""
        if self.weapons:
            self.active_index = (self.active_index + step) % len(self.weapons)

    def tick(self) -> None:
        """Advance every weapon's fire-control one sim tick (cooldowns, heat
        cooling), so a holstered pulse rifle still cools while the shell is up.
        The world calls this once per native tick, beside the active weapon's
        try_fire."""
        for weapon in self.weapons:
            weapon.control.tick()
