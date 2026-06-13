# Auto Warfare — Vision (the compass)

Status: **living design doc.** Unlike `README_POC_Design.md` (the settled
technical contract — the seam, the coordinate hazards, what not to re-litigate),
this doc holds the *game* — the why the architecture serves. It is allowed to
evolve as the game is discovered. When it and the POC design disagree, the POC
design wins on *how things are built*; this doc wins on *what we are building
toward*. Session primers point at both: read the primer for **what to do next**,
this for **why**, the POC design for **how the pieces bolt together**.

This is the cross-seam economy that POC §9 explicitly deferred ("what is *in*
the towers, and what does clearing one change outside... needs a real design
pass before Milestone 3"). This is that pass.

---

## 1. The frame: survival, not score

Auto Warfare is a survival game wearing an arcade-combat skin. Score is
feedback, not the point. The point is **continued existence in the world of
Auto Warfare** — a wireframe Mad Max × Blade Runner dystopia — and existence
runs on power.

The win condition is concrete and physical: you need a replacement **MicroNuke
Power Plant**. Without it you don't continue. It is somewhere in the city. You
have to find it, and finding it means fighting through a war that gets worse the
longer you look.

That single object turns the whole map into a **search problem wrapped in a
war**. Every other system — the vehicles, the weapons, the building dives, the
escalation — exists to make that search tense.

---

## 2. The win condition and the search

The MicroNuke Power Plant is **hidden in one building**, and you don't know
which. It could be the landmark skyscraper; it could be a nothing outbuilding on
the edge of the map. Locating it and securing it is the game.

This is why **buildings are enterable and worth entering** — the dive isn't a
side activity, it's how you search. An interior is where you find out whether
*this* building was the one, and (see §4) where you might learn something about
where it actually is.

---

## 3. The core loop: a risk economy made of escalation

The loop is: drive the battlefield → dive a building to search it → return to
the battlefield → repeat. The tension lives in what "return" costs.

**Every time you re-enter the battlefield from a dive, the war escalates by
reinforcement.** The outdoor world is one persistent place — the wrecks you left
stay wrecked — and while you were inside, the enemy kept coming. You come back
out to *reinforcements*: a harder roster, more of them, nastier mixes. The world
didn't reset and forgive you; it kept fighting. (This is a deliberate choice over
"rebuild a fresh roster each return" — reinforcement reads as a living warzone,
not a respawning arena.)

That escalation is the price of every search, and it makes building choice a
real decision instead of a checklist:

- **Outbuildings are easy to clear but cheap to be wrong about.** A quick dive,
  low combat cost inside — but each clear still ticks the escalation, so methodically
  picking off small buildings to "be thorough" actively hardens the battlefield
  without any guarantee you've found the plant. Thoroughness is punished.
- **Skyscrapers are hard to clear** (the full interior dive) but more likely to
  reward the escalation you pay for entering them.

So the player is always trading *search this building now* against *the war
outside gets worse when I climb back out*. The difficulty curve **is** the
player's own search behavior. That is the game.

---

## 4. Interiors have a reason to exist beyond combat — the hint intent

If interiors were only combat arenas, the dive would be pure cost. They're not.
**Interiors yield information that narrows the search.** Somewhere inside a
building you can learn something — a terminal, a map fragment, a survivor, salvaged
intel — that tells you the plant is *not here*, or *that way*, or *in a tall one*.

This does two things at once: it gives the Bane-dive half of the game a purpose
beyond fighting (the thing POC §9 worried the cross-seam economy needed), and it
gives the player a way to bend the blind search back toward winnable — spend dives
to *learn* as well as to *check*.

**The exact mechanism is deferred on purpose.** The interior is still the scratch
room; there's no real interior to design a hint *into* yet. So the hint system is
recorded here as an **intent** — "interiors yield information that narrows where
the plant is" — and its concrete form (what you find, how it's presented, how
strong a narrowing it gives) waits until there is a real interior to design it
around. Naming it without over-specifying it is what keeps it from going stale.

---

## 5. Tone: a retro engine telling a classic dystopian story

The identity is the contrast between the two:

- **A retro-feeling engine.** Cyberblue-phosphor wireframe, CRT framing, the
  Battlezone vector-arcade soul — now with the smoked-glass occlusion giving it
  real depth and mass. It should *feel* like a recovered machine from an older
  world, which fits a story about scavenging to survive.
- **A traditional sci-fi / dystopian story** executed straight: the last power
  core, the dead city, the war over the scraps, the long search. Not a parody of
  the genre — a sincere take on it, rendered in vectors.

The Mad Max layer is the *texture* (cobbled-together armored autos, the war for a
power source, the wasteland city). The Blade Runner layer is the *light* (the
phosphor neon, the towers, the melancholy). The game earns its feel by playing
both straight rather than winking at either.

---

## 6. What this constrains — and what it doesn't

Nothing built so far prohibits this vision; several pieces already carry it.
Recording the load-bearing ones so future sessions don't accidentally break them:

- **Progression already crosses the seam.** `PlayerState.cleared` is a set the
  portal carries through every dive untouched — it is already the progression
  ledger. ("TOWER LOBBY (cleared)" reading itself back is this loop's counter,
  already working.)
- **The escalation hook already fires.** `OutdoorWorld.on_enter(state, payload)`
  is called by the portal on every return to the battlefield. That is the single
  place "return → reinforce → harder" lives — it reads progression and builds the
  tier's roster. No new shell or portal plumbing; content logic at an existing
  seam.
- **Enemies are the player's own vehicles minus input, plus AI.** A vehicle is
  `model + hp + drive knobs + loadout`; the weapon system is owner-agnostic
  (`try_fire(..., owner="enemy")` already works). So "the flatbed I drive also
  becomes an enemy" is the *same data*, and mixed packs are one spawn table over
  shared definitions.
- **Decouple escalation from building count.** Track a `tier` (or
  `waves_cleared`) integer in `PlayerState` that bumps on each clear, so the
  difficulty curve isn't hostage to how many distinct interiors exist yet (today
  there is exactly one enterable building).

The one genuinely new subsystem this implies is a **spawn director**: a small
data-driven map from progression tier → which vehicles, how many, in what mix.
That is where the difficulty curve and the rock-paper feel (a swarm wants the
pulse, a hauler wants the shell, a mixed pack wants the flatbed) actually get
authored, and it's worth designing deliberately when its time comes.

---

## 7. Open tensions (known-unsettled — balance, not architecture)

These are real and recorded so they aren't mistaken for solved:

- **Escalation needs a ceiling or a pace.** Pure monotonic reinforcement plus a
  blind search means a thorough-but-unlucky player can harden the battlefield
  into an unwinnable state before the plant turns up. Candidate answers (pick
  later): escalation that plateaus; hints (§4) arriving fast enough to keep
  expected search-length under the curve; the plant's location biased toward
  buildings reachable early; or a soft cap on concurrent reinforcements. This is
  the central balance problem of the whole loop.
- **What counts as a progression tick** — clearing a distinct building, or
  re-diving a deepening tower? Repeated escalation needs either several enterable
  buildings (the parked "large = short interior" is the first candidate) or a
  re-enterable interior that deepens. The `tier` integer above keeps this open.
- **The hint mechanism's form** (§4) — deferred until a real interior exists.
- **Enemy weapon-selection AI.** A two-weapon enemy (the flatbed) has to *choose*
  cannon-at-range vs MG-up-close — a small new behavior on top of the tank FSM.
  Single-weapon enemies (buggy, pickup) sidestep it, which is a good reason to
  introduce them first and save the enemy flatbed for the top of the curve.

---

## 8. Where this sits in the build order

This vision is the **Milestone 3** payoff ("clearing the interior changes the
outdoor war" → here, *escalates* it, and the interior *informs* the search). It
sits cleanly downstream of the queued work and does not jump ahead of it:

1. **Damage model + enemy HP + enemy fire** (Milestone 1, increment 3) — you
   can't escalate threat without HP, damage, and enemies that shoot back.
2. **Non-tank vehicles** (increment 4) — you can't field a roster you haven't
   built. The sedan / pickup / flatbed are the player progression *and* the
   enemy bestiary.
3. **The real interior** (Milestone 2, vendoring the Bane renderer) — the hint
   system needs a real interior to live in; the search needs interiors worth
   diving.
4. **Then this loop** (Milestone 3): the spawn director, the reinforcement-on-
   return escalation, the hidden plant as win condition, the interior-driven
   hint. By the time it's built, every piece it stands on already exists.

When that milestone is the active work, it earns its own session primer — this
doc is the brief that primer will be written from.