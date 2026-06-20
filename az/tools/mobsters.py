"""
tools/mobsters.py — the Auto Warfare clone-mobster registry (design-time).

This is the single edit-and-reload surface for designing the three indoor
enemies *before* integration. Each mobster is two things kept side by side so
you tune the look and the feel together:

  - ``geom``  — params for ``humanoid.build_humanoid`` (the threat-triangle
    reskin: bulk, hunch, limb thickness, head, reach pose, held weapon). The
    monster viewer bakes this to a ``{'lines'}`` model dict every reload, so a
    param change here shows live on **L**.
  - ``stats`` — the draft ``EnemyDef`` in Bane's *exact* shipped schema
    (the ghost_monster.json fields). These are the numbers the melee AI will
    read at integration (sight = aggro gate against LOS, attack_range = contact,
    attack_interval = slash cadence, damage -> PlayerState, speed/turn drive the
    grid approach). Authored in the JSON's native convention — intervals in
    SECONDS, turn in DEG/SEC; the per-tick normalization happens at integration,
    not here, so what you design against stays human-readable.

Nothing in this module is imported by the runtime game. At integration the
chosen bodies get baked to static line-dicts in ``az/indoor/models/`` (numpy
stays in this tool), and ``stats`` becomes the ``EnemyDef`` table.

The "clone mobster" framing falls out of the generator: same body code, params
shifted — a bruiser, a lunging blade, a leveled gun — three silhouettes from one
loft. ``behavior`` is "melee" for the thug and knifeman (this round) and
"ranged" for the gunman (body designed now, behavior staged to M2.3, since the
interior has no projectile yet).
"""

from __future__ import annotations

# Default bake height (head top, in game model units — matches GHOST_MODEL).
TARGET_HEIGHT = 48.0


MOBSTERS: dict[str, dict] = {
    # --- the bruiser: bulky, planted, two fists, no weapon -----------------
    "thug": {
        "geom": dict(
            scale=1.0, torso_bulk=1.40, hunch=0.10, limb_r=0.065,
            head_r=0.125, head_style="face", face_deep=0.9, head_elong=1.15,
            sides=8,
        ),
        "stats": dict(
            name="thug", letter="H", behavior="melee",
            hp=3, damage=10, speed=0.45,
            sight_range=9.0, attack_range=1.5, attack_interval=1.0,
            turn_speed=140.0,
        ),
        "model": dict(scale=1.0, bob_speed=1.6, bob_amount=0.6),
    },

    # --- the knifeman: lean, fast, right arm thrust + blade ----------------
    "knifeman": {
        "geom": dict(
            scale=1.0, torso_bulk=0.90, hunch=0.06, limb_r=0.042,
            head_r=0.115, head_style="face", face_deep=0.9, head_elong=1.25,
            reach_arm="R", weapon="knife", cloak=True, sides=8,
        ),
        "stats": dict(
            name="knifeman", letter="F", behavior="melee",
            hp=1, damage=14, speed=0.75,
            sight_range=10.0, attack_range=1.3, attack_interval=0.8,
            turn_speed=200.0,
        ),
        "model": dict(scale=1.0, bob_speed=2.2, bob_amount=0.8),
    },

    # --- the gunman: upright, both arms leveled + gun (ranged, staged) -----
    "gunman": {
        "geom": dict(
            scale=1.0, torso_bulk=1.05, hunch=0.0, limb_r=0.05,
            head_r=0.12, head_style="face", face_deep=0.9, head_elong=1.20,
            grip="rifle", weapon="gun", sides=8,
        ),
        "stats": dict(
            name="gunman", letter="M", behavior="ranged",
            hp=2, damage=8, speed=0.40,
            sight_range=14.0, attack_range=9.0, attack_interval=1.5,
            turn_speed=160.0,
        ),
        "model": dict(scale=1.0, bob_speed=1.4, bob_amount=0.5),
    },
}

# Declared order the viewer pages through (1/2/3, [ / ]).
ORDER = ["thug", "knifeman", "gunman"]


def build_model(name: str, target_height: float = TARGET_HEIGHT) -> dict:
    """Bake one mobster to a model dict the viewer (and later the game) renders:
    ``{'lines': [...], 'scale', 'bob_speed', 'bob_amount'}``. Imported lazily so
    a syntax error in humanoid.py surfaces as a reload status, not an import
    crash of the registry."""
    from az.tools.humanoid import lines_from_params

    spec = MOBSTERS[name]
    model = dict(spec.get("model", {}))
    model.setdefault("scale", 1.0)
    model.setdefault("bob_speed", 0.0)
    model.setdefault("bob_amount", 0.0)
    model["lines"] = lines_from_params(spec["geom"], target_height)
    return model


if __name__ == "__main__":
    for nm in ORDER:
        s = MOBSTERS[nm]["stats"]
        mdl = build_model(nm)
        print(f"{nm:9s} {len(mdl['lines']):4d} lines   "
              f"hp={s['hp']} dmg={s['damage']} spd={s['speed']} "
              f"sight={s['sight_range']} atk_r={s['attack_range']} "
              f"({s['behavior']})")