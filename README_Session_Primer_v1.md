# Auto Warfare — Session Primer (read me first)

Purpose: start a fresh session on this project **without** loading both
engines cover-to-cover. This is the onramp; `AUTOWARFARE_POC_DESIGN.md` is
the spec. Read both of these in full, then read source code *just-in-time*
per the manifest below — never the whole repos.

Current position: **pre-build. Next task is Milestone 0 (the walking
skeleton).** Nothing has been written yet.

---

## Read protocol (the point of this doc)

1. Read this primer and `AUTOWARFARE_POC_DESIGN.md` fully. Together they
   are the complete context. Everything below is settled.
2. Do **not** read the BZ or Bane repos end-to-end. When you reach a step,
   open only the files and symbols named in the manifest for that step.
3. Prefer `grep`/targeted views over full-file reads. `bsp_dungeon_gl3d.py`
   is ~2,137 lines; Milestone 0 needs ~200 of them.
4. The engine READMEs are reference, not pre-reading. The design doc already
   distilled what matters (coordinate axes, BSP rebuild, performance
   envelope). Consult a README only to confirm a specific detail.

---

## Settled — do not re-litigate

These were decided across a long design session. Reopening them burns
budget for no gain.

- **Two engines, one shell.** Not a unified engine. The shell hosts one
  world at a time and hands the player between them.
- **Portal is a hard cut.** Two independent coordinate spaces (different
  unit scales; indoor walls use −Y up, outdoor uses +Y up). Only
  `PlayerState` crosses the seam. Coordinates do not.
- **`PlayerState` lives in the shell.** Health, lives, inventory, score,
  cleared flags. Both worlds read/write through it. Build it first.
- **Wireframe look, static-facing enemies.** No asset superset, no faces,
  no retained skeleton, no limb animation. The `lines` dict + existing
  `humanoid.to_lines` is the whole asset pipeline.
- **No portal/occlusion culling.** Bounded interiors at Bane scale stay
  inside the proven 80–288-face / 60fps envelope. Rely on the existing
  back-face cull + depth + fill + BSP order.
- **Gunman is the first enemy** (ranged; reuses Bane `Projectile` +
  `has_line_of_sight`). Melee comes later.

---

## Milestone 0 — first concrete action

Build the thinnest round-trip; prove the spine before any content:

1. Shell owns the GL context, one `QTimer` loop, and `PlayerState`.
2. Outdoor: drivable stub — player auto + a few obstacles + boundary clamp.
3. One Bane guest room hosted by the shell (not a black screen).
4. Portal round-trips: drive to skyscraper → save pose, swap to guest room
   → exit → restore pose. Health taken indoors stays gone. One flag flips.

**The riskiest assumption, do it first:** can Bane's `GL3DDungeonRenderer`
be driven by an external loop and draw into a context it does not own? If
that refactor is ugly, it reshapes the shell's mode interface — learn it on
day one. Start here: read the renderer's ownership surface (manifest §A),
read BZ's already-decoupled `render.py` as the target pattern (§C), then
extract a guest renderer.

---

## Focus-file manifest (this is also your upload list)

Attach only these to the next session. For each: why it matters for
Milestone 0, what to read, what to skip.

### A. `castleofbane/bsp_dungeon_gl3d.py` — the refactor target
The class being turned into a guest renderer. **Read:** `GL3DDungeonRenderer
.__init__` (GL/`QSurfaceFormat` setup, the `QTimer`, what it owns),
`initializeGL`, `drawBackground` (the GL draw flow — becomes the guest draw
entry), and the level-load sequence (dungeon → `generate_walls` →
`build_bsp_from_dungeon`). **Skip for M0:** monster model builders (the
`_build_*_3d` helpers ~line 370+), `_draw_staff`, periscope/effects, the
full HUD. ~200 of 2,137 lines.

### B. `bz/game.py` — the shell/loop precedent
BZ's `BattlezoneGame` is the closest existing thing to the shell. **Read:**
the `QTimer`/`_tick`/`_handle_input`/`drawBackground` loop structure, and
the constants that migrate into `PlayerState` (`PLAYER_STARTING_LIVES`,
`TANK_SCORE`, `TICK_MS`). **Skip:** spawn/respawn detail, fragment/explosion
specifics. You're extracting the loop shape and the state, not the gameplay.

### C. `bz/battlefield_engine/render.py` — the target pattern
Pure functions that take data and emit GL, with no Qt ownership. This is
exactly what the Bane renderer (§A) must be refactored *into*. **Read:** the
function signatures and how `game.py` calls them. Short. Read it before
touching §A.

### D. `castleofbane/combat.py` — PlayerHealth extraction
**Read:** the `PlayerHealth` class only (`take_damage`, `heal`, `is_dead`,
`hp_fraction`). It gets pulled out of combat and folded into shell
`PlayerState`, consolidated with BZ's lives/score. **Skip for M0:**
`CombatManager`, `Projectile`, `EnemyInfo` — those are Milestone 2.

### E. `castleofbane/wireframe_engine/dungeon.py` — indoor spatial surface
Just-in-time at the guest-room step. **Read:** `CELL_SIZE`, `is_walkable`,
`world_to_grid`, `grid_to_world`, `get_cell`. These back the indoor
`SpatialQuery` implementation. **Skip:** wall-geometry internals unless the
guest room misrenders.

### F. `castleofbane/wireframe_engine/level.py` + one `.level` file
Just-in-time at the guest-room step. **Read:** `load_level`, `Level`,
`Entity`, and one sample `.level` to see the format. The guest room loads
through this.

### Reference only (do not pre-read)
- `castleofbane/README_Engine.md` — coordinate axes, BSP rebuild on door
  open, performance envelope. Confirm details on demand.
- `bz/README_Engine.md` — outdoor conventions. On demand.

### Not needed until later milestones
- `humanoid.py` (`to_lines`, `PRESETS`) — Milestone 2 (enemies).
- `combat.py` `CombatManager`/`Projectile`/`has_line_of_sight` — M2.
- `monsters/*.monster.json` — M2 (thug/knifeman/gunman creature defs).
- BZ `tank_ai.py`, `bullet.py`, `fragment.py` — Milestone 1 (outdoor grows).

---

## Ignore entirely for the POC
Indoor content beyond the one proving room; asset generation work; culling;
the full city; the four building interiors; melee AI; difficulty ramp. All
post-spine. See design doc §8.