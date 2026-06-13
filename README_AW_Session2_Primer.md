# Auto Warfare — Session 2 Primer (read me first)

Purpose: resume Auto Warfare in a fresh session without re-deriving the
architecture. This is the onramp; the code under `az/` is the spec. The
project is now a **self-contained tree** — there is no external `bz`
dependency anymore (the engine is vendored, see below).

Current position: **Milestone 1, increment 1 complete and tested.** The shell
hosts the real (vendored) Battlezone outer-world engine; the player drives,
fires, and can kill enemy autos for score; the portal round-trips into a
scratch interior and back, persisting state. Next task is **Milestone 1,
increment 2 — the player weapon system** (first real fork divergence).

---

## Read protocol

1. Read this primer. Then skim, in order: `az/shell/mode.py` (the World
   contract + InputState/Transition), `az/shell/player_state.py` (the shared
   state), `az/outdoor/world.py` (how the real engine is wrapped). Those four
   files are the whole integration story.
2. Do **not** read `az/outerworld_engine/*` end to end — it is the vendored,
   owned engine (forked from Battlezone). Open a file only when a specific
   symbol matters. `battlefield.py`, `camera.py`, `bullet.py`, `obstacle.py`,
   `tank.py` are the relevant ones; `render.py` is the draw path.
3. Run the tests before changing anything (see "How to run").

---

## The project in one paragraph

Auto Warfare is a first-person vehicular-combat game in a wireframe dystopia
(Mad Max × Blade Runner). You drive an armored auto through an open outer
world fighting enemy autos; certain buildings can be entered, dropping you
into a first-person interior. A thin **shell** owns the process (GL context,
one loop, the player's persistent state) and hosts exactly one **world** at a
time; a **portal** hands the player between them. Two engines, one shell — not
a unified engine.

---

## Settled — do not re-litigate

- **Two engines, one shell.** The shell hosts one world at a time and hands
  the player between them. Only `PlayerState` crosses the seam; coordinates
  never do.
- **`PlayerState` is shell-owned and built first** (`az/shell/player_state.py`):
  health, max_health, lives, score, inventory, upgrades, cleared-set,
  invuln/damage-flash timers. Both worlds read/write through it. This is why a
  shell hit and a knife slash can deduct from one pool with no retrofit.
- **The World contract** (`az/shell/mode.py`): `on_enter/on_exit`,
  `update(dt, InputState) -> Transition | None`, `draw(vp_w, vp_h)`, and a
  `spatial` (SpatialQuery). Input is normalized to semantic `InputState`
  (forward/back/left/right held; action edge; **fire held**) so worlds never
  import Qt.
- **The shell is a single `QOpenGLWidget`** (`az/shell/app.py`): `paintGL`
  draws the active world then a QPainter HUD pass (GL first, painter second —
  the order validated by the model viewers). One QTimer at 16 ms.
- **The model-dict contract** (`az/common/model.py`) is the shared asset
  format; models are +Y-up universally (the -Y-up convention is interior wall
  geometry only, encapsulated in the interior engine).
- **This is a FORK, not a port.** Auto Warfare will do things Battlezone never
  did. The engines are *vendored and owned* (`az/outerworld_engine/`, and later
  `az/innerworld_engine/`), edited freely in this repo — not treated as frozen
  upstreams.
- **Engine naming is locked:** `outerworld_engine` (the open drive world, ex-BZ)
  and `innerworld_engine` (the interior, ex-Castle of Bane, not yet vendored).
  The **game layers** stay `outdoor/` and `indoor/` on purpose — the slight
  name difference marks the game-on-engine boundary.
- **Fixed-timestep hosting.** The outer engine is tuned in per-tick units at
  60 Hz; `OutdoorWorld.update(dt)` runs an accumulator that ticks the sim at
  its native 16 ms, so every original constant is preserved verbatim. Do not
  rescale engine constants to seconds.

---

## What is built and working

- `shell/` — host, PlayerState, World contract, portal. Done.
- `common/` — model contract (with self-tests), motion integrator, SpatialQuery.
- `hud/` — shared HUD compositor (health bar, lives, score, reticle, world tag,
  damage-edge flash), drawn from PlayerState.
- `outerworld_engine/` — vendored BZ sim: Battlefield, Camera, Obstacle, Bullet,
  Tank, tank_ai, Fragment, render, plus model dicts. **Owned, edit freely.**
- `outdoor/world.py` — the real outer world: drivable auto (trial-revert slide +
  boundary clamp), player fire (one shell at a time), enemy autos that roam
  (AI) and can be killed for score routed through PlayerState. Enemy *fire* is
  intentionally not wired yet (see Open decisions).
- `indoor/world.py` — a scratch interior room (placeholder for the real
  innerworld engine). Proves the spine: first-person move, a hazard that spends
  HP, an exit that flips a cleared flag.
- `tests/test_spine.py` — 4 headless acceptance tests, all passing.

Verified headless + offscreen: drive, fire, kill→score(PlayerState), portal
round-trip persisting HP/cleared/pose. GL rendering itself is confirmed by the
running window (M0 screenshots; M1 outer world renders via the real render.py).

---

## Next task — Milestone 1, increment 2: the player weapon system

The first fork divergence. Build a shared `Weapon` abstraction in `common/`
(NOT per-weapon code) on top of the unmodified engine primitives:

- A **weapon** = a projectile spec (model, speed, range, scale, radius, spawn
  offset) + a **fire-control**: ballistics use the on-screen gate (no live
  player round → can fire); rapid-fire uses a cadence gate (cooldown ticks).
- The player holds a **loadout** (`weapons: list`, `active: int`) and switches.
  The wrapper's tick calls `active.try_fire(trigger_held, camera, battlefield,
  owner)`; the weapon decides whether to emit and manages its own cooldown.
  This replaces `OutdoorWorld._fire` / `_can_fire`.
- Putting it in `common/` answers the §9 weapon question: the interior's
  staff-as-gun becomes just another `Weapon`, so both worlds share ONE weapon
  concept.

Why the engine does not need forking for this: `Bullet` is pure per-instance
projectile data, and `Battlefield.step_bullets` already handles an arbitrary
number of heterogeneous, ownership-aware bullets. The one-shell rule lived in
the wrapper, not the engine. So a rapid-fire stream is additive.

### Decisions that gate increment 2 (ask the user, do not guess)

- **Rapid-fire economy:** unlimited fire, finite ammo (Mad Max MG), or
  heat/overheat (Blade Runner pulse rifle)? Shapes the fire-control + HUD.
- **Cadence** (rounds/sec) and whether rapid rounds are visible tracers or
  near-hitscan.
- **Weapon switch keys:** number keys (1 = shells, 2 = rapid) or a cycle key.

---

## Open decisions parked for later increments

- **Damage model + enemy HP (increment 3).** Battlezone is lives-only (one hit
  = lose a life, death pause, respawn with invuln); Castle of Bane is HP-based.
  The fork wants a unified HP pool (design §3: a shell and a knife deduct from
  one pool), with lives as extra lives. This is the *same* question as enemy
  HP: if enemies keep one-hit-kill, the two weapon categories don't earn their
  distinction (shell = burst on a light drone; rapid = sustained on an
  HP-soaking war-rig). So enemy fire + enemy HP + player damage model land
  together in increment 3. `PlayerState` already supports `take_damage` /
  `lose_life` / `invuln_ticks`.
- **Buildings (§9).** The tower is a placeholder box. Real building models
  (warehouse / small / large / skyscraper) and which are enterable is a design
  pass.
- **Innerworld engine.** The interior is still the scratch room. Vendoring the
  real Castle of Bane renderer (the riskiest-assumption test) needs its
  `wireframe_engine/bsp.py` (BSPTree / build_bsp_from_dungeon) — not yet
  provided. Swapping it in is localized behind the `IndoorWorld` seam.

---

## Project structure

```
az/
├── shell/          app.py, player_state.py, mode.py, portal.py
├── common/         model.py, motion.py, spatial.py   (weapon.py lands in inc 2)
├── outerworld_engine/   vendored, owned BZ sim + models   (edit freely)
├── outdoor/        world.py   (AW game layer on outerworld_engine)
├── indoor/         world.py   (scratch interior; innerworld_engine later)
├── hud/            compositor.py
├── tests/          test_spine.py
└── main.py
```

---

## How to run

From the project root (the directory that contains `az/`):

```
python -m az.tests.test_spine     # headless spine acceptance (no GL/Qt needed)
python -m az.main                 # the window: drive (W/S), turn (A/D),
                                  # fire (SPACE), enter tower (E), quit (Q)
```

Requires `PyQt6` and `PyOpenGL` in the venv. The tree is self-contained — no
external `bz` import.
