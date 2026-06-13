# Auto Warfare — Session 3 Primer (read me first)

Purpose: resume Auto Warfare in a fresh session without re-deriving the
architecture or re-discovering what Session 2 built. This is the onramp; the
code under `az/` is the spec. The project is a **self-contained tree** — the
outer engine is vendored and owned (no external `bz` dependency).

Current position: **Milestone 1 well underway.** Increment 1 (real vendored
engine wrapped, score through `PlayerState`) is done. On top of it, Session 2
grew the outdoor world into real content and gave it identity: the **four POC
building types** stand as a cityscape with the **skyscraper as the enterable
portal source**, the **drive feel is retuned** for an armored auto, the player
fires a **wireframe shell** (not a cube), and the HUD carries a **futuristic
targeting reticle**. The portal round-trip is now **hand-validated end to end**
(a human drove in, took the interior hazard, exited, and HP persisted — not
just the headless test). Next real task is still **Milestone 1, increment 2 —
the player weapon system** (the first true fork divergence), unchanged and
un-started.

---

## Read protocol

1. Read this primer. Then skim, in order: `az/shell/mode.py` (the World
   contract + InputState/Transition), `az/shell/player_state.py` (the shared
   state), `az/outdoor/world.py` (how the real engine is wrapped + where the
   scene, the feel knobs, and the portal trigger live). Those three are the
   integration story.
2. New since v2, and worth a look because they are where content now lives:
   `az/outdoor/models/buildings.py` (the four building silhouettes + the
   parametric generator), `az/outdoor/models/projectiles.py` (the shell), and
   `az/hud/compositor.py` (the reticle + HUD).
3. Do **not** read `az/outerworld_engine/*` end to end — it is the vendored,
   owned engine. Open a file only when a specific symbol matters.
   `battlefield.py`, `camera.py`, `bullet.py`, `obstacle.py`, `tank.py` are the
   relevant ones; `render.py` is the draw path.
4. Run the tests before changing anything (see "How to run").

---

## The project in one paragraph

Auto Warfare is a first-person vehicular-combat game in a wireframe dystopia
(Mad Max × Blade Runner). You drive an armored auto through an open outer world
fighting enemy autos; the skyscraper can be entered, dropping you into a
first-person interior. A thin **shell** owns the process (GL context, one loop,
the player's persistent state) and hosts exactly one **world** at a time; a
**portal** hands the player between them. Two engines, one shell — not a
unified engine.

---

## Settled — do not re-litigate

Carried forward from v2 (still true, still load-bearing):

- **Two engines, one shell.** The shell hosts one world at a time and hands the
  player between them. Only `PlayerState` crosses the seam; coordinates never
  do. *(Now proven by a live playthrough, not just CI.)*
- **`PlayerState` is shell-owned** (`az/shell/player_state.py`): health, lives,
  score, inventory, cleared-set, invuln/damage-flash timers. Both worlds
  read/write through it. This is exactly why an indoor hazard could deduct HP
  that was still gone after returning outdoors — the §3 retrofit-killer working
  as designed.
- **The World contract** (`az/shell/mode.py`): `on_enter/on_exit`,
  `update(dt, InputState) -> Transition | None`, `draw(vp_w, vp_h)`, a
  `spatial`. Input normalized to semantic `InputState` (incl. **fire held**).
- **Single `QOpenGLWidget`** (`az/shell/app.py`): `paintGL` draws the active
  world then a QPainter HUD pass (GL first, painter second). One QTimer at 16 ms.
- **Model-dict contract** (`az/common/model.py`): the shared asset format,
  +Y-up universally.
- **This is a FORK, not a port.** Engines are vendored and owned, edited freely.
- **Engine naming locked:** `outerworld_engine` (the open drive world) and
  `innerworld_engine` (the interior, not yet vendored). Game layers stay
  `outdoor/` and `indoor/`.
- **Fixed-timestep hosting.** The outer engine is tuned in per-tick units at
  60 Hz; `OutdoorWorld.update(dt)` runs an accumulator that ticks the sim at its
  native 16 ms. Do not rescale engine constants to seconds.

New, and now settled (Session 2):

- **Drive feel is two knobs, in native per-tick units.**
  `PLAYER_FORWARD_SPEED` and `PLAYER_TURN_SPEED_DEG` at the top of
  `outdoor/world.py` are the *only* values you tune to change how the auto
  drives. Current: `1.6`/tick (96 u/sec) and `1.1`/tick (66 deg/sec) — the
  armored-auto feel, ~2.5×/~1.8× over BZ's ponderous-tank originals. Everything
  else in the file stays engine-canonical. Conversion: u/sec = value × 60.
- **Buildings are game-layer content, not engine assets.** They live in
  `outdoor/models/` (the AW side of the game-on-engine boundary), built by a
  parametric generator (box frame + floor bands + vertical mullions +
  size-specific roof) that emits plain `{'lines'}` dicts. They draw through the
  unmodified `render.draw_obstacle` and collide through the unmodified circle
  `Obstacle.bounding_radius`. No engine edit was needed and none should be.
- **Building gradient (§9) realized as: only the skyscraper is enterable.** The
  warehouse / small / large buildings are pure cover obstacles. The skyscraper
  is THE landmark (placed dead ahead of spawn) and the portal source; its gold
  **doorway** (`DOORWAY`) is the non-solid trigger mark for "E to enter". The
  trigger plumbing (`_lobby`, `_near_lobby`, `TOWER_ID`, `ENTER_RANGE`) is
  unchanged from v2, so the portal tests still hold.
- **The player fires a shell, not a cube.** `outdoor/models/projectiles.py`
  defines `SHELL_MODEL`: an octagonal-section body tapering to a nose point,
  authored along local **−Z** so it points along travel for every heading
  (verified against `Camera.forward` and `render.draw_bullet`'s `−heading`
  rotation). Fired at `scale 1.0`. Collision is still the decoupled
  `BULLET_RADIUS` circle — visual model and hit radius stay independent.
- **The reticle is a layered HUD overlay.** `Hud._draw_reticle` (QPainter):
  center cross + dot, ticked inner ring, cardinal markers, corner brackets, and
  a slowly-rotating segmented outer ring driven by `Hud._frame` (incremented
  per `draw`). Spin speed is the `self._frame * 0.55` term; HUD stays a pure
  read of `PlayerState`.

---

## What is built and working

- `shell/` — host, PlayerState, World contract, portal. Done.
- `common/` — model contract (with self-tests), motion integrator, SpatialQuery.
- `hud/` — shared HUD compositor (health bar, lives, score, **targeting
  reticle**, world tag, damage-edge flash), drawn from PlayerState.
- `outerworld_engine/` — vendored BZ sim: Battlefield, Camera, Obstacle, Bullet,
  Tank, tank_ai, Fragment, render, + model dicts. **Owned, edit freely.**
- `outdoor/world.py` — the real outer world: drivable auto (retuned feel,
  trial-revert slide + boundary clamp), shell fire (one on screen at a time),
  enemy autos that roam (AI) and can be killed for score routed through
  PlayerState, a deliberate **cityscape** + the enterable **skyscraper** with
  its lobby doorway. Enemy *fire* is intentionally not wired yet.
- `outdoor/models/` — **NEW.** `buildings.py` (warehouse / small / large /
  skyscraper + doorway + the parametric generator) and `projectiles.py` (the
  shell). Game-layer content; both dogfood `model.validate`.
- `indoor/world.py` — still the scratch interior room (placeholder for the real
  innerworld engine). Proves the spine: first-person move, a hazard that spends
  HP, an exit that flips a cleared flag. **Unchanged this session.**
- `tests/test_spine.py` — 4 headless acceptance tests, all passing after every
  Session 2 change (drive, one-shell rule, kill→score, portal round-trip).

Verified by hand this session (the live window, not just headless): drive the
retuned auto through the city, shell fire + kill→score reaching 002000, enter
the skyscraper, take the indoor hazard, exit, and watch HP stay spent outdoors.

---

## Next task — Milestone 1, increment 2: the player weapon system

Unchanged from v2 and still the first fork divergence. Build a shared `Weapon`
abstraction in `common/` (NOT per-weapon code) on top of the unmodified engine
primitives:

- A **weapon** = a projectile spec (model, speed, range, scale, radius, spawn
  offset) + a **fire-control**: ballistics use the on-screen gate (no live
  player round → can fire); rapid-fire uses a cadence gate (cooldown ticks).
- The player holds a **loadout** (`weapons: list`, `active: int`) and switches.
  The wrapper's tick calls `active.try_fire(trigger_held, camera, battlefield,
  owner)`; the weapon decides whether to emit and manages its own cooldown.
  This replaces `OutdoorWorld._fire` / `_can_fire`.
- Putting it in `common/` answers the §9 weapon question: the interior's
  staff-as-gun becomes just another `Weapon`, so both worlds share ONE concept.

Head start from Session 2: the shell is now a real, distinct model
(`SHELL_MODEL`) rather than a borrowed cube, so the "ballistic shell" weapon has
its projectile slot ready. A rapid-fire weapon wants its own smaller/faster
round — a second entry in `outdoor/models/projectiles.py`.

### Decisions that gate increment 2 (ask the user, do not guess)

- **Rapid-fire economy:** unlimited fire, finite ammo (Mad Max MG), or
  heat/overheat (Blade Runner pulse rifle)? Shapes the fire-control + HUD.
- **Cadence** (rounds/sec) and whether rapid rounds are visible tracers or
  near-hitscan.
- **Weapon switch keys:** number keys (1 = shells, 2 = rapid) or a cycle key.

---

## Open decisions parked for later increments

- **Damage model + enemy HP (increment 3).** Unified HP pool with lives as
  extra lives; enemy fire + enemy HP + player damage model land together,
  because if enemies stay one-hit-kill the two weapon categories don't earn
  their distinction. `PlayerState` already supports `take_damage` /
  `lose_life` / `invuln_ticks`. (Outdoor currently has NO damage source — the
  only way HP drops today is the indoor hazard.)
- **A second enterable building (§9).** `large` = "short interior" is the next
  candidate after the skyscraper's full dive. The trigger pattern generalizes:
  give another building a lobby marker + `Transition`. Cheap once a second
  interior layout exists.
- **Innerworld engine.** The interior is still the scratch room. Vendoring the
  real Castle of Bane renderer (the last riskiest-assumption test) needs its
  `wireframe_engine/bsp.py` (BSPTree / build_bsp_from_dungeon) — **not yet
  provided.** Swapping it in is localized behind the `IndoorWorld` seam.
- **Building polish.** The four silhouettes read well at distance and on
  approach; if a destructible-warehouse mechanic (§9) is wanted, that's a
  `destructible=True` obstacle + a break effect, not a model change.
- **Hidden-line occlusion — "smoked-glass" wireframe (chosen look; not yet
  built).** Today the constructs are fully transparent: every edge shows
  through every other building (the X-ray tangle). The fix is the textbook
  *hidden-line-via-depth-buffer* trick, which is cheap here precisely because
  the outer world is discrete separated convex solids on a ground plane (the
  opposite of Bane's coplanar-heavy BSP interior, where this is genuinely
  hard). **Target look = smoked glass** (dark translucent fills), which keeps
  the wireframe soul and a hint of see-through while restoring real depth.
  Spec for next session:
  1. **Faces on the generator.** `outdoor/models/buildings.py` already knows
     the geometry it draws as lines — emit the quads alongside. Body = 6 quads;
     each roof type adds a few (gable = 2 slopes + 2 end tris; penthouse /
     setback / spire-crown = box quads; spire tip = 4 tris). Shipped models then
     carry both `lines` and `faces`. Do the same for the BZ debris solids
     (tetra/cube/platform — already solids in BZ data) so everything occludes
     uniformly. Keep `model.validate` happy (extend it to accept an optional
     `faces` key).
  2. **Render-path pass** in `outerworld_engine/render.py` (owned, edit freely):
     per construct, draw faces first, then edges. Enable `GL_DEPTH_TEST` in the
     GL init (`shell/app.py`) and use `glPolygonOffset` so an edge sits just in
     front of its own face (no z-fight). The existing floor-band / mullion lines
     sit ON the faces, so with the offset they read as windows on a now
     solid-feeling facade — that's why the preview looks like a real building.
  3. **One dial constant** to slide the look: OFF (current X-ray) / OPAQUE
     (black fills — max readability, "arcade BZ") / GLASS (dark translucent
     fills, alpha ~0.45 over a near-black navy, drawn back-to-front so
     overlapping glass deepens). GLASS is the pick.
  Self-contained to the outer world; does **not** touch the innerworld/Bane
  path. Validated by software preview on the real cityscape (painter's + a
  software z-buffer); the in-engine version is exact and faster via the hardware
  depth buffer. Clean, Milestone-worthy, no new dependencies.

---

## Project structure

```
az/
├── shell/          app.py, player_state.py, mode.py, portal.py
├── common/         model.py, motion.py, spatial.py   (weapon.py lands in inc 2)
├── outerworld_engine/   vendored, owned BZ sim + models   (edit freely)
├── outdoor/
│   ├── world.py    AW game layer: scene, feel knobs, cityscape, portal trigger
│   └── models/     NEW — buildings.py (4 sizes + doorway), projectiles.py (shell)
├── indoor/         world.py   (scratch interior; innerworld_engine later)
├── hud/            compositor.py   (HUD + targeting reticle)
├── tests/          test_spine.py
└── main.py
```

---

## How to run

From the project root (the directory that contains `az/`):

```
python -m az.tests.test_spine     # headless spine acceptance (no GL/Qt needed)
python -m az.main                 # the window: drive (W/S), turn (A/D),
                                  # fire (SPACE), enter skyscraper (E), quit (Q)
```

Requires `PyQt6` and `PyOpenGL` in the venv. The tree is self-contained — no
external `bz` import.

---

## Tuning quick-reference (so the next session doesn't hunt)

- **Drive feel:** `PLAYER_FORWARD_SPEED`, `PLAYER_TURN_SPEED_DEG` in
  `outdoor/world.py` (per-tick units; × 60 = per-second).
- **Shell size/shape:** `_R`, `_TIP_Z`, `_TAIL_Z`, `_SIDES` in
  `outdoor/models/projectiles.py`, or just `SHELL_SCALE`. (If the shell ever
  looks like it points backward, flip the sign on `_TIP_Z`/`_TAIL_Z` — but the
  math says nose-at-−Z is correct.)
- **Reticle spin:** the `self._frame * 0.55` term in `Hud._draw_reticle`
  (`hud/compositor.py`); `0` = static.
- **City layout:** `_city_blocks()` and `SKYSCRAPER_POS` in `outdoor/world.py`.
```