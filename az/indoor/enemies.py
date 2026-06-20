"""
indoor/enemies.py — the indoor enemy definitions (the EnemyDef table).

The interior analogue of ``outdoor/vehicles.py``'s ``VehicleDef``: each mobster
is ``model + hp + movement + attack profile`` as one immutable record, compared
by identity, that the AI and placement read. The numbers come straight from the
design tool's Bane-schema stats (``tools/mobsters.py`` — the same fields the
shipped ``ghost_monster.json`` carried), converted **once, here**, from Bane's
human-readable convention into the indoor world's native per-tick units:

  - distances (sight, attack range) are authored in Bane "cells"; the indoor
    world is continuous at ``CELL_SIZE``-scaled units, so they scale by
    ``DIST_SCALE``.
  - speed is authored per-tick in Bane units; ``SPEED_SCALE`` brings it onto the
    indoor world's ``INDOOR_FORWARD_SPEED`` (=3.0 u/tick) scale — the knifeman
    lands just under the player so a cornered player can still be caught.
  - ``attack_interval`` (seconds) and ``turn_speed`` (deg/sec) become ticks and
    deg/tick against the 16 ms fixed step.

Keeping the raw Bane numbers beside the scales (rather than baking the derived
values in) means the feel stays tunable in tool units and the relationship is
legible. The bodies are the baked, numpy-free wireframes from
``indoor/models/mobsters.py``.

Roster note: ``behavior`` is "melee" for the thug and knifeman and "ranged" for
the gunman, which fires the slow bolt in ``projectile.py`` (M2.3, wired).
``LIVE_ROSTER`` is what placement fields — a melee-weighted multiset so the
gunman stays a minority threat. ``MELEE_ROSTER`` is kept for melee-only callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from az.indoor.models.mobsters import MODELS

# --- Bane-schema -> indoor-native conversion (documented, one place) ---------
TICK_DT = 0.016          # 16 ms fixed step (matches indoor/world.py)
DIST_SCALE = 35.0        # Bane "cell" distance  -> indoor world units
SPEED_SCALE = 2.2        # Bane units/tick        -> indoor units/tick. Tuned by
                         # play: the knifeman lands ~0.55x the player (3.0/tick),
                         # fast enough to corner you but slow enough to kite.


@dataclass(frozen=True)
class EnemyDef:
    """One indoor enemy archetype: body + combat profile, in indoor-native
    units. Module singletons compared by identity, like ``VehicleDef``."""
    name: str
    behavior: str            # "melee" | "ranged"
    hp: int
    damage: float            # into the shared PlayerState pool on a hit
    speed: float             # indoor world units / tick
    sight: float             # aggro distance, indoor units (then LOS-gated)
    attack_range: float      # contact distance, indoor units (centre-to-centre)
    attack_cooldown: int     # ticks between attacks
    turn_per_tick: float     # degrees / tick (facing slew)
    body_radius: float       # torso footprint, indoor units (grid collision)
    model: dict              # baked {'lines', 'body_radius'}


def _from_bane(name: str, *, behavior: str, hp: int, damage: float,
               speed: float, sight: float, attack_range: float,
               attack_interval_s: float, turn_deg_s: float) -> EnemyDef:
    """Build a def from the tool's Bane-schema stats, applying the conversions."""
    model = MODELS[name]
    return EnemyDef(
        name=name,
        behavior=behavior,
        hp=hp,
        damage=damage,
        speed=speed * SPEED_SCALE,
        sight=sight * DIST_SCALE,
        attack_range=attack_range * DIST_SCALE,
        attack_cooldown=max(1, round(attack_interval_s / TICK_DT)),
        turn_per_tick=turn_deg_s * TICK_DT,
        body_radius=model["body_radius"],
        model=model,
    )


# The three clone-mobsters (stats mirror tools/mobsters.py exactly).
THUG = _from_bane(
    "thug", behavior="melee",
    hp=3, damage=10, speed=0.45, sight=9.0, attack_range=1.5,
    attack_interval_s=1.0, turn_deg_s=140.0,
)
KNIFEMAN = _from_bane(
    "knifeman", behavior="melee",
    hp=1, damage=14, speed=0.75, sight=10.0, attack_range=1.3,
    attack_interval_s=0.8, turn_deg_s=200.0,
)
GUNMAN = _from_bane(
    "gunman", behavior="ranged",
    hp=2, damage=8, speed=0.40, sight=14.0, attack_range=9.0,
    attack_interval_s=1.5, turn_deg_s=160.0,
)

# The live placement roster. Multiset, so ``random.choice`` weights it: melee is
# the body of the threat, the gunman a ~20% punctuation — ranged everywhere would
# be a crossfire, not a dungeon. Tune the mix by changing the repeats.
MELEE_ROSTER: tuple[EnemyDef, ...] = (THUG, KNIFEMAN)
LIVE_ROSTER: tuple[EnemyDef, ...] = (THUG, THUG, KNIFEMAN, KNIFEMAN, GUNMAN)
ALL_DEFS: tuple[EnemyDef, ...] = (THUG, KNIFEMAN, GUNMAN)
BY_NAME = {d.name: d for d in ALL_DEFS}