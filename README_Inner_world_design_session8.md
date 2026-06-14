# Auto Warfare — Innerworld Interior Plan (Session 8 deep dive)

Status: **design pass, not yet built.** This is the interior-structure brief the
vision (§4, §7) and the POC (§9) deferred — "the interior is still the scratch
room; there's no real interior to design a hint *into* yet." It is also the
**upstream half** of the Milestone 3 Ratchet Plan: that plan froze the
outcome-payload seam and built the *consumer* (the ratchet that turns interior
results into battlefield escalation); this plan builds the *producer* — the
interior gameplay that fills `cleared` / `depth` / `found` / `hint`. The two
tracks meet at the payload, and that payload is the only thing this doc and the
ratchet plan share.

Scope is deliberately the **interior's structure** — how a building becomes a
walkable space, how floors stack, how different building shapes/sizes yield
different dives — not interior *combat* (that's the M2.2 health-pool port + the
first gunman, a parallel thread). Structure first, because depth and reach are
what the payload reports, and you can't author combat against floors that don't
exist yet.

Two original Castle of Bane assets are now in hand and folded into this pass:
the **dungeon generator** (`dungeon_generator.py`, the `ProceduralSource` port
target) and the **GL3D host** (`bsp_dungeon_gl3d.py`, whose `_apply_level` /
stairs-teleport path settles the floor transition). The floor transition is
decided: **Option A, the hard-cut swap** (low-friction, a near-verbatim port),
with real walkable stairs deferred as a skyscraper showpiece.

---

## What already exists (so we build the delta, not the foundation)

Grounded in the current tree:

- **The engine is more capable than the wiring uses.** `innerworld_engine` ships
  three things, and the interior currently leans on only the first:
  - `dungeon.py` — `DungeonMap` (grid of `CellType`, auto-generated `Wall`
    geometry at floor/solid boundaries, `carve_room` / `carve_corridor`
    generative primitives, `grid_to_world` / `world_to_grid`). **Used.**
  - `bsp.py` — `build_bsp_from_dungeon` → correct draw order, no runtime sort.
    **Used.**
  - `level.py` — an ASCII `.map` loader that *already* parses `STAIRS_UP` /
    `STAIRS_DOWN` cells, `next:` / `prev:` floor chaining, and on-grid
    **entities** (keys, enemies, treasure, doors). **Completely unused** —
    `IndoorWorld` never calls `load_level`, and no `.map` files exist on disk.
    The multi-floor and entity primitives are already sitting in the engine.

- **The wiring is scratch, by M2.0 design.** `IndoorWorld.on_enter` reads
  `payload["building"]` (a string id) and then ignores it: it always builds the
  one hardcoded `create_test_dungeon()` (a single 20×20 grid), with
  `START_CELL` / `EXIT_CELL` hardcoded. One floor. No entities consumed. No
  notion of building shape or size. This is the placeholder the vision calls
  "still the scratch room."

- **The renderer and spatial query are already floor-swappable for free.**
  `renderer.draw_interior(dungeon=…, bsp_tree=…, …)` is documented and verified
  as *stateless drawing only* — it takes the `(dungeon, bsp_tree)` pair as
  arguments. `IndoorWorld` holds that pair as `self.dungeon` / `self.bsp_tree`.
  `BSPTree` carries no global state. **So changing the active floor is just
  swapping that pair and repositioning the camera — no renderer change, no
  engine change.** This is the seam the whole plan stands on.

- **The seam already carries the payload.** Exit today returns
  `Transition("outdoor", {"from": self._building})` after
  `state.mark_cleared(self._building)`. The channel for "what happened inside"
  exists and is plumbed; it's carrying a building id, and the M3 plan already
  reserved the richer shape it grows into.

So the foundation — grid, walls, BSP, the stateless renderer, the payload
channel, and an *unused* stairs/entity loader — is done. This plan is wiring and
content at known sites, not new architecture.

---

## The two questions this session is about

### Question 1 — multiple floors (the Bane-style vertical dive)

**A building is a *stack of floors*; a floor is a `DungeonMap`. Moving between
floors is internal to `IndoorWorld` — it is NOT a portal transition.** This is
the load-bearing decision, and it follows straight from the one-shell rule: the
portal exists to cross the *world* seam (outdoor ↔ indoor), and the only thing
that crosses it is `PlayerState`. Floors are all inside one world. So a staircase
must not route through the portal — it swaps the active `(dungeon, bsp_tree)`
pair *within* the indoor world and drops the camera at the matching landing on
the new floor. The portal never sees it; the shell never sees it; the seam stays
a hard cut used for exactly one thing.

Concretely, `IndoorWorld` grows from one dungeon to a small stack:

```
self.floors: list[FloorRuntime]   # one per level of the building
self.floor_index: int             # which floor is active right now
```

where a `FloorRuntime` is the `(DungeonMap, BSPTree)` pair plus the floor's
entities and its up/down landing cells. `self.dungeon` / `self.bsp_tree` become
views onto `self.floors[self.floor_index]` — every existing call site keeps
working unchanged, because they already read those two attributes.

A stairs cell, when stepped on with action, does:

1. compute the destination floor index (`+1` for `STAIRS_UP`, `-1` for
   `STAIRS_DOWN` — note Bane's `-Y is up`, so "up" is deeper into the tower),
2. swap `self.floor_index`,
3. lazily build that floor's BSP if first visit (cache it on the
   `FloorRuntime`),
4. place the camera at the *matching* landing (the down-stairs of the floor you
   rose into, so you arrive where the staircase emerges),
5. **no `Transition` returned** — the shell loop continues in the same world.

**This is the mechanism that produces `depth`.** `depth` in the M3 payload is
exactly "how far up/down you got" — the max `floor_index` reached this dive. An
outbuilding is one floor (`depth` tops out at 0); a skyscraper is many
(`depth` climbs). The vision's "skyscraper > outbuilding, depth scales the
ratchet delta" is no longer an abstraction — it's a counter that falls out of
walking up stairs. The interior doesn't have to *report* difficulty; the floor
you reach *is* the difficulty.

**One change to recommend against the existing loader:** `level.py` chains
floors by *filename* (`next: level2.map`). Retire that for the in-building stack.
Filename chaining is a single global namespace — every building would fight over
`level2.map` — and it implies floors live on disk as a fixed sequence, which
collides with Question 2 (procedural buildings of varying height). Keep the
`.map` *cell vocabulary* (the stairs glyphs, the entity glyphs — they're good);
drop the *cross-file `next`/`prev`* in favor of an index into `self.floors`,
which the building's source produces all at once.

#### The floor transition: Option A (chosen), real stairs deferred

The original Castle of Bane host (`bsp_dungeon_gl3d.py`) settles how to build
this, because Bane already did the floor change — it just hid it. Tracing it:

- **`_apply_level` *is* the floor-swap body, already written.** It sets
  `self.dungeon`, rebuilds and caches the BSP, replaces `self.entities`, clears
  door state, and places the camera — about ten lines. The AW floor-swap is a
  near-verbatim port of it, minus the file load.
- **Stairs were entities, triggered on cell-match.** `_check_entity_collisions`
  saw the player's grid cell equal a `stairs_down` / `stairs_up` entity and
  immediately routed to the next/prev level. There was no walkable staircase —
  Bane drew a green stairs *billboard* (`STAIRS_UP_MODEL` / `STAIRS_DOWN_MODEL`)
  on the goal cell and **teleported** on contact. That teleport is exactly the
  hard-cut intra-world swap described above.

So **Option A — the hard-cut floor swap — is the chosen starting point**, and
it is low-friction precisely because it is a port, not new code. Two deltas from
what Bane did:

1. **Matching-stair placement is the one net-new piece.** Bane dropped the
   player at the new level's `@` (a fixed authored entrance). The in-building
   stack instead places the camera at the destination floor's *complementary*
   stair, so you emerge where the staircase comes out. Small, but Bane never
   needed it, so it's written rather than ported.
2. **Action-gate the stairs.** Bane fired the teleport automatically the instant
   your cell matched. AW's *exit* is already action-gated (`inp.action`), so for
   consistency — and to avoid yanking the player between floors by walking over a
   cell — stairs should be "press E to take the stairs" too.

**Real stairs (Option B) are deferred, not abandoned**, and the trace confirms
they're contained: Bane's `cam_y` is a fixed constant, so a walkable staircase
is exactly "make `cam_y` a variable across a stair zone" with no hidden
machinery to inherit. Because the renderer is true-3D with a depth buffer, two
floors can be stacked at different world-y (floor N at `y=0`, floor N+1 at
`y=−wall_height`) and submitted together during the transition — the depth
buffer resolves the cross-floor occlusion, so you can see up/down the stairwell
for free. The plan: ship Option A to unblock the loop, then build Option B as a
vertical-slice showpiece on the **landmark skyscraper only** (§5's "real
geometry" cashed out where the full dive most earns it). Building Option A with
matching-stair placement is already one step into B, since B wants the same
placement. The thing nobody builds: a fully volumetric multi-floor-in-one-map —
different engine, AW doesn't need it.

### Question 2 — multiple buildings of different shapes and sizes

**The building archetype and footprint cross the seam as *parameters*, never as
coordinates.** The outdoor world already knows each building's archetype
(`WAREHOUSE` / `SMALL_BUILDING` / `LARGE_BUILDING` / `SKYSCRAPER`) and its
footprint (it places the obstacle with a known `hw`/`hd`). Today the enter
transition is `{"building": TOWER_ID}`. Grow it to carry what the interior needs
to *shape itself*:

```
Transition("indoor", {
    "building":  "tower_a",       # stable id for the cleared-ledger
    "archetype": "skyscraper",    # warehouse | small | large | skyscraper
    "footprint": (hw, hd),        # the outdoor box's half-extents
    "seed":      <int>,           # stable per building, for repeatable interiors
})
```

This keeps the coordinate seal intact (POC §6): the *numbers describing the
building* cross, but no pose, no axis, no world coordinate. The interior reads
them and decides its own shape in its own space.

The mapping that gives "shapes and sizes" real meaning:

- **Footprint → the floor's outer envelope.** The outdoor box's `hw`/`hd` set the
  grid width/height (in cells at `CELL_SIZE=50`). A wide warehouse becomes a wide,
  shallow grid; a narrow tower becomes a tight footprint. This is the
  *horizontal* dimension of variety.
- **Archetype → floor count + interior density.** This is the *vertical*
  dimension and the dive's character:
  - **warehouse** — destructible cover (vision §9). Either not enterable, or a
    single wide, sparse floor — a fast, low-value check.
  - **small** — hard cover. Not enterable, or a one-room token dive.
  - **large** — "short interior" (§9): 1–2 floors, quick to clear, modest reward
    odds.
  - **skyscraper** — "full dive": many floors, the deep one, the highest reward
    odds and the highest escalation cost on return.

So *breadth* comes from footprint and *depth* comes from archetype, and the two
combine into a building that reads as its outdoor silhouette without ever
reconciling coordinate systems. A thorough player diving small buildings pays
escalation for shallow `depth`; a player committing to the skyscraper pays more
but reaches the floors where the plant is likely hiding. **That is the vision's
risk economy, expressed as interior structure.**

---

## The new seam: `FloorSource` (one contract, two drivers)

The interior needs to turn `(archetype, footprint, seed)` into a stack of
floors, and there are two legitimate ways to author a floor — hand-built for
hero set-pieces, generated for everything else. Rather than picking one, put a
seam between "the interior world" and "where floors come from," exactly the way
the project already seams `World`, `SpatialQuery`, and the projectile factory —
the same one-engine-two-drivers / seed-artifact discipline used elsewhere in the
portfolio:

```
class FloorSource(Protocol):
    def floor_count(self, archetype, footprint, seed) -> int: ...
    def build_floor(self, archetype, footprint, seed, index) -> FloorRuntime: ...
```

Two adapters satisfy it:

- **`ProceduralSource`** — the default, and **a port of the existing Bane
  dungeon generator** (`dungeon_generator.py`), not new code. The generator
  already produces a Rogue-style rooms-and-corridors layout and brings three
  things the interior needs for free:
  - **Verified solvability.** `try_generate_level` rejects (and retries) any
    layout where a BFS flood-fill can't reach the goal from the start. A
    procedural building that strands the player past an unreachable plant is the
    one bug that breaks the loop, and this already refuses to emit one.
  - **Chokepoint lock/key gating → win/hint placement.**
    `find_corridor_chokepoint` finds a one-wide corridor cell that *provably*
    partitions the goal room, places the key on the reachable side, and verifies
    both halves. Those are exactly the two inverse guarantees the plant and hint
    want: the plant can sit behind a verified gate, and the hint must be reachable
    *without* it (§7's winnable blind search). Rename `goal`→`plant`,
    `key`→`intel`; the placement math is done.
  - **A one-place difficulty curve.** `config_for(level_num, total)` is where
    `archetype` and `footprint` plug in — it becomes
    `config_for(archetype, footprint, floor_index)`: footprint sets the grid
    width/height (replacing the hardcoded sizes), archetype sets floor count and
    room/enemy density, floor_index walks the curve.

  Deterministic from the seed, so a re-dived building doesn't reshuffle (the
  persistent world shouldn't rebuild a tower you've half-cleared). **What gets
  dropped on the way in:** the generator's file-I/O tail — `grid_to_level_string`,
  the `.level` writes, and the `next:`/`prev:` filename chain. Keep the
  generation, gating, and config; consume grids in memory and index them by
  floor. Same "vendor the engine, shed the CLI" move that de-windowed the
  renderer. (The generator's glyphs are already what the ported `level.py`
  parses, so the formats are compatible.)
- **`MapFileSource`** — loads a hand-authored `.map` per floor via the existing
  `level.py` parser, for the one or two buildings worth set-piecing (the landmark
  skyscraper; a deliberately-built win room). Reuses the cell vocabulary as-is.

**Win/hint placement is a decorator over whichever source produced the
geometry,** not baked into either — a `placement` pass that, given the finished
floor stack and the building's role, drops the plant entity and/or the intel
entity on a chosen floor/cell. Keeping placement separate from geometry is what
lets the §7 balance dials (how deep the plant biases, how early hints arrive)
be tuned in one place without touching the generators.

This is the join you want: the interior track fills the payload; the generators
fill the interior; the placement decorator fills the win/hint slots; and none of
them know about the outdoor ratchet at all.

---

## How the outcome payload falls out

Exit grows from `{"from": id}` to the record the M3 plan froze. Every field is
now produced by structure that exists in this plan:

```
Transition("outdoor", {
    "from":    building_id,
    "cleared": <reached the top / objective vs bailed at the entrance>,
    "depth":   <max floor_index reached this dive>,     # ← from Question 1
    "found":   <picked up the plant entity>,            # placement decorator
    "hint":    <read the intel entity> | None,          # deferred form, slot kept
})
```

- `depth` is the floor counter from the staircase mechanic — the richest signal,
  and the one the ratchet scales hardest on.
- `cleared` becomes a real outcome (top-reached vs bailed) instead of the single
  unconditional flag the scratch room sets today.
- `found` / `hint` are booleans the placement decorator's entities flip when
  collected; their *placement logic* (biased-deep vs biased-early) is the open
  balance question, deferred but with the slots reserved now so the seam is
  stable.

This is the same contract the M3 ratchet plan consumes. Freezing it here, in the
exit `Transition`, is the one artifact both tracks build against.

---

## Build order (when this becomes the active work)

Each step is thin, lands on a seam that already exists, and is pinned by a
headless test in the established style (`test_indoor_m20` is the template):

1. **Freeze the entry + exit payload shapes** — the enter dict
   (`archetype`/`footprint`/`seed`) and the exit outcome record. The one artifact
   the interior and the ratchet share.
2. **Floor stack + Option-A hard-cut transition** — `self.floors` /
   `self.floor_index`, plus a floor-swap method that is a near-verbatim port of
   Bane's `_apply_level` (set dungeon, rebuild+cache BSP, swap entities, reset
   doors, place camera). The two deltas from Bane: *matching-stair placement*
   (emerge at the destination floor's complementary stair, not a fixed `@`) and
   *action-gating* (press E, not auto-on-step). No `Transition`. Prove it with a
   *two-floor* `create_test_dungeon` extension — no source abstraction yet. Test
   pins: action on the up-stair raises `floor_index`; the camera lands on the
   matching down-stair; the active `(dungeon, bsp_tree)` pair changed; **no portal
   transition fired**; `depth` tracks the max index reached.
3. **`FloorSource` seam + `ProceduralSource` (the generator port)** — vendor
   `dungeon_generator.py`, drop its file-I/O tail, and reparameterize
   `config_for` to `(archetype, footprint, floor_index)`; make
   `large`/`small`/`warehouse` enterable per their gradient. `MapFileSource` comes
   later or in parallel for the hero tower. Test pins: archetype → floor count;
   footprint → grid envelope; same seed → identical stack; generated stack stays
   solvable (the generator's BFS guarantee survives the port).
4. **The outcome payload, wired** — exit reports real `cleared`/`depth`; the
   placement decorator drops the plant/intel entities and flips `found`/`hint`.
   This is the handoff to the ratchet track.
5. **Interior combat** (parallel M2.2 thread, not this plan) — the shared
   health pool and the first gunman give the floors something to fight through,
   which is what finally makes `cleared` (top-reached vs bailed) a *decision*
   rather than a walk.

Floors before buildings before payload, for the same reason the ratchet plan
orders itself "interior before ratchet": `depth` is the payload's richest field,
and you can't author the building gradient or tune the win-placement bias against
a depth axis that doesn't exist yet.

---

## Open tensions (balance/content, not architecture — recorded, not solved)

- **The §7 win-placement tension now has a concrete axis.** The skyscraper should
  *reward* the deep dive (plant biased to high floors), but the whole loop can
  harden into unwinnable if the plant is always deep and the search is blind.
  Floors make this a real dial: how high the plant biases, vs how early hints
  narrow which building, vs whether the plant can also turn up in an
  early-reachable large building. This is the same three-dial co-design the
  ratchet plan flagged — it wants the real interior in hand, which this plan
  provides, but it is still downstream of having floors to place against.
- **Interior/footprint scale honesty.** A skyscraper with a small outdoor box but
  many tall floors is "bigger inside than out." That's a tone call (§5): a hard
  cut through a lobby makes it forgivable, and most of the genre does it, but if
  it reads wrong, clamp interior floor area to the footprint and lean on *floor
  count* (not floor size) for skyscraper bigness.
- **Which buildings are enterable.** Vision §9 makes warehouse/small *cover* and
  large/skyscraper *dives*. If only two archetypes are enterable, the search has
  few buildings to choose among (the §7 "what counts as a progression tick"
  worry). Procedural buildings are the cheap way to make more of them enterable
  without hand-authoring — a reason to favor `ProceduralSource` as the default.
- **Hand-authored vs generated — mostly resolved, one content call left.** The
  generator port settles the *default*: `ProceduralSource` is the proven Bane
  generator, so most buildings are generated and solvability is guaranteed.
  `MapFileSource` remains for hero set-pieces, and the placement decorator keeps
  win/hint independent of geometry either way. The only thing still open is the
  content decision of *which* buildings (likely just the landmark skyscraper) get
  the hand-built treatment.
- **Real stairs (Option B) timing.** Option A ships first and is enough for the
  whole loop. Option B is a deferred showpiece, contained (`cam_y` becomes a
  stair-zone variable; depth buffer handles cross-floor occlusion) but unscheduled
  — it competes with interior combat and the hint's concrete form for the slot
  after the loop closes.
- **Renderer markers are content, not architecture.** Stairs cells and the
  plant/intel entities will want a visible marker the way the exit zone already
  has one (`_draw_exit_marker`). That's a small additive draw pass on the
  existing stateless renderer — no structural change, noted so it isn't mistaken
  for a blocker.