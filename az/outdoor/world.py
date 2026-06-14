"""
outdoor/world.py — the outdoor world, wrapping the real Battlezone engine.

Milestone 1, increment 1: this replaces the M0 from-scratch stub with the
actual ``az.outerworld_engine`` — real Battlefield, Camera, Obstacle, Bullet,
and the real ``render.py`` draw path. The point of this increment is the
*integration*: the genuine BZ sim runs and draws where the scratch boxes were,
with score/lives owned by the shell ``PlayerState`` (the section 3 retrofit),
and nothing else in the shell moving. Enemy autos exist and the player can kill
them for score; enemy *fire* is deliberately deferred (see the damage-model
note at the bottom) so this increment needs no design decision.

Hosting note — the fixed-timestep accumulator
----------------------------------------------
The BZ sim is tuned in **per-tick** units at 60 Hz (forward 0.65/tick, turn
0.6 deg/tick, bullet 2.0/tick, AI countdowns in ticks). The shell drives a
dt-based loop. To host the real sim without altering a single tuned constant,
``update(dt)`` accumulates real time and runs the sim in fixed 16 ms ticks. The
original per-tick logic and constants are ported verbatim; only the *cadence*
is supplied by the shell.

Constants below are ported from ``bz/game.py`` — this wrapper is their new home
now that the QGraphicsView host it lived in is replaced by the shell.
"""

from __future__ import annotations

import math
from typing import Any

from az.outerworld_engine import render
from az.outerworld_engine.battlefield import Battlefield
from az.outerworld_engine.camera import Camera
from az.outerworld_engine.fragment import Fragment
from az.outerworld_engine.obstacle import Obstacle
from az.outerworld_engine.models.cube_model import CUBE_MODEL
from az.outerworld_engine.models.platform_model import PLATFORM_MODEL
from az.outerworld_engine.models.tetra_model import TETRA_MODEL
from az.outerworld_engine.models.texplode1_model import TEXPLODE1_MODEL
from az.outerworld_engine.models.texplode2_model import TEXPLODE2_MODEL
from az.outerworld_engine.models.texplode3_model import TEXPLODE3_MODEL
from az.outerworld_engine.models.texplode4_model import TEXPLODE4_MODEL
from az.outerworld_engine.models.texplode5_model import TEXPLODE5_MODEL
from az.outerworld_engine.models.texplode6_model import TEXPLODE6_MODEL
from az.outdoor.models.buildings import (
    DOORWAY, LARGE_BUILDING, SKYSCRAPER, SMALL_BUILDING, WAREHOUSE,
)

# weapon factory + builders live in outdoor.weapons now (shared by the player
# loadout here and the enemy vehicle loadouts in outdoor.vehicles, no cycle).
# ENEMY_SHELL_DAMAGE and _enemy_loadout are re-exported for the increment-3
# tests and any ad-hoc caller that imported them from this module.
from az.outdoor.weapons import (
    make_player_loadout,
    make_enemy_shell_loadout as _enemy_loadout,
    ENEMY_SHELL_DAMAGE,
)
from az.outdoor.director import Director
from az.shell.mode import InputState, Transition


# --- constants (ported verbatim from bz/game.py) ---------------------------

# --- player drive feel -----------------------------------------------------
# These two are the FEEL KNOBS — the only constants you tune to change how the
# auto drives. They are still expressed in the sim's native per-tick units at
# 60 Hz (so the accumulator and every ENGINE constant below stay verbatim —
# nothing is rescaled to seconds). Conversion: units/sec = value * 60.
#
#   BZ original was a ponderous tank: 0.65/tick (39 u/sec) and 0.6 deg/tick
#   (36 deg/sec — a 90 deg turn took 2.5 s). Auto Warfare drives an armored
#   auto, so it wants weight without sludge. Current values:
#       1.6  /tick  =  96 units/sec   (~13 s to cross the field's 1250 u to
#                                       the skyscraper — was ~32 s)
#       1.1  deg/tick = 66 deg/sec    (90 deg in ~1.4 s, 180 in ~2.7 s)
#   Dial these to taste; everything else is engine-canonical.
PLAYER_FORWARD_SPEED = 1.6       # world units / tick   (feel knob)
PLAYER_TURN_SPEED_DEG = 1.1      # degrees / tick        (feel knob)
PLAYER_RADIUS = 6.0

# --- engine constants (ported verbatim from bz/game.py) --------------------

TICK_DT = 0.016                  # 16 ms — the sim's native fixed timestep
WORLD_HALF_SIZE = 1000.0

# Default score for a bare engine tank. Per-vehicle scores live on the
# VehicleDef now (Sedan 1000, Pickup 2500, Flatbed 4000); this stays as the
# Tank.score_value default and is what the increment-3 tests assert against.
TANK_SCORE = 1000

# Projectile tuning, the damage economy, and all weapon builders now live in
# outdoor.weapons (imported above). ENEMY_SHELL_DAMAGE is re-exported there →
# here for the increment-3 tests.

# Interim two-weapon enemy select (the Flatbed): fire the pulse when the player
# is within this range, the shell beyond it. A placeholder for the real
# weapon-selection AI (vision §7); single-weapon enemies (Sedan, Pickup) never
# reach it.
FLATBED_PULSE_RANGE = 260.0

FOV_DEG, NEAR, FAR = 75.0, 0.5, 6000.0

# the enterable skyscraper — the portal source (POC §9: full dive). The other
# building sizes are pure cover; only this one has a lobby you can enter.
TOWER_ID = "tower_a"
SKYSCRAPER_POS = (0.0, -650.0)   # dead ahead of spawn — the landmark
SKYSCRAPER_HW = 56.0             # half-width; matches the outdoor box
SKYSCRAPER_HD = 56.0             # half-depth; front (+Z) face is at z + HD
TOWER_SEED = 0xA17A              # stable per building -> repeatable interior
ENTER_RANGE = 90.0

# cyberblue phosphor (Auto Warfare identity; BZ's own default is green)
COL_WORLD = (0.0, 0.75, 1.0)
COL_LOBBY = (1.0, 0.85, 0.25)


def _city_blocks() -> list[tuple[dict, float, float, float]]:
    """The deliberate cityscape: (model, x, z, heading) laid out as blocks
    leading to the skyscraper. The skyscraper itself is placed separately as
    the enterable landmark. Warehouses are wide and sit nearer/to the sides;
    small/large towers cluster between spawn and the tower. Headings are
    nudged off-axis so the wireframe city doesn't read as a grid of boxes.
    """
    return [
        (LARGE_BUILDING, -300.0, -480.0, 0.10),
        (LARGE_BUILDING, 330.0, -560.0, -0.18),
        (SMALL_BUILDING, -170.0, -120.0, 0.30),
        (SMALL_BUILDING, 200.0, -40.0, -0.25),
        (SMALL_BUILDING, -330.0, -260.0, 0.0),
        (SMALL_BUILDING, 110.0, -300.0, 0.4),
        (WAREHOUSE, -430.0, 200.0, 0.5),
        (WAREHOUSE, 360.0, 240.0, -0.6),
    ]


# fragment palette for the kill burst / hit spit
_TEXPLODE_MODELS = (
    TEXPLODE1_MODEL, TEXPLODE2_MODEL, TEXPLODE3_MODEL,
    TEXPLODE4_MODEL, TEXPLODE5_MODEL, TEXPLODE6_MODEL,
)


def _spawn_burst(battlefield: Battlefield, x: float, z: float,
                 count: int, rng) -> None:
    """Shatter into wireframe shards at (x, z) — the arcade tank death (and,
    with a small count, the non-lethal hit spit). Each shard flies outward with
    a random velocity, arcs under gravity (Fragment owns that), and tumbles on
    two axes. Purely visual; fragments carry no collision."""
    for _ in range(count):
        model = rng.choice(_TEXPLODE_MODELS)
        ang = rng.uniform(0.0, 2.0 * math.pi)
        speed = rng.uniform(0.6, 1.8)
        battlefield.add_fragment(Fragment(
            model=model,
            x=x, y=rng.uniform(4.0, 12.0), z=z,
            vx=math.sin(ang) * speed,
            vy=rng.uniform(0.8, 2.0),
            vz=-math.cos(ang) * speed,
            spin_y=rng.uniform(-0.3, 0.3),
            spin_x=rng.uniform(-0.3, 0.3),
        ))


class OutdoorWorld:
    name = "outdoor"

    def __init__(self) -> None:
        import random
        self.battlefield = Battlefield(half_size=WORLD_HALF_SIZE)
        self.camera = Camera(x=0.0, z=0.0, heading=0.0)
        self.time_sec = 0.0
        self._accum = 0.0
        self._fx_rng = random.Random(20240613)   # fragment burst/spit jitter

        # the spawn director (M1 increment 4). It owns the enemy roster now —
        # which vehicles, how many — keyed off PlayerState.tier. The field is
        # filled on_enter (it needs the tier from state), not here.
        self.director = Director(seed=20240613)

        self._populate_city()      # buildings + skyscraper + lobby trigger
        self._populate_scene()     # terrain debris, kept clear of footprints

        # the player's weapons (M1 inc 2). Slot 0 ballistic shell (one on
        # screen at a time), slot 1 the heat-gated pulse rifle. Cycle with the
        # weapon-cycle input (bound to Tab in the shell).
        self.loadout = make_player_loadout()

    # --- scene setup -----------------------------------------------------

    def _populate_city(self) -> None:
        """Place the four POC building types as cover, plus the one enterable
        skyscraper with its gold lobby doorway."""
        self._city_centers: list[tuple[float, float]] = []

        for model, x, z, heading in _city_blocks():
            self.battlefield.add(Obstacle(model=model, x=x, z=z, heading=heading))
            self._city_centers.append((x, z))

        sx, sz = SKYSCRAPER_POS
        self._skyscraper = Obstacle(model=SKYSCRAPER, x=sx, z=sz)
        self.battlefield.add(self._skyscraper)
        self._city_centers.append((sx, sz))

        # lobby: a non-solid gold doorway flush to the skyscraper's +Z face;
        # the visible mark for the "E to enter" trigger (not added to the
        # battlefield, so it neither collides nor occludes shots).
        self._lobby = Obstacle(model=DOORWAY, x=sx, z=sz + SKYSCRAPER_HD + 4.0)

    def _populate_scene(self) -> None:
        import random
        rng = random.Random(1)
        margin = 150.0
        lo, hi = -WORLD_HALF_SIZE + margin, WORLD_HALF_SIZE - margin
        keep_out = 220.0   # don't drop debris on top of a building

        def _clear(x: float, z: float) -> bool:
            return all((x - cx) ** 2 + (z - cz) ** 2 > keep_out * keep_out
                       for cx, cz in self._city_centers)

        def place(model: dict, count: int) -> None:
            for _ in range(count):
                for _try in range(20):
                    x, z = rng.uniform(lo, hi), rng.uniform(lo, hi)
                    if abs(x) < 80 and abs(z) < 80:
                        z += 200 * (1 if z >= 0 else -1)
                    if _clear(x, z):
                        break
                self.battlefield.add(Obstacle(model=model, x=x, z=z,
                                              heading=rng.uniform(0, 2 * math.pi)))
        place(TETRA_MODEL, 5)
        place(CUBE_MODEL, 5)
        place(PLATFORM_MODEL, 3)

    def _current_tier(self, state) -> int:
        """The escalation tier the director spawns against. Reads
        ``PlayerState.tier`` (bumped on return-from-dive — the Milestone-3
        ratchet). An ``AWF_TIER`` env var overrides it for in-seat / headless
        testing of the deep curve before there are enough buildings to climb
        the ledger naturally (vision §7's open 'what counts as a tick')."""
        import os
        forced = os.environ.get("AWF_TIER")
        base = getattr(state, "tier", 0)
        if forced is not None:
            try:
                return max(base, int(forced))
            except ValueError:
                pass
        return base

    # --- World protocol --------------------------------------------------

    def on_enter(self, state, payload: dict[str, Any]) -> None:
        self.camera.x, self.camera.z, self.camera.heading = 0.0, 600.0, 0.0

        # Escalation ratchet (vision §6: the single place "return → reinforce →
        # harder" lives). The real Milestone-3 form bumps tier and injects a
        # harder reinforcement on each dive-return; for now tier tracks dives
        # cleared (a progression-derived placeholder, not a clock), and the
        # director fills the persistent field back up to the tier's target —
        # the war kept coming while you were inside. AWF_TIER can force a tier
        # for testing the deep curve (see _current_tier).
        if getattr(state, "tier", 0) < len(state.cleared):
            state.tier = len(state.cleared)
        self.director.fill(self.battlefield, self._current_tier(state),
                           self.camera.x, self.camera.z)

    def on_exit(self, state) -> None:
        pass

    def save_pose(self) -> tuple[float, float, float]:
        return (self.camera.x, self.camera.z, self.camera.heading)

    def restore_pose(self, pose: tuple[float, float, float]) -> None:
        self.camera.x, self.camera.z, self.camera.heading = pose

    def update(self, dt: float, inp: InputState, state) -> Transition | None:
        # weapon cycle is a frame-level UI action (edge intent), applied once
        # per frame — not inside the fixed-step loop, which would over-cycle.
        if inp.cycle:
            self.loadout.cycle()

        # fixed-timestep accumulator: run the native-tick sim under dt drive
        self.time_sec += dt
        self._accum += dt
        steps = 0
        transition: Transition | None = None
        while self._accum >= TICK_DT and steps < 5:
            transition = self._sim_tick(inp, state)
            self._accum -= TICK_DT
            steps += 1
            if transition is not None:
                self._accum = 0.0
                break
        return transition

    @property
    def spatial(self):
        return self

    # --- one native sim tick (ported from game._tick / _handle_input) ----

    def _sim_tick(self, inp: InputState, state) -> Transition | None:
        # Terminal state: once every life is spent the battlefield freezes —
        # input is ignored, enemies hold, and (critically) the damage path below
        # never re-enters lose_life on a corpse. Restart is a shell concern (a
        # fresh PlayerState); this world just stops driving.
        if state.is_game_over:
            return None

        cam = self.camera

        # turn, then move (BZ order)
        if inp.left:
            cam.turn(-math.radians(PLAYER_TURN_SPEED_DEG))
        if inp.right:
            cam.turn(math.radians(PLAYER_TURN_SPEED_DEG))

        old_x, old_z = cam.x, cam.z
        if inp.forward:
            cam.move_forward(PLAYER_FORWARD_SPEED)
        if inp.back:
            cam.move_forward(-PLAYER_FORWARD_SPEED)
        new_x, new_z = cam.x, cam.z

        # trial-revert slide-along
        if (new_x, new_z) != (old_x, old_z) and self._collides_at(new_x, new_z):
            if not self._collides_at(new_x, old_z):
                cam.x, cam.z = new_x, old_z
            elif not self._collides_at(old_x, new_z):
                cam.x, cam.z = old_x, new_z
            else:
                cam.x, cam.z = old_x, old_z
        cam.x, cam.z = self.battlefield.clamp(cam.x, cam.z)

        # fire (held; the active weapon owns its own gate — for the ballistic
        # shell that gate is the canonical one-on-screen-at-a-time rule).
        self.loadout.active.try_fire(inp.fire, cam, self.battlefield,
                                     owner="player")
        # advance every weapon's fire-control one native tick (pulse cooldown +
        # heat cooling), so a holstered rifle still cools while the shell is up.
        self.loadout.tick()

        # enemy AI moves the tanks and decides whether each wants to fire.
        self.battlefield.step_tanks(cam.x, cam.z, cam.heading)
        # enemy fire (increment 3): a tank that wants to fire emits an
        # owner='enemy' round through its OWN Loadout — the same Weapon
        # abstraction the player uses, just owner-tagged. Every armed tank ticks
        # its fire-control each frame so cooldowns/heat advance even when idle.
        for t in self.battlefield.tanks:
            if t.loadout is not None:
                # Interim two-weapon select (the Flatbed): pulse up close, shell
                # at range. A placeholder for the real weapon-selection AI
                # (vision §7); single-weapon enemies have nothing to choose.
                if len(t.loadout.weapons) > 1:
                    dist = math.hypot(cam.x - t.x, cam.z - t.z)
                    t.loadout.select(1 if dist <= FLATBED_PULSE_RANGE else 0)
                if t.ai_wants_fire:
                    t.loadout.active.try_fire(True, t, self.battlefield,
                                              owner="enemy")
                t.loadout.tick()
            t.ai_wants_fire = False   # intent consumed this tick

        # advance bullets. Player rounds chip tank HP (kill at 0 -> score +
        # fragment burst); enemy rounds chip the shared PlayerState pool.
        player_damage, killed, damaged = self.battlefield.step_bullets(
            player_x=cam.x, player_z=cam.z, player_radius=PLAYER_RADIUS)

        if killed:
            # score is per-vehicle now (a Flatbed is worth more than a Sedan)
            state.add_score(sum(t.score_value for t in killed))
            for t in killed:
                _spawn_burst(self.battlefield, t.x, t.z, 9, self._fx_rng)
        for t in damaged:
            # non-lethal hit: a small spit of shards reads the chip even before
            # the damage tint (which draw_tank pulls from hp_fraction).
            _spawn_burst(self.battlefield, t.x, t.z, 2, self._fx_rng)

        # within-tier persistence (M1 increment 4): the director refills the
        # field back toward the tier's population target on a cooldown — losses
        # are felt, then the war answers. This sustains; it does NOT escalate
        # (that's the tier bump on return-from-dive). Runs after the kill pass so
        # this tick's losses are reflected.
        self.director.update(self.battlefield, self._current_tier(state),
                             cam.x, cam.z)

        # player damage routes through the shell-owned pool — the one place a
        # hit *means* something (grace, lives, game over). take_damage no-ops
        # during respawn invulnerability; a hit that empties the pool spends a
        # life (respawn at full + grace in place; 0 lives -> game over flag).
        if player_damage > 0.0:
            state.take_damage(player_damage)
            if state.is_dead:
                state.lose_life()

        self.battlefield.step_fragments()

        if inp.action and self._near_lobby():
            return Transition("indoor", {
                "building":  TOWER_ID,
                "archetype": "skyscraper",
                "footprint": (SKYSCRAPER_HW, SKYSCRAPER_HD),
                "seed":      TOWER_SEED,
            })
        return None

    # --- firing: the BZ projectile factory the player's weapons fire through -
    #
    # The shared common.weapon.Weapon stays engine-neutral by emitting through
    # an injected factory; this is the outdoor world's — it turns a neutral
    # ProjectileSpec + resolved spawn state into a real engine Bullet. (A future
    # indoor weapon would inject a Bane-Projectile factory instead.)

    def _can_fire(self) -> bool:
        """Back-compat shim: the one-shell gate now lives on the active
        weapon's fire-control. Kept so status/HUD callers have a simple read."""
        return self.loadout.active.can_fire(self.battlefield, "player")

    # --- SpatialQuery ----------------------------------------------------

    def _collides_at(self, x: float, z: float) -> bool:
        sweep = PLAYER_RADIUS + 200.0
        for obs in self.battlefield.obstacles_near(x, z, sweep):
            r = PLAYER_RADIUS + obs.bounding_radius
            if (x - obs.x) ** 2 + (z - obs.z) ** 2 < r * r:
                return True
        return False

    def can_move_to(self, x: float, z: float, radius: float
                    ) -> tuple[bool, float, float]:
        was_free = True
        sweep = radius + 200.0
        for obs in self.battlefield.obstacles_near(x, z, sweep):
            dx, dz = x - obs.x, z - obs.z
            d = math.hypot(dx, dz)
            min_d = obs.bounding_radius + radius
            if d < min_d:
                was_free = False
                if d > 1e-6:
                    x, z = obs.x + dx / d * min_d, obs.z + dz / d * min_d
                else:
                    x, z = obs.x + min_d, obs.z
        cx, cz = self.battlefield.clamp(x, z)
        if (cx, cz) != (x, z):
            was_free = False
        return was_free, cx, cz

    def line_of_sight(self, ax, az, bx, bz) -> bool:
        sx, sz = bx - ax, bz - az
        seg2 = sx * sx + sz * sz
        for obs in self.battlefield.obstacles:
            if seg2 <= 1e-9:
                if math.hypot(ax - obs.x, az - obs.z) < obs.bounding_radius:
                    return False
                continue
            t = max(0.0, min(1.0, ((obs.x - ax) * sx + (obs.z - az) * sz) / seg2))
            cx, cz = ax + sx * t, az + sz * t
            if math.hypot(cx - obs.x, cz - obs.z) < obs.bounding_radius:
                return False
        return True

    # --- helpers ---------------------------------------------------------

    def _near_lobby(self) -> bool:
        return math.hypot(self.camera.x - self._lobby.x,
                          self.camera.z - self._lobby.z) <= ENTER_RANGE

    def status_text(self, state) -> str:
        if state.is_game_over:
            return f"GAME OVER  —  no lives remaining   (SCORE {state.score:06d})"
        if self._near_lobby():
            tag = "cleared" if state.has_cleared(TOWER_ID) else "uncleared"
            return f"TOWER LOBBY ({tag}) — press E to enter"
        return "drive: W/S  turn: A/D  fire: SPACE  cycle: TAB   reach the tower"

    def weapon_status(self) -> dict:
        """A small read of the active weapon for the HUD: its name, a heat
        fraction (None for weapons without heat, e.g. the ballistic shell), and
        whether it is currently locked out. The HUD never mutates this."""
        w = self.loadout.active
        return {
            "name": w.name,
            "heat": getattr(w.control, "heat_fraction", None),
            "overheated": getattr(w.control, "overheated", False),
        }

    # --- draw (real render.py) -------------------------------------------

    def draw(self, vp_w: int, vp_h: int) -> None:
        render.setup_frame(vp_w, vp_h, FOV_DEG, NEAR, FAR)
        render.apply_camera(self.camera)
        r, g, b = COL_WORLD
        render.draw_battlefield(self.battlefield, r, g, b, self.time_sec,
                                camera=self.camera)
        render.draw_obstacle(self._lobby, *COL_LOBBY, self.time_sec)