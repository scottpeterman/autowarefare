"""
indoor/renderer.py — the de-windowed Castle of Bane wall renderer.

This is the riskiest-assumption test from the POC, cashed in. The original
``GL3DDungeonRenderer.drawBackground`` issued all its GL between a QGraphicsView
``beginNativePainting()`` / ``endNativePainting()`` bracket, because in Bane the
GL context belonged to a ``QOpenGLWidget`` *viewport* of a ``QGraphicsView`` it
owned. In Auto Warfare the shell owns a single ``QOpenGLWidget`` and calls
``World.draw(vp_w, vp_h)`` with that context already current (``shell/app.py``
``paintGL``) — so the guest sheds the native-painting bracket entirely and just
issues raw GL, exactly like the outdoor renderer and the old scratch room.

What moved here verbatim (in intent) from ``drawBackground`` + ``_render_wall_3d``:
the projection/modelview setup, the polygon-offset fill pass, the BSP
front-to-back wall traversal, and the per-quad back-face cull + fill-then-edge
draw. What did NOT come over for M2.0: entities, projectiles, hit/death
effects, the first-person staff overlay, and the QPainter HUD/minimap — those
arrive with the combat port (M2.2) and the gunman (M2.3). The HUD is the shell's
job (``hud/compositor.py``), drawn after this returns.

Coordinate convention is Bane-native and stays sealed in here: **-Y is up**
(floor ``y=0``, ceiling ``y≈-60``), human scale (``CELL_SIZE=50``). Nothing
about this convention crosses the portal seam — only ``PlayerState`` does.
"""

from __future__ import annotations

from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_LEQUAL,
    GL_LESS, GL_LINE_LOOP, GL_LINES, GL_MODELVIEW, GL_POLYGON,
    GL_PROJECTION, glBegin, glClear, glClearColor, glClearDepth, glColor3f,
    glDepthFunc, glDisable, glEnable, glEnd, glLineWidth, glLoadIdentity,
    glMatrixMode, glRotatef, glScalef, glTranslatef,
    glVertex3f, glViewport,
)
from OpenGL.GLU import gluPerspective

# Cyberblue phosphor — matches the outer world's wall hue and the old scratch
# room (≈ #00BFFF). Fill is a dim wash so facets read as solid without hiding
# the wireframe edge on top.
WALL_RGB = (0.0, 0.75, 1.0)
FILL_INTENSITY = 0.15
GRID_RGB = (0.0, 0.22, 0.32)
EXIT_RGB = (0.25, 1.0, 0.5)
STAIR_RGB = (1.0, 0.7, 0.1)      # amber — distinct from exit-green and wall-blue

FOV_DEG = 75.0
NEAR, FAR = 1.0, 1000.0      # Bane's own near/far; interiors are bounded


def draw_interior(*, dungeon, bsp_tree, cam_x: float, cam_y: float,
                  cam_z: float, cam_angle_deg: float, vp_w: int, vp_h: int,
                  exit_world: tuple[float, float] | None = None,
                  exit_half: float = 25.0,
                  stair_world: tuple[float, float] | None = None,
                  stair_dirs: tuple[bool, bool] = (False, False)) -> None:
    """Render one indoor frame into the shell's already-current GL context.

    ``cam_angle_deg`` is degrees about +Y (Bane convention). ``cam_y`` is the
    eye height in the -Y-up space (Bane uses ``-15``). The caller (IndoorWorld)
    owns all of this state; this function is stateless drawing only.
    """
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClearDepth(1.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glEnable(GL_DEPTH_TEST)
    glDepthFunc(GL_LESS)

    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    glViewport(0, 0, vp_w, max(vp_h, 1))
    gluPerspective(FOV_DEG, vp_w / max(vp_h, 1), NEAR, FAR)
    # -Y-up correction. Bane's world is -Y-up (floor y=0, ceiling y<0); it
    # looked upright only because it rendered into a QGraphicsView's QOpenGLWidget
    # viewport, whose Qt composite flips GL's native Y-up output. The shell draws
    # directly in QOpenGLWidget.paintGL with no such composite, so we restore the
    # flip explicitly here. Render-only: world-space movement, collision, and the
    # manual wall cull are unaffected. (Sealed inside the guest, per POC §6.)
    glScalef(1.0, -1.0, 1.0)

    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    glRotatef(cam_angle_deg, 0.0, 1.0, 0.0)
    glTranslatef(-cam_x, -cam_y, -cam_z)

    r, g, b = WALL_RGB
    fr, fg, fb = r * FILL_INTENSITY, g * FILL_INTENSITY, b * FILL_INTENSITY

    # Floor grid first (under everything, depth-writes at y=0).
    _draw_floor_grid(dungeon)

    # Walls: BSP front-to-back, per-quad back-face cull, fill then edge.
    # Fills draw at TRUE depth so they occlude correctly — no polygon offset
    # pushing them backward (that was the leak: a far room's floor sat nearer
    # than the pushed-back fill and showed through at wall bases). The bright
    # wireframe edge still wins its z-fight against its own coplanar fill via
    # GL_LEQUAL: it's drawn immediately after the fill at identical depth, so
    # `<=` lets it overwrite. Anything genuinely behind a fill stays hidden;
    # open corridor sightlines (no fill between) legitimately show through.
    glLineWidth(2.0)
    glDepthFunc(GL_LEQUAL)
    for wall in bsp_tree.traverse_front_to_back(cam_x, cam_z):
        _render_wall(wall, cam_x, cam_z, r, g, b, fr, fg, fb)
    glDepthFunc(GL_LESS)

    if exit_world is not None:
        _draw_exit_marker(exit_world[0], exit_world[1], exit_half)

    if stair_world is not None:
        _draw_stair_marker(stair_world[0], stair_world[1],
                           stair_dirs[0], stair_dirs[1])

    glLineWidth(1.0)
    # Leave the context QPainter-safe for the shell's HUD pass (the validated
    # GL-then-QPainter order in shell/app.py). Mirrors Bane's own teardown.
    glDisable(GL_DEPTH_TEST)


def _render_wall(wall, cam_x: float, cam_z: float,
                 r, g, b, fr, fg, fb) -> None:
    """Faithful port of GL3DDungeonRenderer._render_wall_3d: per-quad manual
    back-face cull (dot of to-camera vs outward normal), fill polygon then a
    wireframe loop on top."""
    for quad, normal in wall.get_all_quads_with_normals():
        cx = sum(v[0] for v in quad) / 4.0
        cz = sum(v[2] for v in quad) / 4.0
        if (cam_x - cx) * normal[0] + (cam_z - cz) * normal[2] < 0:
            continue

        glColor3f(fr, fg, fb)
        glBegin(GL_POLYGON)
        for wx, wy, wz in quad:
            glVertex3f(wx, wy, wz)
        glEnd()

        glColor3f(r, g, b)
        glBegin(GL_LINE_LOOP)
        for wx, wy, wz in quad:
            glVertex3f(wx, wy, wz)
        glEnd()


def _draw_floor_grid(dungeon) -> None:
    """A dim grid on the floor plane (y=0), drawn only on walkable cells so it
    stops at the walls instead of bleeding through into solid rock. One square
    per floor cell; the cell edges line up with Bane's wall bases (walls are
    generated at center ± half), so the grid reads as intentional flooring.
    Pure orientation aid; the real Bane floor is otherwise implied by walls."""
    from az.innerworld_engine import CELL_SIZE
    h = CELL_SIZE / 2.0
    glColor3f(*GRID_RGB)
    glLineWidth(1.0)
    glBegin(GL_LINES)
    for gz in range(dungeon.height):
        for gx in range(dungeon.width):
            if not dungeon.is_walkable(gx, gz):
                continue
            cx, cz = dungeon.grid_to_world(gx, gz)
            x0, x1 = cx - h, cx + h
            z0, z1 = cz - h, cz + h
            # four edges of the cell square (shared edges double-draw — cheap
            # and invisible at this scale, not worth deduping)
            glVertex3f(x0, 0.0, z0); glVertex3f(x1, 0.0, z0)
            glVertex3f(x1, 0.0, z0); glVertex3f(x1, 0.0, z1)
            glVertex3f(x1, 0.0, z1); glVertex3f(x0, 0.0, z1)
            glVertex3f(x0, 0.0, z1); glVertex3f(x0, 0.0, z0)
    glEnd()


def _draw_exit_marker(cx: float, cz: float, half: float) -> None:
    """A green square just above the floor (slightly -Y, i.e. 'up') marking the
    cell where pressing action leaves the tower. Stand-in for the lobby door
    until the real interior authors one."""
    y = -2.0
    glColor3f(*EXIT_RGB)
    glLineWidth(2.0)
    glBegin(GL_LINE_LOOP)
    glVertex3f(cx - half, y, cz - half)
    glVertex3f(cx + half, y, cz - half)
    glVertex3f(cx + half, y, cz + half)
    glVertex3f(cx - half, y, cz + half)
    glEnd()


def _square_loop(cx: float, cz: float, half: float, y: float) -> None:
    glBegin(GL_LINE_LOOP)
    glVertex3f(cx - half, y, cz - half)
    glVertex3f(cx + half, y, cz - half)
    glVertex3f(cx + half, y, cz + half)
    glVertex3f(cx - half, y, cz + half)
    glEnd()


def _draw_stair_marker(cx: float, cz: float,
                       up_ok: bool, down_ok: bool) -> None:
    """An amber stairwell glyph on the column cell: a floor footprint, a centre
    beacon rising toward the ceiling (so the stairwell is findable from across
    the room), and stacked steps that *shrink upward* for an available climb and
    *shrink downward* (below the floor) for an available descent. A mid-floor
    shows both — an hourglass that reads 'stairs both ways'; an endpoint shows
    only its one direction. -Y is up in this space, so 'up' rises toward the
    ceiling exactly as it should.
    """
    from az.innerworld_engine import CELL_SIZE
    half = CELL_SIZE / 2.0 - 4.0
    glColor3f(*STAIR_RGB)
    glLineWidth(2.0)

    # floor footprint of the stairwell
    _square_loop(cx, cz, half, -2.0)

    # centre beacon — a vertical post visible over the floor clutter
    glBegin(GL_LINES)
    glVertex3f(cx, -2.0, cz)
    glVertex3f(cx, -CELL_SIZE * 0.9, cz)
    glEnd()

    steps = 4
    if up_ok:
        for i in range(1, steps + 1):
            t = i / steps
            _square_loop(cx, cz, half * (1.0 - 0.55 * t),
                         -2.0 - t * (CELL_SIZE * 0.45))
    if down_ok:
        for i in range(1, steps + 1):
            t = i / steps
            _square_loop(cx, cz, half * (1.0 - 0.55 * t),
                         -2.0 + t * (CELL_SIZE * 0.30))