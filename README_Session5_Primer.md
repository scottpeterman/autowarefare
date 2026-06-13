# Auto Warfare — Session 5 Primer (read me first)

Purpose: resume Auto Warfare in a fresh session without re-deriving the
architecture. This is the onramp; the code under `az/` is the spec. The project
is a **self-contained tree** — both engines are vendored and owned.

Current position: **Milestone 2.0 done — the architecture is proven.** Since the
Session 4 primer was written, the Castle of Bane interior engine was vendored,
de-windowed, and hosted as a shell guest; the riskiest-assumption test is
retired (see the delta below). **Session 4's planned next task — the outdoor
damage model — was never started** because the Bane integration jumped the
queue. This session returns to it, and carries straight on into the three
vehicles.

This session's work, in order: **Milestone 1, increment 3 — the damage model**
(enemy HP + player damage from enemy fire), then **increment 4 — the three
vehicles** (Sedan / Pickup / Flatbed). Damage is the gate; the vehicles are
mostly data once HP + a per-entity loadout exist.

---

## Since Session 4 — M2.0 landed (the delta)

Read this so you don't trust the stale parts of older docs. The Session 4 primer
describes the interior as "still the scratch room" and the innerworld engine as
"not yet vendored" — **both are now false.** What changed:

- **The Bane engine is vendored and owned**: `az/innerworld_engine/{bsp,dungeon,
  level}.py` (pure geometry — grid, BSP, level loading; no Qt/GL).
- **`indoor/world.py` is now the real Bane guest** (no longer the scratch room):
  loads a real grid dungeon, first-person movement with grid collision +
  slide-along, grid LOS, exit → portal. Plus a new **`indoor/renderer.py`** — the
  de-windowed wall renderer extracted from Bane's `drawBackground`.
- **The riskiest-assumption test is retired.** A second engine with its own
  coordinate convention, geometry pipeline, and (pending) combat model dropped
  into the shell by satisfying the three contracts (`World`, `SpatialQuery`, a
  projectile factory) — *no change to the shell, the portal, or the outdoor
  world.* The seam held under a real second engine, not just CI.
- **Indoor occlusion is solved — differently than feared.** The Session 4 worry
  ("the indoor/Bane path's coplanar BSP is where the glass trick is hard") did
  not materialize: Bane's walls are discrete convex quads, so occlusion fell out
  of true-depth fills + a `GL_LEQUAL` edge pass, plus a cell-aware floor grid
  that only draws on walkable cells. No polygon-offset-on-coplanar problem.
- **Indoor is -Y-up, sealed.** Bane renders -Y-up (floor `y=0`, ceiling `y<0`);
  the one reconciliation to the shell's +Y-up GL is a single `glScalef(1,-1,1)`
  in `indoor/renderer.py`, documented at its point of use. Movement, collision,
  and the manual wall cull are world-space and unaffected. Coordinates still
  never cross the portal.
- **Tests are now eleven**: `tests/test_spine.py` (6, unchanged in spirit) +
  `tests/test_indoor_m20.py` (5: dungeon loads, grid collision, slide-along,
  LOS, exit transition). **`test_d` was updated** — it no longer drains HP via
  the scratch hazard (M2.0 removed indoor combat); it now proves the round-trip
  *mechanics* (exit → cleared → pose restored → state intact). The HP-via-combat
  proof moves to M2.2.
- **There is now a top-level `README.md`** (the project's front door).

**Roadmap reframe:** Milestone 2's risk is retired. The remaining indoor thread
is **M2.2 — the combat port** (move Bane's `PlayerHealth` out of its
`CombatManager` onto the shell's `PlayerState`, wire grid-LOS enemies, stand up
the first gunman). It is **deferred this session** in favor of the outdoor work.
Note the coupling: increment 3 (this session) and M2.2 both wire a damage source
into the *same* pre-built `PlayerState` pool — doing increment 3 first settles
the damage economy that M2.2 will inherit, so this ordering de-risks the indoor
port rather than delaying it.

---

## Read protocol

1. Read this primer. Then skim, in order: `az/shell/player_state.py` (the shared
   pool — it **already has** `take_damage`, `lose_life`, `heal`, `is_dead`,
   `is_invulnerable`, `hp_fraction`, `invuln_ticks`, `damage_flash_ticks`;
   increment 3 plugs into these, it does not invent them), `az/common/weapon.py`
   (`ProjectileSpec` / `FireControl` / `Weapon` / `Loadout` — `ProjectileSpec`
   is where a `damage` field will live; `try_fire(..., owner=...)` is already
   owner-agnostic), and `az/outdoor/world.py` (the `_sim_tick`: where kills
   route to score, where the loadout fires, the **two lines that deliberately
   disable enemy fire**, and `add_tank` for the enemy roster).
2. Load-bearing for the damage work (carried from S4, still accurate — this code
   was never touched): `az/outerworld_engine/battlefield.py` `step_bullets` (the
   hit path: player bullets currently *one-hit-kill* via `_bullet_hits_tank`;
   enemy bullets already return `player_hit`) and `step_tanks` (already passes
   `enemy_bullet_in_flight` to the AI). `az/outerworld_engine/tank.py` (`Tank`
   is a dataclass with `model/x/z/heading/ai_wants_fire/ai_seed` — **no HP
   yet**). `az/outerworld_engine/tank_ai.py` only if cadence needs tuning.
3. For the vehicle models: `az/outerworld_engine/models/tank_model.py` (the
   `{'lines'}` wireframe format, +Y-up, **-Z forward**) and
   `az/outdoor/models/projectiles.py` (how a silhouette becomes line geometry).
   New vehicle models go in a new `az/outdoor/models/vehicles.py`.
4. Do **not** read `outerworld_engine/*` or `innerworld_engine/*` end to end —
   vendored, owned engines. Open a file only when a symbol matters.
5. Run all eleven tests before changing anything (see "How to run").

---

## Settled — do not re-litigate

Carried forward (still true, still load-bearing):

- **Two engines, one shell.** The shell hosts one world at a time; only
  `PlayerState` crosses the seam, coordinates never do. *Now proven by a second
  real engine (Bane), not just the outdoor world.*
- **`PlayerState` is shell-owned and already exposes the full damage API** —
  `take_damage`, `heal`, `lose_life()` (respawn at full + grace, game over at 0),
  `is_dead`, `is_invulnerable`, `hp_fraction`, `invuln_ticks`,
  `damage_flash_ticks`, `tick()`. §3 built this ahead of damage existing;
  increment 3 cashes it in.
- **The World contract** (`shell/mode.py`): `on_enter/on_exit`,
  `update(dt, InputState, state) -> Transition | None`, `draw(vp_w, vp_h)`,
  `spatial`. `InputState` is normalized intent: `forward/back/left/right`,
  `action` (edge), `fire` (held), `cycle` (edge). Worlds never import Qt.
- **Single `QOpenGLWidget`** (`shell/app.py`): `paintGL` draws the active world
  then a QPainter HUD; one QTimer at 16 ms; keys → intents here (drive W/S, turn
  A/D, fire SPACE, enter/exit E, cycle TAB, quit Q).
- **Model-dict contract** (`common/model.py`): shared `{'lines'}` format, +Y-up
  universally, optional `faces` used only by the outer occlusion pass.
- **This is a FORK, not a port.** Engines vendored and owned, edited freely.
- **Engine naming locked:** `outerworld_engine` / `innerworld_engine` (**now
  vendored**). Game layers stay `outdoor/` and `indoor/`.
- **Fixed-timestep hosting.** Each world's `update(dt)` runs an accumulator
  ticking the sim at native 16 ms; engine constants stay per-tick.
- **Drive feel is per-vehicle knobs** — today `PLAYER_FORWARD_SPEED` (1.6/tick)
  and `PLAYER_TURN_SPEED_DEG` (1.1/tick) in `outdoor/world.py`; increment 4
  makes these per-vehicle (see below).
- **One weapon concept, engine-neutral** (`common/weapon.py`): a `Weapon` =
  `ProjectileSpec` + `FireControl` + injected `ProjectileFactory`.
  `BallisticFireControl` (one-shell-on-screen gate) and `HeatFireControl`
  (cadence + heat + overheat) exist; a `Loadout` holds weapons with
  `select`/`cycle`/`tick`. `try_fire(..., owner=...)` is owner-agnostic — enemy
  weapons are the *same* abstraction.
- **Vehicles stay faceless (pure wireframe).** Tanks/bullets/fragments carry no
  `faces`, so they read as *lighter* objects against the solid architecture — an
  emergent vehicle-vs-building hierarchy. **Keep new vehicles faceless.**

New, settled this milestone (M2.0):

- **The interior is a real Bane dungeon hosted as a guest.** `indoor/world.py`
  drives `innerworld_engine`; `indoor/renderer.py` is the de-windowed renderer.
  The indoor occlusion approach (true-depth fills + `GL_LEQUAL` edge, cell-aware
  floor grid) is settled — **do not touch it this session.**
- **Indoor -Y-up is sealed** behind the single flip in `indoor/renderer.py`.

---

## Increment 3 — the damage model (the gate)

One unified damage economy: **every damage source mutates one pool** (POC §3).
The player's pool is `PlayerState` (ready). Enemies get HP. Weapons carry
damage. Mostly *connecting parts that already exist*. Shape, in dependency order:

1. **Damage on the projectile.** Add `damage: float` to
   `common.weapon.ProjectileSpec` and carry it onto the spawned round (add a
   `damage` field to the engine `Bullet` — owned edit). This is the single fact
   that differentiates the weapons once targets have HP. *Note: this field is
   what the future indoor weapon (M2.3) will also use — increment 3 is now
   load-bearing for both engines.*
2. **Enemy HP.** Give `Tank` an `hp`/`max_hp` (owned edit). Change
   `_bullet_hits_tank`/`step_bullets` so a player bullet *subtracts its damage*
   instead of one-hit-killing; death (with the existing fragment burst + kill →
   `PlayerState` score) fires only at `hp <= 0`.
3. **Player damage.** Stop ignoring the `player_hit` return from `step_bullets`;
   route it to `state.take_damage(bullet.damage)`. On `state.is_dead`, call
   `state.lose_life()`. The indoor path already uses `take_damage`, so the pool
   is genuinely shared the moment this is wired.
4. **Enemy fire.** The AI already decides *whether* to fire (`ai_wants_fire`)
   under the one-enemy-bullet gate. Stop forcing it `False`; on a wanting tick,
   spawn an `owner='enemy'` bullet via the tank's own `Weapon` (the abstraction
   is owner-agnostic — give enemies a `Loadout` exactly like the player).
5. **Feedback.** Player damage flash exists (`damage_flash_ticks` → HUD red
   edge). Add enemy-hit feedback so chipping a high-HP target reads (brief
   flash / small fragment spit on non-lethal hits).

---

## Increment 4 — the three vehicles

A vehicle is now a **data bundle**: `model` (faceless wireframe) + `hp`/`max_hp`
+ drive knobs (`forward_speed`, `turn_speed`) + a `Loadout`. **The player is a
vehicle + input; an enemy is the same vehicle + AI** (vision §6). The roster and
the player's chassis options are the *same definitions*. Increment 3 builds enemy
HP + the enemy `Loadout`; increment 4 promotes "a vehicle" to a first-class def
both sides instantiate.

The three (from the concept sheet — both player-selectable chassis and the enemy
bestiary):

| Vehicle | Loadout | Feel | Role as enemy |
|---------|---------|------|---------------|
| **Sedan** | pulse only (roof MG, `HeatFireControl`) | fast, fragile, heat-limited | the swarm/harasser — chips, dies quick |
| **Pickup** | shell only (bed cannon, `BallisticFireControl`) | slow, tough, one big hit | the bruiser — soaks shells, hits hard |
| **Flatbed** | shell + pulse (the full kit, cycle TAB) | medium, versatile | the elite — top of the curve |

Work:

- **Models** → new `az/outdoor/models/vehicles.py`: build each from its side
  silhouette as a faceless `{'lines'}` model, +Y-up, **-Z forward** (match
  `tank_model.py` so heading semantics line up). Carry a weapon **mount point /
  fire origin** per vehicle (sedan: roof; pickup: bed; flatbed: both) for bullet
  spawn placement.
- **Vehicle def.** Bundle model + hp + drive knobs + loadout-builder into one
  definition (a small dataclass or factory in `outdoor/`). The player picks one;
  the spawn roster references them.
- **Enemy roster.** Replace the two hardcoded `Tank(model=TANK_MODEL, ...)`
  autos with spawns over the three defs. Keep it a simple roster list this
  session — the data-driven **spawn director** (tier → mix) is a Milestone 3
  concern (vision §6), don't build it yet.
- **Player chassis.** First-person, so the player's own chassis isn't drawn —
  its def supplies hp + drive knobs + loadout (the per-vehicle drive knobs
  replace today's two globals).

### Decisions to confirm / tune (the archetypes answer the qualitative half)

The concept sheet already fixes the *shape* (fast/fragile, slow/tough,
full-kit). What remains is numbers — proposed below as a **starting point to
react to in the window**, not defaults chosen for you. They follow from the
archetypes; tune by feel.

- **TTK ratio.** Player pool ~100. Suggested start: shell `damage` 60, pulse
  `damage` 12/hit. Sedan hp 40 (one shell, ~4 pulse), Pickup hp 120 (two shells,
  or a long heat-limited pulse burn — making pulse the *wrong* tool for the
  bruiser, which is the point), Flatbed hp 80 (two shells, ~7 pulse).
- **Player survivability.** Confirm the model: enemy hits chip the unified pool;
  0 → `lose_life()` (respawn at full + invuln); 0 lives → game over. **Respawn
  position** — in place, or reset to spawn pose? Suggested enemy damage: shell
  ~25 (≈4 clean hits = a life), pulse ~8 (chip).
- **Enemy fire behavior.** Cadence (telegraphed vs pressure), lead the player or
  fire straight, one-bullet rule (already supported) vs small magazine per
  vehicle.
- **Enemy health readability.** No UI (read from hit-flash + death burst, most
  arcade-authentic) vs damage-tint that brightens/reddens the wireframe as it
  takes hits. (Recommend the tint — it suits the wireframe look and needs no HUD.)

### AI notes (parked — don't block the build)

- The tank FSM (`tank_ai.py`) covers slow/medium (Pickup, Flatbed body). The
  fast **Sedan** may want a more evasive approach/strafe profile — a movement
  variant, parked.
- A two-weapon **enemy Flatbed** needs weapon-*selection* AI (cannon-at-range vs
  MG-up-close) — the one genuinely new behavior. Introduce single-weapon enemies
  (Sedan, Pickup) first and save the enemy Flatbed for the top of the curve
  (vision §7).

---

## Parked for later (updated)

- **M2.2 — indoor combat port.** Bane's `PlayerHealth` → shell `PlayerState`;
  grid-LOS enemies; the first gunman. The next indoor thread, deferred this
  session. Localized behind the `IndoorWorld` seam.
- **A second enterable building (§9).** `large` = "short interior" after the
  skyscraper's full dive; the lobby-trigger pattern generalizes.
- **Destructible obstacle (§9).** Rides on the increment-3 damage model once
  obstacles can take damage (an obstacle-HP variant of the tank-HP work).
- **Cross-seam economy / spawn director (§9, Milestone 3).** Reinforcement on
  return, what clearing a tower changes outside, hint-yielding interiors. The
  `cleared` flag is already load-bearing; this is what makes it *mean* something.

---

## Project structure

```
az/
├── shell/              app.py, player_state.py (full damage API), mode.py, portal.py
├── common/             model.py (+faces), motion.py, spatial.py, weapon.py
├── hud/                compositor.py (HUD + reticle + weapon/heat gauge)
├── outerworld_engine/  vendored BZ sim + models + render (+ OCCLUSION_MODE)   (owned)
├── outdoor/
│   ├── world.py        AW outer layer: feel knobs, loadout, cityscape, enemies, portal
│   └── models/         buildings.py (+faces), projectiles.py, vehicles.py (NEW: 3 autos)
├── innerworld_engine/  vendored Castle of Bane — bsp.py, dungeon.py, level.py   (owned)
├── indoor/
│   ├── world.py        the real Bane interior guest (collision, LOS, exit)
│   └── renderer.py     de-windowed wall renderer (-Y-up flip sealed here)
├── tests/              test_spine.py (6) + test_indoor_m20.py (5)
└── main.py
README.md  ·  README_AutoWarfare_Vision.md  ·  README_POC_Design.md  ·  README_Innerworld_Design.md
```

---

## How to run

From the project root (the directory containing `az/`):

```
python -m az.tests.test_spine        # 6 spine acceptance tests (headless)
python -m az.tests.test_indoor_m20   # 5 indoor acceptance tests (headless)
python -m az.main                    # the window: drive (W/S), turn (A/D),
                                     # fire (SPACE), cycle (TAB), enter/exit (E), quit (Q)
```

Requires Python 3.11+, `PyQt6`, `PyOpenGL`. Self-contained — no external deps.
Headless tests can't verify rendering; visual changes are signed off in the window.

---

## Tuning quick-reference (so the next session doesn't hunt)

- **Drive feel (per-vehicle after increment 4):** `forward_speed` / `turn_speed`
  on each vehicle def; until then the globals `PLAYER_FORWARD_SPEED`,
  `PLAYER_TURN_SPEED_DEG` in `outdoor/world.py`.
- **Damage:** projectile `damage` on the weapon specs (`_shell_weapon` /
  `_pulse_weapon` in `outdoor/world.py`); enemy `hp`/`max_hp` on the vehicle def;
  enemy weapon spec/cadence on the enemy `Loadout`.
- **Vehicle stats:** the three defs in `outdoor/` (hp/speed/loadout); shapes in
  `outdoor/models/vehicles.py`.
- **Shell / pulse rounds:** `BULLET_*` / `TRACER_*` in `outdoor/world.py`; shapes
  in `outdoor/models/projectiles.py`; pulse heat knobs in `_pulse_weapon()`.
- **Occlusion look:** `OCCLUSION_MODE` in `outerworld_engine/render.py` (outer);
  indoor occlusion is settled in `indoor/renderer.py` — leave it.
- **City layout:** `_city_blocks()` / `SKYSCRAPER_POS` in `outdoor/world.py`.