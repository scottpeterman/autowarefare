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
    GL_BLEND, GL_COLOR_BUFFER_BIT, GL_COLOR_LOGIC_OP, GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST, GL_LEQUAL, GL_LIGHTING, GL_LINE_LOOP, GL_LINES,
    GL_LESS, GL_MODELVIEW, GL_POLYGON, GL_PROJECTION, GL_TEXTURE_2D, GL_TRUE,
    glBegin, glClear, glClearColor, glClearDepth, glColor3f, glColorMask,
    glDepthFunc, glDisable, glEnable, glEnd, glLineWidth, glLoadIdentity,
    glMatrixMode, glPopMatrix, glPushMatrix, glRotatef, glScalef, glTranslatef,
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
PLANT_RGB = (1.0, 0.84, 0.0)     # bright gold — the win object (vision §2)
INTEL_RGB = (1.0, 0.2, 0.85)     # bright magenta — information, distinct from gold
MOB_RGB = (1.0, 0.27, 0.20)      # hot red — threat, distinct from blue/green/amber/gold
BOLT_RGB = (1.0, 0.95, 0.40)     # hot yellow — gunman fire, distinct from red mobs

# Baked, numpy-free enemy wireframes (indoor -Y-up space, +Z forward).
from az.indoor.models.mobsters import MODELS as _MOB_MODELS
from az.indoor.projectile import BOLT_Y

FOV_DEG = 75.0
NEAR, FAR = 1.0, 1000.0      # Bane's own near/far; interiors are bounded


def draw_interior(*, dungeon, bsp_tree, cam_x: float, cam_y: float,
                  cam_z: float, cam_angle_deg: float, vp_w: int, vp_h: int,
                  exit_world: tuple[float, float] | None = None,
                  exit_half: float = 25.0,
                  up_world: tuple[float, float] | None = None,
                  down_world: tuple[float, float] | None = None,
                  objectives: list | None = None,
                  enemies: list | None = None,
                  bolts: list | None = None) -> None:
    """Render one indoor frame into the shell's already-current GL context.

    ``cam_angle_deg`` is degrees about +Y (Bane convention). ``cam_y`` is the
    eye height in the -Y-up space (Bane uses ``-15``). The caller (IndoorWorld)
    owns all of this state; this function is stateless drawing only.
    """
    # Re-establish a clean fixed-function color pipeline before any draw. The
    # de-windowed renderer shed Bane's beginNativePainting/endNativePainting
    # bracket, which used to make Qt save/restore GL state around raw GL. Without
    # it, the QPainter HUD pass can leave blend / colormask / lighting / logic-op
    # state dirty for the *next* frame, silently dropping a channel (the red-loss
    # bug: white renders cyan, amber renders green, gold renders green). A guest
    # issuing raw GL must assert the state it assumes — a colormask reset alone
    # wasn't enough, so we also disable every stage that can modulate colour.
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)
    glDisable(GL_BLEND)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glDisable(GL_COLOR_LOGIC_OP)

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

    # Up-stair and down-stair are independent cells now: an up-glyph at the
    # up-stair, a down-glyph at the down-stair. On a chimney-point floor they
    # share a cell and the two single-direction glyphs composite into the old
    # both-ways hourglass for free.
    if up_world is not None:
        _draw_stair_marker(up_world[0], up_world[1], True, False)
    if down_world is not None:
        _draw_stair_marker(down_world[0], down_world[1], False, True)

    # Objective markers: a plant (hot magenta) or intel (cyan) diamond beacon,
    # cell-keyed and stateless like the exit/stair glyphs. The caller passes only
    # uncollected objectives, so a picked-up one simply stops being drawn.
    for ox, oz, kind in (objectives or []):
        _draw_objective_marker(ox, oz, PLANT_RGB if kind == "plant"
                               else INTEL_RGB)

    # Enemy wireframes: the baked humanoid bodies, placed + faced per mob. Drawn
    # at true depth (GL_LESS) so a wall occludes a mob behind it. Bodies are
    # authored +Z forward; the per-mob rotation aims that +Z down the mob's
    # heading (the same (sin h, -cos h) forward the player and walls share).
    for ex, ez, facing_deg, name in (enemies or []):
        model = _MOB_MODELS.get(name)
        if model is not None:
            _draw_enemy(model["lines"], ex, ez, facing_deg)

    # Gunman bolts: a small bright glyph at chest height, so a shot reads as an
    # object in flight you can sidestep — not an instant line.
    for bx, bz in (bolts or []):
        _draw_bolt(bx, bz)

    glLineWidth(1.0)
    # Leave the context QPainter-safe for the shell's HUD pass (the validated
    # GL-then-QPainter order in shell/app.py). Mirrors Bane's own teardown.
    glDisable(GL_DEPTH_TEST)


def _draw_bolt(bx: float, bz: float, r: float = 5.0) -> None:
    """A bolt in flight: a small bright 3-axis cross centred at chest height
    (BOLT_Y), readable from any angle without billboarding."""
    glColor3f(*BOLT_RGB)
    glLineWidth(3.0)
    glBegin(GL_LINES)
    glVertex3f(bx - r, BOLT_Y, bz); glVertex3f(bx + r, BOLT_Y, bz)
    glVertex3f(bx, BOLT_Y - r, bz); glVertex3f(bx, BOLT_Y + r, bz)
    glVertex3f(bx, BOLT_Y, bz - r); glVertex3f(bx, BOLT_Y, bz + r)
    glEnd()


def _draw_enemy(lines, ex: float, ez: float, facing_deg: float) -> None:
    """Draw one baked humanoid wireframe at (ex, ez) on the floor, faced along
    its heading. The model is already in indoor -Y-up space (feet y=0, head at
    negative y); we translate to the floor cell and rotate its +Z forward onto
    the world heading. ``180 - facing`` maps model +Z=(0,0,1) to the world's
    forward (sin h, -cos h) — the Y-flip in the modelview commutes with this
    Y-rotation, so the heading is unaffected by it."""
    glColor3f(*MOB_RGB)
    glLineWidth(2.0)
    glPushMatrix()
    glTranslatef(ex, 0.0, ez)
    glRotatef(180.0 - facing_deg, 0.0, 1.0, 0.0)
    glBegin(GL_LINES)
    for a, b in lines:
        glVertex3f(a[0], a[1], a[2])
        glVertex3f(b[0], b[1], b[2])
    glEnd()
    glPopMatrix()


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

def _draw_objective_marker(cx: float, cz: float, rgb) -> None:
    """A flag: a tall pole rising nearly to the ceiling with a triangular pennant
    near the top, plus a small floor base so it roots visibly. Tall and bright so
    it's spotted from across the room — the 'come search here' read the diamond
    didn't carry. Drawn only for uncollected objectives (the caller filters);
    colour tells plant (gold) from intel (magenta)."""
    from az.innerworld_engine import CELL_SIZE
    base_y = -2.0
    top_y = -CELL_SIZE * 1.05          # -Y is up: nearly to the ceiling
    glColor3f(*rgb)
    glLineWidth(3.0)

    # pole
    glBegin(GL_LINES)
    glVertex3f(cx, base_y, cz)
    glVertex3f(cx, top_y, cz)
    glEnd()

    # pennant — a triangle flying off the top of the pole (+x side)
    flag_w = CELL_SIZE * 0.34
    flag_drop = CELL_SIZE * 0.22       # +Y is down, so the pennant hangs below apex
    glBegin(GL_LINE_LOOP)
    glVertex3f(cx, top_y, cz)
    glVertex3f(cx + flag_w, top_y + flag_drop * 0.5, cz)
    glVertex3f(cx, top_y + flag_drop, cz)
    glEnd()

    # small base footprint so the pole reads as planted on the floor
    glLineWidth(2.0)
    _square_loop(cx, cz, 8.0, base_y)