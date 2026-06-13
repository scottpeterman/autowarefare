# Auto Warfare

A wireframe **Mad Max × Blade Runner** survival game: a cyberblue-phosphor
vector city you drive, fight, and search on foot — built as two very different
rendering engines hosted side by side behind one shell, sharing one game state
across a single seam.

This README is the entry point. It describes **what the project is** and **what
actually works today**, then points at the deeper design docs for the *why* and
the *how*. As of this milestone, the architecture is no longer a bet — a second,
independent engine has been integrated into the shell and proven it.

---

## What it is (the frame)

Auto Warfare is a survival game wearing an arcade-combat skin. You drive an
armored auto through a dead, war-torn city looking for one thing — a
replacement **MicroNuke Power Plant** hidden in one of the buildings. Finding it
means diving buildings to search them, and every time you climb back out into
the battlefield the war has escalated. The whole map is a search problem wrapped
in a war, and the difficulty curve *is* the player's own search behavior.

That single design idea is why the game is built the way it is: there are two
worlds — an **outdoor** battlefield and **indoor** building interiors — and the
tension lives in crossing between them. The engineering exists to make that
crossing seamless and cheap to author. The full design rationale lives in
`README_AutoWarfare_Vision.md` (the *why*); this README covers the machine that
serves it.

---

## What works today (base capabilities)

The engine spine is complete and exercised by an automated test suite. Concretely:

**One shell, two engines.** A single `QOpenGLWidget` owns the process: one GL
context, one 16 ms game loop, one HUD, one player state. It hosts two completely
different renderers as interchangeable *guests*, switching between them through
a portal — neither engine owns a window, a timer, or the loop.

**The outdoor world** — a Battlezone-derived vector engine (`outerworld_engine`).
You drive a tank-scale auto across a ~2 km battlefield with horizon, terrain, and
wireframe buildings; fire two weapons (a ballistic shell and a heat-gated pulse
rifle, switchable); destroy enemy autos driven by AI for score; and drive to the
landmark skyscraper to enter it.

**The indoor world** — the vendored *Castle of Bane* wireframe dungeon engine
(`innerworld_engine`), de-windowed and hosted as a shell guest. A real
grid-based dungeon with BSP-ordered wall rendering, smoked-glass occlusion, and
first-person movement with grid collision and slide-along. You walk real
geometry, the walls occlude believably, and you leave through an exit that hands
control back to the battlefield.

**The seam.** Crossing between worlds carries `PlayerState` — health, lives,
score, cleared-building ledger, inventory — and nothing else. Damage taken,
score earned, and progress all persist across the portal; coordinate systems and
vertical conventions never cross it. The outdoor auto's position is restored on
return, so the battlefield is one persistent place.

**Shared, engine-neutral systems.** Weapons/loadout, spatial queries
(collision + line-of-sight), and motion live in `common/` and are written
against neither engine, so the same weapon concept fires real (but different)
projectiles in both worlds.

What this milestone proved: a second engine with its own coordinate convention,
its own geometry pipeline, and its own combat model dropped into the shell by
satisfying three small contracts (`World`, `SpatialQuery`, a projectile
factory) — with no change to the shell, the portal, or the outdoor world. The
seam holds.

---

## Architecture in brief

The shell is the only thing that owns the runtime. Everything else is a guest.

- **`World` contract** (`shell/mode.py`) — every world implements
  `on_enter / on_exit`, `update(dt, input, state) → Transition?`, and
  `draw(viewport)`. The shell calls these; the world never reaches back.
- **One-shell rule** — a single `QOpenGLWidget` (`shell/app.py`) runs the loop:
  normalize input → `active.update(dt, input, state)` → `active.draw(...)` into
  the current GL context → a QPainter HUD pass on top. Exactly one world is
  active at a time.
- **The portal + `PlayerState`** (`shell/portal.py`, `shell/player_state.py`) —
  a `Transition` returned from `update` swaps the active world; `PlayerState` is
  the only thing that survives the swap. This is the entire cross-world economy.
- **Engines as guests** — `outerworld_engine` (Battlezone-derived vectors) and
  `innerworld_engine` (Castle of Bane dungeon) are kept as self-contained
  engines; the game-specific wiring that adapts each to the `World` contract
  lives in `outdoor/` and `indoor/` respectively.
- **Coordinate sealing** — the indoor engine renders in a **-Y-up** space
  (floor `y=0`, ceiling `y<0`) and the outdoor engine in **+Y-up**; each seals
  its own convention inside its renderer, and the portal is a hard cut so the
  two never have to reconcile. (The one explicit reconciliation — a vertical
  flip in the indoor renderer — is documented at its single point of use.)
- **Fixed-timestep hosting** — engine feel-constants are authored per-tick;
  each world runs an accumulator so the sim ticks at its native 16 ms regardless
  of frame rate.

The settled technical contract (the seam, the coordinate hazards, what not to
re-litigate) is `README_POC_Design.md`. The detailed pass on integrating the
Bane engine is `README_Innerworld_Design.md`.

---

## Running it

From the project root (so `az` resolves as a package):

```
python -m az.main          # run the game
python -m az.tests.test_spine        # 6 spine tests (drive/fire/score/portal/weapons) — headless
python -m az.tests.test_indoor_m20   # 5 indoor tests (dungeon/collision/LOS/exit) — headless
```

Controls: **W/S** drive or walk · **A/D** turn · **Space** fire · **Tab** cycle
weapon · **E** enter the tower / leave through the exit.

Requires Python 3.11+, `PyQt6`, and `PyOpenGL`. The automated tests are
headless (no GL/Qt context); the one thing they can't verify is live rendering,
so visual changes are signed off by running the window.

---

## Project layout

```
az/
  shell/            the runtime spine — app, World contract, portal, PlayerState
  common/           engine-neutral systems — weapons, spatial queries, motion, models
  hud/              the HUD compositor (reads PlayerState)
  outdoor/          the outdoor world wiring (adapts outerworld_engine to World)
  outerworld_engine/  Battlezone-derived vector engine — tanks, AI, terrain, render
  indoor/           the indoor world wiring + de-windowed renderer
  innerworld_engine/  vendored Castle of Bane — grid dungeon, BSP, level loading
  tests/            headless acceptance tests
  main.py           entry point
```

---

## Status & roadmap

- **M0 — walking skeleton** ✅ drive outdoor, enter a placeholder interior,
  return; the one-shell loop and portal proven.
- **M1 — combat abstraction** ✅ engine-neutral weapons/loadout; ballistic shell
  + heat-gated pulse; enemy tank AI and scoring outdoors.
- **M2.0 — Bane integration** ✅ the real dungeon engine vendored and de-windowed
  as a guest; first-person movement, occluding wireframe render, portal
  round-trip. *Architecture proven.*
- **M2.1 / M2.2 — indoor combat** ⏳ grid line-of-sight enemies; move
  Bane's player-health into the shell's `PlayerState` (the one invasive thread);
  the first gunman.
- **M3 — the loop** ⏳ the search economy: a hidden win-condition object,
  reinforcement-on-return escalation, and interiors that yield hints. This is the
  payoff the whole architecture was built toward (see the vision doc).

---

## Documentation map

- **`README.md`** (this file) — what it is, what works, how it's built, how to run.
- **`README_AutoWarfare_Vision.md`** — the game design and the *why*: the search
  loop, the escalation economy, the tone. The living compass.
- **`README_POC_Design.md`** — the settled technical contract: the seam, the
  coordinate hazards, the one-shell rule. How the pieces bolt together.
- **`README_Innerworld_Design.md`** — the detailed Bane-engine port: the
  guest-renderer refactor, the three contracts, the build order for the interior.
- **Session primers** — per-session onramps written from the docs above when a
  milestone becomes the active work.