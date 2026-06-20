"""
humanoid.py - Procedural humanoid wireframe mesh generator.

Builds a "complete" 3D body the same way clean quad-topology models are built:
cross-section rings lofted along a joint skeleton. No assets, no exotic deps.
Output is a plain (vertices, edges) wireframe ready for GL_LINES.

    verts : (N, 3) float32   model space, Y up, +Z forward (facing the camera)
    edges : list[(i, j)]     deduplicated index pairs

Same generator drives skeleton / zombie / ghost via a small params dict, so the
threat-triangle silhouettes stay distinct while sharing one code path.
"""

import math
import numpy as np


# ----------------------------------------------------------------------------
# Mesh accumulator
# ----------------------------------------------------------------------------
class Mesh:
    def __init__(self):
        self.verts = []
        self._edges = set()  # frozenset-ish: store sorted tuple to dedup

    def add_vert(self, p):
        self.verts.append((float(p[0]), float(p[1]), float(p[2])))
        return len(self.verts) - 1

    def add_edge(self, i, j):
        if i == j:
            return
        self._edges.add((i, j) if i < j else (j, i))

    def add_ring(self, pts, close=True):
        """Add a loop of points; returns their indices and wires the loop."""
        idx = [self.add_vert(p) for p in pts]
        n = len(idx)
        for k in range(n if close else n - 1):
            self.add_edge(idx[k], idx[(k + 1) % n])
        return idx

    def connect_rings(self, a, b):
        """Longitudinal edges between two equal-length index rings."""
        for ia, ib in zip(a, b):
            self.add_edge(ia, ib)

    def finalize(self):
        return (np.asarray(self.verts, dtype=np.float32), sorted(self._edges))


# ----------------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------------
def _basis(axis):
    """Return two unit vectors perpendicular to `axis` (stable)."""
    axis = axis / (np.linalg.norm(axis) + 1e-9)
    ref = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(axis, ref)) > 0.9:
        ref = np.array([0.0, 0.0, 1.0])
    u = np.cross(ref, axis)
    u /= np.linalg.norm(u) + 1e-9
    v = np.cross(axis, u)
    return u, v


def _ring_points(center, u, v, rx, ry, sides, phase=0.0):
    pts = []
    for s in range(sides):
        a = phase + 2.0 * math.pi * s / sides
        pts.append(center + rx * math.cos(a) * u + ry * math.sin(a) * v)
    return pts


def add_tube(mesh, p0, p1, r0, r1, segments=4, sides=8, squash=1.0):
    """Tapered generalized cylinder from p0 to p1. `squash` flattens one axis
    (front-to-back) so limbs read as oval rather than perfectly round."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis = p1 - p0
    u, v = _basis(axis)
    prev = None
    for s in range(segments + 1):
        t = s / segments
        c = p0 + axis * t
        r = r0 + (r1 - r0) * t
        ring = mesh.add_ring(_ring_points(c, u, v, r, r * squash, sides))
        if prev is not None:
            mesh.connect_rings(prev, ring)
        prev = ring
    return mesh


def add_lathe(mesh, profile, sides=12, phase=0.0):
    """Surface of revolution-ish trunk: profile is a list of
    (height_y, radius_x, radius_z, center_z). Rings stacked + lofted.
    center_z lets us bend the spine forward (hunch)."""
    prev = None
    for (y, rx, rz, cz) in profile:
        c = np.array([0.0, y, cz])
        u = np.array([1.0, 0.0, 0.0])
        v = np.array([0.0, 0.0, 1.0])
        ring = mesh.add_ring(_ring_points(c, u, v, rx, rz, sides, phase))
        if prev is not None:
            mesh.connect_rings(prev, ring)
        prev = ring
    return mesh


def add_sphere(mesh, center, radius, stacks=7, slices=10, squash_y=1.0):
    """UV sphere; squash_y < 1 flattens into a skull-ish ellipsoid."""
    center = np.asarray(center, float)
    rings = []
    for st in range(1, stacks):
        phi = math.pi * st / stacks
        y = math.cos(phi) * radius * squash_y
        rr = math.sin(phi) * radius
        c = center + np.array([0.0, y, 0.0])
        u = np.array([1.0, 0.0, 0.0])
        v = np.array([0.0, 0.0, 1.0])
        rings.append(mesh.add_ring(_ring_points(c, u, v, rr, rr, slices)))
    top = mesh.add_vert(center + np.array([0.0, radius * squash_y, 0.0]))
    bot = mesh.add_vert(center - np.array([0.0, radius * squash_y, 0.0]))
    for idx in rings[0]:
        mesh.add_edge(top, idx)
    for idx in rings[-1]:
        mesh.add_edge(bot, idx)
    for a, b in zip(rings, rings[1:]):
        mesh.connect_rings(a, b)
    return mesh


def _face_field(u, v, deep):
    """Forward (+Z) displacement in radius units; + out, - in. `deep`
    exaggerates sockets/brow for a more skull-like look."""
    g = lambda cu, cv, su, sv: math.exp(-(((u - cu) / su) ** 2 + ((v - cv) / sv) ** 2))
    d = 0.0
    d += 0.30 * math.exp(-(u / 0.11) ** 2) * g(0, -0.05, 1.0, 0.24)      # nose
    d += 0.10 * deep * g(0, 0.34, 0.40, 0.05)                            # brow
    d -= 0.20 * deep * (g(0.28, 0.15, 0.13, 0.10) + g(-0.28, 0.15, 0.13, 0.10))  # sockets
    d += 0.07 * (g(0.46, -0.08, 0.17, 0.16) + g(-0.46, -0.08, 0.17, 0.16))       # cheeks
    d -= 0.07 * g(0, -0.46, 0.32, 0.06)                                  # mouth
    d += 0.09 * g(0, -0.80, 0.26, 0.13)                                  # chin
    return d


def add_face_head(mesh, center, radius, stacks=11, slices=13,
                  deep=1.0, elong=1.25, triangulate=True):
    """Sphere sculpted into a low-poly face (front = +Z), then triangulated
    for the faceted mask look. `deep` > 1 deepens sockets/brow toward a skull.
    `elong` stretches the head vertically (1.0 = round, higher = longer)."""
    center = np.asarray(center, float)
    grid = [[None] * slices for _ in range(stacks + 1)]
    for i in range(stacks + 1):
        phi = math.pi * i / stacks
        for jj in range(slices):
            theta = 2 * math.pi * jj / slices
            x = math.sin(phi) * math.sin(theta)
            y = math.cos(phi) * elong                # vertical stretch
            z = math.sin(phi) * math.cos(theta)
            taper = 1.0 + 0.20 * min(0.0, y)         # narrow the jaw
            x *= taper
            z *= taper
            z += max(0.0, z) * _face_field(x, y, deep)
            p = center + radius * np.array([x, y, z])
            grid[i][jj] = mesh.add_vert(p)
    top, bot = grid[0][0], grid[stacks][0]
    for jj in range(slices):
        grid[0][jj] = top
        grid[stacks][jj] = bot
    for i in range(stacks):
        for jj in range(slices):
            a = grid[i][jj]; b = grid[i][(jj + 1) % slices]
            c = grid[i + 1][jj]; d = grid[i + 1][(jj + 1) % slices]
            mesh.add_edge(a, b); mesh.add_edge(a, c)
            if triangulate:
                mesh.add_edge(a, d)
    return mesh


def add_box(mesh, center, half, ):
    """Axis-aligned box wireframe (hands, feet)."""
    cx, cy, cz = center
    hx, hy, hz = half
    corners = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                corners.append(mesh.add_vert((cx + sx * hx, cy + sy * hy, cz + sz * hz)))
    # 12 edges of a cube by Hamming-distance-1 corner pairs
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") == 1:
                mesh.add_edge(corners[i], corners[j])
    return mesh


def _rect_ring(mesh, c, u, v, hu, hv):
    """Add a 4-corner rectangle loop in the (u, v) plane at center c."""
    pts = [c + hu * u + hv * v, c + hu * u - hv * v,
           c - hu * u - hv * v, c - hu * u + hv * v]
    return mesh.add_ring(pts)


def add_hand(mesh, elbow, wrist, s, fingers=3):
    """Tapered palm (oriented along the forearm) + finger stubs + a thumb.
    Built along the elbow->wrist axis so a reaching arm points its hand
    forward instead of dangling sideways."""
    elbow, wrist = np.asarray(elbow, float), np.asarray(wrist, float)
    axis = wrist - elbow
    axis = axis / (np.linalg.norm(axis) + 1e-9)   # palm grows past the wrist
    u, v = _basis(axis)                            # u across knuckles, v thickness

    # palm: three lofted rects, slightly bulged at the knuckles
    palm_len = 0.13 * s
    profile = [(0.00, 0.038, 0.024),
               (0.55, 0.048, 0.026),
               (1.00, 0.044, 0.020)]
    rings = []
    for t, hu, hv in profile:
        c = wrist + axis * (palm_len * t)
        rings.append(_rect_ring(mesh, c, u, v, hu * s, hv * s))
    for a, b in zip(rings, rings[1:]):
        mesh.connect_rings(a, b)

    tip = wrist + axis * palm_len
    # finger stubs fanning off the fingertip edge
    for k in range(fingers):
        off = (k - (fingers - 1) / 2.0) * 0.030 * s
        base = tip + u * off
        add_tube(mesh, base, base + axis * 0.045 * s,
                 0.010 * s, 0.007 * s, segments=2, sides=4)
    # thumb: off the side of the palm, angled out and forward
    thumb_base = wrist + axis * (palm_len * 0.35) + u * 0.045 * s
    thumb_dir = (axis * 0.6 + u * 0.8)
    thumb_dir /= np.linalg.norm(thumb_dir)
    add_tube(mesh, thumb_base, thumb_base + thumb_dir * 0.05 * s,
             0.012 * s, 0.008 * s, segments=2, sides=4)
    return mesh


def add_foot(mesh, ankle, s, toe_fwd=1.0):
    """Lofted wedge foot: flat sole on the floor, instep sloping down toward
    the toe. Cross-sections are rects in X-Y, marched forward in +Z."""
    ax = float(ankle[0])
    az = float(ankle[2])
    # (z_offset, half_width, top_height) ; sole sits at y=0
    sections = [
        (-0.05, 0.050, 0.115),   # heel
        ( 0.02, 0.055, 0.100),   # arch
        ( 0.12, 0.055, 0.055),   # ball
        ( 0.18, 0.046, 0.028),   # toe
    ]
    rings = []
    for dz, hw, top in sections:
        z = az + dz * toe_fwd * s
        hw *= s
        top *= s
        pts = [(ax - hw, 0.0, z), (ax + hw, 0.0, z),
               (ax + hw, top, z), (ax - hw, top, z)]
        rings.append(mesh.add_ring(pts))
    for a, b in zip(rings, rings[1:]):
        mesh.connect_rings(a, b)
    return mesh


# ----------------------------------------------------------------------------
# Humanoid assembly
# ----------------------------------------------------------------------------
def build_humanoid(p):
    """Build a humanoid from a params dict. Returns (verts, edges)."""
    m = Mesh()
    s = p.get("scale", 1.0)
    hunch = p.get("hunch", 0.0)          # forward lean of upper body (+Z)
    limb_r = p.get("limb_r", 0.05) * s
    sides = p.get("sides", 8)
    reach = p.get("reach_arm", None)     # which arm reaches forward: 'L','R','B',None
    grip = p.get("grip", None)           # two-handed weapon hold: 'rifle' or None

    # --- joint skeleton (Y up, +Z forward) ---
    j = {
        "pelvis":  np.array([0.00, 1.00, 0.00]),
        "chest":   np.array([0.00, 1.45, hunch]),
        "neck":    np.array([0.00, 1.55, hunch]),
        "head":    np.array([0.00, 1.72, hunch * 1.3]),
        "sh_L":    np.array([0.20, 1.50, hunch]),
        "sh_R":    np.array([-0.20, 1.50, hunch]),
        "el_L":    np.array([0.29, 1.18, hunch]),
        "el_R":    np.array([-0.29, 1.18, hunch]),
        "wr_L":    np.array([0.33, 0.92, hunch]),
        "wr_R":    np.array([-0.33, 0.92, hunch]),
        "hip_L":   np.array([0.10, 0.98, 0.00]),
        "hip_R":   np.array([-0.10, 0.98, 0.00]),
        "kn_L":    np.array([0.11, 0.54, 0.00]),
        "kn_R":    np.array([-0.11, 0.54, 0.00]),
        "an_L":    np.array([0.11, 0.08, 0.00]),
        "an_R":    np.array([-0.11, 0.08, 0.00]),
    }
    for k in j:
        j[k] = j[k] * np.array([s, s, 1.0])
        j[k][1] *= 1.0  # height already in scale-ish units

    # --- torso as a lofted trunk (silhouette control) ---
    bulk = p.get("torso_bulk", 1.0)
    waist = 0.13 * bulk * s
    chest_w = 0.20 * bulk * s
    depth = 0.62  # front-back squash for the whole trunk
    trunk = [
        (0.95 * s, waist * 1.05, waist * depth * 1.05, 0.0),
        (1.10 * s, waist,        waist * depth,        hunch * 0.3),
        (1.28 * s, chest_w * 0.92, chest_w * depth,    hunch * 0.7),
        (1.45 * s, chest_w,      chest_w * depth,      hunch),
        (1.54 * s, 0.11 * s,     0.11 * depth * s,     hunch),
    ]
    add_lathe(m, trunk, sides=max(sides, 10))

    # --- neck + head ---
    add_tube(m, j["neck"], j["head"] - np.array([0, 0.10 * s, 0]),
             0.06 * s, 0.055 * s, segments=1, sides=sides)
    head_squash = p.get("head_squash", 0.95)
    if p.get("head_style") == "face":
        add_face_head(m, j["head"], p.get("head_r", 0.12) * s,
                      deep=p.get("face_deep", 1.0),
                      elong=p.get("head_elong", 1.25))
    else:
        add_sphere(m, j["head"], p.get("head_r", 0.12) * s,
                   stacks=7, slices=max(sides, 9), squash_y=head_squash)

    # --- limbs ---
    def limb(a, b, r0, r1, seg=3):
        add_tube(m, j[a], j[b], r0, r1, segments=seg, sides=sides, squash=0.85)

    for side in ("L", "R"):
        # arms
        wr = j[f"wr_{side}"].copy()
        el = j[f"el_{side}"].copy()
        if grip == "rifle":
            # Two-handed hold: both hands come off the shoulders, bend inward,
            # and meet on the weapon centerline — staggered fore/aft so the gun
            # runs *through* both fists. R = rear/firing hand at the receiver,
            # L = front/support hand on the fore-end (further forward).
            if side == "R":
                el = np.array([-0.17 * s, 1.26 * s, 0.18])
                wr = np.array([-0.05 * s, 1.16 * s, 0.40])
            else:
                el = np.array([0.15 * s, 1.24 * s, 0.30])
                wr = np.array([0.03 * s, 1.15 * s, 0.56])
            j[f"wr_{side}"], j[f"el_{side}"] = wr, el
        elif reach == side or reach == "B":    # one (or both, "B") arm forward
            el[2] += 0.18 * s
            wr[2] += 0.42 * s
            wr[1] += 0.10 * s
            j[f"wr_{side}"], j[f"el_{side}"] = wr, el
        limb(f"sh_{side}", f"el_{side}", limb_r * 1.05, limb_r * 0.85)
        limb(f"el_{side}", f"wr_{side}", limb_r * 0.85, limb_r * 0.7)
        add_hand(m, j[f"el_{side}"], j[f"wr_{side}"], s)
        # legs
        limb(f"hip_{side}", f"kn_{side}", limb_r * 1.25, limb_r * 0.95)
        limb(f"kn_{side}", f"an_{side}", limb_r * 0.95, limb_r * 0.8)
        # foot
        add_foot(m, j[f"an_{side}"], s)

    # --- shoulder yoke (connect trunk top to shoulders) ---
    add_tube(m, j["sh_L"], j["sh_R"], 0.05 * s, 0.05 * s, segments=2, sides=6)

    # --- per-monster extras ---
    if p.get("ribcage"):
        # exposed hoops around upper torso
        for y in (1.18, 1.28, 1.38):
            c = np.array([0.0, y * s, hunch * (y - 0.95)])
            u = np.array([1.0, 0.0, 0.0]); v = np.array([0.0, 0.0, 1.0])
            r = (chest_w * 0.95)
            m.add_ring(_ring_points(c, u, v, r, r * depth, max(sides, 10)))
        # spine line
        spine = [m.add_vert((0, yy * s, hunch * (yy - 0.95)))
                 for yy in np.linspace(0.98, 1.5, 6)]
        for a, b in zip(spine, spine[1:]):
            m.add_edge(a, b)

    if p.get("robe"):
        # flaring skirt replaces lower legs: cone of expanding rings to floor
        prev = None
        for t in np.linspace(0, 1, 6):
            y = (1.0 - t) * 1.0 * s
            r = (0.16 + 0.34 * t) * s
            c = np.array([0.0, y, hunch * 0.4 * (1 - t)])
            u = np.array([1.0, 0.0, 0.0]); v = np.array([0.0, 0.0, 1.0])
            ring = m.add_ring(_ring_points(c, u, v, r, r * 0.7, max(sides, 12)))
            if prev is not None:
                m.connect_rings(prev, ring)
            prev = ring
        # vertical robe folds
        for k in range(0, max(sides, 12), 2):
            top = prev[k] if prev else None  # connected already; skip

    if p.get("hood"):
        # cowl ring arcing over and behind the head
        c = j["head"] + np.array([0.0, 0.04 * s, -0.02 * s])
        u = np.array([1.0, 0.0, 0.0]); v = np.array([0.0, 1.0, 0.6])
        m.add_ring(_ring_points(c, u, v, 0.17 * s, 0.20 * s, 12))

    if p.get("cloak"):
        # A hooded cape draped down the back (-Z): the top rows wrap up and over
        # the crown as a hood (open at the face, +Z), the lower rows fall as a
        # cape to a mid-shin hem so the legs and the forward knife arm stay read-
        # able. One continuous garment — unlike the ghost's full floor robe,
        # which would swallow the lunge. A rear angular arc only; the front is
        # left open, which is what frames the hood as a hood.
        head = j["head"]
        y_peak = float(head[1]) + 0.20 * s     # hood peak just above the crown
        y_hem = 0.42 * s                       # mid-shin hem (legs show below)
        r_hood, r_hem = 0.16 * s, 0.36 * s
        rows, cols = 7, 9
        th_max = math.radians(112)             # rear arc; the face stays open
        grid = []
        for ri in range(rows):
            t = ri / (rows - 1)
            te = t * t * (3.0 - 2.0 * t)        # smoothstep fall
            y = y_peak + (y_hem - y_peak) * te
            r = r_hood + (r_hem - r_hood) * t
            # hang from the (hunched) shoulders, billow backward through the middle
            cz = hunch * (1.0 - t) - (0.10 * s) * math.sin(t * math.pi)
            rowpts = []
            for ci in range(cols):
                a = -th_max + (2.0 * th_max) * ci / (cols - 1)
                rr = r * (1.0 + 0.05 * math.sin(ci * 1.7) * t)   # wavy cloth hem
                x = rr * math.sin(a)
                z = cz - rr * math.cos(a) * 0.9
                rowpts.append(m.add_vert((x, y, z)))
            grid.append(rowpts)
        for ri in range(rows):                  # wire the drape: |__ verticals + horizontals
            for ci in range(cols):
                if ci + 1 < cols:
                    m.add_edge(grid[ri][ci], grid[ri][ci + 1])
                if ri + 1 < rows:
                    m.add_edge(grid[ri][ci], grid[ri + 1][ci])

    # --- held weapon (Auto Warfare reskins) ------------------------------
    # A small forward-pointing prop in the hand(s), so the threat-triangle
    # silhouette carries the mobster's role at a glance: the knifeman's blade,
    # the gunman's barrel. Mounted off the (reach-adjusted) wrist joints, in the
    # same model units as the body, so to_lines() rescales it with everything.
    weapon = p.get("weapon")
    if weapon == "knife":
        # blade extending forward from the reaching fingertip (the thrust)
        wr = j[f"wr_{reach if reach in ('L', 'R') else 'R'}"]
        el = j[f"el_{reach if reach in ('L', 'R') else 'R'}"]
        axis = wr - el
        axis = axis / (np.linalg.norm(axis) + 1e-9)
        hilt = wr + axis * 0.14 * s            # just past the fist
        tip = hilt + axis * 0.34 * s           # slim blade
        add_tube(m, hilt, tip, 0.018 * s, 0.004 * s, segments=2, sides=4)
        # crossguard: a short bar across the blade base
        gu, _gv = _basis(axis)
        m.add_edge(m.add_vert(hilt + gu * 0.05 * s),
                   m.add_vert(hilt - gu * 0.05 * s))
    elif weapon == "gun":
        wrr, wl = j["wr_R"], j["wr_L"]         # rear (firing) + front (support)
        if grip == "rifle":
            # The gun runs through both fists: receiver clamped in the rear hand,
            # barrel out of the front hand to the muzzle, the two tied by a stock
            # line so it reads as one continuous weapon both hands hold.
            axis = wl - wrr
            axis = axis / (np.linalg.norm(axis) + 1e-9)   # rear -> front
            add_box(m, wrr + axis * 0.03 * s, (0.045 * s, 0.05 * s, 0.05 * s))  # receiver
            add_tube(m, wl, wl + axis * 0.26 * s,
                     0.017 * s, 0.012 * s, segments=2, sides=6)                 # barrel
            m.add_edge(m.add_vert(wrr), m.add_vert(wl))                         # stock/body
        else:
            # legacy centered mount (kept for non-grip uses)
            mid = (wl + wrr) * 0.5
            fwd = np.array([0.0, 0.0, 1.0])    # body +Z forward
            add_box(m, mid + fwd * 0.04 * s, (0.05 * s, 0.04 * s, 0.07 * s))
            add_tube(m, mid + fwd * 0.10 * s, mid + fwd * 0.30 * s,
                     0.018 * s, 0.013 * s, segments=2, sides=6)

    return m.finalize()


# ----------------------------------------------------------------------------
# Monster presets (the threat triangle)
# ----------------------------------------------------------------------------
PRESETS = {
    "skeleton": dict(scale=1.0, limb_r=0.035, torso_bulk=0.8,
                     head_r=0.115, head_style="face", face_deep=1.6,
                     head_elong=1.45, ribcage=True, sides=8),
    "zombie":   dict(scale=1.0, limb_r=0.06, torso_bulk=1.25, hunch=0.18,
                     head_r=0.125, head_style="face", face_deep=1.1,
                     head_elong=1.30, reach_arm="R", sides=8),
    "ghost":    dict(scale=1.0, limb_r=0.03, torso_bulk=0.85, head_r=0.12,
                     head_style="face", face_deep=1.5, head_elong=1.45,
                     robe=True, hood=True, sides=8),
}


def make(kind):
    return build_humanoid(PRESETS[kind])


def _rescale_to_lines(verts, edges, target_height=48.0):
    """Shared baker: (verts, edges) -> segment-pair list in game model space,
    feet at y=0 and the head top mapped to ``target_height``. +Y up, +Z forward
    (the same space this module authors in; the indoor integration flips +Z->-Z
    and rides the renderer's documented -Y flip)."""
    top = float(verts[:, 1].max()) or 1.0
    s = target_height / top
    out = []
    for i, j in edges:
        a = verts[i] * s
        b = verts[j] * s
        out.append(((float(a[0]), float(a[1]), float(a[2])),
                    (float(b[0]), float(b[1]), float(b[2]))))
    return out


def lines_from_params(params, target_height=48.0):
    """Build a humanoid straight from a params dict (not a PRESETS key) and bake
    it to the game's ``'lines'`` format. This is the path the AW mobster registry
    uses, so a tuned body in ``mobsters.py`` becomes a model dict with no preset
    indirection."""
    verts, edges = build_humanoid(params)
    return _rescale_to_lines(verts, edges, target_height)


def to_lines(kind, target_height=48.0):
    """Adapter for castleofbane: return geometry as a list of segment pairs
    ((x0,y0,z0),(x1,y1,z1)) in the game's model space.

    The game keeps feet near y=0 and +Z forward (same as this module), so we
    only rescale: feet stay at 0, the head top maps to `target_height`.
    Drop the result straight into a model dict's 'lines' field; leave
    'scale'/'bob_speed'/'bob_amount'/'face_mode' untouched.
    """
    verts, edges = make(kind)
    return _rescale_to_lines(verts, edges, target_height)


if __name__ == "__main__":
    for k in PRESETS:
        v, e = make(k)
        print(f"{k:9s}  verts={len(v):4d}  edges={len(e):4d}")