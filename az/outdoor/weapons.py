"""
outdoor/weapons.py — the outdoor world's projectile factory and weapon
builders, factored out of world.py (M1 increment 4).

Both the player loadout (world.py) and the enemy vehicle loadouts (vehicles.py)
build from here, so there is one home for the BZ bullet factory and the
projectile tuning — and no import cycle (this module imports only common.weapon,
the engine Bullet, and the projectile models; never world or vehicles).

Weapon damage is ASYMMETRIC by deliberate choice (the increment-4 balance fork
we settled): a vehicle's weapon firing the SAME damage at anyone would be the
"symmetric" route, but it would make a Pickup's shell do the player's 60 and
two-shot the pool. Instead enemy weapons keep their own, softer specs — the
25-damage shell, the 5-damage MG — so the feel tuned in increment 3 holds and
balance rides HP / population / respawn grace rather than a nerf bus. Player
specs stay at shell 60 / pulse 12. Owner-tagging at fire time still decides
who-hits-whom; this is only about the numbers.
"""

from __future__ import annotations

from az.common.weapon import (
    BallisticFireControl, HeatFireControl, Loadout, ProjectileSpec, Weapon,
)
from az.outerworld_engine.bullet import Bullet
from az.outdoor.models.projectiles import (
    SHELL_MODEL, SHELL_SCALE, TRACER_MODEL, TRACER_SCALE,
)

# --- projectile constants (per-tick units @ 60 Hz; ported from bz/game.py) ---

BULLET_SPEED = 2.0               # units / tick
BULLET_RANGE = 1000.0
BULLET_RADIUS = 1.0
BULLET_MODEL_SCALE = SHELL_SCALE  # shell authored at world size -> 1.0
BULLET_SPAWN_OFFSET = 12.0
BULLET_Y = 4.5

# pulse rifle — faster, lighter, shorter-reaching tracer than the shell
TRACER_SPEED = 5.0               # units / tick (300 u/sec — 2.5x the shell)
TRACER_RANGE = 700.0
TRACER_RADIUS = 0.8
TRACER_SPAWN_OFFSET = 12.0
TRACER_Y = 4.5

# --- the unified damage economy (see module docstring on asymmetry) ---------

SHELL_DAMAGE = 60.0          # player shell vs enemy HP
PULSE_DAMAGE = 12.0          # player pulse vs enemy HP (per hit)
ENEMY_SHELL_DAMAGE = 25.0    # enemy shell vs the player pool (the Pickup's hit)
ENEMY_PULSE_DAMAGE = 5.0     # enemy pulse vs the player pool (the Sedan's chip)

# Enemy rounds emerge from the front of the ~27u tank hull, so their spawn
# offset is larger than the player's (the player is a first-person eye, not a
# 48u body).
ENEMY_SHELL_SPAWN_OFFSET = 34.0
ENEMY_PULSE_SPAWN_OFFSET = 30.0


def bz_bullet_factory(spec: ProjectileSpec, x: float, z: float, y: float,
                      vx: float, vz: float, heading: float, owner: str
                      ) -> Bullet:
    """ProjectileFactory: a neutral spec + resolved spawn state -> a real engine
    ``Bullet``. The seam that lets the shared Weapon stay free of any engine
    import while still firing genuine BZ rounds. (A future indoor weapon injects
    a Bane-Projectile factory instead.)"""
    return Bullet(
        model=spec.model, x=x, z=z, y=y, vx=vx, vz=vz,
        range_remaining=spec.max_range, heading=heading,
        scale=spec.scale, bounding_radius=spec.radius, owner=owner,
        damage=spec.damage,
    )


# --- player weapons --------------------------------------------------------

def make_shell_weapon() -> Weapon:
    """The ballistic shell: one on screen at a time, big hit, the canonical BZ
    main gun."""
    return Weapon(
        name="shell",
        spec=ProjectileSpec(
            model=SHELL_MODEL, speed=BULLET_SPEED, max_range=BULLET_RANGE,
            scale=BULLET_MODEL_SCALE, radius=BULLET_RADIUS,
            spawn_offset=BULLET_SPAWN_OFFSET, fly_height=BULLET_Y,
            damage=SHELL_DAMAGE,
        ),
        control=BallisticFireControl(),
        make_projectile=bz_bullet_factory,
    )


def make_pulse_weapon() -> Weapon:
    """The pulse rifle: heat-gated rapid-fire tracer (the Blade Runner side of
    the look). 12 rounds/sec, ~2.8 s of held fire to overheat, ~1.8 s lockout."""
    return Weapon(
        name="pulse",
        spec=ProjectileSpec(
            model=TRACER_MODEL, speed=TRACER_SPEED, max_range=TRACER_RANGE,
            scale=TRACER_SCALE, radius=TRACER_RADIUS,
            spawn_offset=TRACER_SPAWN_OFFSET, fly_height=TRACER_Y,
            damage=PULSE_DAMAGE,
        ),
        control=HeatFireControl(
            cadence_ticks=5, heat_per_shot=0.06,
            cool_per_tick=0.006, reengage=0.35,
        ),
        make_projectile=bz_bullet_factory,
    )


def make_player_loadout() -> Loadout:
    """Slot 0 shell, slot 1 pulse — cycled with Tab in the shell."""
    return Loadout([make_shell_weapon(), make_pulse_weapon()])


# --- enemy weapons (softer specs; see module docstring) --------------------

def make_enemy_shell_weapon() -> Weapon:
    """The Pickup's bed cannon (and any shell-armed enemy): one big, slow hit on
    the canonical one-on-screen ballistic gate."""
    return Weapon(
        name="enemy-shell",
        spec=ProjectileSpec(
            model=SHELL_MODEL, speed=BULLET_SPEED, max_range=BULLET_RANGE,
            scale=BULLET_MODEL_SCALE, radius=BULLET_RADIUS,
            spawn_offset=ENEMY_SHELL_SPAWN_OFFSET, fly_height=BULLET_Y,
            damage=ENEMY_SHELL_DAMAGE,
        ),
        control=BallisticFireControl(),
        make_projectile=bz_bullet_factory,
    )


def make_enemy_pulse_weapon() -> Weapon:
    """The Sedan's roof MG: rapid, light, heat-limited chip. (Truly rapid enemy
    spray and two-weapon selection are the deferred enemy-fire-AI pass, vision
    §7; the weapon data is correct now so that pass is pure behavior.)"""
    return Weapon(
        name="enemy-pulse",
        spec=ProjectileSpec(
            model=TRACER_MODEL, speed=TRACER_SPEED, max_range=TRACER_RANGE,
            scale=TRACER_SCALE, radius=TRACER_RADIUS,
            spawn_offset=ENEMY_PULSE_SPAWN_OFFSET, fly_height=BULLET_Y,
            damage=ENEMY_PULSE_DAMAGE,
        ),
        control=HeatFireControl(
            cadence_ticks=8, heat_per_shot=0.05,
            cool_per_tick=0.008, reengage=0.30,
        ),
        make_projectile=bz_bullet_factory,
    )


def make_enemy_shell_loadout() -> Loadout:
    """A shell-armed enemy's weapons — one ballistic shell, own fire-control
    state per instance. (Re-exported by world.py as the back-compat
    ``_enemy_loadout`` the increment-3 tests use.)"""
    return Loadout([make_enemy_shell_weapon()])