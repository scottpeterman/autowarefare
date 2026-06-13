# Auto Warfare — Session 4 Primer (read me first)

Purpose: resume Auto Warfare in a fresh session without re-deriving the
architecture or re-discovering what Session 3 built. This is the onramp; the
code under `az/` is the spec. The project is a **self-contained tree** — the
outer engine is vendored and owned (no external `bz` dependency).

Current position: **Milestone 1 substantially done.** Increment 1 (real
vendored engine wrapped, score through `PlayerState`) and increment 2 (the
player **weapon system** — a shared `Weapon`/`Loadout` abstraction with a
ballistic shell and a heat-gated pulse rifle, cycle-switched) are both
complete and hand-validated in the live window. On top of that, Session 3 also
landed the parked **smoked-glass occlusion** pass: the outer world's buildings
and debris now carry `faces`, the render path draws fills-then-edges through a
hardware depth buffer, and a one-line dial (`OCCLUSION_MODE`, default `GLASS`)
turns the old X-ray wireframe tangle into a real cityscape with depth. The
portal seam still round-trips clean (verified live: drive in, take the indoor
hazard, exit with HP spent and the tower marked *cleared*).

Next real task is **Milestone 1, increment 3 — the damage model**: enemy HP,
the player damage pool wired to enemy fire, and the feedback that makes a hit
read. This is the increment that makes the two weapons *earn their existence*
(a one-shot shell vs. a heat-limited tracer spray are indistinguishable while
every enemy is one-hit-kill) and that makes the **pulse rifle vs. the old tank
fair** — today the pulse is brutally, pointlessly unfair against a one-HP
target. Increment 3 is the gate that unlocks the thread after it: **non-tank
vehicles** (increment 4), which are mostly data once HP + a loadout + drive
knobs are per-vehicle.

---

## Read protocol

1. Read this primer. Then skim, in order: `az/shell/player_state.py` (the
   shared pool — note it **already has** `take_damage`, `lose_life`,
   `invuln_ticks`, `damage_flash_ticks`, `heal`; increment 3 plugs into these,
   it does not invent them), `az/common/weapon.py` (the `ProjectileSpec` /
   `FireControl` / `Weapon` / `Loadout` abstraction — `ProjectileSpec` is where
   a `damage` field will live), and `az/outdoor/world.py` (the `_sim_tick`:
   where kills route to score, where the loadout fires, and the **two lines
   that deliberately disable enemy fire** today).
2. New since Session 2 and load-bearing for this increment:
   `az/outerworld_engine/battlefield.py` `step_bullets` (the hit-resolution
   path: player bullets currently *one-hit-kill* tanks via `_bullet_hits_tank`;
   enemy bullets already return `player_hit`) and `step_tanks` (it already
   passes `enemy_bullet_in_flight` to the AI so the one-enemy-bullet gate
   works); `az/outerworld_engine/tank.py` (has `ai_wants_fire` — the fire
   intent the world currently throws away — but **no HP yet**); and
   `az/outerworld_engine/tank_ai.py` only if the fire cadence needs tuning.
3. For the render look (so you don't re-derive it): `az/outerworld_engine/
   render.py` — the `OCCLUSION_MODE` dial and the `_draw_faces_pass`. **Do not
   touch occlusion this increment**; it is settled and self-contained.
4. Do **not** read `az/outerworld_engine/*` end to end — it is the vendored,
   owned engine. Open a file only when a specific symbol matters.
5. Run the tests before changing anything (see "How to run"). There are now
   **six** acceptance tests, all passing.

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

Carried forward (still true, still load-bearing):

- **Two engines, one shell.** The shell hosts one world at a time and hands the
  player between them. Only `PlayerState` crosses the seam; coordinates never
  do. *(Proven by repeated live playthroughs, not just CI.)*
- **`PlayerState` is shell-owned** (`az/shell/player_state.py`): health, lives,
  score, inventory, cleared-set, invuln/damage-flash timers. Both worlds
  read/write through it. **It already exposes the full damage API** —
  `take_damage(amount)`, `heal`, `lose_life()` (respawn at full + grace, game
  over at 0), `is_dead`, `is_invulnerable`, `hp_fraction`, plus `invuln_ticks`
  and `damage_flash_ticks` with `tick()` housekeeping. The whole point of §3
  was to have this ready before damage existed; Session 4 cashes that in.
- **The World contract** (`az/shell/mode.py`): `on_enter/on_exit`,
  `update(dt, InputState) -> Transition | None`, `draw(vp_w, vp_h)`, a
  `spatial`. `InputState` is normalized semantic intent: `forward/back/left/
  right`, `action` (edge), `fire` (held), and `cycle` (edge — weapon switch,
  added in Session 3). Worlds never import Qt.
- **Single `QOpenGLWidget`** (`az/shell/app.py`): `paintGL` draws the active
  world then a QPainter HUD pass. One QTimer at 16 ms. Keys mapped to intents
  here: drive W/S, turn A/D, fire SPACE, enter E, **cycle weapon TAB** (Q is
  quit, so cycle is Tab; rebind via `_CYCLE_KEYS`).
- **Model-dict contract** (`az/common/model.py`): the shared `{'lines'}` asset
  format, +Y-up universally, now with an **optional `faces`** key (convex
  polygons) used only by the outer render's occlusion pass. `validate` accepts
  it.
- **This is a FORK, not a port.** Engines are vendored and owned, edited freely.
- **Engine naming locked:** `outerworld_engine` / `innerworld_engine` (the
  latter still not vendored). Game layers stay `outdoor/` and `indoor/`.
- **Fixed-timestep hosting.** `OutdoorWorld.update(dt)` runs an accumulator
  that ticks the sim at its native 16 ms; engine constants stay per-tick. Do
  not rescale to seconds.
- **Drive feel is two knobs** at the top of `outdoor/world.py`:
  `PLAYER_FORWARD_SPEED` (1.6/tick) and `PLAYER_TURN_SPEED_DEG` (1.1/tick).

New, and now settled (Session 3):

- **One weapon concept, engine-neutral** (`az/common/weapon.py`). A `Weapon` =
  a `ProjectileSpec` (model, speed, range, scale, radius, spawn offset, fly
  height) + a `FireControl` + an injected `ProjectileFactory`. The factory is
  the seam that keeps `common/` free of any engine import while still firing a
  real BZ `Bullet` — a future indoor weapon injects a Bane-`Projectile`
  factory, so both worlds share ONE concept (answers POC §9). Two controls
  exist: `BallisticFireControl` (the canonical one-shell-on-screen gate,
  stateless) and `HeatFireControl` (cadence + heat budget + overheat lockout
  with re-engage hysteresis). A `Loadout` holds the weapons and the active
  index with `select`/`cycle`/`tick`; `tick()` runs every weapon's control each
  sim tick so a holstered weapon still cools.
- **The player carries shell (slot 0) + pulse rifle (slot 1).** Built in
  `outdoor/world.py` by `_shell_weapon()` and `_pulse_weapon()`; fired via
  `loadout.active.try_fire(...)`; cycled once per frame in `update()`. The HUD
  shows the active weapon name and, for heat weapons, a gauge that ambers as it
  climbs and reads `OVERHEAT` while locked.
- **Smoked-glass occlusion is the outer-world look.** Buildings and the BZ
  debris solids carry `faces`; `render.draw_battlefield` draws all faces
  (depth-writing fills) then all edges, with `glPolygonOffset` so the floor
  bands / mullions read as windows on a solid facade. `OCCLUSION_MODE` =
  `glass` (default) | `opaque` | `off`. **Self-contained to the outer world —
  the indoor/Bane path is untouched** (its coplanar BSP is where this trick is
  hard; our discrete convex solids are where it's easy). Validated live; the
  software preview tool lives at `tools/glass_preview.py`.
- **Vehicles and projectiles stay faceless (pure wireframe).** Tanks, bullets,
  and fragments are intentionally NOT given `faces`, so they read as *lighter*
  objects against the solid architecture — an emergent vehicle-vs-building
  hierarchy that is a feature, not an omission. **Keep new vehicles faceless.**

---

## What is built and working

- `shell/` — host, PlayerState (full damage API), World contract, portal. Done.
- `common/` — model contract (now with optional `faces`), motion integrator,
  SpatialQuery, **weapon abstraction** (`weapon.py`).
- `hud/` — shared HUD compositor (health bar, lives, score, targeting reticle,
  world tag, damage-edge flash, **active-weapon name + heat gauge**).
- `outerworld_engine/` — vendored BZ sim: Battlefield, Camera, Obstacle,
  Bullet, Tank (+ `ai_wants_fire`, no HP yet), tank_ai, Fragment, render (+ the
  **occlusion dial**), + model dicts (cube/tetra/platform now carry `faces`).
  Owned, edit freely.
- `outdoor/world.py` — the outer world: drivable retuned auto, the **two-weapon
  loadout** (shell + pulse, cycle), enemy autos that roam and can be killed for
  score, the smoked-glass cityscape + enterable skyscraper. **Enemy fire is
  deliberately disabled** (`t.ai_wants_fire = False` after `step_tanks`; the
  `_player_hit` return from `step_bullets` is ignored) — increment 3 turns this
  on.
- `outdoor/models/` — `buildings.py` (4 sizes + doorway, now emitting `faces`)
  and `projectiles.py` (`SHELL_MODEL` + `TRACER_MODEL`).
- `indoor/world.py` — still the scratch interior room. Proves the spine:
  first-person move, a hazard that spends HP via `state.take_damage`, an exit
  that flips a cleared flag. Unchanged.
- `tests/test_spine.py` — **6 headless acceptance tests**, all passing: drive,
  one-shell rule, kill→score(PlayerState), portal round-trip persisting
  HP/cleared/pose, weapon loadout + ballistic gate, pulse heat overheat + cycle.

---

## Next task — Milestone 1, increment 3: the damage model

The goal is one unified damage economy: **every damage source mutates one
pool** (POC §3). The player's pool is `PlayerState` (already there). Enemies get
their own HP. Weapons carry damage. The plumbing is mostly *connecting parts
that already exist*; the design is in the gated decisions below.

The shape of the work (in dependency order):

1. **Damage on the projectile.** Add a `damage: float` to `common.weapon.
   ProjectileSpec` and carry it onto the spawned round (extend the engine
   `Bullet` with a `damage` field — owned, edit freely). The shell's spec gets
   a big number, the tracer's a small one. This is the single fact that makes
   the two weapons differ once targets have HP.
2. **Enemy HP.** Give `Tank` an `hp` / `max_hp` (owned engine edit). Change
   `Battlefield._bullet_hits_tank` / `step_bullets` so a player bullet
   *subtracts its damage* instead of one-hit-killing; the tank dies (and scores
   via the existing kill→`PlayerState` path) only at `hp <= 0`. Keep the
   death→fragment burst.
3. **Player damage.** Stop ignoring the `player_hit` return from `step_bullets`;
   route it to `state.take_damage(bullet.damage)`. On `state.is_dead`, call
   `state.lose_life()` (respawn at full + invuln, game over at 0). The indoor
   hazard already uses `take_damage`, so the pool is genuinely shared the moment
   this is wired — nothing to reconcile.
4. **Enemy fire.** The AI already decides *whether* it wants to fire
   (`ai_wants_fire`) under the one-enemy-bullet gate (`step_tanks` passes
   `enemy_bullet_in_flight`). Stop forcing it to `False`; on a wanting tick,
   spawn an `owner='enemy'` bullet from the tank toward the player. Cleanest:
   give enemies a `Weapon` too (the abstraction is owner-agnostic —
   `try_fire(..., owner='enemy')` already works), so the enemy cannon is just
   another `Weapon` with its own spec/damage/cadence.
5. **Feedback.** Player damage flash already exists (`damage_flash_ticks` → HUD
   red edge). Add enemy hit feedback so chipping a high-HP target reads (a brief
   flash and/or a small fragment spit on non-lethal hits), and decide whether
   enemies show any health UI.

### Decisions that gate increment 3 (ask the user, do not guess)

- **TTK / damage numbers.** How many pulse tracers kill the basic enemy auto,
  and is the shell a one-shot or two-shot on it? This sets the ratio:
  enemy `hp` vs. shell `damage` vs. tracer `damage`. (Example to react to, not a
  default: tank hp 100, shell 100 = one-shot, tracer ~12 = ~9 hits — which would
  make the pulse a viable-but-slower option and the shell the precise finisher.)
- **Player survivability.** Confirm the model is the existing one: enemy hits
  chip the unified HP pool, hitting 0 spends a life and respawns at full with
  invuln grace, 0 lives = game over. Confirm respawn *position* — respawn in
  place, or reset to the spawn pose? And roughly how many clean hits should kill
  the player (sets enemy `damage`)?
- **Enemy fire behavior.** Cadence (slow telegraphed shots, or pressure?), and
  does enemy fire lead the player or fire straight? Does it obey the same
  one-bullet-on-screen rule (it already can) or get a small magazine?
- **Enemy health readability.** No enemy HP UI (read state from the hit flash +
  death burst — most arcade-authentic), floating pips, or a damage-tint that
  brightens/reddens as the wireframe takes hits?

---

## After increment 3 — non-tank vehicles (the thread it unlocks)

Once HP, damage, and a per-entity loadout exist, a new vehicle is mostly
**data**: a faceless wireframe model + `hp` + drive knobs + an AI + a `Loadout`.
The Weapon abstraction and the enemy-HP work are exactly what make this cheap.
This is **Milestone 1, increment 4** (further outdoor enrichment), distinct
from Milestone 2 (the real Bane interior), which remains the bigger
riskiest-assumption test and a separate thread.

Parked design questions for vehicles (do not block increment 3):

- **The roster.** What inhabits the Mad Max × Blade Runner street — light fast
  bikes/buggies (low HP, rapid weapon), armored haulers (high HP, slow, heavy
  shell), drones? Each is a point in the HP × speed × loadout space; pick 2–3
  that contrast.
- **AI reuse.** Does the existing tank FSM (`tank_ai.py`) cover a faster, more
  evasive vehicle, or does a bike want a new approach/strafe behavior? The
  fire-intent + one-bullet gate generalize; the movement profile may not.
- **Faceless, still.** Keep new vehicles pure wireframe (the architecture-vs-
  vehicle hierarchy). No `faces` on vehicles.
- **Flight / Y movement.** Everything is 2D XZ today (drive + turn about Y). If
  any vehicle flies, that is a new axis through the whole motion/collision path
  — treat it as its own decision, not a free addition.

---

## Open decisions parked for later increments (unchanged)

- **A second enterable building (§9).** `large` = "short interior" is the next
  candidate after the skyscraper's full dive; the lobby-trigger pattern
  generalizes.
- **Innerworld engine.** The interior is still the scratch room. Vendoring the
  real Castle of Bane renderer (the last riskiest-assumption test) needs its
  `wireframe_engine/bsp.py` — not yet provided. Localized behind the
  `IndoorWorld` seam.
- **Destructible warehouse (§9).** A `destructible=True` obstacle + a break
  effect — rides naturally on the increment-3 damage model once obstacles can
  take damage (an obstacle-HP variant of the tank-HP work).
- **Cross-seam economy (§9, Milestone 3).** What clearing a tower changes
  outside (disable an enemy class, open a district, grant a carried upgrade).
  The `cleared` flag is already load-bearing; this makes it *mean* something.

---

## Project structure

```
az/
├── shell/          app.py, player_state.py (full damage API), mode.py, portal.py
├── common/         model.py (+faces), motion.py, spatial.py, weapon.py
├── outerworld_engine/   vendored, owned BZ sim + models   (edit freely)
│   └── render.py        + OCCLUSION_MODE dial + faces pass
├── outdoor/
│   ├── world.py    AW game layer: feel knobs, loadout, cityscape, portal trigger
│   └── models/     buildings.py (+faces), projectiles.py (shell + tracer)
├── indoor/         world.py   (scratch interior; innerworld_engine later)
├── hud/            compositor.py   (HUD + reticle + weapon/heat gauge)
├── tests/          test_spine.py   (6 acceptance tests)
└── main.py
tools/
└── glass_preview.py     dev aid: software preview of the occlusion dial
```

---

## How to run

From the project root (the directory that contains `az/`):

```
python -m az.tests.test_spine     # headless spine acceptance (no GL/Qt needed)
python -m az.main                 # the window: drive (W/S), turn (A/D),
                                  # fire (SPACE), cycle weapon (TAB),
                                  # enter skyscraper (E), quit (Q)
```

Requires `PyQt6` and `PyOpenGL`. The tree is self-contained — no external `bz`.

---

## Tuning quick-reference (so the next session doesn't hunt)

- **Drive feel:** `PLAYER_FORWARD_SPEED`, `PLAYER_TURN_SPEED_DEG` in
  `outdoor/world.py` (per-tick; × 60 = per-second).
- **Shell round:** `BULLET_*` constants in `outdoor/world.py`; shape in
  `outdoor/models/projectiles.py` (`_R`, `_TIP_Z`, `_TAIL_Z`, `_SIDES`).
- **Pulse rifle:** `TRACER_*` constants (speed/range/radius) in
  `outdoor/world.py`; heat feel knobs in `_pulse_weapon()`
  (`cadence_ticks`, `heat_per_shot`, `cool_per_tick`, `reengage`); tracer shape
  in `projectiles.py` (`_TR_*`).
- **Occlusion look:** `OCCLUSION_MODE` in `outerworld_engine/render.py`
  (`glass`/`opaque`/`off`); tint via `GLASS_RGBA` / `OPAQUE_RGB`; offset via the
  `glPolygonOffset` call in `_draw_faces_pass`.
- **Reticle spin:** the `self._frame * 0.55` term in `hud/compositor.py`.
- **City layout:** `_city_blocks()` and `SKYSCRAPER_POS` in `outdoor/world.py`.
- **Damage (increment 3, once built):** projectile `damage` on the weapon
  specs in `outdoor/world.py`; enemy `hp`/`max_hp` on `Tank`; enemy weapon
  spec/cadence wherever the enemy `Weapon` is built.
```