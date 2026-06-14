"""
outdoor/models/vehicles.py — the three Auto Warfare chassis silhouettes
(M1 visual pass).

This is the *look* half of the three-vehicle system. The *data* half — hp,
handling, loadout, score — lives in ``az/outdoor/vehicles.py`` and attaches a
model here via each ``VehicleDef``'s ``model=`` field. Until this pass all three
defs shared ``TANK_MODEL``; identity rode the dynamics. These wireframes give the
eye what the data already says: a fragile darting Sedan, a heavy boxy Pickup, a
long elite Flatbed, distinguishable at battlefield distance.

Asset contract (mirrors ``tank_model.py`` so heading semantics line up):

  * Plain ``{'lines'}`` model dicts — pairs of ``(x, y, z)`` endpoints.
  * **+Y up** (ground plane at ``y≈0``, the body builds upward).
  * **-Z forward.** The nose / hood / gun barrel sits at the most-negative Z so
    ``heading=0`` faces the player's spawn forward and ``draw_tank`` rotates the
    barrel onto the world fire vector with no offset (same as ``TANK_MODEL``).
  * **No ``faces``.** Vehicles stay faceless (settled, primer "do not
    re-litigate"): they never occlude or take the smoked-glass fill, so they read
    as *lighter* objects against the solid architecture. Lines only.
  * Authored at final world units → ``scale: 1.0`` (no per-instance Tank.scale).

Sizing is deliberate, because ``Tank.bounding_radius`` derives from the model's
2D (XZ) extent (``model_radius_2d * scale``), so a silhouette's footprint *is*
its hit circle. The canonical tank is ~27. These come out roughly:

  Sedan   ~16   — genuinely the smallest hull. Harder to hit, which suits the
                  fragile darting swarm; still eats one player shell cleanly.
  Pickup  ~24   — bigger than the Sedan and reads *heavy* (its mass is height,
                  not footprint); comfortably under the tank, never a free hit.
  Flatbed ~30   — the longest hull; the elite carrier earns the largest circle.

Vertical grounding (lowest geometry near ``y≈0``, slight wheel clearance) and the
exact read are seat sign-off items — ``draw_tank`` translates at ``y=0`` with no
offset, so what's authored here is what sits on the dirt.
"""

from __future__ import annotations

from az.common import model as model_mod

Vec3 = tuple[float, float, float]
Line = tuple[Vec3, Vec3]


# --- primitives ------------------------------------------------------------

def _box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float,
         *, top: bool = True, bottom: bool = True) -> list[Line]:
    """Edges of an axis-aligned box. ``top``/``bottom`` drop the +Y / -Y face
    rectangles (an open-top box is the Pickup bed; an open frame is the Flatbed
    deck). The four vertical pillars are always drawn."""
    # corner shorthand: (x, z) at a given y
    def c(x: float, z: float, y: float) -> Vec3:
        return (x, y, z)

    lines: list[Line] = []
    # bottom rectangle
    if bottom:
        lines += [
            (c(x0, z0, y0), c(x1, z0, y0)), (c(x1, z0, y0), c(x1, z1, y0)),
            (c(x1, z1, y0), c(x0, z1, y0)), (c(x0, z1, y0), c(x0, z0, y0)),
        ]
    # top rectangle
    if top:
        lines += [
            (c(x0, z0, y1), c(x1, z0, y1)), (c(x1, z0, y1), c(x1, z1, y1)),
            (c(x1, z1, y1), c(x0, z1, y1)), (c(x0, z1, y1), c(x0, z0, y1)),
        ]
    # four vertical pillars
    lines += [
        (c(x0, z0, y0), c(x0, z0, y1)), (c(x1, z0, y0), c(x1, z0, y1)),
        (c(x1, z1, y0), c(x1, z1, y1)), (c(x0, z1, y0), c(x0, z1, y1)),
    ]
    return lines


def _barrel(cx: float, cy: float, r: float, z_back: float, z_tip: float
            ) -> list[Line]:
    """A square-section gun barrel along Z, capped at both ends. ``z_tip`` is
    the muzzle (author it < ``z_back`` so the barrel points -Z / forward).
    ``r`` = half-width, so a thin ``r`` reads as the Sedan's MG and a fat ``r``
    as the Pickup/Flatbed cannon."""
    def corners(z: float) -> list[Vec3]:
        return [(cx - r, cy - r, z), (cx + r, cy - r, z),
                (cx + r, cy + r, z), (cx - r, cy + r, z)]
    back, tip = corners(z_back), corners(z_tip)
    lines: list[Line] = []
    for ring in (back, tip):                       # the two end caps
        for i in range(4):
            lines.append((ring[i], ring[(i + 1) % 4]))
    for i in range(4):                             # the four long edges
        lines.append((back[i], tip[i]))
    return lines


def _wheel(cx: float, cz: float, *, half: float = 1.6, y0: float = 0.0,
           y1: float = 3.0, run: float = 4.0) -> list[Line]:
    """A small wheel hint — a short box straddling the ground at a corner, its
    long axis along Z (the rolling direction). Cheap, but it grounds a faceless
    hull so it reads as a vehicle rather than a floating crate."""
    return _box(cx - half, cx + half, y0, y1, cz - run, cz + run)


def _finish(lines: list[Line]) -> dict:
    m = {'lines': lines, 'scale': 1.0, 'bob_speed': 0.0, 'bob_amount': 0.0}
    model_mod.validate(m)
    return m


# --- Sedan: low, sleek, small — the fragile swarm (pulse MG) ---------------
# Classic three-box car read: a low body, a raised glasshouse cabin set back of
# centre, a sloped hood to the nose and a fastback tail. A thin MG rides the
# roof, muzzle forward. Smallest footprint of the three (~16 hit radius).

def _sedan_model() -> dict:
    L: list[Line] = []
    # lower body
    L += _box(-7.0, 7.0, 1.5, 5.0, -13.0, 13.0)
    # cabin / glasshouse (raised, set back, shorter than the body -> sleek)
    L += _box(-5.5, 5.5, 5.0, 9.0, -4.0, 7.0)
    # hood: body front-top down to a nose lip
    L += [((-7.0, 5.0, -13.0), (-6.0, 3.5, -15.0)),
          (( 7.0, 5.0, -13.0), ( 6.0, 3.5, -15.0)),
          ((-6.0, 3.5, -15.0), ( 6.0, 3.5, -15.0))]
    # windshield: cabin front down to the hood line
    L += [((-5.5, 9.0, -4.0), (-7.0, 5.0, -13.0)),
          (( 5.5, 9.0, -4.0), ( 7.0, 5.0, -13.0))]
    # backlight + trunk: cabin rear down to the body tail
    L += [((-5.5, 9.0, 7.0), (-7.0, 5.0, 13.0)),
          (( 5.5, 9.0, 7.0), ( 7.0, 5.0, 13.0))]
    # roof-mounted MG (thin), muzzle forward (-Z)
    L += _barrel(0.0, 9.5, 0.8, z_back=-1.0, z_tip=-10.0)
    # wheels
    L += _wheel(-6.5, -8.5) + _wheel(6.5, -8.5) + _wheel(-6.5, 9.0) + _wheel(6.5, 9.0)
    return _finish(L)


# --- Pickup: tall, boxy, raised bed — the bruiser (shell cannon) -----------
# A tall slab cab at the front and an open, walled bed at the rear. Mass reads
# as *height*, not footprint. A fat cannon sits high on the cab, muzzle forward.

def _pickup_model() -> dict:
    L: list[Line] = []
    # tall boxy cab (front, -Z)
    L += _box(-11.0, 11.0, 1.5, 18.0, -21.0, -3.0)
    # bed: walled, open top (the four top edges dropped -> reads as a bed)
    L += _box(-11.0, 11.0, 1.5, 13.0, -3.0, 21.0, top=False)
    # raised bed floor (so it reads as a high bed, not a deep well)
    L += [((-11.0, 7.0, -3.0), (11.0, 7.0, -3.0)),
          (( 11.0, 7.0, -3.0), (11.0, 7.0, 21.0)),
          (( 11.0, 7.0, 21.0), (-11.0, 7.0, 21.0)),
          ((-11.0, 7.0, 21.0), (-11.0, 7.0, -3.0))]
    # fat shell cannon high on the cab, muzzle forward (-Z)
    L += _barrel(0.0, 14.0, 1.6, z_back=-3.0, z_tip=-18.0)
    # wheels (bigger), front + rear pairs
    L += (_wheel(-10.0, -14.0, half=2.0, y1=3.6, run=5.0)
          + _wheel(10.0, -14.0, half=2.0, y1=3.6, run=5.0)
          + _wheel(-10.0, 14.0, half=2.0, y1=3.6, run=5.0)
          + _wheel(10.0, 14.0, half=2.0, y1=3.6, run=5.0))
    return _finish(L)


# --- Flatbed: long, low, flat deck — the elite carrier (shell + pulse) ------
# Longest hull. A modest cab forward, a long low load deck behind it on a frame.
# It carries both weapons, so both read: a long main cannon on the cab roof and
# a short pulse nub beside it. Largest hit circle (~30) — the elite earns it.

def _flatbed_model() -> dict:
    L: list[Line] = []
    # long low chassis frame running the whole length
    L += _box(-9.0, 9.0, 1.5, 3.0, -29.0, 29.0)
    # cab (front)
    L += _box(-9.0, 9.0, 3.0, 12.0, -29.0, -15.0)
    # flat load deck (a frame on legs, open top — the flat rear deck)
    L += _box(-9.0, 9.0, 6.0, 6.0001, -15.0, 29.0, bottom=False)  # deck plane
    #   deck legs down to the frame
    for z in (-15.0, 0.0, 14.0, 29.0):
        L += [((-9.0, 3.0, z), (-9.0, 6.0, z)), ((9.0, 3.0, z), (9.0, 6.0, z))]
    #   a couple of cross-members so the deck reads as planks, not a sheet
    for z in (-2.0, 12.0, 24.0):
        L += [((-9.0, 6.0, z), (9.0, 6.0, z))]
    # main shell cannon on the cab roof, muzzle forward (-Z)
    L += _barrel(-3.0, 9.5, 1.4, z_back=-15.0, z_tip=-27.0)
    # secondary pulse nub beside it (thin, shorter)
    L += _barrel(4.5, 9.5, 0.7, z_back=-15.0, z_tip=-22.0)
    # wheels — three pairs along the long frame
    for z in (-22.0, 2.0, 22.0):
        L += (_wheel(-8.0, z, half=1.8, y1=3.2, run=4.5)
              + _wheel(8.0, z, half=1.8, y1=3.2, run=4.5))
    return _finish(L)


SEDAN_MODEL = _sedan_model()
PICKUP_MODEL = _pickup_model()
FLATBED_MODEL = _flatbed_model()


if __name__ == '__main__':  # quick extent / hit-radius report
    from az.outerworld_engine.obstacle import model_radius_2d
    for name, m in (('SEDAN', SEDAN_MODEL), ('PICKUP', PICKUP_MODEL),
                    ('FLATBED', FLATBED_MODEL)):
        (xn, xx), (yn, yx), (zn, zx) = model_mod.bounds(m)
        print(f'{name:8s} lines={len(m["lines"]):3d}  '
              f'X[{xn:6.1f},{xx:5.1f}] Y[{yn:5.1f},{yx:5.1f}] '
              f'Z[{zn:6.1f},{zx:5.1f}]  hit_r2d={model_radius_2d(m):5.1f}')