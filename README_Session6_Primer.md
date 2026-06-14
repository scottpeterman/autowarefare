# Auto Warfare — Session 6 Primer (read me first)

Purpose: resume Auto Warfare in a fresh session without re-deriving the
architecture. This is the onramp; the code under `az/` is the spec. Read the
**vision** (`README_AutoWarfare_Vision.md`) for *why*, the **POC design**
(`README_POC_Design.md`) for *how the pieces bolt together*, and this primer for
*what to do next*. The project is a **self-contained tree** — both engines are
vendored and owned.

Current position: **Milestone 1 is complete.** Since the Session 5 primer,
increment 3 (the damage model) and increment 4 (the three vehicles + the spawn
director) both landed and are confirmed in the seat. The outdoor war now has a
real damage economy, three distinct chassis as data, enemies that fire back, and
a tier-keyed director that holds a refilling field whose mix shifts as the
player searches. **What's missing is purely visual:** all three chassis still
wear the shared `TANK_MODEL` hull.

This session's work: **the vehicle-model visual pass** — author distinct
faceless wireframes for Sedan / Pickup / Flatbed and swap them onto the defs. It
is deliberately self-contained (no logic changes), which is why it's a clean
session boundary: the dynamics are proven and signed off; the silhouettes are
the next thing the eye is asking for.

---

## Since Session 5 — increments 3 & 4 landed (the delta)

Read this so you don't trust the stale parts of older docs. The Session 5 primer
describes `Tank` as having "**no HP yet**," enemy fire as disabled by "two lines
that deliberately disable enemy fire," the spawn director as a "**Milestone 3
concern — don't build it yet**," and per-vehicle drive knobs as not-yet-done.
Several of those are now false. What changed:

- **The damage economy is live (increment 3).** `ProjectileSpec`/`Bullet` carry
  `damage`; `Tank` has `hp`/`max_hp`/`hp_fraction`; `step_bullets` chips HP and
  kills at `hp <= 0` (fragment burst + score); player damage routes to
  `PlayerState.take_damage` → `lose_life` → game over. `lose_life()` was made
  idempotent at the terminal state (it was driving lives negative on a corpse).
  Enemy fire is **on** — each armed enemy fires an `owner='enemy'` round through
  its own `Loadout`. A damage tint reddens the wireframe as a target is chipped.

- **The three vehicles are data (increment 4).** A new `az/outdoor/vehicles.py`
  defines `VehicleDef` (frozen, identity-eq) and the three singletons — Sedan
  (hp 40, fast/twitchy, pulse MG, score 1000), Pickup (hp 120, slow/heavy, shell
  cannon, 2500), Flatbed (hp 80, medium, shell + pulse, 4000). `spawn_vehicle()`
  builds the enemy embodiment (a `Tank`). **This is the player-and-enemy shared
  data of vision §6** — though today only the enemy embodiment is wired; the
  player adopting a def (the camera taking its hp/handling, the player *picking*
  a chassis) is still future.

- **Per-vehicle handling landed — for enemies.** The AI (`tank_ai.py`) now reads
  `move_speed` / `turn_speed_deg` / `engage_distance` off the `Tank` instead of
  module globals; patrol/evade speeds, evade turn, and the disengage range are
  fixed *ratios* of those, so a chassis is consistently fast or slow across all
  its states. The defaults reproduce the pre-inc4 single-tank feel exactly. **The
  player's** chassis still uses the two globals (`PLAYER_FORWARD_SPEED`,
  `PLAYER_TURN_SPEED_DEG`) because the player is a first-person camera, not a
  `Tank` — those go per-vehicle when the player-embodiment work lands.

- **The spawn director was built — early, but in its vision-correct form.** The
  S5 primer parked it for Milestone 3; the escalation-dynamics conversation
  pulled it forward, and it's worth keeping because it's the natural home for the
  tier→mix curve. `az/outdoor/director.py` is **keyed off `tier`, runs no clock,
  reads no score** (the correction that landed mid-session: *difficulty is the
  player's search behavior, not elapsed time*). It emits `population_target(tier)`
  (steps +1 every 3 tiers, **plateaus at 6** — the §7 anti-unwinnable ceiling)
  and `mix_weights(tier)` (Sedan-only early with a floor, Pickup gated at tier 2,
  Flatbed gated at tier 6 and kept rare), and **refills to target within a tier**
  on a cooldown — persistence, not escalation.

- **`PlayerState.tier` exists** — the escalation ledger (vision §6), default 0.
  `on_enter` sets it from dives cleared (a progression-derived placeholder, not a
  clock) and fills the field via the director. An `AWF_TIER` env var forces a
  tier for testing the deep curve before there are enough buildings to climb it
  naturally (vision §7's open "what counts as a tick").

- **Weapon code was extracted to its own module.** `az/outdoor/weapons.py` now
  holds the BZ bullet factory, the projectile/damage constants, and all weapon
  builders (player + enemy), so both the player loadout (`world.py`) and the
  enemy vehicle loadouts (`vehicles.py`) build from one place with no import
  cycle. Dependency direction is strictly one-way: `world → director → vehicles
  → weapons`. `world.py` re-exports `ENEMY_SHELL_DAMAGE` and `_enemy_loadout` for
  the increment-3 tests.

- **Tests are now thirty-four**: `test_spine` (6) + `test_indoor_m20` (5) +
  `test_damage_inc3` (7) + **`test_director` (16, new)** — pinning the population
  plateau, the unlock gates, the sedan floor, per-chassis spawn stats, and
  refill-to-target-never-past-it.

**Roadmap reframe:** Milestone 1 is done. The two big remaining threads are
unchanged — **M2.2 (indoor combat port)** and **Milestone 3 (the cross-seam
escalation loop)** — but Milestone 3 is now *substantially de-risked*: the
director exists and is the right shape; what remains for it is wiring, not
design. This session does neither; it does the visual pass that the proven
dynamics have earned.

---

## Read protocol

1. Read this primer. Then skim, in order: `az/outdoor/vehicles.py` (the three
   defs — the data this session reskins), `az/outerworld_engine/models/tank_model.py`
   (the `{'lines'}` wireframe format you'll mirror — **+Y-up, -Z forward**), and
   `az/outdoor/models/projectiles.py` (how a silhouette becomes line geometry).
2. Load-bearing for the swap: `az/outerworld_engine/render.py` `draw_tank` (the
   model/translate/rotate path + the damage tint — confirm a new model renders
   and tints), and `az/outerworld_engine/tank.py` (`bounding_radius` is derived
   from `model_radius_2d(model) * model['scale'] * scale` — **a new model's size
   changes the hit circle**, so size them deliberately).
3. Only if you touch behavior: `az/outdoor/director.py` (tier → mix), but the
   visual pass should not need it.
4. Do **not** read `outerworld_engine/*` or `innerworld_engine/*` end to end —
   vendored, owned engines. Open a file only when a symbol matters.
5. Run all 34 tests before changing anything (see "How to run"). The visual pass
   shouldn't move any of them; if it does, something logic-level slipped in.

The concept sheet is `vehicle_concepts.png` (uploaded) — the reference for the
three silhouettes.

---

## Settled — do not re-litigate

Carried forward (still true, still load-bearing):

- **Two engines, one shell.** Only `PlayerState` crosses the seam; coordinates
  never do. Proven by a real second engine (Bane).
- **`PlayerState` is shell-owned**, exposes the full damage API, and now also
  carries `cleared` (set) and **`tier` (int)** as the cross-seam progression
  ledger.
- **The World contract** (`shell/mode.py`): `on_enter/on_exit`, `update(dt,
  InputState, state)`, `draw`, `spatial`. Worlds never import Qt.
- **Model-dict contract** (`common/model.py`): shared `{'lines'}` format, +Y-up
  universally; `faces` used only by the outer occlusion pass.
- **Vehicles stay faceless (pure wireframe).** Tanks/bullets/fragments carry no
  `faces`, so they read as *lighter* objects against the solid architecture — an
  emergent vehicle-vs-building hierarchy. **Keep the three new vehicle models
  faceless** — no `faces`, so they never occlude or get the smoked-glass fill.
- **One weapon concept, engine-neutral** (`common/weapon.py`): `Weapon` =
  `ProjectileSpec` + `FireControl` + injected `ProjectileFactory`. `try_fire(...,
  owner=...)` is owner-agnostic — enemy weapons are the *same* abstraction.
- **This is a FORK, not a port.** Engines vendored and owned, edited freely.
- **Fixed-timestep hosting.** Each world's `update(dt)` runs an accumulator
  ticking the sim at native 16 ms; engine constants stay per-tick.
- **Indoor is settled and sealed** (M2.0): real Bane dungeon guest, -Y-up behind
  one flip in `indoor/renderer.py`. Don't touch the indoor occlusion.

New, settled this milestone (M1 complete):

- **A vehicle is `VehicleDef` = model + hp + drive knobs + loadout-factory +
  score.** `make_loadout` is a *factory* (not a shared instance) so every spawn
  owns its fire-control state. The defs are module singletons compared by
  identity.
- **Difficulty is the tier ledger, not a clock.** The director takes `tier` and
  is otherwise pure. Population steps then **plateaus**; the mix shifts and
  gates; the field **refills to target within a tier** (sustain) and only
  *escalates* when `tier` bumps (on return-from-dive). Do not reintroduce a
  time- or score-driven difficulty term — the plateau-plus-shifting-mix is the
  agreed answer to the §7 unwinnable fear.
- **Score is per-vehicle** (`Tank.score_value`, set from `VehicleDef.score`).
- **The weapon home is `outdoor/weapons.py`.** Build/tune weapons there; the
  import direction is one-way (see the delta).

---

## This session — the vehicle-model visual pass

Today all three chassis share `TANK_MODEL`; identity rides hp/handling/loadout/
score (which is everything the dynamics need). This session gives the eye what
the data already says. **Logic stays put — only the `model=` field on each def
changes.**

Work, in order:

1. **Author three faceless wireframes** → new `az/outdoor/models/vehicles.py`
   (distinct from `az/outdoor/vehicles.py`, which holds the *defs*). Each a
   `{'lines'}` model, **+Y-up, -Z forward** (match `tank_model.py` so heading
   semantics line up), **no `faces`** (keep them faceless). From the concept
   sheet:
   - **Sedan** — low, sleek, small. The smallest hull (it's the fragile swarm).
   - **Pickup** — tall, boxy, a raised bed. Reads heavy.
   - **Flatbed** — long, low, a flat rear deck. Reads as the carrier/elite.
2. **Size them deliberately.** `Tank.bounding_radius` derives from the model's
   2D extent — a bigger silhouette is a bigger hit circle. The Sedan should be
   genuinely smaller (harder to hit, suits its dodge profile); the Pickup larger.
   Sanity-check that a Sedan still takes a shell cleanly and a Pickup isn't
   trivially un-missable.
3. **Swap the defs.** Change `model=TANK_MODEL` → `model=SEDAN_MODEL` (etc.) in
   `az/outdoor/vehicles.py`. That's the whole wiring change.
4. **Confirm in the window.** New models render, the damage tint still reddens
   them, headings point the right way (the gun fires along -Z forward), and the
   three are distinguishable at battlefield distance. Headless tests can't verify
   any of this — it's signed off in the seat.

Optional, if the eye asks for it once the shapes exist:

- **Per-vehicle fire origin / mount point.** Today the bullet spawns from a
  single front offset. With distinct hulls you may want the Sedan's MG firing
  from the roof, the Pickup's shell from the bed. That's a small per-model spawn
  offset, not a logic change — but it's genuinely optional polish.

**Resist scope creep here.** The enemy-fire richness and the Milestone-3 wiring
(below) are *not* this session. The visual pass is valuable precisely because
it's bounded.

---

## Parked for later (updated)

Ordered roughly by how soon they'll want attention:

- **The enemy-fire-AI pass (vision §7).** Three things bundle here, and the
  multi-enemy field now makes them visible:
  - *One enemy round at a time, globally.* The increment-3 ballistic gate caps
    enemy bullets to one on screen across the **whole** field — safe (the war
    shoots sparsely with 6 enemies) but it undersells "the war kept coming."
    Loosening it needs **per-shooter bullet attribution** (tag each round with
    its tank, gate per-tank instead of per-owner).
  - *Rapid enemy pulse.* The Sedan's MG fires on the shared single-beat cadence,
    not a true spray, because the AI's fire *probability* is tuned for the shell.
    Per-weapon fire intent would let the heat control be the real limiter.
  - *Two-weapon selection.* The enemy Flatbed uses an **interim range-based
    select** (pulse close, shell far — `FLATBED_PULSE_RANGE` in `world.py`). The
    real choice AI is the genuinely-new behavior §7 calls out.
  The **weapon data is already correct** (Sedan=pulse, Pickup=shell, Flatbed=
  both), so this pass is pure behavior.
- **Milestone 3 — the real escalation loop.** The director is built; this is the
  wiring: bump `tier` on return-from-dive (the real ratchet, replacing the
  `len(cleared)` placeholder), **inject** a harder reinforcement at `on_enter`
  (not just refill to target), the hidden **MicroNuke Power Plant** win
  condition, and the interior **hint** that narrows the search (vision §4 — needs
  a real interior to live in). The `tier` ledger and `cleared` flag are already
  load-bearing.
- **Player as a vehicle.** Let the player adopt a `VehicleDef` (camera takes its
  hp + handling; player picks Sedan/Pickup/Flatbed). This promotes the two
  player drive-knob globals to per-vehicle and completes the "player is a vehicle
  + input" half of vision §6.
- **M2.2 — indoor combat port.** Bane's `PlayerHealth` → shell `PlayerState`
  (the pool is already shared and damage-tested); grid-LOS enemies; the first
  gunman. Localized behind the `IndoorWorld` seam.
- **A second enterable building / re-deepening interior (§7, §9).** The
  escalation loop wants more than one place to dive; `large` = "short interior"
  is the first candidate. The lobby-trigger pattern generalizes.
- **Destructible obstacle (§9).** An obstacle-HP variant of the tank-HP work,
  now that the damage model exists.

---

## Project structure

```
az/
├── shell/              app.py, player_state.py (damage API + cleared + tier), mode.py, portal.py
├── common/             model.py (+faces), motion.py, spatial.py, weapon.py
├── hud/                compositor.py (HUD + reticle + weapon/heat gauge)
├── outerworld_engine/  vendored BZ sim + models + render   (owned)
│   ├── tank.py         Tank: hp/max_hp + drive knobs (move/turn/engage) + score_value
│   └── tank_ai.py      FSM; reads handling off the Tank now (ratios for patrol/evade)
├── outdoor/
│   ├── world.py        AW outer layer: player feel knobs, loadout, cityscape, portal, _sim_tick
│   ├── weapons.py      (NEW) bullet factory + projectile/damage consts + all weapon builders
│   ├── vehicles.py     (NEW) VehicleDef + Sedan/Pickup/Flatbed defs + spawn_vehicle()
│   ├── director.py     (NEW) tier → population_target + mix_weights + refill-to-target
│   └── models/         buildings.py (+faces), projectiles.py, vehicles.py (TO BUILD: 3 hulls)
├── innerworld_engine/  vendored Castle of Bane   (owned)
├── indoor/             world.py (Bane guest), renderer.py (-Y-up sealed)
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

AWF_TIER=9 python -m az.main         # force a deep tier to see the heavier mix in the seat
```

Requires Python 3.11+, `PyQt6`, `PyOpenGL`. Self-contained — no external deps.
Headless tests can't verify rendering; visual changes are signed off in the
window. (If you hit a `ModuleNotFoundError` after pulling files by hand, the
three new `outdoor/` modules and `test_director.py` must all be present, and
clear stale bytecode: `find az -name __pycache__ -type d -prune -exec rm -rf {} +`.)

---

## Tuning quick-reference (so the next session doesn't hunt)

- **Vehicle stats:** the three defs in `outdoor/vehicles.py` — hp, `move_speed`,
  `turn_speed_deg`, `engage_distance`, loadout, score. **Models** (this session)
  go in `outdoor/models/vehicles.py` and attach via each def's `model=` field.
- **Difficulty curve:** `outdoor/director.py` — `population_target` (base/step/
  cap), `mix_weights` (sedan floor/decay, pickup & flatbed gates/ramps/caps),
  refill cadence (`SPAWN_INTERVAL_TICKS`), spawn geometry (`SPAWN_RING`). Tier is
  `PlayerState.tier` (set in `world.on_enter`; `AWF_TIER` to force).
- **Weapons / damage:** `outdoor/weapons.py` — player (`make_shell_weapon` /
  `make_pulse_weapon`) and enemy (`make_enemy_shell_weapon` /
  `make_enemy_pulse_weapon`) builders; `SHELL_DAMAGE` / `PULSE_DAMAGE` /
  `ENEMY_SHELL_DAMAGE` / `ENEMY_PULSE_DAMAGE`; pulse heat knobs in the builders.
- **Player drive feel:** `PLAYER_FORWARD_SPEED` / `PLAYER_TURN_SPEED_DEG` in
  `outdoor/world.py` (per-vehicle once the player adopts a def).
- **Enemy AI handling:** per-chassis on the def (above); the cross-state ratios
  (`PATROL_SPEED_RATIO`, `EVADE_*`, `DISENGAGE_RATIO`) and fire cadence/cone in
  `outerworld_engine/tank_ai.py`.
- **Interim Flatbed weapon select:** `FLATBED_PULSE_RANGE` in `outdoor/world.py`
  (placeholder until the §7 selection AI).
- **Occlusion look:** `OCCLUSION_MODE` in `outerworld_engine/render.py` (outer);
  indoor occlusion is settled in `indoor/renderer.py` — leave it.
- **City layout:** `_city_blocks()` / `SKYSCRAPER_POS` in `outdoor/world.py`.