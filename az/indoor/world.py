"""
indoor/world.py — the Castle-of-Bane interior, hosted as a shell guest, now a
*stack of floors* (session 8, Question 1).

Milestone 2.0 made the scratch room a real single-floor grid dungeon. This step
(the floor stack) grows that one dungeon into ``self.floors`` — a building is a
stack, a floor is a ``DungeonMap``, and **moving between floors is internal to
this world**, never a portal transition. The portal still crosses exactly one
seam (outdoor <-> indoor) carrying only ``PlayerState``; a staircase swaps the
active ``(dungeon, bsp_tree)`` pair *within* this world and repositions the
camera. The shell never sees it.

The stair mechanic is **prompt-gated** on per-link stair cells: stand on an
up-stair and press U to climb, stand on a down-stair and press I to descend
(dedicated edge keys mapped in the shell). A floor's up-stair and down-stair are
usually different cells, so climbing in lands you at the down-stair and you have
to cross the floor to find the next up-stair — except on a within-run chimney
point, where the two coincide and both keys work. The phosphor prompt names
whichever key the cell you're on offers. This deletes the auto-on-contact
debounce wholesale: walking across a stair does nothing, and *arriving* on the
destination stair just shows the prompt again instead of bouncing you back.

``depth`` (the M3 outcome payload's richest field) falls straight out of this:
it is ``self.max_floor`` — the highest floor index reached this dive. The
interior doesn't *report* difficulty; the floor you climb to *is* it.

Coordinate space is Bane-native and stays sealed here and in the renderer:
**-Y is up** (eye at y=-15, floor y=0), human scale (CELL_SIZE=50). heading is
degrees about +Y; forward is (sin h, -cos h). Only PlayerState crosses the
portal — never coordinates, never the vertical axis.
"""

from __future__ import annotations

import math
import random
from typing import Any

from az.innerworld_engine import CELL_SIZE, CellType, create_test_dungeon
from az.indoor import renderer
from az.indoor.floor import FloorRuntime
from az.indoor.mob import ENEMY_RADIUS
from az.indoor.projectile import BOLT_HIT_RADIUS
from az.shell.mode import InputState, Transition

# --- feel knobs (Bane-native per-tick constants; do NOT rescale to seconds) --
TICK_DT = 0.016                  # 16 ms native fixed timestep (shell drives it)
INDOOR_FORWARD_SPEED = 3.0       # world units / tick  (Bane _handle_input speed)
INDOOR_TURN_SPEED_DEG = 2.0      # degrees / tick       (Bane _handle_input turn)
BODY_RADIUS = 12.0               # collision radius     (Bane collision_radius)
EYE_Y = -15.0                    # eye height in -Y-up space (Bane cam_y)

# --- player melee strike (M2.2): the one weapon the player has indoors so the
# mobs are fightable, not just avoidable. The first-person staff *overlay* is
# M2.3 art; this is the mechanic. Fire (Space) swings; mobs in a forward arc
# within reach take STRIKE_DAMAGE, cadence-gated. ---
STRIKE_RANGE = 62.0              # reach, indoor units (a touch past melee contact)
STRIKE_HALF_ARC = 0.62           # cos gate ~ 52 deg half-arc in front
STRIKE_DAMAGE = 2                # knifeman (1hp) one-shot; thug (3hp) in two
STRIKE_COOLDOWN = 22             # ticks between swings

# Inter-mob spacing: mobs jostle apart to this centre distance so two converging
# on the same spot fan into an arc around the player instead of fusing into one
# blob. ~2.2x body radius — shoulder-to-shoulder, still able to gang up.
ENEMY_SEPARATION = ENEMY_RADIUS * 2.2

# --- dwell-time escalation (within a building): the longer you stay, the more
# often the building sends another mob onto your floor. This is the *intra-dive*
# ramp — distinct from PlayerState.tier (the cross-dive ledger that sets how hard
# a building STARTS). Heat is the building's response to your lingering; tier is
# its baseline. They compose. Reset per dive (on_enter); persists across floors. -
REINFORCE_BASE = 1080            # ticks before the first wave (~18s) — quiet to read
REINFORCE_FLOOR = 360            # the fastest the building ever responds (~6s)
REINFORCE_RAMP = 4800            # dwell ticks (~80s) over which the rate ramps in

# Default-stack cells (the M2.0 test dungeon, verified walkable):
#   start = (9, 9)   centre room — spawn
#   exit  = (15, 9)  far east room — the door you came in by
#   stair = (11, 8)  centre room — the shared stairwell column
# These are create_test_dungeon artifacts; a generated stack (step 3) names its
# own from carved geometry. Kept module-level because test_indoor_m20 imports
# START_CELL / EXIT_CELL to assert the bare-payload fallback.
START_CELL = (9, 9)
EXIT_CELL = (15, 9)
STAIR_CELL = (11, 8)
EXIT_HALF = 22.0                 # action-to-leave zone half-extent (cell ~= 50)


def _build_default_floors() -> list[FloorRuntime]:
    """The bare-payload fallback (``{"building": id}`` with no archetype): a
    two-floor stack on the M2.0 test dungeon. Floor 0 keeps the exact geometry
    M2.0 pinned (start/exit/solid-corners unchanged) so test_indoor_m20 stays
    green; both floors share the stairwell column at STAIR_CELL so the climb is
    aligned by construction. Floor 1 exists purely to give the stack a second
    storey to climb to — its own exit is None (you only leave from the ground)."""
    d0 = create_test_dungeon()
    d0.set_cell(*STAIR_CELL, CellType.STAIRS_UP)
    d0.generate_walls()
    f0 = FloorRuntime(dungeon=d0, up_cell=STAIR_CELL, down_cell=None,
                      start_cell=START_CELL, exit_cell=EXIT_CELL)

    d1 = create_test_dungeon()
    d1.set_cell(*STAIR_CELL, CellType.STAIRS_DOWN)
    d1.generate_walls()
    f1 = FloorRuntime(dungeon=d1, up_cell=None, down_cell=STAIR_CELL,
                      start_cell=STAIR_CELL)

    return [f0, f1]


class IndoorWorld:
    name = "indoor"

    def __init__(self) -> None:
        self.floors: list[FloorRuntime] = []
        self.floor_index = 0
        self.max_floor = 0          # -> the M3 payload's ``depth``
        self.dungeon = None         # view onto floors[floor_index].dungeon
        self.bsp_tree = None        # view onto floors[floor_index].bsp()
        self.cam_x = 0.0
        self.cam_z = 0.0
        self.cam_angle_deg = 0.0
        self.exit_x = 0.0
        self.exit_z = 0.0
        self._building = "tower_a"
        self._accum = 0.0
        self._floor_changed = False
        self._found = False         # picked up the plant this dive -> payload
        self._hint = False          # read the intel this dive -> payload
        self._strike_cd = 0         # player melee-strike cooldown (ticks)
        self._bolts = []            # gunman bolts in flight (active floor only)
        self._dwell = 0             # ticks in this building this dive (heat clock)
        self._reinforce_cd = 0      # ticks until the next reinforcement wave
        self._populated = False     # only a populated (archetype) building reinforces
        self._reinforce_rng = random.Random(0)

    # --- World protocol --------------------------------------------------

    def on_enter(self, state, payload: dict[str, Any]) -> None:
        """Spin up at floor 0's start cell. No pose persists across the seam
        (POC §6): the interior always starts at its door.

        New behavior is additive and gated on ``archetype`` being present in the
        payload. A bare ``{"building": id}`` payload (what test_floor_stack and
        test_indoor_m20 send) takes the default two-floor stack — the step-2
        fallback — untouched. The archetype branch (step 3, ProceduralSource)
        slots in here."""
        self._building = payload.get("building", "tower_a")

        archetype = payload.get("archetype")
        if archetype is not None:
            from az.indoor.floor_source import ProceduralSource
            from az.indoor.placement import place_objectives
            src = ProceduralSource()
            footprint = payload.get("footprint", (200.0, 200.0))
            seed = payload.get("seed", 0)
            n = src.floor_count(archetype, footprint, seed)
            self.floors = [src.build_floor(archetype, footprint, seed, i)
                           for i in range(n)]
            # Decorate the finished stack with objectives. Whether this building
            # hides the plant is a game-level fact carried across the enter seam
            # (vision §2); the intel lands in every dived building. The bare-
            # payload fallback below stays objective-free, so the step-2/3 pins
            # keep their geometry untouched.
            place_objectives(self.floors,
                             holds_plant=bool(payload.get("holds_plant", False)),
                             seed=seed)
            # Then populate the threat: live mobs scaled by the same escalation
            # ledger the outdoor war reads (vision §6), so a deeper run into the
            # search is harder inside as well as out. Live roster: thug, knifeman,
            # and the gunman (melee-weighted).
            from az.indoor.enemy_placement import place_enemies
            place_enemies(self.floors, seed=seed, tier=getattr(state, "tier", 0))
            # A populated building responds to dwelling with reinforcement waves.
            # Seed a dedicated RNG (distinct salt from layout/loot/initial spawns)
            # so the waves are reproducible per dive without correlating.
            self._populated = True
            self._reinforce_rng = random.Random(
                (int(seed) * 2246822519 + 0xB5297A4D) & 0xFFFFFFFF)
        else:
            self.floors = _build_default_floors()
            self._populated = False        # bare stack stays inert (M2.0 pins)

        self.floor_index = 0
        self.max_floor = 0
        self._found = False
        self._hint = False
        self._dwell = 0                    # reset the heat clock for the new dive
        self._reinforce_cd = REINFORCE_BASE
        self.cam_angle_deg = 0.0
        self._apply_floor(0, self.floors[0].start_cell)
        self._accum = 0.0

    def on_exit(self, state) -> None:
        pass

    def update(self, dt: float, inp: InputState, state) -> Transition | None:
        # Fixed-timestep accumulator — identical shape to OutdoorWorld.update,
        # so engine constants stay per-tick regardless of frame dt.
        self._accum += dt
        steps = 0
        transition: Transition | None = None
        self._floor_changed = False
        while self._accum >= TICK_DT and steps < 5:
            transition = self._sim_tick(inp, state)
            self._accum -= TICK_DT
            steps += 1
            # One swap (or one handoff) per frame: a floor change zeroes the
            # accumulator and breaks, so the same edge-held action can't act
            # again on the cell we just arrived on. The prompt re-asks next frame.
            if transition is not None or self._floor_changed:
                self._accum = 0.0
                break
        return transition

    @property
    def spatial(self):
        return self

    # --- floor stack -----------------------------------------------------

    def _apply_floor(self, index: int, arrive_cell) -> None:
        """Swap the active floor: point ``self.dungeon`` / ``self.bsp_tree`` at
        floor ``index`` (lazy-building its BSP on first visit), drop the camera
        on ``arrive_cell``, and advance ``max_floor`` (the depth counter). The
        renderer and spatial query read ``self.dungeon`` / ``self.bsp_tree``
        unchanged — this is the whole floor-swap, exactly the seam the plan
        stands on."""
        self.floor_index = index
        self._bolts = []            # bolts are floor-local; a swap voids them
        fr = self.floors[index]
        self.dungeon = fr.dungeon
        self.bsp_tree = fr.bsp()
        self.cam_x, self.cam_z = self.dungeon.grid_to_world(*arrive_cell)
        if index > self.max_floor:
            self.max_floor = index
        if fr.exit_cell is not None:
            self.exit_x, self.exit_z = self.dungeon.grid_to_world(*fr.exit_cell)

    def _change_floor(self, new_index: int, *, ascending: bool) -> None:
        """Take the stairwell to ``new_index``. Arrival is the shared landing for
        the link just traversed: climbing UP you land on the new floor's
        down-stair (the cell you climbed through); descending, on its up-stair.
        Both are the same coordinate as the stair you left, by the per-link
        matching-landing contract. Heading is preserved; the accumulator break in
        update() makes this one-swap-per-frame."""
        fr = self.floors[new_index]
        arrive = fr.down_cell if ascending else fr.up_cell
        self._apply_floor(new_index, arrive)
        self._floor_changed = True

    def _can_ascend(self) -> bool:
        return self.floor_index + 1 < len(self.floors)

    def _can_descend(self) -> bool:
        return self.floor_index - 1 >= 0

    def _player_cell(self) -> tuple[int, int]:
        return self.dungeon.world_to_grid(self.cam_x, self.cam_z)

    def _on_up_stair(self) -> bool:
        up = self.floors[self.floor_index].up_cell
        return up is not None and self._player_cell() == up

    def _on_down_stair(self) -> bool:
        down = self.floors[self.floor_index].down_cell
        return down is not None and self._player_cell() == down

    # --- one native sim tick (ported from Bane _handle_input) ------------

    def _sim_tick(self, inp: InputState, state) -> Transition | None:
        if inp.left:
            self.cam_angle_deg -= INDOOR_TURN_SPEED_DEG
        if inp.right:
            self.cam_angle_deg += INDOOR_TURN_SPEED_DEG

        rad = math.radians(self.cam_angle_deg)
        old_x, old_z = self.cam_x, self.cam_z
        nx, nz = old_x, old_z
        if inp.forward:
            nx += math.sin(rad) * INDOOR_FORWARD_SPEED
            nz -= math.cos(rad) * INDOOR_FORWARD_SPEED
        if inp.back:
            nx -= math.sin(rad) * INDOOR_FORWARD_SPEED
            nz += math.cos(rad) * INDOOR_FORWARD_SPEED

        # Trial-revert slide-along (same approach as the outdoor world): if the
        # full move is blocked, keep whichever single axis is free so a glancing
        # wall slides instead of stopping dead.
        if (nx, nz) != (old_x, old_z) and self._blocked(nx, nz):
            if not self._blocked(nx, old_z):
                nx, nz = nx, old_z
            elif not self._blocked(old_x, nz):
                nx, nz = old_x, nz
            else:
                nx, nz = old_x, old_z
        self.cam_x, self.cam_z = nx, nz

        # Objective pickup (walk-over, no action key — matches the exit zone's
        # low-friction feel). Stepping onto an uncollected objective on this
        # floor flips the dive-scoped flag the exit record reports; collecting
        # the plant also drops it in the shared inventory so the outdoor side can
        # read the win without widening the seam.
        gx, gz = self._player_cell()
        for ent in self.floors[self.floor_index].entities:
            if not ent.collected and ent.cell == (gx, gz):
                ent.collected = True
                if ent.kind == "plant":
                    self._found = True
                    state.add_item("plant")
                elif ent.kind == "intel":
                    self._hint = True

        # Enemies: the active floor's mobs chase + slash (damage -> PlayerState),
        # then the player's strike (fire) culls those in the forward arc. M2.2
        # melee; only the active floor updates (matching the pickup loop).
        self._update_enemies(inp, state)
        # (dedicated edge keys, mapped in the shell). A within-run chimney point
        # is both cells at once, so both keys work there. Dedicated keys rather
        # than E+direction because a movement key would walk you off the stair
        # cell before the swap could fire. A swap consumes the frame (the
        # accumulator break in update()), so one press = one floor.
        if inp.stair_up and self._on_up_stair() and self._can_ascend():
            self._change_floor(self.floor_index + 1, ascending=True)
            return None
        if inp.stair_down and self._on_down_stair() and self._can_descend():
            self._change_floor(self.floor_index - 1, ascending=False)
            return None

        # Exit: gated to floor 0 (you leave the building only from the ground).
        # Stand in the exit zone and tap action (E) -> hand back the M3 outcome
        # record. ``cleared`` is now a real outcome — true only when the top was
        # reached this dive (a thorough search), not the old unconditional flag —
        # so the cross-seam ledger means "searched to the top," which is what the
        # return-from-dive escalation reads. Bailing at the entrance returns
        # cleared=False and leaves the ledger untouched.
        if inp.action and self.floor_index == 0 and self._in_exit_zone():
            cleared = self.max_floor >= len(self.floors) - 1
            if cleared:
                state.mark_cleared(self._building)
            return Transition("outdoor", {
                "from":    self._building,
                "cleared": cleared,
                "depth":   self.depth,
                "found":   self._found,
                "hint":    self._hint or None,   # boolean now; §4 narrowing later
            })
        return None

    # --- SpatialQuery ----------------------------------------------------

    def can_move_to(self, x: float, z: float, radius: float
                    ) -> tuple[bool, float, float]:
        """Resolve a desired position against the active floor's grid. Returns
        (was_free, resolved_x, resolved_z). Player slide-along is handled in
        _sim_tick (origin-aware trial-revert, mirroring the outdoor world); this
        method answers the stateless 'can a body of this radius stand here?'
        used by general/AI callers."""
        free = not self._blocked(x, z, radius)
        return (free, x, z)

    def line_of_sight(self, ax: float, az: float,
                      bx: float, bz: float) -> bool:
        """Grid-sampled LOS on the active floor: walk the segment in half-cell
        steps and fail on the first solid cell."""
        dx, dz = bx - ax, bz - az
        dist = math.hypot(dx, dz)
        if dist < 1e-6:
            return True
        step = CELL_SIZE * 0.5
        n = max(1, int(dist / step))
        for i in range(1, n):
            t = i / n
            gx, gz = self.dungeon.world_to_grid(ax + dx * t, az + dz * t)
            if self.dungeon.is_solid(gx, gz):
                return False
        return True

    # --- helpers ---------------------------------------------------------

    def _blocked(self, x: float, z: float, radius: float = BODY_RADIUS) -> bool:
        """Grid collision against the active floor: sample the body centre plus
        four cardinal offsets at ``radius``; blocked if any sample is
        non-walkable or a closed door."""
        for dx, dz in ((0.0, 0.0), (radius, 0.0), (-radius, 0.0),
                       (0.0, radius), (0.0, -radius)):
            gx, gz = self.dungeon.world_to_grid(x + dx, z + dz)
            if not self.dungeon.is_walkable(gx, gz):
                return True
            if self.dungeon.get_cell(gx, gz) == CellType.DOOR:
                return True   # closed doors block (opened doors become FLOOR)
        return False

    def _in_exit_zone(self) -> bool:
        return (abs(self.cam_x - self.exit_x) <= EXIT_HALF and
                abs(self.cam_z - self.exit_z) <= EXIT_HALF)

    def _update_enemies(self, inp: InputState, state) -> None:
        """One tick of indoor combat on the active floor: step every live mob
        (chase + slash into PlayerState), resolve the player's strike (fire, arc
        + reach, cadence-gated), then cull the dead. Frozen at game over so a mob
        can't keep swinging on a spent run."""
        if state.is_game_over:
            self._bolts = []
            return

        # Dwell-time escalation: a populated building sends reinforcements onto
        # the current floor, faster the longer you linger (the wave fires before
        # the step loop, so a new mob is live this same tick).
        if self._populated:
            self._dwell += 1
            if self._reinforce_cd > 0:
                self._reinforce_cd -= 1
            if self._reinforce_cd <= 0:
                self._spawn_reinforcement()
                self._reinforce_cd = self._reinforce_interval()

        mobs = self.floors[self.floor_index].enemies
        for mob in mobs:
            bolt = mob.step(self.cam_x, self.cam_z, self, state)
            if bolt is not None:          # a gunman fired this tick
                self._bolts.append(bolt)

        self._update_bolts(state)

        if self._strike_cd > 0:
            self._strike_cd -= 1
        if inp.fire and self._strike_cd <= 0:
            self._player_strike(mobs)
            self._strike_cd = STRIKE_COOLDOWN

        # Rebind so a killed mob stops being stepped and drawn this same frame.
        alive = [m for m in mobs if m.alive]
        self.floors[self.floor_index].enemies = alive
        self._separate_mobs(alive)

    def _separate_mobs(self, mobs) -> None:
        """Jostle overlapping mobs apart to ``ENEMY_SEPARATION`` so two closing on
        the player fan into an arc instead of fusing. Each push is wall-aware and
        half-strength, so a stack relaxes over a few ticks rather than snapping —
        and a mob is never shoved through geometry."""
        n = len(mobs)
        if n < 2:
            return
        for i in range(n):
            a = mobs[i]
            for j in range(i + 1, n):
                b = mobs[j]
                dx, dz = b.x - a.x, b.z - a.z
                d = math.hypot(dx, dz)
                if d >= ENEMY_SEPARATION:
                    continue
                if d < 1e-6:                 # exact overlap: deterministic split
                    dx, dz, d = 1.0, 0.0, 1.0
                push = (ENEMY_SEPARATION - d) * 0.5
                ux, uz = dx / d, dz / d
                self._nudge(a, -ux * push, -uz * push)
                self._nudge(b, ux * push, uz * push)

    def _nudge(self, mob, dx: float, dz: float) -> None:
        """Move a mob by (dx, dz) only if the destination clears walls."""
        free, rx, rz = self.can_move_to(mob.x + dx, mob.z + dz, ENEMY_RADIUS)
        if free:
            mob.x, mob.z = rx, rz

    def _reinforce_interval(self) -> int:
        """Ticks until the next wave, ramping linearly from ``REINFORCE_BASE``
        down to ``REINFORCE_FLOOR`` over ``REINFORCE_RAMP`` ticks of dwell — so
        the building responds faster the longer the dive runs."""
        t = min(1.0, self._dwell / REINFORCE_RAMP)
        return int(REINFORCE_BASE - (REINFORCE_BASE - REINFORCE_FLOOR) * t)

    def _spawn_reinforcement(self) -> bool:
        """Drop one mob onto the current floor at a legal cell clear of the
        player, preferring a cell the player can't currently see so it doesn't
        pop into view. No-op (returns False) once the floor is at its live cap."""
        from az.indoor.enemy_placement import (
            legal_cells, spawn_mob, REINFORCE_CAP, RUNTIME_SPAWN_CLEAR)
        from az.indoor.enemies import LIVE_ROSTER

        fr = self.floors[self.floor_index]
        if sum(m.alive for m in fr.enemies) >= REINFORCE_CAP:
            return False
        cells = legal_cells(fr, clear_from=self._player_cell(),
                            clear_radius=RUNTIME_SPAWN_CLEAR)
        if not cells:
            return False
        hidden = [c for c in cells
                  if not self.line_of_sight(self.cam_x, self.cam_z,
                                            *self.dungeon.grid_to_world(*c))]
        pool = hidden or cells                  # arrive unseen when possible
        cell = self._reinforce_rng.choice(pool)
        spawn_mob(fr, cell, self._reinforce_rng.choice(LIVE_ROSTER),
                  self._reinforce_rng)
        return True

    def _update_bolts(self, state) -> None:
        """Fly every in-flight gunman bolt one tick: a wall or expiry drops it; a
        bolt within ``BOLT_HIT_RADIUS`` of the player lands its damage through
        the shared pool (respawn-grace and death handled like any other hit)."""
        if not self._bolts:
            return
        live = []
        for b in self._bolts:
            b.advance()
            if b.expired:
                continue
            gx, gz = self.dungeon.world_to_grid(b.x, b.z)
            if not self.dungeon.is_walkable(gx, gz):
                continue                  # spent on a wall
            if math.hypot(b.x - self.cam_x, b.z - self.cam_z) <= BOLT_HIT_RADIUS:
                state.take_damage(b.damage)
                if state.is_dead:
                    state.lose_life()
                continue                  # spent on the player
            live.append(b)
        self._bolts = live

    def _player_strike(self, mobs) -> None:
        """A swing: every mob within ``STRIKE_RANGE`` and inside the forward arc
        takes ``STRIKE_DAMAGE``. Forward is the player's (sin h, -cos h)."""
        rad = math.radians(self.cam_angle_deg)
        fx, fz = math.sin(rad), -math.cos(rad)
        for mob in mobs:
            dx, dz = mob.x - self.cam_x, mob.z - self.cam_z
            dist = math.hypot(dx, dz)
            if dist > STRIKE_RANGE or dist < 1e-6:
                continue
            if (dx / dist) * fx + (dz / dist) * fz >= STRIKE_HALF_ARC:
                mob.hit(STRIKE_DAMAGE)

    @property
    def depth(self) -> int:
        """Max floor index reached this dive — the M3 outcome payload's richest
        field. 0 for an outbuilding you never climbed; it grows with the dive."""
        return self.max_floor

    def status_text(self, state) -> str:
        on_up = self._on_up_stair()
        on_down = self._on_down_stair()
        if on_up and on_down:
            return "STAIRWELL — U: up   I: down"
        if on_up:
            return "STAIRWELL — press U to climb"
        if on_down:
            return "STAIRWELL — press I to descend"
        if self.floor_index == 0 and self._in_exit_zone():
            return "EXIT — press E to leave the tower"
        # Per-floor flag count: how many objectives sit on THIS floor and how
        # many you've collected. Tells you whether you've swept the floor you're
        # on without revealing the building total (so it never leaks whether the
        # plant is in this building — only that this floor still holds something).
        ents = self.floors[self.floor_index].entities
        m = len(ents)
        flags = f"   flags {sum(e.collected for e in ents)}/{m}" if m else ""
        return (f"floor {self.floor_index}/{len(self.floors) - 1}{flags}   "
                "move: W/S  turn: A/D  strike: SPACE")

    # --- draw ------------------------------------------------------------

    def draw(self, vp_w: int, vp_h: int) -> None:
        fr = self.floors[self.floor_index]
        # The exit marker only exists on the ground floor.
        exit_world = ((self.exit_x, self.exit_z)
                      if self.floor_index == 0 else None)
        # Stair markers: an up-glyph at the up-stair, a down-glyph at the
        # down-stair. They're independent cells now; on a chimney-point floor the
        # two coincide and the glyphs composite into the both-ways hourglass.
        up_world = (self.dungeon.grid_to_world(*fr.up_cell)
                    if fr.up_cell is not None else None)
        down_world = (self.dungeon.grid_to_world(*fr.down_cell)
                      if fr.down_cell is not None else None)
        # Uncollected objectives on this floor, as (world_x, world_z, kind).
        objectives = [(*self.dungeon.grid_to_world(*ent.cell), ent.kind)
                      for ent in fr.entities if not ent.collected]
        # Live mobs on this floor, as (world_x, world_z, facing_deg, name).
        enemies = [(mob.x, mob.z, mob.facing_deg, mob.def_.name)
                   for mob in fr.enemies if mob.alive]
        # Gunman bolts in flight, as (world_x, world_z).
        bolts = [(b.x, b.z) for b in self._bolts]
        renderer.draw_interior(
            dungeon=self.dungeon, bsp_tree=self.bsp_tree,
            cam_x=self.cam_x, cam_y=EYE_Y, cam_z=self.cam_z,
            cam_angle_deg=self.cam_angle_deg, vp_w=vp_w, vp_h=vp_h,
            exit_world=exit_world, exit_half=EXIT_HALF,
            up_world=up_world, down_world=down_world,
            objectives=objectives, enemies=enemies, bolts=bolts,
        )