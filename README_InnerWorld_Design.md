# Auto Warfare — Innerworld Design (the Bane port & guest-renderer spec)

Status: **build spec, grounded in vendored source.** This is the detailed pass
on the indoor half that `README_POC_Design.md` deferred. The POC doc settled
the *spine* and gave the indoor port a one-row summary in its §5 table
("Indoor renderer → a guest renderer … the single unproven assumption");
`README_AutoWarfare_Vision.md` owns *why* the interior exists (the search, the
§4 hint intent). This doc owns *how the Castle of Bane renderer becomes a guest
of the Auto Warfare shell* now that its source is in hand.

Where this and the POC doc disagree on **how things are built**, this doc wins
for the indoor half only — it has read the code the POC doc was predicting.
Where it touches **what we are building toward** (the hint, the economy), the
vision doc still wins.

Source read for this pass: `bsp_dungeon_gl3d.py` (2,137 lines — the renderer),
`combat.py`, `wireframe_engine/{bsp,dungeon,level}.py`, `humanoid.py`, and the
`monsters/` data format. Symbol names below are from that source.

---

## 1. Headline: the riskiest assumption tested clean

The POC named exactly one unproven thing and scheduled it first: can the
~2,137-line `GL3DDungeonRenderer` — which today owns its window, its dungeon,
its combat, its loop, and its HUD — be turned into a renderer that draws into a
context it does **not** own, driven by the shell's loop? Reading it answers
yes, and more cleanly than feared. Three facts make the extraction mechanical
rather than architectural:

1. **All GL is one contiguous block.** `drawBackground(painter, rect)` brackets
   every GL call between `painter.beginNativePainting()` and
   `painter.endNativePainting()`, then runs the QPainter HUD
   (`_draw_hud(painter)`) after. There is no GL/QPainter interleaving to
   untangle — it is already "GL pass, then 2D pass," which is precisely the
   shell's `paintGL`-then-QPainter shape (`shell/app.py`).
2. **Window/loop/input ownership is localized and small.** The QGraphicsScene,
   the `QOpenGLWidget` viewport, the `QTimer` (`timer.start(16)`), and
   `keyPressEvent`/`keyReleaseEvent` are the entire host surface — all in
   `__init__` and two event handlers. The shell already provides every one of
   them. De-windowing is deletion, not redesign.
3. **The player-state API already lines up.** `PlayerHealth` (in `combat.py`)
   exposes `take_damage`, `heal`, `is_dead`, `hp_fraction`. The shell's
   `PlayerState` exposes the same names plus `lose_life`, `invuln_ticks`,
   `damage_flash_ticks`. Removing `PlayerHealth` (POC §5) is a rename-and-route,
   not a reconciliation — §3 built `PlayerState` ahead of time for exactly this.

The takeaway for sequencing: the interior is **not** a green-field design. It
is a fill-in-three-contracts job over a working reference implementation (the
scratch room already satisfies all three contracts). The work is bounded.

---

## 2. The seam is already defined — three contracts, confirmed against code

`indoor/world.py` (the M0 scratch room) is a working reference implementation
of everything the shell asks of an indoor world. The Bane port replaces its
*internals*, not its interface. The three contracts, and where Bane satisfies
each:

| Contract | Shell expects | Bane supplies | Gap to close |
|----------|---------------|---------------|--------------|
| `World` (`shell/mode.py`) | `on_enter/on_exit`, `update(dt, InputState, state) → Transition?`, `draw(vp_w, vp_h)`, `spatial` | `drawBackground` GL block; `_tick`+`_handle_input` sim | de-window; read `InputState` not `keys_pressed`; drive from shell loop |
| `SpatialQuery` (`common/spatial.py`) | `can_move_to(x,z,r) → (free, rx, rz)`, `line_of_sight(ax,az,bx,bz)` | `_handle_input` grid sampling vs `DungeonMap.is_walkable`; `combat.has_line_of_sight` | repackage to the tuple shape; add slide-along; world↔grid wrap on LOS |
| weapon (`common/weapon.py`) | a `Weapon` = `ProjectileSpec` + `FireControl` + injected `ProjectileFactory` | `StaffState` (cast/cooldown gate) + `Projectile` | wrap `StaffState` as a `FireControl`; inject a Bane-`Projectile` factory |

Nothing in this table requires inventing a new abstraction. Every gap is a
repackage of code that already runs.

---

## 3. The renderer-as-guest refactor (the main event)

Target: `indoor/renderer.py` holding the GL drawing as plain functions/methods
that assume the context is current and the viewport is theirs — the same
discipline `outerworld_engine/render.py` already follows. `indoor/world.py`
becomes the thin `World` that owns indoor state and calls the renderer in
`draw()`.

**Strip (host surface the shell already owns):**

- `QGraphicsScene` / `setScene` / all `QGraphicsView` viewport config.
- `gl_widget = QOpenGLWidget(); setViewport(gl_widget)` — the shell's single
  `QOpenGLWidget` is the context now.
- `self.timer = QTimer(); timer.start(16)` — the shell's one 16 ms `QTimer`
  drives `update()`. **Do not keep a second timer.**
- `keyPressEvent` / `keyReleaseEvent` / `self.keys_pressed` — input arrives as
  the normalized `InputState`. (See §6 for the input remap.)
- `setWindowTitle`, `resizeEvent` window plumbing.

**Lift almost verbatim into `draw(vp_w, vp_h)`** — the body of `drawBackground`
between the native-painting brackets, in order: clear + depth enable, viewport,
`gluPerspective(75°, ar, 1, 1000)`, modelview from the camera
(`glRotatef(cam_angle, 0,1,0)`, `glTranslatef(-cam_x, -cam_y, -cam_z)`), the
polygon-offset fill pass, the BSP front-to-back wall traversal
(`bsp_tree.traverse_front_to_back(cam_x, cam_z)` → `_render_wall_3d`),
`_draw_entities`, `_draw_projectiles`, `_draw_effects`, `_draw_staff`, and the
damage-flash overlay. This is the whole indoor look and it moves as a unit.

**Hand to the shell's existing HUD pass:** `_draw_hud(painter)` and
`_draw_minimap(painter)` are QPainter. The shell already runs a QPainter HUD
after the world draws (`hud/compositor.py`, drawing from `PlayerState`). Two
options, decide once: (a) fold the indoor HUD/minimap into the compositor so
one HUD authority draws health/lives/score for both worlds and the minimap is
an indoor-only addition; or (b) let the indoor world expose a small
`hud_overlay(painter)` the shell calls. (a) is cleaner long-term and keeps the
"HUD reads `PlayerState`" rule whole; (b) is faster to stand up. **Recommend
(a)**, because the compositor already owns the health bar / lives / score and
the indoor `_draw_hud` currently duplicates them from `combat.player_hp` — that
duplication dies with the `PlayerHealth` removal anyway (§4).

**GL-state hygiene (the one thing to verify live, not on paper):** the outdoor
world already proves GL→QPainter handoff works in the shell, so the pattern is
sound. The indoor block enables `GL_DEPTH_TEST` and `GL_POLYGON_OFFSET_FILL`
and disables depth at the end (`glDisable(GL_DEPTH_TEST)` before
`endNativePainting`). Confirm on first run that it leaves GL state the shell's
next frame and the QPainter HUD tolerate — match whatever the outdoor world
already restores. This is a 10-minute live check, not a redesign; flag it in
the M2.0 acceptance test.

---

## 4. Removing `PlayerHealth` — the single invasive thread

POC §3/§5: player HP lives in the shell, not in a world. Today
`CombatManager.__init__` does `self.player_hp = PlayerHealth()`, and the field
is read in `combat.update`, `_update_enemy` (`dmg = self.player_hp.take_damage(
enemy.damage)`), the death path, the damage-flash check in `drawBackground`
(`self.combat.player_hp.damage_flash`), and `_draw_hud`.

The edit (owned fork — edit freely):

1. `CombatManager` stops owning `player_hp`. Its update signature takes the
   shell `PlayerState`: `combat.update(..., player_state)`.
2. Every `self.player_hp.take_damage(n)` → `player_state.take_damage(n)`;
   `is_dead`/`hp_fraction` reads → the same names on `PlayerState`.
3. The damage-flash that `drawBackground` reads moves from
   `combat.player_hp.damage_flash` → `state.damage_flash_ticks` (the shell
   already ticks this; the HUD already renders a red edge from it).
4. `combat.update` already returns an events dict
   (`damage_taken`, `enemies_killed`, `player_died`). Keep it — it is the clean
   bridge the world uses to drive flashes/score without the renderer reaching
   into combat internals. `player_died` routes to `state.lose_life()` (respawn
   + grace, game over at 0 lives — already implemented shell-side).

This is mechanical because the names match, but it is the one place the port
touches more than one file, so it gets its own increment (M2.2) and its own
test: damage taken indoors must persist outdoors through the portal — which the
scratch room already proves, so the test already exists in spirit.

---

## 5. The −Y-up coordinate hazard — sealed inside the guest

Confirmed in source: indoor is `cam_y = -15.0`, walls run floor `y=0` to
ceiling near `y=-60` (`CELL_SIZE = 50`, human scale). Outdoor is +Y-up,
tank-scale. POC §6 already ruled the portal a hard cut for this reason, and the
ruling holds: **the −Y-up convention never leaves the guest renderer.** The
shell, `PlayerState`, and the portal payload carry no vertical convention at
all — only HP/score/cleared/inventory and a `building` tag cross. The
inversion trap (POC §6) only bites if +Y-up structural geometry is fed into the
−Y-up wall pipeline; we feed it none — walls come from Bane's own
`DungeonMap.generate_walls`, authored in its own space. Humanoid *entities* are
authored +Y-up and the existing entity/billboard path already handles them, so
a person-enemy drops in without a flip (POC §6 note, still true).

Rule to carry forward: **no shared vertical axis across the seam, ever.** If a
future feature wants "the same object indoors and out," it carries a `lines`
model and each world places it in its own convention — it does not share a
transform.

---

## 6. `SpatialQuery` from the grid

Both methods already exist as logic inside Bane; they move behind the interface.

**`can_move_to(x, z, radius)`** — `_handle_input` already samples the body
center plus four cardinal offsets at `collision_radius = 12` through
`DungeonMap.world_to_grid` → `is_walkable`, with a closed-`DOOR`-cell block.
Repackage that into the `(was_free, resolved_x, resolved_z)` tuple. One
upgrade: today it is all-or-nothing (move fully or stop dead). The shell's
spatial contract promises *slide-along*; adopt the outdoor world's per-axis
trial-revert (try X then Z independently) so a glancing wall slides instead of
sticking. Small, and it makes indoor movement feel like the rest of the game.

**`line_of_sight(ax, az, bx, bz)`** — wrap `combat.has_line_of_sight(dungeon,
gx1, gz1, gx2, gz2)` with `world_to_grid` on both endpoints. It is already the
grid-walk LOS the ranged enemy uses (`enemy.los_cached = has_line_of_sight(...)`
in `_update_enemy`), so the gunman path is wired the moment this is exposed.

**Input remap:** `_handle_input` reads `Qt.Key.*` from `self.keys_pressed`;
the guest reads the normalized `InputState` (`forward/back/left/right` held,
`action`/`fire`/`cycle` edge). Door-open (`_try_open_door`, today a key) binds
to `action`; staff cast binds to `fire`. Movement constants (`speed = 3.0`,
`turn_speed = 2.0`) stay per-tick under the shell's fixed-timestep host (do not
rescale to seconds — same rule as outdoor).

---

## 7. The weapon — `StaffState` becomes a gun via the factory seam

`common/weapon.py` was built for this (its docstring names the indoor staff
explicitly). `StaffState` is a cast-animation + cooldown gate that returns
`spawn = True` on cast completion — i.e. it is already a `FireControl` in all
but name (a cadence/cooldown gate, sibling to the outdoor `BallisticFireControl`
and `HeatFireControl`). The port:

- Wrap `StaffState`'s cooldown logic as a `FireControl` implementation.
- The indoor world injects a `ProjectileFactory` that builds a Bane
  `Projectile` (the outdoor world injects a BZ `Bullet` factory today). This is
  the seam that lets `common/` stay engine-neutral while both worlds fire real,
  different rounds — the answer POC §9 asked for, now exercised on both sides.
- A `ProjectileSpec` carries the staff round's model/speed/range/damage. Once
  increment 3's `damage` field exists on `ProjectileSpec`, the indoor weapon
  inherits the unified damage economy for free.
- `_draw_staff` (the ~200-line first-person weapon overlay) stays in the guest
  renderer's draw — it is view, not logic.

Net: the player carries one weapon concept across both worlds; the shell's
`cycle`/`fire` intents already drive it.

---

## 8. Creatures & levels — data-driven; gunman first; people are content

**The monster system is already a data format**, not hardcoded enemies:
`monsters/*.monster.json` carry `hp`, `damage`, `speed`, `sight_range`,
`attack_range`, `attack_interval`, `turn_speed`, `behavior` (e.g. `melee`),
and a `model_2d` (billboard wireframe vertices) — with a parallel `.py`. This
is why POC M2 says **gunman first**: a `behavior: "ranged"` creature reuses
`Projectile` + `has_line_of_sight` + the locked-facing entity path most
directly, while melee (thug/knifeman) needs the new approach-and-strike Ai the
POC flagged. So the first interior enemy is a new `.monster.json` with ranged
behavior and a human silhouette — **content over an existing schema**, not new
architecture. Re-skinning skeleton/zombie/ghost → thug/knifeman/gunman is
authoring `model_2d` vertices and stats; it does not touch the engine.

**Levels** load from `.level` files (`wireframe_engine/level.py`:
`load_level` / `parse_level` → a `Level` with a `DungeonMap` + typed
`Entity` list). The portal payload's `building` tag selects which `.level` the
indoor world loads in `on_enter`. The first real interior is one `.level` with
one gunman and one exit — the scratch room's trap/exit zones become a real
room with a real enemy.

---

## 9. Build order (indoor increments, riskiest-first inside the half)

Each is a localized change behind the `IndoorWorld` seam; the outdoor world and
shell do not move.

- **M2.0 — Guest renderer round-trips.** Extract `indoor/renderer.py` from
  `drawBackground`; strip the host surface (§3); `indoor/world.py` drives it.
  No combat changes yet — load one `.level`, walk it first-person, exit through
  the portal. **This is the riskiest-assumption test made real**; acceptance =
  the existing portal round-trip test still green, plus a live GL-state-hygiene
  check (§3).
- **M2.1 — Grid `SpatialQuery`.** Swap the scratch room's box-clamp for the
  real grid collision + slide-along, and wire `line_of_sight` (§6). Movement now
  respects real walls and closed doors.
- **M2.2 — Combat on shell `PlayerState`.** Remove `PlayerHealth`; route combat
  damage/flash/death through the shell (§4). HUD de-duplicates onto the
  compositor. Acceptance = damage taken indoors persists through the portal
  (already proven by the scratch hazard — now via real combat).
- **M2.3 — One gunman.** A `behavior: "ranged"` human `.monster.json` in the
  level; the staff-as-`Weapon` fires a Bane `Projectile` via the injected
  factory (§7). First real fight indoors. This is the POC's Milestone 2 done.
- **M2.4+ — content.** More creatures (melee AI is the next *architecture*
  piece, when wanted), richer interiors, the `large = short interior` second
  building.

---

## 10. Open / deferred (carried, not solved)

- **Cross-seam economy + the hint intent.** Still owned by the vision doc
  (§4/§9): what is *in* a tower and what clearing it changes outside, and the
  interior-yields-information mechanism. The renderer/combat port is the
  *vehicle* for it; the design is downstream and unblocked by this spec.
  Reminder from the previous pass: the hint's form and the escalation pace are
  the same knob from two ends — designing the hint is designing the difficulty
  ceiling.
- **Melee AI (thug/knifeman).** Approach-and-strike behavior absent from both
  codebases; introduce after the gunman so single-weapon, ranged-only behavior
  is proven first (mirrors the POC's own ordering rationale).
- **Door state across re-entry.** Indoor `on_enter` resets to entry today (no
  pose persists — correct). If a tower becomes re-enterable-and-deepening (a
  vision §7 open tension), decide then whether `door_open_states` / cleared
  sub-rooms persist in `PlayerState.inventory`/`cleared` or reset. Not now.

---

## 11. Bottom line

The unproven assumption is no longer unproven: the Bane renderer de-windows
cleanly because its GL is already one bracketed block and its host surface is
exactly what the shell supplies. The interior reduces to filling three
contracts the scratch room already implements, plus one mechanical (name-matched)
removal of `PlayerHealth`. The −Y-up trap stays sealed inside the guest, as the
POC prescribed. Start at M2.0 — extract the renderer and prove the round-trip —
because every increment after it is content over an interface that already
holds.