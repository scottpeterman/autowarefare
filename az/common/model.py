"""
common/model.py — the wireframe model-dict contract for Auto Warfare.

Both worlds (outdoor Battlezone lineage, indoor Castle of Bane lineage) draw
every wireframe drawable from the same dict shape. This module is the single
definition of that shape: validation, normalization, and pure geometry
helpers. It is the section 4a "asset contract" from the POC design.

The contract
------------
A *model dict* is::

    MODEL = {
        'lines': [((x1, y1, z1), (x2, y2, z2)), ...],  # REQUIRED
        'scale':      1.0,          # intrinsic scale            (optional)
        'bob_speed':  0.0,          # idle-bob radians/sec       (optional)
        'bob_amount': 0.0,          # idle-bob amplitude (units) (optional)
        'face_mode':  'billboard',  # entity-only: billboard|lock(optional)
    }

Coordinates are **+Y up, universally.** Both model viewers
(bz_model_viewer.py, model_viewer_pro.py) render model geometry +Y-up, and so
do both in-game entity paths. The -Y-up convention in Castle of Bane applies
only to BSP *wall* geometry, which never travels as a model dict and is
therefore out of scope here. A humanoid authored +Y-up drops into either world
with no flip.

Provenance (so nothing here is invented):
  - ``is_model`` is the duck-type from bz_model_viewer._is_wireframe_dict.
  - the normalized defaults match _discover_models' setdefault calls.
  - ``bounds`` / ``radius`` mirror _model_bounds / _model_radius.
  - ``bob_offset`` is the shared sin(t*bob_speed)*bob_amount formula used
    identically by render.py and the BZ viewer.

What this module deliberately does NOT do
------------------------------------------
  - **No scale composition.** Instance scale (tank.scale, obstacle.scale)
    lives on the entity, a per-world concern. The draw helper composes
    ``model['scale'] * instance.scale``; that rule stays at the draw site
    (see render.py.draw_tank / draw_obstacle).
  - **No heading / rotation.** Outdoor negates model-space glRotatef to match
    its forward-vector convention; indoor entities billboard or lock-face.
    Rotation is per-world and never uniform, so it is not modeled here.
  - **No axis flips.** Models are +Y-up; there is nothing to flip.
  - **No OpenGL.** Pure data, so it stays testable and host-agnostic. Drawing
    lives in each world's render functions.
"""

from __future__ import annotations

import math
from typing import TypedDict


# --- Type aliases ----------------------------------------------------------

Vec3 = tuple[float, float, float]
Line = tuple[Vec3, Vec3]


class _ModelRequired(TypedDict):
    lines: list[Line]


class Model(_ModelRequired, total=False):
    """Documented shape of a wireframe model dict. Keys past ``lines`` are
    optional and backfilled by :func:`normalize`."""
    scale: float
    bob_speed: float
    bob_amount: float
    face_mode: str


# --- Contract constants ----------------------------------------------------

DEFAULT_SCALE = 1.0
DEFAULT_BOB_SPEED = 0.0
DEFAULT_BOB_AMOUNT = 0.0

FACE_BILLBOARD = 'billboard'
FACE_LOCK = 'lock'
DEFAULT_FACE_MODE = FACE_BILLBOARD

# The three keys every world backfills so draw helpers never KeyError-guard.
# Matches bz_model_viewer._discover_models. ``face_mode`` is intentionally NOT
# here: it is entity-only and read with .get(...) at draw time, so outdoor
# obstacles never carry a meaningless facing key.
_NORMALIZED_DEFAULTS = {
    'scale': DEFAULT_SCALE,
    'bob_speed': DEFAULT_BOB_SPEED,
    'bob_amount': DEFAULT_BOB_AMOUNT,
}


class ModelError(ValueError):
    """Raised by :func:`validate` when a dict violates the model contract."""


# --- Validation ------------------------------------------------------------

def is_model(obj: object) -> bool:
    """Duck-type check for the wireframe model shape. Cheap, never raises.

    Faithful to bz_model_viewer._is_wireframe_dict: an empty ``lines`` list is
    structurally valid (allowed, if not useful); a non-empty one is checked
    only at its first entry for the ((x,y,z),(x,y,z)) shape. Use this for
    discovery/filtering. For authoring-time failures with a reason, use
    :func:`validate`.
    """
    if not isinstance(obj, dict):
        return False
    lines = obj.get('lines')
    if not isinstance(lines, (list, tuple)):
        return False
    if not lines:
        return True
    first = lines[0]
    return (
        isinstance(first, (list, tuple))
        and len(first) == 2
        and all(isinstance(p, (list, tuple)) and len(p) == 3 for p in first)
    )


def validate(model: object) -> None:
    """Strict check that raises :class:`ModelError` with a specific reason.

    Stricter than :func:`is_model` in two deliberate ways: it inspects *every*
    line (not just the first), so a malformed vertex deep in a hand-authored
    building model is caught; and it type-checks the optional scalar keys.
    Use at load time where a clear failure beats the viewer's silent skip.
    """
    if not isinstance(model, dict):
        raise ModelError(f'model must be a dict, got {type(model).__name__}')
    if 'lines' not in model:
        raise ModelError("model missing required 'lines' key")
    lines = model['lines']
    if not isinstance(lines, (list, tuple)):
        raise ModelError(
            f"'lines' must be a list/tuple, got {type(lines).__name__}")
    for i, entry in enumerate(lines):
        if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
            raise ModelError(f'line {i}: expected a (start, end) pair')
        for end_name, p in zip(('start', 'end'), entry):
            if not (isinstance(p, (list, tuple)) and len(p) == 3):
                raise ModelError(f'line {i} {end_name}: expected (x, y, z)')
            if not all(isinstance(c, (int, float)) for c in p):
                raise ModelError(f'line {i} {end_name}: coords must be numbers')
    for key in _NORMALIZED_DEFAULTS:
        if key in model and not isinstance(model[key], (int, float)):
            raise ModelError(f"'{key}' must be a number if present")
    if 'face_mode' in model and model['face_mode'] not in (FACE_BILLBOARD, FACE_LOCK):
        raise ModelError(
            f"'face_mode' must be {FACE_BILLBOARD!r} or {FACE_LOCK!r}")
    # Optional 'faces': filled polygons used only for hidden-line occlusion in
    # the outer world's smoked-glass render pass (lines remain the soul of the
    # look). Each face is a convex polygon of >= 3 (x, y, z) points. Absent on
    # most models; present on solids (buildings, debris) that should occlude.
    if 'faces' in model:
        faces = model['faces']
        if not isinstance(faces, (list, tuple)):
            raise ModelError(
                f"'faces' must be a list/tuple, got {type(faces).__name__}")
        for i, poly in enumerate(faces):
            if not (isinstance(poly, (list, tuple)) and len(poly) >= 3):
                raise ModelError(f'face {i}: expected >= 3 points')
            for p in poly:
                if not (isinstance(p, (list, tuple)) and len(p) == 3
                        and all(isinstance(c, (int, float)) for c in p)):
                    raise ModelError(f'face {i}: each point must be (x, y, z)')


# --- Normalization ---------------------------------------------------------

def normalize(model: Model) -> Model:
    """Return a shallow copy with scale/bob_speed/bob_amount backfilled.

    Shallow by design: the (potentially large) ``lines`` list is shared, not
    copied — only scalar keys are added. Unlike the viewer's in-place
    ``setdefault``, this does not mutate the source, so module-level model
    constants stay pristine when shared across both worlds.
    """
    out = dict(model)
    for key, default in _NORMALIZED_DEFAULTS.items():
        out.setdefault(key, default)
    return out  # type: ignore[return-value]


# --- Geometry helpers ------------------------------------------------------

_UNIT_BOX = ((-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0))


def bounds(model: Model
           ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Axis-aligned bounds ((xmin,xmax),(ymin,ymax),(zmin,zmax)) over all line
    endpoints. Empty model -> unit box (matches the viewer)."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for a, b in model['lines']:
        xs.append(a[0]); xs.append(b[0])
        ys.append(a[1]); ys.append(b[1])
        zs.append(a[2]); zs.append(b[2])
    if not xs:
        return _UNIT_BOX
    return ((min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs)))


def center(model: Model) -> Vec3:
    """Midpoint of the model's bounds. Useful for vertical framing — the BZ
    viewer aims its orbit target at the Y center this way."""
    (xn, xx), (yn, yx), (zn, zx) = bounds(model)
    return ((xn + xx) / 2.0, (yn + yx) / 2.0, (zn + zx) / 2.0)


def radius(model: Model) -> float:
    """Worst-case distance from the origin to any vertex. Used for camera
    framing and as a broad-phase collision radius for the outdoor stub. Empty
    model -> 0.0."""
    r = 0.0
    for a, b in model['lines']:
        for p in (a, b):
            d = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
            if d > r:
                r = d
    return r


def bob_offset(model: Model, t: float) -> float:
    """The shared idle-bob Y offset: sin(t * bob_speed) * bob_amount.

    Returns 0.0 when bob_speed <= 0, matching the conditional in both
    render.py and the BZ viewer. Centralizing it means outdoor and indoor
    compute identical bob from the same model dict. Reads with defaults, so it
    is safe on a non-normalized dict.
    """
    speed = model.get('bob_speed', DEFAULT_BOB_SPEED)
    if speed <= 0:
        return 0.0
    return math.sin(t * speed) * model.get('bob_amount', DEFAULT_BOB_AMOUNT)


def face_mode(model: Model) -> str:
    """Entity facing mode, defaulting to billboard. Read at draw time by the
    indoor entity path; outdoor obstacles/tanks ignore it."""
    return model.get('face_mode', DEFAULT_FACE_MODE)


# --- Contract self-test ----------------------------------------------------

if __name__ == '__main__':
    # Smoke test + executable usage examples.  Run: python common/model.py
    good: Model = {'lines': [((0, 0, 0), (0, 2, 0)), ((0, 2, 0), (1, 2, 0))]}
    assert is_model(good)
    validate(good)  # must not raise

    n = normalize(good)
    assert n['scale'] == 1.0 and n['bob_speed'] == 0.0 and n['bob_amount'] == 0.0
    assert 'scale' not in good, 'normalize must not mutate the source dict'

    assert bounds(good) == ((0.0, 1.0), (0.0, 2.0), (0.0, 0.0))
    assert center(good) == (0.5, 1.0, 0.0)
    assert abs(radius(good) - math.sqrt(1 + 4)) < 1e-9

    bobbed: Model = {'lines': good['lines'], 'bob_speed': 2.0, 'bob_amount': 0.5}
    assert bob_offset(bobbed, math.pi / 4) != 0.0
    assert bob_offset(good, 1.0) == 0.0          # no bob_speed -> no bob

    empty: Model = {'lines': []}
    assert is_model(empty)
    assert bounds(empty) == _UNIT_BOX
    assert radius(empty) == 0.0

    assert face_mode(good) == FACE_BILLBOARD
    assert face_mode({'lines': [], 'face_mode': FACE_LOCK}) == FACE_LOCK

    # validate() is strict: every one of these must raise ModelError.
    bad_cases = [
        (42, 'not a dict'),
        ({}, 'missing lines'),
        ({'lines': 'nope'}, 'lines not a sequence'),
        ({'lines': [((0, 0), (1, 1, 1))]}, 'start not a 3-vector'),
        ({'lines': [((0, 0, 0),)]}, 'line not a pair'),
        ({'lines': [((0, 0, 0), (1, 1, 1))], 'scale': 'big'}, 'scale not numeric'),
        ({'lines': [], 'face_mode': 'sideways'}, 'unknown face_mode'),
    ]
    for bad, why in bad_cases:
        try:
            validate(bad)
        except ModelError:
            pass
        else:
            raise AssertionError(f'validate should reject ({why})')

    # is_model() is the cheap structural duck-type: lines-shape only. It passes
    # the scale-type case (never inspects scale) but rejects the structurally
    # broken ones — the deliberate is_model/validate split.
    assert not is_model(42)
    assert not is_model({})
    assert not is_model({'lines': 'nope'})
    assert not is_model({'lines': [((0, 0), (1, 1, 1))]})
    assert is_model({'lines': [((0, 0, 0), (1, 1, 1))], 'scale': 'big'})

    print('common/model.py: all contract self-tests passed.')