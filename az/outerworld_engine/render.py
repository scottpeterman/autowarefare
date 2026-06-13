"""
GL helpers for drawing the battlefield.

Pure functions: take data (Battlefield, Obstacle, Camera) and emit GL calls.
The Qt renderer class in ``bz/game.py`` calls into here from its
``drawBackground`` — keeping the GL-side logic out of the Qt class makes
it testable and means we don't have to subclass anything to swap in a
different scene.

Pattern lifted from:
  - Castle of Bane's ``GL3DDungeonRenderer.drawBackground`` /
    ``_draw_entities`` (the chassis we're forking).
  - bz_model_viewer.py's draw loop (the Battlezone-side reference that's
    already been validated against every converted asset).
"""

from __future__ import annotations

import math

from OpenGL.GL import (
    GL_BLEND, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
    GL_LESS, GL_LINES, GL_MODELVIEW, GL_ONE_MINUS_SRC_ALPHA, GL_POLYGON,
    GL_POLYGON_OFFSET_FILL, GL_PROJECTION, GL_SRC_ALPHA,
    glBegin, glBlendFunc, glClear, glClearColor, glClearDepth, glColor3f,
    glColor4f, glDepthFunc, glDisable, glEnable, glEnd, glLineWidth,
    glLoadIdentity, glMatrixMode, glPolygonOffset, glPopMatrix, glPushMatrix,
    glRotatef, glTranslatef, glVertex3f, glViewport,
)
from OpenGL.GLU import gluPerspective

from .battlefield import Battlefield
from .bullet import Bullet
from .camera import Camera
from .fragment import Fragment
from .obstacle import Obstacle
from .tank import Tank


# Default projection params. World half_size is 1000, diagonal ~2828.
# DEFAULT_FAR=6000 covers the worst case: player at one corner looking
# at horizon decoration on the opposite side (corner-to-origin 1414 +
# decoration-from-origin ~2200 + decoration half-extent ~700 ≈ 4300),
# with comfortable headroom. 24-bit depth absorbs the precision cost.
DEFAULT_FOV_DEG = 75.0
DEFAULT_NEAR = 0.5
DEFAULT_FAR = 6000.0


def setup_frame(viewport_width: int, viewport_height: int,
                fov_deg: float = DEFAULT_FOV_DEG,
                near: float = DEFAULT_NEAR,
                far: float = DEFAULT_FAR) -> None:
    """Clear the framebuffer and set the standard frame state.

    Sets viewport, projection (gluPerspective), and resets modelview to
    identity. Caller is responsible for then applying the camera transform
    via ``apply_camera``.
    """
    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClearDepth(1.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    glEnable(GL_DEPTH_TEST)
    glDepthFunc(GL_LESS)

    glViewport(0, 0, viewport_width, max(viewport_height, 1))

    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(fov_deg,
                   viewport_width / max(viewport_height, 1),
                   near, far)

    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()


def apply_camera(camera: Camera) -> None:
    """Apply the inverse camera transform to the current modelview.

    Battlezone-style: rotate by heading about Y, then translate by -position.
    No pitch, no roll.

    Order matters: rotate first, then translate. (The conventional
    "view = inverse(camera_world_transform)" identity for a camera at
    position p with rotation R(theta) is V = R(-theta) * T(-p).)
    """
    glRotatef(math.degrees(camera.heading), 0.0, 1.0, 0.0)
    glTranslatef(-camera.x, -camera.eye_height, -camera.z)


# --- hidden-line occlusion: the smoked-glass dial (POC primer §9) -----------
#
# The outer world is discrete convex solids on a ground plane, so the textbook
# hidden-line-via-depth-buffer trick is cheap and exact here: draw each solid's
# FACES first (writing the depth buffer) then its EDGES with a polygon offset
# so an edge sits just in front of its own face. Without faces, pure GL_LINES
# never fills the depth buffer, so every edge shows through every building —
# the X-ray tangle. (Depth testing was always on; there was just nothing opaque
# to test against.) Faces ride on the model dict's optional 'faces' key.
#
# One dial, three looks:
#   OFF    — no fills: the original see-through wireframe (X-ray).
#   OPAQUE — black fills: maximum readability, arcade-BZ hidden line.
#   GLASS  — dark translucent fills (default): solids occlude the tangle but
#            keep a hint of see-through and the wireframe soul.
OCCLUSION_OFF = "off"
OCCLUSION_OPAQUE = "opaque"
OCCLUSION_GLASS = "glass"
OCCLUSION_MODE = OCCLUSION_GLASS          # <- the dial; default GLASS

# GLASS fill: dark translucent navy over black; alpha so overlapping panes
# deepen. OPAQUE fill: near-black (a hair above 0 so it reads as surface, not
# void, against the black sky).
GLASS_RGBA = (0.04, 0.10, 0.18, 0.45)
OPAQUE_RGB = (0.01, 0.02, 0.03)


def _emit_lines(model: dict, scale: float) -> None:
    """Emit a model's wireframe as GL_LINES at the current matrix. Assumes the
    caller has pushed the per-entity transform and set the color."""
    glBegin(GL_LINES)
    for (x1, y1, z1), (x2, y2, z2) in model['lines']:
        glVertex3f(x1 * scale, y1 * scale, z1 * scale)
        glVertex3f(x2 * scale, y2 * scale, z2 * scale)
    glEnd()


def _emit_faces(model: dict, scale: float) -> None:
    """Emit a model's filled polygons (its optional 'faces'), one GL_POLYGON
    each, at the current matrix. No-op for line-only models (e.g. the doorway,
    tanks, bullets) so they simply don't occlude."""
    faces = model.get('faces')
    if not faces:
        return
    for poly in faces:
        glBegin(GL_POLYGON)
        for (x, y, z) in poly:
            glVertex3f(x * scale, y * scale, z * scale)
        glEnd()


def _push_obstacle(obstacle: Obstacle, time_sec: float) -> float:
    """Push the obstacle's model transform (translate + bob + heading) and
    return the composed scale. Caller pops. Shared by the edge and face passes
    so the wireframe and its fill never drift apart."""
    model = obstacle.model
    scale = model.get('scale', 1.0) * obstacle.scale
    bob_speed = model.get('bob_speed', 0.0)
    bob_amount = model.get('bob_amount', 0.0)
    bob_y = math.sin(time_sec * bob_speed) * bob_amount if bob_speed > 0 else 0.0
    glPushMatrix()
    glTranslatef(obstacle.x, bob_y, obstacle.z)
    if obstacle.heading:
        glRotatef(-math.degrees(obstacle.heading), 0.0, 1.0, 0.0)
    return scale


def draw_obstacle(obstacle: Obstacle, r: float, g: float, b: float,
                  time_sec: float = 0.0) -> None:
    """Draw a single obstacle's wireframe.

    Composes ``obstacle.scale`` with the model's intrinsic ``scale``.
    Honors the model's bob fields if present (``bob_speed``, ``bob_amount``).
    Edges only — the occluding fills are drawn separately in the faces pass
    of ``draw_battlefield`` (see the OCCLUSION_MODE dial).
    """
    scale = _push_obstacle(obstacle, time_sec)
    glColor3f(r, g, b)
    _emit_lines(obstacle.model, scale)
    glPopMatrix()


def draw_bullet(bullet: Bullet, r: float, g: float, b: float) -> None:
    """Draw a single bullet's wireframe.

    Same composition as ``draw_obstacle`` but with the bullet's own Y
    offset (eye-line / gun-level rather than the ground plane that
    obstacles sit on). No bob — bullets are short-lived and travel in
    a straight line. Visual scale is per-instance only; bullets carry
    no model intrinsic-scale composition because they all use the same
    model with the same intended visual size.
    """
    model = bullet.model
    scale = bullet.scale

    glPushMatrix()
    glTranslatef(bullet.x, bullet.y, bullet.z)
    if bullet.heading:
        # See draw_tank — negative for model-space convention parity.
        glRotatef(-math.degrees(bullet.heading), 0.0, 1.0, 0.0)

    glColor3f(r, g, b)
    glBegin(GL_LINES)
    for (x1, y1, z1), (x2, y2, z2) in model['lines']:
        glVertex3f(x1 * scale, y1 * scale, z1 * scale)
        glVertex3f(x2 * scale, y2 * scale, z2 * scale)
    glEnd()

    glPopMatrix()


def draw_fragment(frag: Fragment, r: float, g: float, b: float) -> None:
    """Draw a single explosion fragment with two-axis tumble.

    Fragments have both a Y-axis heading (like everything else) and
    an X-axis tumble angle, composed together to create the arcade's
    tumbling-shrapnel look. The Y position is dynamic (arcs under
    gravity), unlike tanks and obstacles which sit on the ground.

    Fade-out: fragments dim linearly over their lifetime so they
    don't just blink out — they fade into the background.
    """
    model = frag.model
    scale = frag.scale

    # Fade: full brightness at spawn, dims to ~20% at death.
    fade = max(0.2, frag.lifetime / 90.0)  # 90 = default lifetime
    fr, fg, fb = r * fade, g * fade, b * fade

    glPushMatrix()
    glTranslatef(frag.x, frag.y, frag.z)
    # Y-axis rotation (heading — same convention as tanks/obstacles)
    if frag.heading:
        glRotatef(-math.degrees(frag.heading), 0.0, 1.0, 0.0)
    # X-axis tumble (the visible "tumble" that makes fragments look
    # like shrapnel, not just spinning discs)
    if frag.tumble:
        glRotatef(math.degrees(frag.tumble), 1.0, 0.0, 0.0)

    glColor3f(fr, fg, fb)
    glBegin(GL_LINES)
    for (x1, y1, z1), (x2, y2, z2) in model['lines']:
        glVertex3f(x1 * scale, y1 * scale, z1 * scale)
        glVertex3f(x2 * scale, y2 * scale, z2 * scale)
    glEnd()

    glPopMatrix()


def draw_tank(tank: Tank, r: float, g: float, b: float) -> None:
    """Draw a single tank's wireframe.

    Same composition as ``draw_obstacle`` but tighter — tanks have no
    bob (the model has its own treads/turret detail; bobbing the whole
    rigid body would look weird) and no Y offset (sits on the ground
    plane like an obstacle, unlike bullets which fly above it).

    Heading inversion (the negative sign on glRotatef): ``glRotatef``
    applied as a *model* transform rotates the model in the opposite
    direction from the same call applied as a *view* transform (the
    way ``apply_camera`` uses it). The Camera and AI both use the
    convention forward = (sin(h), -cos(h)) — heading=0 faces -Z, +π/2
    faces +X (east), positive heading clockwise from above. Without
    the negation here, a tank with heading=π/2 (AI thinks: faces east)
    visually points west; heading=0 and heading=π are coincidentally
    correct (X-axis is zero so the mirror is invisible), which is why
    static test tanks at h∈{0, π} rendered fine but the AI tank's
    intermediate angles all faced the wrong direction. Negating here
    makes the render match the AI's forward-vector convention end to
    end. ``draw_obstacle`` and ``draw_bullet`` carry the same
    correction for consistency.
    """
    model = tank.model
    intrinsic_scale = model.get('scale', 1.0)
    scale = intrinsic_scale * tank.scale

    glPushMatrix()
    glTranslatef(tank.x, 0.0, tank.z)
    if tank.heading:
        glRotatef(-math.degrees(tank.heading), 0.0, 1.0, 0.0)

    # Damage tint (M1 increment 3): a full-HP tank renders in the world color;
    # as it takes hits the wireframe lerps toward a hot orange-red and brightens
    # slightly, so health reads straight off the model with no HUD. A default
    # one-hit tank (max_hp 1.0) never shows damaged — it dies on the first hit.
    frac = tank.hp_fraction
    if frac < 1.0:
        t = 1.0 - frac                       # 0 = pristine, 1 = near death
        hot_r, hot_g, hot_b = 1.0, 0.35, 0.2
        r = r + (hot_r - r) * t
        g = g + (hot_g - g) * t
        b = b + (hot_b - b) * t

    glColor3f(r, g, b)
    glBegin(GL_LINES)
    for (x1, y1, z1), (x2, y2, z2) in model['lines']:
        glVertex3f(x1 * scale, y1 * scale, z1 * scale)
        glVertex3f(x2 * scale, y2 * scale, z2 * scale)
    glEnd()

    glPopMatrix()


def _draw_faces_pass(battlefield: Battlefield, time_sec: float,
                     camera: Camera | None) -> None:
    """Fill every solid's faces into the depth buffer so edges behind them are
    hidden. GLASS sorts solids back-to-front and blends dark translucent panes
    (so overlapping glass deepens and a near tower veils the tower behind it);
    OPAQUE fills near-black for maximum hidden-line readability. A polygon
    offset pushes the fills just behind their own edges, so the floor bands and
    mullions read as windows on a now-solid facade rather than z-fighting it.
    """
    obstacles = [o for o in battlefield.obstacles if o.model.get('faces')]
    if not obstacles:
        return

    glass = (OCCLUSION_MODE == OCCLUSION_GLASS)
    if glass and camera is not None:
        # back-to-front: farthest solid drawn first so nearer panes blend over
        obstacles.sort(
            key=lambda o: (o.x - camera.x) ** 2 + (o.z - camera.z) ** 2,
            reverse=True)

    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(1.0, 1.0)
    if glass:
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(*GLASS_RGBA)
    else:
        glColor3f(*OPAQUE_RGB)

    for obstacle in obstacles:
        scale = _push_obstacle(obstacle, time_sec)
        _emit_faces(obstacle.model, scale)
        glPopMatrix()

    if glass:
        glDisable(GL_BLEND)
    glDisable(GL_POLYGON_OFFSET_FILL)


def draw_battlefield(battlefield: Battlefield,
                     r: float, g: float, b: float,
                     time_sec: float = 0.0,
                     camera: Camera | None = None) -> None:
    """Draw all obstacles, tanks, and bullets in a battlefield.

    Two passes when occlusion is on (the default GLASS): first every solid's
    faces (writing depth so the X-ray tangle behind them is hidden), then all
    edges. Doing every face before any edge is what lets a near building occlude
    a far building's wireframe — not just its own. ``camera`` is needed only to
    sort the translucent glass back-to-front; pass it from the world's draw.

    Edge order: obstacles → tanks → fragments → bullets (most-recent action
    drawn last). No frustum culling yet — cheap at these entity counts.
    """
    if OCCLUSION_MODE != OCCLUSION_OFF:
        _draw_faces_pass(battlefield, time_sec, camera)

    glLineWidth(2.0)
    for obstacle in battlefield.obstacles:
        draw_obstacle(obstacle, r, g, b, time_sec)
    for tank in battlefield.tanks:
        draw_tank(tank, r, g, b)
    for fragment in battlefield.fragments:
        draw_fragment(fragment, r, g, b)
    for bullet in battlefield.bullets:
        draw_bullet(bullet, r, g, b)


def draw_ground_grid(half_size: float, step: float,
                     r: float, g: float, b: float,
                     y: float = 0.0) -> None:
    """Optional reference grid on the ground plane.

    Useful for spatial debugging before the horizon line is in. The
    original Battlezone has no ground grid — this is a development aid,
    toggle it off for the "real" look.
    """
    glLineWidth(1.0)
    glColor3f(r, g, b)
    glBegin(GL_LINES)
    n = int(half_size / step)
    for i in range(-n, n + 1):
        x = i * step
        glVertex3f(x, y, -half_size)
        glVertex3f(x, y,  half_size)
        glVertex3f(-half_size, y, x)
        glVertex3f( half_size, y, x)
    glEnd()