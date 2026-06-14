# Auto Warfare — Session Transition (the M2→M3 seam)

**What this doc is.** A handoff brief, in the same spirit as the session primers:
it records *what this session decided and shipped*, the *current state of the
build*, the *contracts now frozen*, and the *open threads* — so the next session
(or a cold reader) can pick up without re-deriving any of it. Read the
`README_AutoWarfare_Vision.md` for **why**, `README_POC_Design.md` for **how the
pieces bolt together**, and this for **where we are and what's next**. When this
doc and the POC design disagree on *how things are built*, the POC design wins;
this records what the build actually did.

---

## Where the build sits, in one line

The indoor dive is now a real **search**: procedurally distinct floors, a
navigable multi-core stairwell, a deterministically-hidden gold **plant** and an
early magenta **intel**, walk-over pickup, and a frozen exit record that reports
the dive's outcome. Everything the search *produces* is built and green. Nothing
*consumes* it yet — that consumer is Milestone 3, and it is the next build.

---

## What this session shipped (in order, with the why)

### 1. Generator variety + tower breadth ("commit A")

The lived complaint was that every skyscraper floor read identical and the tower
was "skinny." Both were real regressions from the native port of Bane's
generator. Restored and corrected, in `innerworld_engine/generate.py` and
`indoor/floor_source.py`:

- **Loop links.** The spanning chain is now followed by 1–2 redundant corridor
  links between random room pairs. Strictly additive over an already-connected
  graph, so solvability-by-construction is untouched — it just stops a floor
  reading as one linear thread.
- **Coin-flipped corridor elbow.** A local `_carve_corridor` helper restores
  Bane's randomized bend (the engine's own `carve_corridor` is a fixed
  horizontal-then-vertical corner, so every elbow looked the same).
- **Per-archetype texture.** `_Archetype` gained `min_room` / `max_room` /
  `min_grid`. The archetype table is now the one place a building's character is
  tuned: the **skyscraper** floors broad (26×26 plate, 5 floors, widest
  room-size spread), the **warehouse** is a wide sparse floor of cover, etc.
  `_envelope` clamps to the archetype's `min_grid` instead of a global 14 —
  that's the "skinny tower" fix (every building used to floor to one 14×14 plate).

Result, proven headless: the skyscraper went from five near-identical 14×14
box-mazes to five distinct 26×26 floors, still solvable and byte-deterministic.

### 2. Segmented stairwells ("commit B")

A single shared stairwell column up the whole stack made the climb a chimney.
Now stairs are **per-link shared cells**, clustered into cores:

- `FloorRuntime.stair_cell` → `up_cell` / `down_cell` (each optional; floor 0
  has no down, the roof has no up).
- `STAIR_RUN` (default **2**) groups consecutive inter-floor links into a shared
  core; `_choose_cores` disperses cores across the plate (each new core biased
  far from the ones already placed). `run >= floors` collapses back to the old
  single column.
- The matching-landing contract holds *per link by construction* — one shared
  cell per link instead of one global cell, nothing to reconcile.
- `world.py`: direction-aware arrival (`_change_floor(..., ascending=)` lands you
  on the destination's down-stair when climbing, up-stair when descending);
  `_on_up_stair` / `_on_down_stair` gate U / I by which stair you stand on;
  per-stair prompt text; two markers in `draw`.
- `renderer.py`: independent `up_world` / `down_world` single-direction glyphs
  that composite into the old both-ways hourglass on a within-run chimney point.

Result for a 5-floor, `run=2` tower: floor 2 is a **crossing** (arrive at the
down-stair, walk across the floor to find the up-stair); floors 1 and 3 are
chimney points; the roof is down-only. The climb now makes you navigate the
distinct floors commit A produced.

### 3. The outcome payload + plant/intel placement (session-8 step 4)

The Milestone-3 **producer**. New `indoor/placement.py`, new
`tests/test_outcome_payload.py`; edits to `indoor/world.py`, `indoor/renderer.py`,
`outdoor/world.py`; and contract-driven fixes to `tests/test_indoor_m20.py` and
`tests/test_spine.py`.

- **`placement.py`** — `Objective(kind, cell, collected)` plus a
  `place_objectives(floors, *, holds_plant, seed)` decorator over the *finished*
  stack. The **plant** lands once, only in a `holds_plant` building, biased
  **deep**; the **intel** lands in every dive, biased **early**. `_pick` chooses
  a walkable cell that is not a reserved landing (`up_cell` / `down_cell` /
  `start_cell` / `exit_cell`); reachability is free (one connected component per
  floor). The placement seed is a **pure-int derivation** of the building seed —
  deliberately *not* the primer's `random.Random((seed, "place"))`, whose
  tuple-with-string hashes differently under `PYTHONHASHSEED` and would reshuffle
  loot between dives.
- **`world.py`** — dive-scoped `_found` / `_hint` flags (reset in `on_enter`);
  placement runs on the generated path only (the bare-payload fallback stays
  objective-free); walk-over pickup in `_sim_tick` flips the flags and
  `add_item("plant")` on the plant; the exit now returns the **frozen M3 record**
  `{from, cleared, depth, found, hint}`; and `mark_cleared` fires **only on a
  top-reached clear** (`cleared = max_floor >= len(floors) - 1`), not on every
  exit.
- **`outdoor/world.py`** — `holds_plant: True` on the indoor enter payload. With
  one enterable building today, the skyscraper *is* the plant building, so the
  win is reachable to test.
- **Test contract update** — `test_indoor_m20` and `test_spine` each asserted the
  old "every exit clears" behavior; both now reach the top before asserting the
  clear, matching the new gate.

All 10 outcome pins plus the full headless suite are green.

### 4. Marker polish + a per-floor flag counter

- Markers became **tall flags** (pole + pennant + floor base) instead of low
  diamonds, so they're spotted across a room. Plant is **bright gold**
  `(1.0, 0.84, 0.0)`, intel **bright magenta** `(1.0, 0.2, 0.85)` — distinct from
  each other and off the cyan wall palette.
- `status_text` carries a **per-floor** flag count (`flags n/m`). This is
  deliberately per-floor, not building-wide: a building total would leak whether
  the plant is present (plant+intel = 2, intel-only = 1) and trivialize the §2
  search once there are several buildings. Per-floor only tells you whether
  you've swept the floor you're on.

### 5. The GL red-loss bug — and the reusable lesson

Markers rendered with the **red channel zeroed** (amber→green, gold→green,
magenta→blue; a white probe rendered cyan). The diagnosis took a few wrong turns
worth recording so they aren't repeated:

- It is **not** a `glColorMask` in app code (there is none), **not** a leftover
  Bane green-draw path (the vendored engine — `dungeon.py`, `bsp.py`, `level.py`
  — is pure data, zero color/GL), and a `glColorMask` reset in `paintGL` did
  **not** fix it.
- **Root cause:** the de-windowed renderers shed Bane's
  `beginNativePainting`/`endNativePainting` bracket, which used to make Qt
  save/restore GL state around raw GL. Without it, the QPainter HUD pass leaves a
  GL *enable* dirty (blend or similar), the next frame's raw GL inherits it, and
  a channel gets eaten. A colormask reset couldn't fix it because the dirty state
  wasn't the colormask.
- **Fix:** assert the full fixed-function color pipeline at the top of
  `draw_interior` — `glColorMask(GL_TRUE×4)` plus `glDisable` of `GL_BLEND`,
  `GL_LIGHTING`, `GL_TEXTURE_2D`, `GL_COLOR_LOGIC_OP`. Confirmed in the window:
  gold plant, magenta intel.

**The lesson, generalized:** the moment a renderer sheds
`beginNativePainting`/`endNativePainting`, it inherits responsibility for
asserting its own pipeline state every frame. The bug lay dormant for months
because everything indoors was low-red until the gold flag forced it — and the
M2.0 test message had even flagged it ("GL-state hygiene at the QPainter handoff
is the one live check").

---

## Frozen contracts (don't re-litigate)

- **The M3 exit record:** `{"from": id, "cleared": bool, "depth": int,
  "found": bool, "hint": bool | None}`. Facts about the dive only — no pose, no
  world coordinate (coordinate seal, POC §6).
- **The clear gate:** `cleared` is true only when the top floor was reached this
  dive; `mark_cleared` fires only then. A bail returns `cleared=False` and leaves
  the ledger untouched. **`cleared` ≠ won** — finding the plant (`found`) is a
  separate fact on the same record.
- **Per-link matching-landing:** floor *i*'s `up_cell` == floor *i+1*'s
  `down_cell`, by construction. Ascend → arrive on the down-stair; descend →
  arrive on the up-stair.
- **Placement determinism:** the same `(seed, holds_plant)` drops objectives on
  identical cells every dive (pure-int seed).
- **The entity rail:** placement → `FloorRuntime.entities` → renderer marker →
  per-tick proximity check. Static objectives ride it today; an interior gunman
  (M2.2/2.3) is the same spine with motion + AI added.

---

## Open threads / caveats

- **The M3 record is produced but not consumed.** Nothing reads
  `cleared`/`depth`/`found` yet, so collecting the plant flips `found` and adds
  inventory but does not "win," and re-entering a cleared tower still works while
  the war outside never hardens. This is expected — it's the next build.
- **The outdoor renderer has the same shed-bracket exposure.** Fine today (its
  palette is nearly all low-red), but a red/orange explosion or the low-HP damage
  tint would green out the same way. The same five-line pipeline reset at the top
  of its frame setup closes it.
- **`app.py`'s `glColorMask` line is now redundant** — the renderer-level reset
  supersedes it. Keep it (harmless) or drop it.
- **Tree drift / delivery.** The working tree has drifted from the `az.zip`
  snapshot, so whole-file replacement has been safer than patches this session
  (a `floor.py` patch once rejected and caused a crash). Re-baseline (re-upload
  the current tree) before relying on patches again.
- **§7 dials are first-pass.** `STAIR_RUN`, the archetype room-size/breadth/
  density numbers, and the plant-deep / intel-early bias weights are all sane
  defaults, untuned. They're the levers to turn once the consumer exists and the
  curve can be felt; none requires a code change to retune.
- **GL tests need PyOpenGL** to import `IndoorWorld`; the logic is validated
  headless (the tests drive `update()`, never `draw()`).

---

## What's next — the M3 consumer

This is the Milestone-3 payoff the vision was always pointing at (§3, §6, §8):
**`OutdoorWorld.on_enter` reads the returned exit record and changes the world.**
Two jobs on one record:

1. **Reinforce on return** — use `cleared` / `depth` (and `PlayerState.tier`,
   which already bumps) to escalate the battlefield roster via the spawn
   director. Thoroughness is the cost (vision §3).
2. **Register the win** — `found` is what actually wins the run (vision §1/§2);
   `cleared` is only "searched thoroughly."

Downstream of the consumer, two things earn their revision once it exists: the
**§4 hint** (boolean `hint` → a real narrowing: "not here" / "that way" / "a tall
one"), and **multiple enterable buildings** with per-run plant assignment (the
`holds_plant` flag becomes a game-level fact instead of a hardcoded `True`).

**Parked, unchanged:** interior combat / the gunman (M2.2/M2.3) — it rides the
entity rail step 4 just built. `MapFileSource` (hand-authored set-pieces behind
the existing `FloorSource` seam). Action-gated pickup and objective audio/feel.

When the consumer is the active work, it earns its own session primer — this doc
is the brief that primer is written from.

---

## Files touched this session (manifest)

**New**
- `az/indoor/placement.py` — `Objective` + `place_objectives` + biased `_pick`.
- `az/tests/test_outcome_payload.py` — 10 headless pins for the M3 producer.

**Modified**
- `az/innerworld_engine/generate.py` — loop links + coin-flipped elbow (commit A).
- `az/indoor/floor_source.py` — archetype texture/breadth dials, `_choose_cores`,
  per-link stair carve (commits A + B).
- `az/indoor/floor.py` — `up_cell` / `down_cell` (commit B).
- `az/indoor/world.py` — segmented-stair logic (B); placement, pickup, M3 exit
  record, clear gate, per-floor flag counter (step 4 + polish).
- `az/indoor/renderer.py` — independent stair markers (B); flag-shaped objective
  markers + gold/magenta colors (step 4 + polish); **full pipeline reset at the
  top of `draw_interior`** (the red-loss fix).
- `az/outdoor/world.py` — `holds_plant` on the indoor enter payload.
- `az/shell/app.py` — `glColorMask` reset before `active.draw()` (now redundant
  with the renderer reset; keep or drop).
- `az/tests/test_indoor_m20.py`, `az/tests/test_spine.py` — clear-gate assertions
  updated (bail ≠ clear).

**Green:** `test_outcome_payload`, `test_indoor_m20`, `test_spine`,
`test_director`, `test_damage_inc3`, `test_enemy_fire`.