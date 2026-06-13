"""
indoor/world.py — the real Castle of Bane interior, hosted as a shell guest.

Milestone 2.0 (the riskiest-assumption test, cashed in): the scratch room is
gone. This world now drives the vendored Bane engine (``az.innerworld_engine``:
DungeonMap + BSPTree + Level) and the de-windowed wall renderer
(``indoor/renderer.py``). It loads a real grid dungeon, walks it first-person
with grid collision against real walls and closed doors, and hands back to the
outer world through the portal — proving the guest renderer round-trips inside
the shell's loop without owning a window, a timer, or the GL context.

NOT yet here (by M2.0 design): combat, enemies, projectiles, the staff weapon,
and the interior HUD/minimap. Those are M2.2 (combat on shell PlayerState) and
M2.3 (the first gunman). See README_Innerworld_Design.md.

Coordinate space is Bane-native and stays sealed in this world and its
renderer: **-Y is up** (eye at y=-15, floor y=0, ceiling y≈-60), human scale
(CELL_SIZE=50). heading is degrees about +Y (Bane convention); forward is
(sin h, -cos h), the same forward convention as the rest of the game. Only
PlayerState crosses the portal — never coordinates, never the vertical axis.
"""

from __future__ import annotations

import math
from typing import Any

from az.innerworld_engine import (
    CELL_SIZE, CellType, build_bsp_from_dungeon, create_test_dungeon,
)
from az.indoor import renderer
from az.shell.mode import InputState, Transition

# --- feel knobs (Bane-native per-tick constants; do NOT rescale to seconds) --
TICK_DT = 0.016                  # 16 ms native fixed timestep (shell drives it)
INDOOR_FORWARD_SPEED = 3.0       # world units / tick  (Bane _handle_input speed)
INDOOR_TURN_SPEED_DEG = 2.0      # degrees / tick       (Bane _handle_input turn)
BODY_RADIUS = 12.0               # collision radius     (Bane collision_radius)
EYE_Y = -15.0                    # eye height in -Y-up space (Bane cam_y)

# Entry and exit cells in the test dungeon (both verified walkable):
#   start  = (9, 9)   centre room
#   exit   = (15, 9)  far east room — walk the east corridor to leave
START_CELL = (9, 9)
EXIT_CELL = (15, 9)
EXIT_HALF = 22.0                 # action-to-leave zone half-extent (cell ≈ 50)


class IndoorWorld:
    name = "indoor"

    def __init__(self) -> None:
        self.dungeon = None
        self.bsp_tree = None
        self.cam_x = 0.0
        self.cam_z = 0.0
        self.cam_angle_deg = 0.0
        self.exit_x = 0.0
        self.exit_z = 0.0
        self._building = "tower_a"
        self._accum = 0.0

    # --- World protocol --------------------------------------------------

    def on_enter(self, state, payload: dict[str, Any]) -> None:
        """Spin up at this world's own entry. No pose persists across the seam
        (POC §6): the interior always starts at its door."""
        self._building = payload.get("building", "tower_a")
        self.dungeon = create_test_dungeon()
        self.bsp_tree = build_bsp_from_dungeon(self.dungeon)

        self.cam_x, self.cam_z = self.dungeon.grid_to_world(*START_CELL)
        self.cam_angle_deg = 0.0
        self.exit_x, self.exit_z = self.dungeon.grid_to_world(*EXIT_CELL)
        self._accum = 0.0

    def on_exit(self, state) -> None:
        pass

    def update(self, dt: float, inp: InputState, state) -> Transition | None:
        # Fixed-timestep accumulator — identical shape to OutdoorWorld.update,
        # so engine constants stay per-tick regardless of frame dt.
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

        # Exit: stand in the exit zone and tap action -> clear + hand back.
        if inp.action and self._in_exit_zone():
            state.mark_cleared(self._building)
            return Transition("outdoor", {"from": self._building})
        return None

    # --- SpatialQuery ----------------------------------------------------

    def can_move_to(self, x: float, z: float, radius: float
                    ) -> tuple[bool, float, float]:
        """Resolve a desired position against the grid. Returns
        (was_free, resolved_x, resolved_z). Player slide-along is handled in
        _sim_tick (origin-aware trial-revert, mirroring the outdoor world); this
        method answers the stateless 'can a body of this radius stand here?'
        used by general/AI callers."""
        free = not self._blocked(x, z, radius)
        return (free, x, z)

    def line_of_sight(self, ax: float, az: float,
                      bx: float, bz: float) -> bool:
        """Grid-sampled LOS: walk the segment in half-cell steps and fail on the
        first solid cell. Real Bane uses combat.has_line_of_sight (grid DDA);
        this minimal version satisfies the contract until the combat port (M2.3)
        brings the enemy that needs it."""
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
        """Grid collision: sample the body centre plus four cardinal offsets at
        ``radius``; blocked if any sample is non-walkable or a closed door
        (ported from Bane _handle_input's collision check)."""
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

    def status_text(self, state) -> str:
        if self._in_exit_zone():
            return "EXIT — press E to leave the tower"
        return "move: W/S  turn: A/D   reach the green exit (far east room)"

    # --- draw ------------------------------------------------------------

    def draw(self, vp_w: int, vp_h: int) -> None:
        renderer.draw_interior(
            dungeon=self.dungeon, bsp_tree=self.bsp_tree,
            cam_x=self.cam_x, cam_y=EYE_Y, cam_z=self.cam_z,
            cam_angle_deg=self.cam_angle_deg, vp_w=vp_w, vp_h=vp_h,
            exit_world=(self.exit_x, self.exit_z), exit_half=EXIT_HALF,
        )
