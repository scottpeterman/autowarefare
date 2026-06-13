"""
outdoor/models/buildings.py — the four POC building silhouettes (§1, §9).

These are *game-layer* content, not engine assets, so they live under
``outdoor/models/`` (the AW side of the game-on-engine boundary) rather than
in ``outerworld_engine/models/`` with the ported BZ dicts.

POC §1 names four sizes — **warehouse, small, large, skyscraper** — and §9
gives them a gameplay gradient: warehouse = destructible cover, small = hard
cover, large = short interior (later), **skyscraper = full dive** (the portal
source). For this increment all four exist as drivable-around obstacles and
the skyscraper is the one with a lobby you can enter.

Every building is a plain ``{'lines': [...]}`` model dict — the §4a asset
contract — so it draws through the unmodified ``render.draw_obstacle`` path
and collides through the unmodified ``Obstacle.bounding_radius`` (circle of
``model_radius_2d``). Coordinates are **+Y up**, footprint centered on the
local origin, base at ``y = 0``. No new asset format, no engine edit.

The wireframe detail (corner edges + floor bands + vertical mullions + a
size-specific roof) is what makes a box read as a *building* in the cyberblue
phosphor look and gives the eye a sense of scale and height at distance.
"""

from __future__ import annotations

from az.common import model as model_mod

Vec3 = tuple[float, float, float]
Line = tuple[Vec3, Vec3]
Face = tuple[Vec3, ...]          # a convex polygon (occlusion fill)


# --- parametric primitives -------------------------------------------------

def _box_frame(hw: float, hd: float, y0: float, y1: float) -> list[Line]:
    """The 12 edges of an axis-aligned box (footprint 2hw x 2hd, y0..y1)."""
    c = [(-hw, y0, -hd), (hw, y0, -hd), (hw, y0, hd), (-hw, y0, hd),
         (-hw, y1, -hd), (hw, y1, -hd), (hw, y1, hd), (-hw, y1, hd)]
    e = [(0, 1), (1, 2), (2, 3), (3, 0),      # base ring
         (4, 5), (5, 6), (6, 7), (7, 4),      # top ring
         (0, 4), (1, 5), (2, 6), (3, 7)]      # verticals
    return [(c[a], c[b]) for a, b in e]


def _box_faces(hw: float, hd: float, y0: float, y1: float) -> list[Face]:
    """The 6 quad faces of the same box — the fills that occlude (the §9
    smoked-glass pass). Same 8 corners as ``_box_frame``; one quad per side,
    floor, and roof so the solid reads opaque/translucent from every angle."""
    c = [(-hw, y0, -hd), (hw, y0, -hd), (hw, y0, hd), (-hw, y0, hd),
         (-hw, y1, -hd), (hw, y1, -hd), (hw, y1, hd), (-hw, y1, hd)]
    q = [(0, 1, 2, 3),    # floor
         (4, 5, 6, 7),    # roof
         (0, 1, 5, 4),    # -Z wall
         (2, 3, 7, 6),    # +Z wall
         (1, 2, 6, 5),    # +X wall
         (3, 0, 4, 7)]    # -X wall
    return [tuple(c[i] for i in face) for face in q]


def _floor_rings(hw: float, hd: float, ys: list[float]) -> list[Line]:
    """A horizontal rectangle ring at each y — reads as floor slabs."""
    out: list[Line] = []
    for y in ys:
        r = [(-hw, y, -hd), (hw, y, -hd), (hw, y, hd), (-hw, y, hd)]
        out += [(r[0], r[1]), (r[1], r[2]), (r[2], r[3]), (r[3], r[0])]
    return out


def _mullions(hw: float, hd: float, y0: float, y1: float,
              bays_x: int, bays_z: int) -> list[Line]:
    """Vertical lines splitting each face into bays — reads as window columns."""
    out: list[Line] = []
    for i in range(1, bays_x):
        x = -hw + 2.0 * hw * i / bays_x
        out += [((x, y0, hd), (x, y1, hd)), ((x, y0, -hd), (x, y1, -hd))]
    for j in range(1, bays_z):
        z = -hd + 2.0 * hd * j / bays_z
        out += [((hw, y0, z), (hw, y1, z)), ((-hw, y0, z), (-hw, y1, z))]
    return out


def _make_building(hw: float, hd: float, height: float, *,
                   floors: int, bays_x: int, bays_z: int,
                   roof: list[Line] | None = None,
                   roof_faces: list[Face] | None = None) -> dict:
    lines = _box_frame(hw, hd, 0.0, height)
    if floors > 1:
        lines += _floor_rings(hw, hd, [height * k / floors
                                       for k in range(1, floors)])
    lines += _mullions(hw, hd, 0.0, height, bays_x, bays_z)
    if roof:
        lines += roof

    # The occluding solid: the body's 6 quads plus any roof faces. The floor
    # bands and mullions stay as lines — with the render's polygon offset they
    # sit just in front of these faces and read as windows on a solid facade.
    faces = _box_faces(hw, hd, 0.0, height)
    if roof_faces:
        faces += roof_faces

    m = {'lines': lines, 'faces': faces}
    model_mod.validate(m)          # dogfood the shared contract
    return m


# --- size-specific roof details --------------------------------------------

def _gable_roof(hw: float, hd: float, h: float, rise: float) -> list[Line]:
    """A ridge running the long (z) axis with four slopes to the eaves."""
    a = (0.0, h + rise, -hd)
    b = (0.0, h + rise, hd)
    eaves = [(-hw, h, -hd), (hw, h, -hd), (hw, h, hd), (-hw, h, hd)]
    return [(a, b),
            (a, eaves[0]), (a, eaves[1]), (b, eaves[2]), (b, eaves[3])]


def _penthouse(hw: float, hd: float, h: float, ph: float) -> list[Line]:
    """A small mechanical box on the roof (inset half-footprint)."""
    return _box_frame(hw * 0.45, hd * 0.45, h, h + ph)


def _setback(hw: float, hd: float, h: float, sh: float) -> list[Line]:
    """A stepped-back smaller tower crowning a large building."""
    return (_box_frame(hw * 0.6, hd * 0.6, h, h + sh)
            + _floor_rings(hw * 0.6, hd * 0.6, [h + sh * 0.5]))


def _spire(hw: float, hd: float, h: float, ch: float, sh: float) -> list[Line]:
    """A crown ring then a tapering antenna to a point — the skyscraper tell."""
    crown = _box_frame(hw * 0.7, hd * 0.7, h, h + ch)
    tip = (0.0, h + ch + sh, 0.0)
    base = [(-hw * 0.7, h + ch, -hd * 0.7), (hw * 0.7, h + ch, -hd * 0.7),
            (hw * 0.7, h + ch, hd * 0.7), (-hw * 0.7, h + ch, hd * 0.7)]
    return crown + [(tip, p) for p in base]


# --- size-specific roof faces (the occluding fills, §9 smoked glass) --------

def _gable_faces(hw: float, hd: float, h: float, rise: float) -> list[Face]:
    """The gable as occluding fill: two slope quads + two end triangles."""
    a = (0.0, h + rise, -hd)
    b = (0.0, h + rise, hd)
    e = [(-hw, h, -hd), (hw, h, -hd), (hw, h, hd), (-hw, h, hd)]
    return [
        (e[0], a, b, e[3]),      # -X slope
        (e[1], e[2], b, a),      # +X slope
        (e[0], e[1], a),         # -Z gable end
        (e[3], b, e[2]),         # +Z gable end
    ]


def _penthouse_faces(hw: float, hd: float, h: float, ph: float) -> list[Face]:
    return _box_faces(hw * 0.45, hd * 0.45, h, h + ph)


def _setback_faces(hw: float, hd: float, h: float, sh: float) -> list[Face]:
    return _box_faces(hw * 0.6, hd * 0.6, h, h + sh)


def _spire_faces(hw: float, hd: float, h: float, ch: float,
                 sh: float) -> list[Face]:
    """Crown box quads + the four triangles tapering to the antenna tip."""
    faces = _box_faces(hw * 0.7, hd * 0.7, h, h + ch)
    tip = (0.0, h + ch + sh, 0.0)
    base = [(-hw * 0.7, h + ch, -hd * 0.7), (hw * 0.7, h + ch, -hd * 0.7),
            (hw * 0.7, h + ch, hd * 0.7), (-hw * 0.7, h + ch, hd * 0.7)]
    for i in range(4):
        faces.append((tip, base[i], base[(i + 1) % 4]))
    return faces


# --- the four POC buildings -------------------------------------------------

# Warehouse — low, wide, long; destructible cover (§9). Big footprint, gabled.
WAREHOUSE = _make_building(
    80.0, 120.0, 58.0, floors=1, bays_x=4, bays_z=6,
    roof=_gable_roof(80.0, 120.0, 58.0, 34.0),
    roof_faces=_gable_faces(80.0, 120.0, 58.0, 34.0),
)

# Small building — modest tower; hard cover (§9). A few floors + a penthouse.
SMALL_BUILDING = _make_building(
    42.0, 42.0, 132.0, floors=4, bays_x=2, bays_z=2,
    roof=_penthouse(42.0, 42.0, 132.0, 22.0),
    roof_faces=_penthouse_faces(42.0, 42.0, 132.0, 22.0),
)

# Large building — blockier and taller; short-interior candidate (§9).
LARGE_BUILDING = _make_building(
    90.0, 90.0, 252.0, floors=6, bays_x=3, bays_z=3,
    roof=_setback(90.0, 90.0, 252.0, 70.0),
    roof_faces=_setback_faces(90.0, 90.0, 252.0, 70.0),
)

# Skyscraper — the landmark and the full-dive portal source (§9). Tall, narrow,
# many floor bands, crowned with a spire so it reads as THE tower at distance.
SKYSCRAPER = _make_building(
    56.0, 56.0, 540.0, floors=13, bays_x=3, bays_z=3,
    roof=_spire(56.0, 56.0, 540.0, 40.0, 120.0),
    roof_faces=_spire_faces(56.0, 56.0, 540.0, 40.0, 120.0),
)


# --- the lobby doorway (the gold entry trigger marker) ----------------------

def _doorway(width: float, height: float) -> dict:
    """A flat double-door frame in the local XY plane, facing +Z.

    Drawn in the lobby's gold so it stands out against the building's blue;
    placed flush to the skyscraper's front face by the world. Not a solid
    obstacle — it is the ``E to enter`` trigger's visible mark.
    """
    hw = width / 2.0
    frame = [
        ((-hw, 0.0, 0.0), (-hw, height, 0.0)),       # left jamb
        ((hw, 0.0, 0.0), (hw, height, 0.0)),         # right jamb
        ((-hw, height, 0.0), (hw, height, 0.0)),     # lintel
        ((0.0, 0.0, 0.0), (0.0, height, 0.0)),       # center mullion (double doors)
        ((-hw, height * 0.72, 0.0), (hw, height * 0.72, 0.0)),  # transom
    ]
    m = {'lines': frame}
    model_mod.validate(m)
    return m


DOORWAY = _doorway(46.0, 64.0)