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
from az.outerworld_engine.bullet import Bullet
from az.outerworld_engine.camera import Camera
from az.outerworld_engine.obstacle import Obstacle
from az.outerworld_engine.tank import Tank
from az.outerworld_engine.models.cube_model import CUBE_MODEL
from az.outerworld_engine.models.platform_model import PLATFORM_MODEL
from az.outerworld_engine.models.tank_model import TANK_MODEL
from az.outerworld_engine.models.tetra_model import TETRA_MODEL
from az.outdoor.models.buildings import (
    DOORWAY, LARGE_BUILDING, SKYSCRAPER, SMALL_BUILDING, WAREHOUSE,
)
from az.outdoor.models.projectiles import (
    SHELL_MODEL, SHELL_SCALE, TRACER_MODEL, TRACER_SCALE,
)

from az.common.weapon import (
    BallisticFireControl, HeatFireControl, Loadout, ProjectileSpec, Weapon,
)
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


BULLET_SPEED = 2.0               # units / tick
BULLET_RANGE = 1000.0
BULLET_RADIUS = 1.0
BULLET_MODEL_SCALE = SHELL_SCALE  # shell authored at world size -> 1.0
BULLET_SPAWN_OFFSET = 12.0
BULLET_Y = 4.5

TANK_SCORE = 1000

# --- pulse rifle (rapid-fire weapon, M1 inc 2) -----------------------------
# Faster, lighter, shorter-reaching round than the shell — a tracer streak the
# heat-gated rifle sprays. Speed/range in per-tick units like everything else.
TRACER_SPEED = 5.0               # units / tick (300 u/sec — 2.5x the shell)
TRACER_RANGE = 700.0
TRACER_RADIUS = 0.8
TRACER_SPAWN_OFFSET = 12.0
TRACER_Y = 4.5

FOV_DEG, NEAR, FAR = 75.0, 0.5, 6000.0

# the enterable skyscraper — the portal source (POC §9: full dive). The other
# building sizes are pure cover; only this one has a lobby you can enter.
TOWER_ID = "tower_a"
SKYSCRAPER_POS = (0.0, -650.0)   # dead ahead of spawn — the landmark
SKYSCRAPER_HD = 56.0             # half-depth; front (+Z) face is at z + HD
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


def _bz_bullet_factory(spec: ProjectileSpec, x: float, z: float, y: float,
                       vx: float, vz: float, heading: float, owner: str
                       ) -> Bullet:
    """Outdoor world's ProjectileFactory: a neutral spec + resolved spawn state
    -> a real engine ``Bullet``. The seam that lets the shared Weapon stay free
    of any engine import while still firing genuine BZ rounds."""
    return Bullet(
        model=spec.model, x=x, z=z, y=y, vx=vx, vz=vz,
        range_remaining=spec.max_range, heading=heading,
        scale=spec.scale, bounding_radius=spec.radius, owner=owner,
    )


def _shell_weapon() -> Weapon:
    """The ballistic shell — the relocated _fire/_can_fire behavior, now a
    Weapon. Same shell model, same per-tick speed/range/radius/offset, and the
    canonical one-on-screen gate, just expressed as spec + control."""
    return Weapon(
        name="shell",
        spec=ProjectileSpec(
            model=SHELL_MODEL,
            speed=BULLET_SPEED,
            max_range=BULLET_RANGE,
            scale=BULLET_MODEL_SCALE,
            radius=BULLET_RADIUS,
            spawn_offset=BULLET_SPAWN_OFFSET,
            fly_height=BULLET_Y,
        ),
        control=BallisticFireControl(),
        make_projectile=_bz_bullet_factory,
    )


def _pulse_weapon() -> Weapon:
    """The pulse rifle — a heat-gated rapid-fire tracer weapon (the Blade
    Runner side of the look). Fires fast, light rounds until it overheats, then
    locks out until it cools. The heat numbers are feel knobs, set here:
    12 rounds/sec, ~2.8 s of held fire to overheat, ~1.8 s lockout to re-engage.
    """
    return Weapon(
        name="pulse",
        spec=ProjectileSpec(
            model=TRACER_MODEL,
            speed=TRACER_SPEED,
            max_range=TRACER_RANGE,
            scale=TRACER_SCALE,
            radius=TRACER_RADIUS,
            spawn_offset=TRACER_SPAWN_OFFSET,
            fly_height=TRACER_Y,
        ),
        control=HeatFireControl(
            cadence_ticks=5,        # 12 rounds/sec @ 60 Hz
            heat_per_shot=0.06,     # ~33 sustained rounds (~2.8 s) to overheat
            cool_per_tick=0.006,    # ~2.8 s for a full cool from max
            reengage=0.35,          # ~1.8 s lockout after an overheat
        ),
        make_projectile=_bz_bullet_factory,
    )


class OutdoorWorld:
    name = "outdoor"

    def __init__(self) -> None:
        self.battlefield = Battlefield(half_size=WORLD_HALF_SIZE)
        self.camera = Camera(x=0.0, z=0.0, heading=0.0)
        self.time_sec = 0.0
        self._accum = 0.0

        self._populate_city()      # buildings + skyscraper + lobby trigger
        self._populate_scene()     # terrain debris, kept clear of footprints
        self._populate_tanks()

        # the player's weapons (M1 inc 2). Slot 0 ballistic shell (one on
        # screen at a time), slot 1 the heat-gated pulse rifle. Cycle with the
        # weapon-cycle input (bound to Tab in the shell).
        self.loadout = Loadout([_shell_weapon(), _pulse_weapon()])

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

    def _populate_tanks(self) -> None:
        # Two enemy autos forward of spawn. They roam (AI ticks) and can be
        # killed for score; they do NOT fire yet (increment 2 + damage model).
        self.battlefield.add_tank(Tank(model=TANK_MODEL, x=-150.0, z=-350.0,
                                       ai_seed=1))
        self.battlefield.add_tank(Tank(model=TANK_MODEL, x=220.0, z=-300.0,
                                       ai_seed=2))

    # --- World protocol --------------------------------------------------

    def on_enter(self, state, payload: dict[str, Any]) -> None:
        self.camera.x, self.camera.z, self.camera.heading = 0.0, 600.0, 0.0

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

        # enemy AI moves the tanks; enemy fire is intentionally NOT wired yet.
        self.battlefield.step_tanks(cam.x, cam.z, cam.heading)
        for t in self.battlefield.tanks:
            t.ai_wants_fire = False   # consume the fire intent — no enemy bullets

        # advance bullets; player bullets kill tanks -> score via PlayerState
        tanks_before = len(self.battlefield.tanks)
        _player_hit, _killed = self.battlefield.step_bullets(
            player_x=cam.x, player_z=cam.z, player_radius=PLAYER_RADIUS)
        kills = tanks_before - len(self.battlefield.tanks)
        if kills > 0:
            state.add_score(kills * TANK_SCORE)
        # _player_hit is always False here (no enemy bullets); damage model TBD.

        self.battlefield.step_fragments()

        if inp.action and self._near_lobby():
            return Transition("indoor", {"building": TOWER_ID})
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