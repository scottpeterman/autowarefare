# Auto Warfare — Session 7 Primer (read me first)

Purpose: resume Auto Warfare in a fresh session without re-deriving the
architecture. This is the onramp; the code under `az/` is the spec. Read the
**vision** (`README_AutoWarfare_Vision.md`) for *why*, the **POC design**
(`README_POC_Design.md`) for *how the pieces bolt together*, and this primer for
*what to do next*. The project is a **self-contained tree** — both engines are
vendored and owned.

Current position: **Milestone 1 is complete, and the vehicle-model visual pass
(Session 6) landed and is signed off in the seat.** The outdoor war has a real
damage economy, three distinct chassis as data *and now as distinct faceless
hulls*, enemies that fire back, and a tier-keyed director that holds a refilling
field whose mix shifts as the player searches. The eye is satisfied; the next
thing the *ear* is asking for is the war to **shoot like a war**.

This session's work: **the enemy-fire-AI pass (vision §7)** — three bundled
behaviors that the now-visible multi-vehicle field exposes. It is pure behavior
(the weapon *data* is already correct), which is why it's a clean boundary: no
new chassis, no new models, no cross-seam plumbing — just making the field's
fire read as a living warzone instead of a polite one-shot-at-a-time skirmish.

---

## Since Session 6 — the visual pass landed (the delta)

Read this so you don't trust the stale "all three wear `TANK_MODEL`" lines in
the Session 6 primer. What changed:

- **The three chassis now wear distinct faceless hulls.** A new
  `az/outdoor/models/vehicles.py` defines `SEDAN_MODEL` / `PICKUP_MODEL` /
  `FLATBED_MODEL` — plain `{'lines'}` dicts, **+Y up, -Z forward, no `faces`**,
  authored at final world units (`scale 1.0`), built procedurally from a
  `_box` / `_barrel` / `_wheel` kit. The Sedan is a low three-box car with a
  roof MG; the Pickup a tall slab cab + open walled bed + cannon; the Flatbed a
  long low frame + cab + flat deck + twin guns.

- **The defs were re-skinned — that was the whole wiring change.** Each
  `VehicleDef` in `az/outdoor/vehicles.py` swapped its `model=` field
  (`TANK_MODEL` → its own hull) plus the import line. Nothing else moved: hp,
  handling, loadout, score, `spawn_vehicle` are untouched.

- **Sizes are deliberate, because the silhouette *is* the hit circle.**
  `Tank.bounding_radius` derives from the model's 2D (XZ) extent, so the hulls
  were sized to give distinct hit circles: **Sedan 16.2** (smallest — harder to
  hit, suits the darting swarm), **Pickup 23.7** (heavy via height, not
  footprint), **Flatbed 30.4** (longest — the elite earns the biggest circle).
  Confirmed in the seat: distinct at battlefield distance, the damage tint still
  reddens them, and the faceless-vs-solid hierarchy reads (light wireframe
  vehicles against smoked-glass architecture).

- **A new inspection tool: `az/tools/vehicle_viewer.py`.** The Battlezone model
  viewer re-adopted for AW — it keeps the orbit/render/HUD core but imports the
  **real game model dicts by reference** (so it never drifts from what spawns),
  and adds two AW overlays: a **-Z forward arrow** (confirm nose/barrel
  orientation) and the **2D hit circle** drawn to scale on the floor (confirm
  sizing). Hot-reload (`L`) re-imports the hull modules after an edit. Run:
  `python -m az.tools.vehicle_viewer` from the project root.

- **Tests are unchanged at thirty-four** — `test_spine` (6) + `test_indoor_m20`
  (5) + `test_damage_inc3` (7) + `test_director` (16). The visual pass moved
  none of them (it was geometry, not logic); if a test moves this session,
  something behavioral slipped in, which *is* expected this time — see below.

**Roadmap reframe:** the outdoor war is now visually complete and mechanically
proven. The two big remaining threads are still **M2.2 (indoor combat port)** and
**Milestone 3 (the cross-seam escalation loop)** — but before either, the
outdoor *combat feel* has three known-soft spots that the six-enemy field makes
audible. This session closes them so that when M3 wiring lands, the battlefield
it escalates *into* already feels alive.

---

## Read protocol

1. Read this primer. Then skim, in order: `az/common/weapon.py` (the
   `FireControl` gate — `BallisticFireControl.can_fire` is the per-owner cap
   you'll change; `PulseFireControl` is the heat/cadence gate; `Weapon` /
   `Loadout` / `try_fire(owner=...)`), `az/outerworld_engine/bullet.py` (the
   `owner` tag — where per-shooter attribution attaches), and
   `az/outdoor/world.py` `_sim_tick` enemy-fire path (the `ai_wants_fire` →
   `loadout.active.try_fire(..., owner="enemy")` loop, and the interim
   `FLATBED_PULSE_RANGE` weapon select).
2. Load-bearing for the behavior: `az/outerworld_engine/tank_ai.py` (tanks fire
   from `lookchase`; the per-tick aim probability and the `ai_wants_fire`
   intent flag) and `az/outdoor/weapons.py` (the enemy weapon builders — pulse
   vs shell cadence/heat live here).
3. Only if you touch chassis data: `az/outdoor/vehicles.py` (loadouts per def).
   The fire-AI pass should not need to edit the defs.
4. Do **not** read `outerworld_engine/*` or `innerworld_engine/*` end to end —
   vendored, owned engines. Open a file only when a symbol matters.
5. Run all 34 tests before changing anything (see "How to run"). Then add the
   new fire tests *first* (red), and make them green — the existing 34 must stay
   green throughout.

---

## Settled — do not re-litigate

Carried forward (still true, still load-bearing):

- **Two engines, one shell.** Only `PlayerState` crosses the seam; coordinates
  never do. Proven by a real second engine (Bane).
- **`PlayerState` is shell-owned**, exposes the full damage API, and carries
  `cleared` (set) and `tier` (int) as the cross-seam progression ledger.
- **The World contract** (`shell/mode.py`): `on_enter/on_exit`, `update(dt,
  InputState, state)`, `draw`, `spatial`. Worlds never import Qt.
- **Model-dict contract** (`common/model.py`): shared `{'lines'}` format, +Y-up;
  `faces` only for the outer occlusion pass. **Vehicles stay faceless** — the
  three hulls carry no `faces` and must keep it (the vehicle-vs-building read).
- **One weapon concept, engine-neutral** (`common/weapon.py`): `Weapon` =
  `ProjectileSpec` + `FireControl` + injected `ProjectileFactory`. `try_fire(...,
  owner=...)` is owner-agnostic — **enemy fire is the same abstraction**; do not
  fork a separate enemy weapon path.
- **This is a FORK, not a port.** Engines vendored and owned, edited freely.
- **Fixed-timestep hosting.** Each world's `update(dt)` ticks the sim at native
  16 ms; engine constants stay per-tick.
- **Indoor is settled and sealed** (M2.0). Don't touch the indoor occlusion.
- **A vehicle is `VehicleDef` = model + hp + drive knobs + loadout-factory +
  score**, module singletons compared by identity; `make_loadout` is a *factory*
  so every spawn owns its fire-control state.
- **Difficulty is the tier ledger, not a clock.** The director takes `tier` and
  is otherwise pure; population steps then **plateaus**; the mix shifts and
  gates; the field refills within a tier and only escalates when `tier` bumps.
  Do not reintroduce a time- or score-driven difficulty term.
- **The weapon home is `outdoor/weapons.py`**; import direction is one-way
  (`world → director → vehicles → weapons`).

New guardrails for *this* session (so the fire pass doesn't overcorrect):

- **The cap stays — it just moves from per-owner to per-shooter.** Loosening the
  ballistic gate does **not** mean removing it. Keep a small per-tank cap
  (1, maybe 2) on concurrent ballistic rounds so the field still shoots sparsely
  enough to be *fair* with six enemies. The fear §7 names is an unwinnable wall
  of bullets; the answer is per-shooter attribution **with** a per-shooter cap,
  not an ungated field.
- **Fire richness is per-weapon / per-shooter behavior, never a global term.**
  Don't express "the war shoots more" as a difficulty multiplier; express it as
  the pulse's heat being its real limiter and each shooter owning its own gate.
- **Keep enemy fire on the shared `try_fire(owner='enemy')` path.** Per-shooter
  attribution is a new *field/predicate*, not a new fire pipeline.

---

## This session — the enemy-fire-AI pass (vision §7)

Three behaviors bundle here. They're ordered because **(1) unblocks (2) and
(3)** — per-shooter attribution is the load-bearing change the other two stand
on. The weapon *data* is already correct (Sedan = pulse, Pickup = shell,
Flatbed = both), so all three are pure behavior.

Work, in order:

1. **Per-shooter bullet attribution.** Today `BallisticFireControl.can_fire`
   reads `not any(b.owner == owner for b in battlefield.bullets)` — a single
   `owner='enemy'` bucket, so the **whole field** shares one live enemy round.
   With six enemies that badly undersells "the war kept coming." Tag each round
   with its firing tank (add a `shooter` identity to `Bullet`, or maintain a
   per-tank live-round count), and gate the enemy ballistic cap **per shooter**
   instead of per owner. Keep a per-shooter cap (start at 1). Acceptance: six
   enemies can each have a round in flight simultaneously; the player's own
   one-round ballistic gate is unchanged.

2. **Rapid enemy pulse.** The Sedan's MG currently fires on the shared
   single-beat cadence because the AI's fire *probability* (in `tank_ai.py`, the
   `lookchase` aim gate) is tuned for the shell. Give fire intent a per-weapon
   sense so the pulse's **heat/`PulseFireControl`** is the real limiter — a
   Sedan should *spray*, not single-beat. Watch player fairness: six Sedans
   spraying is a lot of tracer; tune the pulse cadence/heat or the per-shooter
   cap so it reads as pressure, not a firehose. Acceptance: a pulse shooter puts
   rounds downrange faster than a shell shooter over the same window.

3. **Flatbed two-weapon selection.** Replace the interim `FLATBED_PULSE_RANGE`
   range-gate in `world.py` (`loadout.select(1 if dist <= … else 0)`) with a
   real selection behavior the §7 doc calls out: cannon at range, pulse up
   close — but with **hysteresis** so it doesn't flip-flop at the boundary (the
   same anti-oscillation lesson the evade-cone already learned). This is the one
   genuinely-new AI behavior of the three. Acceptance: the Flatbed picks pulse
   inside the band and shell outside it, and doesn't chatter at the edge.

**Tests (mirror the project's test-pinning habit).** Add a `test_enemy_fire`
suite (or extend `test_damage_inc3`) pinning: multiple staged enemies each get a
concurrent live round (the per-shooter gate); a pulse shooter emits more rounds
than a shell shooter over N ticks; the Flatbed selects pulse close / shell far
with hysteresis (no flip at the boundary). Keep the existing 34 green — note
that unlike Session 6, this session *should* add tests and may legitimately
touch `test_damage_inc3` if the enemy-fire gate assertions there tighten.

**Resist scope creep.** This is the *outdoor* combat-feel pass. Milestone 3
(escalation wiring), player-as-vehicle, and the indoor port are **not** this
session. The value is in the bounded richness of how the existing field shoots.

Optional, only if the eye/ear asks once the behavior lands:

- **Per-vehicle fire origin / mount point** (deferred from S6): the Sedan's MG
  from the roof, the Pickup's shell from the bed, the Flatbed's two guns from
  their two mounts. A small per-model spawn offset, not a logic change — but it
  pairs naturally with this pass now that the hulls have distinct gun positions.

---

## Parked for later (updated)

Ordered roughly by how soon they'll want attention:

- **Milestone 3 — the real escalation loop.** The director is built and the
  right shape; this is the wiring: bump `tier` on return-from-dive (the real
  ratchet, replacing the `len(cleared)` placeholder), **inject** a harder
  reinforcement at `on_enter` (not just refill to target), the hidden
  **MicroNuke Power Plant** win condition, and the interior **hint** that
  narrows the search (vision §4 — needs a real interior to live in). The `tier`
  ledger and `cleared` flag are already load-bearing.
- **Player as a vehicle.** Let the player adopt a `VehicleDef` (camera takes its
  hp + handling; player picks Sedan/Pickup/Flatbed). Promotes the two player
  drive-knob globals (`PLAYER_FORWARD_SPEED`, `PLAYER_TURN_SPEED_DEG`) to
  per-vehicle and completes the "player is a vehicle + input" half of vision §6.
- **M2.2 — indoor combat port.** Bane's `PlayerHealth` → shell `PlayerState`
  (the pool is already shared and damage-tested); grid-LOS enemies; the first
  gunman. Localized behind the `IndoorWorld` seam.
- **A second enterable building / re-deepening interior (§7, §9).** The
  escalation loop wants more than one place to dive; `large` = "short interior"
  is the first candidate. The lobby-trigger pattern generalizes.
- **Sedan silhouette legibility (small, optional).** Noted in the seat: the
  Sedan reads slightly *busy* at distance (cabin diagonals + wheels + MG), and
  it's the hull most often on screen in a swarm. If it crowds at battlefield
  range, thin a few cabin lines. Taste, not a bug.
- **Destructible obstacle (§9).** An obstacle-HP variant of the tank-HP work,
  now that the damage model exists.

---

## Project structure

```
az/
├── shell/              app.py, player_state.py (damage API + cleared + tier), mode.py, portal.py
├── common/             model.py (+faces), motion.py, spatial.py, weapon.py (FireControl gates)
├── hud/                compositor.py (HUD + reticle + weapon/heat gauge)
├── outerworld_engine/  vendored BZ sim + models + render   (owned)
│   ├── tank.py         Tank: hp + drive knobs + score_value + ai_wants_fire
│   ├── tank_ai.py      FSM; fires from lookchase (aim probability + cone evade)
│   └── bullet.py       Bullet: owner tag  (per-shooter attribution attaches here)
├── outdoor/
│   ├── world.py        AW outer layer: player feel, loadout, cityscape, portal, _sim_tick
│   │                   (enemy-fire loop + interim FLATBED_PULSE_RANGE select)
│   ├── weapons.py      bullet factory + projectile/damage consts + all weapon builders
│   ├── vehicles.py     VehicleDef + Sedan/Pickup/Flatbed defs + spawn_vehicle()
│   ├── director.py     tier → population_target + mix_weights + refill-to-target
│   └── models/         buildings.py (+faces), projectiles.py, vehicles.py (3 hulls)
├── innerworld_engine/  vendored Castle of Bane   (owned)
├── indoor/             world.py (Bane guest), renderer.py (-Y-up sealed)
├── tools/              vehicle_viewer.py  (orbit inspector — real dicts, hit circle, -Z arrow)
├── tests/              test_spine (6) + test_indoor_m20 (5) + test_damage_inc3 (7) + test_director (16)
└── main.py
README.md · README_AutoWarfare_Vision.md · README_POC_Design.md · README_Innerworld_Design.md
```

---

## How to run

From the project root (the directory containing `az/`):

```
export QT_QPA_PLATFORM=offscreen     # only for headless test runs
python -m az.tests.test_spine        # 6  spine acceptance tests
python -m az.tests.test_indoor_m20   # 5  indoor acceptance tests
python -m az.tests.test_damage_inc3  # 7  damage-economy tests
python -m az.tests.test_director     # 16 spawn-director tests

python -m az.main                    # the window: drive (W/S), turn (A/D),
                                     # fire (SPACE), cycle (TAB), enter/exit (E), quit (Q)

AWF_TIER=9 python -m az.main         # force a deep tier — the heavier mix
                                     # (Pickups + Flatbeds) so the fire pass is
                                     # exercised against all three chassis at once

python -m az.tools.vehicle_viewer    # orbit-inspect the hulls (1-4, H=hit circle, Z=fwd, L=reload)
```

Requires Python 3.11+, `PyQt6`, `PyOpenGL`. Self-contained — no external deps.
Headless tests can't verify rendering or fire *feel*; the spray/pressure read is
signed off in the window. (If you hit a `ModuleNotFoundError` after pulling files
by hand, clear stale bytecode:
`find az -name __pycache__ -type d -prune -exec rm -rf {} +`.)

---

## Tuning quick-reference (so the next session doesn't hunt)

- **Enemy fire gate (this session):** `common/weapon.py` —
  `BallisticFireControl.can_fire` (the per-owner cap → per-shooter); the
  per-shooter live-round cap. `outerworld_engine/bullet.py` — the `owner` tag
  (where shooter attribution attaches).
- **Enemy AI fire intent:** `outerworld_engine/tank_ai.py` — tanks fire from
  `lookchase`; the per-tick aim probability and the `ai_wants_fire` flag. The
  pulse-vs-shell cadence split lands here.
- **Flatbed weapon select:** `outdoor/world.py` — `FLATBED_PULSE_RANGE = 260.0`
  (interim range gate → real selection AI with hysteresis).
- **Weapons / heat:** `outdoor/weapons.py` — enemy builders
  (`make_enemy_shell_loadout` / pulse) and the pulse heat knobs; `SHELL_DAMAGE`
  / `PULSE_DAMAGE` / `ENEMY_SHELL_DAMAGE` / `ENEMY_PULSE_DAMAGE`.
- **Vehicle stats / loadouts:** the three defs in `outdoor/vehicles.py` — hp,
  `move_speed`, `turn_speed_deg`, `engage_distance`, `make_loadout`, score.
- **Vehicle models:** `outdoor/models/vehicles.py` — the `_box`/`_barrel`/
  `_wheel` kit; `model_radius_2d` (hit circle) follows the silhouette's 2D extent.
- **Difficulty curve:** `outdoor/director.py` — `population_target`,
  `mix_weights`, refill cadence; `tier` is `PlayerState.tier` (`AWF_TIER` forces).
- **Player drive feel:** `PLAYER_FORWARD_SPEED` / `PLAYER_TURN_SPEED_DEG` in
  `outdoor/world.py` (per-vehicle once the player adopts a def).
- **Occlusion look:** `OCCLUSION_MODE` in `outerworld_engine/render.py` (outer);
  indoor occlusion is settled in `indoor/renderer.py` — leave it.
- **City layout:** `_city_blocks()` / `SKYSCRAPER_POS` in `outdoor/world.py`.