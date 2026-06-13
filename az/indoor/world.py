"""
indoor/world.py — the M0 indoor stub (Castle of Bane lineage placeholder).

Milestone 0 wants "one Bane guest room — not a black screen." The *real* M0
indoor world is the existing GL3DDungeonRenderer refactored into a guest
renderer (the riskiest-assumption test). That extraction needs the Bane
``wireframe_engine/bsp.py`` (BSPTree / build_bsp_from_dungeon), which isn't in
the onramp set. Until it lands, this is a self-contained scratch room that
exercises the *spine* end to end: first-person movement, a hazard that spends
HP, and an exit that flips a cleared flag — so we can prove health and progress
survive the portal today. Swapping in the real guest renderer later is a
localized change behind this same World interface; nothing else moves.

Coordinate space here is private and human-scale. Note it is +Y up: this
scratch room owns its own convention, and since only PlayerState crosses the
seam, that is free to differ from the real Bane wall pipeline (-Y up), which
will live encapsulated inside the guest renderer. heading is in radians, same
forward convention as everywhere else (forward = (sin h, -cos h)).
"""

from __future__ import annotations

import math
from typing import Any

from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_LESS,
    GL_LINE_LOOP, GL_LINES, GL_MODELVIEW, GL_PROJECTION, glBegin, glClear,
    glClearColor, glClearDepth, glColor3f, glDepthFunc, glEnable, glEnd,
    glLineWidth, glLoadIdentity, glMatrixMode, glRotatef, glTranslatef,
    glVertex3f, glViewport,
)
from OpenGL.GLU import gluPerspective

from az.shell.mode import InputState, Transition

# --- room constants (human scale) -----------------------------------------

ROOM_HX = 220.0              # half-extent in x
ROOM_HZ = 220.0              # half-extent in z
WALL_H = 70.0
EYE_HEIGHT = 15.0
BODY_RADIUS = 12.0

MOVE_SPEED = 180.0           # units / second (~3 per 60 Hz tick)
TURN_SPEED = 2.4             # radians / second

FOV_DEG = 75.0
NEAR, FAR = 0.5, 1000.0      # indoor far is short (Bane uses 1000)

TRAP_HALF = 45.0
TRAP_DAMAGE = 25.0
EXIT_HALF = 45.0

COL_WALL = (0.0, 0.75, 1.0)
COL_GRID = (0.0, 0.22, 0.32)
COL_TRAP = (1.0, 0.25, 0.2)
COL_EXIT = (0.25, 1.0, 0.5)


class IndoorWorld:
    name = "indoor"

    def __init__(self) -> None:
        self.x = 0.0
        self.z = 0.0
        self.heading = 0.0
        self._building = "tower_a"
        self._trap_sprung = False

        # trap zone (centre) and exit zone (far -Z wall)
        self.trap_x, self.trap_z = 0.0, 0.0
        self.exit_x, self.exit_z = 0.0, -ROOM_HZ + 55.0

    # --- World protocol --------------------------------------------------

    def on_enter(self, state, payload: dict[str, Any]) -> None:
        # The indoor world always spins up at its own entry (no pose persists),
        # so it does NOT implement save_pose/restore_pose.
        self._building = payload.get("building", "tower_a")
        self._trap_sprung = False
        self.x, self.z = 0.0, ROOM_HZ - 50.0   # just inside the +Z wall
        self.heading = 0.0                       # facing -Z, into the room

    def on_exit(self, state) -> None:
        pass

    def update(self, dt: float, inp: InputState, state) -> Transition | None:
        if inp.left:
            self.heading -= TURN_SPEED * dt
        if inp.right:
            self.heading += TURN_SPEED * dt

        move = 0.0
        if inp.forward:
            move += MOVE_SPEED
        if inp.back:
            move -= MOVE_SPEED
        if move:
            fx, fz = math.sin(self.heading), -math.cos(self.heading)
            nx = self.x + fx * move * dt
            nz = self.z + fz * move * dt
            _, self.x, self.z = self.can_move_to(nx, nz, BODY_RADIUS)

        # Hazard: spend HP once on first entry into the trap zone. This is what
        # proves, on return, that damage taken indoors persists outdoors.
        if not self._trap_sprung and self._in_zone(self.trap_x, self.trap_z, TRAP_HALF):
            state.take_damage(TRAP_DAMAGE)
            self._trap_sprung = True

        # Exit: stand in the exit zone and tap action -> clear + hand back.
        if inp.action and self._in_zone(self.exit_x, self.exit_z, EXIT_HALF):
            state.mark_cleared(self._building)
            return Transition("outdoor", {"from": self._building})
        return None

    @property
    def spatial(self):
        return self

    # --- SpatialQuery ----------------------------------------------------

    def can_move_to(self, x: float, z: float, radius: float
                    ) -> tuple[bool, float, float]:
        lx, lz = ROOM_HX - radius, ROOM_HZ - radius
        cx = max(-lx, min(lx, x))
        cz = max(-lz, min(lz, z))
        was_free = (cx == x and cz == z)
        return was_free, cx, cz

    def line_of_sight(self, ax: float, az: float,
                      bx: float, bz: float) -> bool:
        # Single open room, no interior occluders at M0.
        return True

    # --- helpers ---------------------------------------------------------

    def _in_zone(self, cx: float, cz: float, half: float) -> bool:
        return abs(self.x - cx) <= half and abs(self.z - cz) <= half

    def status_text(self, state) -> str:
        if self._in_zone(self.exit_x, self.exit_z, EXIT_HALF):
            return "EXIT — press E to leave the tower"
        if self._trap_sprung:
            return f"hazard triggered (-{int(TRAP_DAMAGE)} HP) — find the exit (green)"
        return "move: W/S  turn: A/D   reach the green exit at the far wall"

    # --- draw (the only GL surface) -------------------------------------

    def draw(self, vp_w: int, vp_h: int) -> None:
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClearDepth(1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glViewport(0, 0, vp_w, max(vp_h, 1))

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(FOV_DEG, vp_w / max(vp_h, 1), NEAR, FAR)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(math.degrees(self.heading), 0.0, 1.0, 0.0)
        glTranslatef(-self.x, -EYE_HEIGHT, -self.z)

        self._draw_floor_grid()
        self._draw_walls()
        self._draw_floor_marker(self.trap_x, self.trap_z, TRAP_HALF, COL_TRAP)
        self._draw_floor_marker(self.exit_x, self.exit_z, EXIT_HALF, COL_EXIT)

    def _draw_floor_grid(self) -> None:
        glLineWidth(1.0)
        glColor3f(*COL_GRID)
        step = 40.0
        glBegin(GL_LINES)
        nx = int(ROOM_HX / step)
        nz = int(ROOM_HZ / step)
        for i in range(-nx, nx + 1):
            x = i * step
            glVertex3f(x, 0.0, -ROOM_HZ); glVertex3f(x, 0.0, ROOM_HZ)
        for j in range(-nz, nz + 1):
            z = j * step
            glVertex3f(-ROOM_HX, 0.0, z); glVertex3f(ROOM_HX, 0.0, z)
        glEnd()

    def _draw_walls(self) -> None:
        glLineWidth(2.0)
        glColor3f(*COL_WALL)
        x0, x1 = -ROOM_HX, ROOM_HX
        z0, z1 = -ROOM_HZ, ROOM_HZ
        # top and bottom rectangles
        for y in (0.0, WALL_H):
            glBegin(GL_LINE_LOOP)
            glVertex3f(x0, y, z0); glVertex3f(x1, y, z0)
            glVertex3f(x1, y, z1); glVertex3f(x0, y, z1)
            glEnd()
        # vertical edges
        glBegin(GL_LINES)
        for cx, cz in ((x0, z0), (x1, z0), (x1, z1), (x0, z1)):
            glVertex3f(cx, 0.0, cz); glVertex3f(cx, WALL_H, cz)
        glEnd()

    def _draw_floor_marker(self, cx: float, cz: float, half: float,
                           color: tuple[float, float, float]) -> None:
        glLineWidth(2.0)
        glColor3f(*color)
        glBegin(GL_LINE_LOOP)
        glVertex3f(cx - half, 0.5, cz - half)
        glVertex3f(cx + half, 0.5, cz - half)
        glVertex3f(cx + half, 0.5, cz + half)
        glVertex3f(cx - half, 0.5, cz + half)
        glEnd()
