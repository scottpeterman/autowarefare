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
from typing import Any

from az.innerworld_engine import CELL_SIZE, CellType, create_test_dungeon
from az.indoor import renderer
from az.indoor.floor import FloorRuntime
from az.shell.mode import InputState, Transition

# --- feel knobs (Bane-native per-tick constants; do NOT rescale to seconds) --
TICK_DT = 0.016                  # 16 ms native fixed timestep (shell drives it)
INDOOR_FORWARD_SPEED = 3.0       # world units / tick  (Bane _handle_input speed)
INDOOR_TURN_SPEED_DEG = 2.0      # degrees / tick       (Bane _handle_input turn)
BODY_RADIUS = 12.0               # collision radius     (Bane collision_radius)
EYE_Y = -15.0                    # eye height in -Y-up space (Bane cam_y)

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
        else:
            self.floors = _build_default_floors()

        self.floor_index = 0
        self.max_floor = 0
        self._found = False
        self._hint = False
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
                "move: W/S  turn: A/D")

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
        renderer.draw_interior(
            dungeon=self.dungeon, bsp_tree=self.bsp_tree,
            cam_x=self.cam_x, cam_y=EYE_Y, cam_z=self.cam_z,
            cam_angle_deg=self.cam_angle_deg, vp_w=vp_w, vp_h=vp_h,
            exit_world=exit_world, exit_half=EXIT_HALF,
            up_world=up_world, down_world=down_world,
            objectives=objectives,
        )