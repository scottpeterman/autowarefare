# Auto Warfare — Proof-of-Concept Design

Status: pre-build design. Scope is the integration spine, not the game.
Source projects: **Battlezone** (`bz/`, the `battlefield_engine`) and
**Castle of Bane** (`castleofbane/`, the `wireframe_engine` + dungeon
renderer + combat). This document defines what we port, what we build
new, what we refactor, and the order to do it in.

---

## 1. Concept

Auto Warfare is a first-person vehicular-combat game set in a wireframe
cityscape, rendered in the cyberblue phosphor look. You drive an armored
auto through open city blocks fighting enemy autos (Battlezone lineage).
Buildings come in four sizes — warehouse, small, large, skyscraper — and
**skyscrapers can be entered**. Entering one drops you out of the vehicle
into a first-person interior built on the Castle of Bane dungeon engine,
where the enemies are people (thug, knifeman, gunman) instead of monsters.
Clear the interior, return to the auto, and something in the outdoor war
has changed.

The pitch in one line: *Battlezone overworld, Castle of Bane dungeon dives,
stitched at skyscraper doors.*

---

## 2. The core architectural decision

**Auto Warfare is two engines hosted by one shell. It is not a unified
engine.**

We are not merging Battlezone and Castle of Bane into a single renderer.
Both already exist, both work, and they solve genuinely different problems:
open continuous wireframe space versus grid-based solid-walled interiors.
Forcing them into one abstraction is pure risk for zero gameplay gain.

Instead, a thin **shell** owns the process — the Qt host, the GL context,
the main loop, and the player's persistent state — and runs exactly one
**world** at a time. A **portal** hands the player between worlds at a
skyscraper lobby. The two engines never reference each other; they only
implement a small shared interface the shell understands.

What is actually shared is small and deliberate:

- **The motion integrator** — heading→forward-vector, constant velocity
  per tick. Both codebases already do this identically. It's a helper,
  not an engine.
- **The asset format** — the `lines` model dict. Already universal across
  both projects (see §4).
- **The spatial-query interface** — `can_move_to` / `line_of_sight`,
  implemented twice (see §4).
- **`PlayerState`** — health, lives, inventory, score, progress flags.
  Owned by the shell, mutated by both worlds (see §3).

Everything else is per-world and private to that world.

---

## 3. PlayerState — the retrofit-killer, built first

The single most important rule in the whole project:

> Player health, lives, collected artifacts/keys, score, and
> cleared-district flags live in the **shell**, in one `PlayerState`
> object. Neither world owns them. Both read and write through it.

This matters because both source codebases already carry their own health
and score:

- Battlezone has lives and score in its game object
  (`PLAYER_STARTING_LIVES`, `TANK_SCORE`, the lives-chevron HUD).
- Castle of Bane has `PlayerHealth` inside `combat.py`.

If we build the outdoor world with health living inside it, we will have
to tear it out later so that an enemy tank shell and a knifeman's slash can
both deduct from the same pool. A tank shell and a knife are two damage
sources mutating one shared number. Establishing that ownership on day one
means the indoor world slots in with nothing to reconcile; getting it wrong
means surgery on a working outdoor game.

`PlayerState` (shell-owned) carries at minimum:

- `health`, `max_health`, `lives`
- `score`
- `inventory` (keys, artifacts, upgrades)
- `cleared` — set of cleared building/district identifiers
- `invuln_ticks` (post-respawn grace, already a BZ concept)

The portal serializes nothing of the *world* across the seam — only
`PlayerState` survives the handoff. Coordinates explicitly do **not** cross
(see §6).

---

## 4. The two shared contracts

Beyond `PlayerState`, the worlds agree on exactly two things.

### 4a. Asset contract — the `lines` model dict

This already exists and is already universal. Every drawable in both
projects reduces to:

```python
MODEL = {
    'lines': [((x1,y1,z1),(x2,y2,z2)), ...],
    'scale': 1.0,
    'bob_speed': 0.0,
    'bob_amount': 0.0,
}
```

Drawn as `GL_LINES`. Battlezone's `an8_to_wireframe.py` emits this from
Anim8or meshes; Castle of Bane's `_build_*_3d` helpers build it directly;
and the procedural humanoid generator already projects into it via
`humanoid.to_lines(kind, target_height)` — whose docstring literally says
"drop the result straight into a model dict's 'lines' field." No new asset
format is required, and **no asset superset is needed** because the look is
wireframe and enemies are static-facing (see §8).

### 4b. Behavior contract — the spatial-query interface

The motion integrator is shared, but the *collision query* differs because
it is welded to how each world represents space. The interface that hides
that difference:

```python
class SpatialQuery(Protocol):
    def can_move_to(self, x: float, z: float, radius: float
                    ) -> tuple[bool, float, float]:
        """Returns (allowed, slid_x, slid_z) — supports slide-along."""
    def line_of_sight(self, ax, az, bx, bz) -> bool: ...
```

- **Outdoor** implements it with the existing continuous math: circle-vs-
  circle against obstacle bounding radii, per-axis trial-revert for
  slide-along, hard square clamp at the world boundary.
- **Indoor** implements it with the existing grid checks: sample points
  against walkable cells (`DungeonMap.is_walkable`, closed-door block) and
  grid-walk LOS (`combat.has_line_of_sight`).

All shared behavior — entity stepping, bullet stepping, enemy AI's "advance
toward the player" — calls this interface and never knows which world it's
in. The shell's mode router selects the live implementation.

---

## 5. What ports, what's new, what gets refactored

### Ports cleanly (lift from the source repos, light edits)

| From | Module(s) | Notes |
|------|-----------|-------|
| BZ | `battlefield.py`, `obstacle.py`, `tank.py`, `tank_ai.py`, `bullet.py`, `fragment.py`, `camera.py` | Outdoor world internals. Largely unchanged. |
| BZ | `render.py` | Already pure functions decoupled from the Qt shell — the target pattern for the indoor refactor too. |
| BZ | `models/*` | Existing wireframe model dicts. |
| BZ | `audio_manager.py` | 8-channel AudioManager; becomes a shell service. |
| Bane | `wireframe_engine/` (`bsp.py`, `dungeon.py`, `level.py`) | Grid + BSP + level loading. Faithful to its README; trustworthy. |
| Bane | `combat.py` | `CombatManager`, `Projectile`, `EnemyInfo`, `has_line_of_sight`, `StaffState` (→ weapon). **Remove `PlayerHealth`** — that moves to shell `PlayerState`. |
| Bane | `humanoid.py` | Procedural humanoid. **`to_lines` path only** — no skeleton retention, no faces. |

### New (build from scratch)

| Component | Purpose |
|-----------|---------|
| `shell/app.py` | Qt host: owns the GL context and the single `QTimer` loop. |
| `shell/player_state.py` | The `PlayerState` object (§3). |
| `shell/mode.py` | The `World` protocol + mode router. |
| `shell/portal.py` | Handoff: save/restore world position, scene swap, state carry-over. |
| `common/motion.py` | Thin shared heading→forward integrator. |
| `common/spatial.py` | The `SpatialQuery` interface (§4b). |
| `hud/` | Shared HUD compositor that draws from `PlayerState`. |
| `outdoor/world.py` | Wraps the BZ engine + implements `World` and `SpatialQuery`. |
| `indoor/world.py` | Wraps the Bane engine + implements `World` and `SpatialQuery`. |
| `indoor/creatures/` | Thug / knifeman / gunman creature defs (Bane monster-JSON format: stats + behavior + model refs). |
| `outdoor/models/buildings/` | The four building sizes as wireframe models. |
| `assets/` | City layout, tower interior `.level` files. |

### Refactored (the real work, and the riskiest part)

| What | From → To |
|------|-----------|
| Indoor renderer | `GL3DDungeonRenderer` (one ~2,137-line `QGraphicsView` subclass that owns its window, dungeon, combat, and HUD) → a **guest renderer** that draws into a context it does not own, driven by the shell's loop. BZ's `render.py` is the pattern: separate "the world + how to draw it" from "the Qt window." |

This refactor is the single unproven assumption in the plan and is
scheduled first (see §7).

---

## 6. The portal handoff

The portal is a **hard cut**, not a continuous walk-through. This is a
deliberate decision forced by the engines, and the READMEs make the reason
concrete:

- **Unit scale differs.** Outdoor is tank-scale (`WORLD_HALF_SIZE = 1000`,
  tank radius ~27). Indoor is human-scale (`CELL_SIZE = 50`, eye height
  `cam_y = -15`).
- **The vertical axis is inverted.** Indoor *walls* use **−Y = up** (floor
  `y=0`, ceiling `y=-60`). Outdoor uses **+Y = up**, ground-aligned. You
  cannot share a vertical convention across the seam without conversion.

Therefore the two worlds are independent coordinate spaces joined only by
`PlayerState`. The handoff:

1. Player drives up to a skyscraper and triggers entry at the lobby.
2. Shell saves outdoor `(x, z, heading)`, fades, swaps the active world to
   an indoor instance for that building.
3. Indoor world spins up in its own units with its own entry point.
4. On "cleared" (or exit), shell swaps back, restores the saved outdoor
   pose, and applies any cross-seam effects (a `cleared` flag, an inventory
   item). `PlayerState` carried straight through; nothing else did.

Note on the humanoid axis: indoor **entity** models already use +Y = up
(the billboard transform inverts them), and the humanoids are authored
+Y = up. So a thug drops into the existing entity path with no flip. The
inversion trap only bites if +Y-up structural geometry is fed into the
−Y-up wall pipeline — i.e. building interiors, not characters.

---

## 7. POC scope and build order

The POC proves the **spine**, not the game. The order is
riskiest-assumption-first, folded into an outdoor-first plan.

### Milestone 0 — Walking skeleton (the whole point of the POC)

Build the thinnest possible round-trip before growing any content:

1. **Shell** owns the GL context, the main loop, and `PlayerState`.
2. **Outdoor** is a near-empty stub: player auto, a handful of obstacles,
   drivable, clamped to the boundary.
3. **One Bane guest room** — not a black screen. The existing dungeon
   renderer, hosted as a guest, proving it can render when it is not in
   charge. This is the riskiest-assumption test; if the refactor is ugly it
   reshapes the mode interface, and that must be learned now while the
   interface is cheap to change.
4. **Portal round-trips.** Drive to the skyscraper → shell saves pose,
   swaps to the guest room → "done" → swaps back, restores pose. Health
   taken indoors is still gone outdoors. One `cleared` flag flips.

When Milestone 0 runs, the integration spine is standing and everything
after it is content, not architecture.

### Milestone 1 — Grow outdoor inside the correct shell

Flesh out the Battlezone world (enemy autos, the four building sizes as
obstacles, scoring) — but with health/score already reading and writing
through shell `PlayerState`, not owned locally.

### Milestone 2 — One real interior

One skyscraper with one procedurally/handcrafted interior and **one enemy
type — gunman first**. Gunman is ranged and reuses Bane's `Projectile` and
`has_line_of_sight` most directly; melee (thug, knifeman) needs new
approach-and-strike AI and comes later. Enemy uses the existing locked-
facing 3D entity path (static model, turns to face — confirmed sufficient).

### Milestone 3 — Close one cross-seam loop

Clearing the interior changes one thing outdoors (disable an enemy class,
open a district, or grant an upgrade carried back). This proves the portal
is load-bearing in the *economy*, not just the code — the difference
between a real game and two demos sharing a launcher.

---

## 8. Explicitly out of scope for the POC

These were considered and deliberately cut, so they don't creep in:

- **Asset superset / faces / skeleton retention.** The look is wireframe
  and enemies are static-facing, so the `lines` dict + existing `to_lines`
  is the entire pipeline. No `to_faces`, no retained joints.
- **Limb / walk animation.** Static turning with clear facing is sufficient
  for combat readability. The dormant `bob` is available but unneeded.
- **Portal / occlusion culling.** Bane's own numbers (80–288 wall faces at
  60fps, "instant" BSP rebuild on door open) put bounded interiors inside
  the proven envelope. Keep tower interiors at Bane scale; rely on the
  existing back-face cull + depth + fill + BSP order. Don't build culling.
- **Full city, all four building interiors, melee enemies, difficulty
  ramp.** All content, all post-spine.

---

## 9. Open design questions (deferred, not blocking)

Tracked so they aren't lost; none block the POC:

- **Cross-seam economy.** What exactly is *in* the towers, and what does
  clearing one change outside? (Control nodes? Commanders? Upgrades?) This
  is what makes the two halves one game; needs a real design pass before
  Milestone 3.
- **Building-size gradient.** Proposed: warehouse = destructible cover,
  small = hard cover, large = short interior, skyscraper = full dive. Gives
  the four sizes a gameplay reason beyond silhouette.
- **Melee AI** for thug/knifeman — approach-and-strike behavior not present
  in either codebase.
- **Weapon model** — Bane's `StaffState` becomes a gun; outdoor already has
  bullet logic. Reconcile into one weapon concept or keep per-world.

---

## 10. Proposed project structure

```
autowarfare/
├── shell/                  # NEW — the host; owns process, loop, state
│   ├── app.py              #   Qt host: GL context + single QTimer loop
│   ├── player_state.py     #   PlayerState (health, lives, inventory, score, cleared)
│   ├── mode.py             #   World protocol + mode router
│   └── portal.py           #   handoff: save/restore pose, scene swap, state carry
│
├── common/                 # shared contracts (the common language)
│   ├── model.py            #   the 'lines' dict contract + helpers
│   ├── motion.py           # NEW — heading→forward integrator (thin)
│   └── spatial.py          # NEW — SpatialQuery interface
│
├── outdoor/                # PORT — Battlezone lineage (free space, wireframe)
│   ├── world.py            # NEW — implements World + SpatialQuery (circle collision, clamp)
│   ├── battlefield.py      # port
│   ├── tank.py             # port
│   ├── tank_ai.py          # port (FSM)
│   ├── bullet.py           # port
│   ├── fragment.py         # port
│   ├── obstacle.py         # port
│   ├── camera.py           # port
│   ├── render.py           # port (already shell-decoupled)
│   └── models/
│       ├── *.py            # port — existing BZ model dicts
│       └── buildings/      # NEW — warehouse / small / large / skyscraper
│
├── indoor/                 # PORT + REFACTOR — Castle of Bane lineage (grid, solid)
│   ├── world.py            # NEW — implements World + SpatialQuery (grid collision, grid LOS)
│   ├── renderer.py         # REFACTOR — guest renderer from GL3DDungeonRenderer
│   ├── combat.py           # port — minus PlayerHealth (moved to shell)
│   ├── humanoid.py         # port — to_lines path only
│   ├── wireframe_engine/
│   │   ├── bsp.py          # port
│   │   ├── dungeon.py      # port
│   │   └── level.py        # port
│   ├── creatures/          # NEW — thug / knifeman / gunman (monster-JSON format)
│   └── levels/             # NEW — tower interior .level files
│
├── hud/                    # NEW — shared HUD compositor, draws from PlayerState
│   └── compositor.py
│
├── audio/                  # PORT — AudioManager as a shell service
│   └── audio_manager.py
│
├── assets/                 # audio, city layout data
│
└── main.py                 # entry: build shell, register worlds, run
```

---

## 11. Bottom line

We have enough to start. The architecture, the two contracts, the port
boundaries, the coordinate hazards, and the build order are all settled and
grounded in code that already runs. The hard part — two working engines —
is behind us; what remains is integration glue and content. Milestone 0 is
the real test, and it's small: a shell that hands a character between two
nearly-empty worlds without losing their health on the way.