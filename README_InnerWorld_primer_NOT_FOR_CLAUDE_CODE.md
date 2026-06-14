# Auto Warfare — Session Primer: the floor stack (Interior step 2)

**Read first:** `README_Innerworld_Interior_Plan.md` for the *why*. This primer is
**only** build-order step 2 — the two-floor vertical slice. Do this one thing;
everything else in the interior plan stays parked.

## Goal

Turn `IndoorWorld` from one dungeon into a **stack of floors** you move between
with stairs, entirely inside the indoor world — no portal. Prove `depth` (max
floor reached) falls out. No generator, no building shapes, no combat, no payload
growth yet.

## The seam it stands on (don't re-litigate)

`renderer.draw_interior(dungeon=…, bsp_tree=…, …)` is stateless drawing over the
pair `IndoorWorld` holds as `self.dungeon` / `self.bsp_tree`; `BSPTree` carries no
global state. So a floor change is: **swap that pair + reposition the camera** —
no renderer or engine edit. A staircase is **not** a `Transition`: floors are
intra-world; only the outdoor↔indoor seam uses the portal.

## What to add — `az/indoor/world.py`

(Extend the engine import to `DungeonMap, BSPTree` for the dataclass hints —
`CellType` / `build_bsp_from_dungeon` / `create_test_dungeon` are already imported.)

1. **`FloorRuntime`** — one per floor:
   ```python
   @dataclass
   class FloorRuntime:
       dungeon: DungeonMap
       bsp: BSPTree | None = None            # lazily built + cached
       up_stair:   tuple[int, int] | None = None   # STAIRS_UP cell (scan once)
       down_stair: tuple[int, int] | None = None   # STAIRS_DOWN cell
   ```

2. **Stack state** on `IndoorWorld`: `self.floors: list[FloorRuntime]`,
   `self.floor_index: int`, `self.max_floor: int`. `self.dungeon` / `self.bsp_tree`
   become views onto `floors[floor_index]`, so every existing call site (`draw`,
   `_blocked`, LOS) keeps working untouched.

3. **`_apply_floor(index, arrive_cell)`** — the Bane `_apply_level` port, minus the
   file load and minus combat:
   ```python
   def _apply_floor(self, index, arrive_cell):
       self.floor_index = index
       fr = self.floors[index]
       if fr.bsp is None:                         # lazy cache
           fr.bsp = build_bsp_from_dungeon(fr.dungeon)
       self.dungeon, self.bsp_tree = fr.dungeon, fr.bsp
       gx, gz = arrive_cell
       self.cam_x, self.cam_z = self.dungeon.grid_to_world(gx, gz)
       self.max_floor = max(self.max_floor, index)
   ```

4. **Stair trigger** in `_sim_tick`, mirroring the existing action-gated exit.
   Detect by **cell type** — the engine already has `CellType.STAIRS_UP/DOWN`, so no
   entity layer is needed for step 2:
   ```python
   if inp.action:
       gx, gz = self.dungeon.world_to_grid(self.cam_x, self.cam_z)
       cell = self.dungeon.get_cell(gx, gz)
       if cell == CellType.STAIRS_UP and self.floor_index + 1 < len(self.floors):
           self._apply_floor(self.floor_index + 1,
                             self.floors[self.floor_index + 1].down_stair)
           return None                            # intra-world: NO Transition
       if cell == CellType.STAIRS_DOWN and self.floor_index > 0:
           self._apply_floor(self.floor_index - 1,
                             self.floors[self.floor_index - 1].up_stair)
           return None
   ```
   `on_enter` builds the stack (the test fixture below, for now) and calls
   `_apply_floor(0, <floor-0 start cell>)` instead of the single
   `create_test_dungeon()` path.

## The two deltas from Bane (the only non-obvious bits)

- **Matching-stair placement.** Bane dropped you at the new level's `@`. You
  instead arrive at the destination floor's *complement* stair (climb an UP → land
  on the floor above's DOWN), so you emerge where the staircase comes out. That's
  the `arrive_cell` argument.
- **Action-gate it.** Bane teleported the instant your cell matched. Gate on
  `inp.action` (consistent with the existing exit) so walking over a stair doesn't
  yank you between floors.

## One guard

The building exit (back to outdoor) must only fire on **floor 0** — you can't leave
the building from floor 3. Gate the existing `_in_exit_zone()` exit with
`self.floor_index == 0`.

## Test — `az/tests/test_floor_stack.py` (headless, `test_indoor_m20` style)

Fixture: a `_two_floor_building()` helper returning `[FloorRuntime, FloorRuntime]` —
two `create_test_dungeon`-style grids, floor 0 carrying a `STAIRS_UP` cell, floor 1
a `STAIRS_DOWN` cell at the complementary position (`set_cell` + `generate_walls`;
scan the stair cells into `up_stair` / `down_stair`).

Pins:
- action on floor 0's up-stair → `floor_index == 1`
- after the climb, the camera's grid cell == floor 1's `down_stair` (matching placement)
- the active `(dungeon, bsp_tree)` pair changed **identity**
- the climb returned **`None`**, not a `Transition` (no portal fired)
- `max_floor` tracks the deepest index reached across an up-then-down round trip
- action on floor 1's down-stair → back to `floor_index == 0`

## Out of scope (stays parked in the interior plan)

`FloorSource` / `MapFileSource`, the generator port, building archetype/footprint,
the outcome-payload growth (`cleared` / `depth` / `found` / `hint`), real walkable
stairs (Option B), interior combat. Step 2 is *only* the stack + the swap + the pins.

## Done when

`python -m az.tests.test_floor_stack` passes, and a window run lets you climb and
descend between two floors with **E**. Then the generator port (step 3) is the next
primer.