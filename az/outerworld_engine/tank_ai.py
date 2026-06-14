"""
Enemy-tank AI — port of Heminger's ``enemytank.js`` movement state machine.

Slice 1 (done): movement-only FSM — patrol, patrolrotate, chase,
lookchase. Five states lifted from ``enemytank.js:283-322``.

Slice 2 (this version): ``setavoid()`` cone-projection reactivity
from ``player.js:83-86``. When a tank in chase or lookchase is
inside the player's gun-sight cone (a narrow forward wedge, not the
full viewport FOV), it breaks into ``evade`` — turning perpendicular
to the player's line of fire and advancing to exit the cone as fast
as possible. This is the single best AI decision in the original
Battlezone: the tank doesn't just run away (which keeps it in the
cone), it *dodges sideways*. The result on screen is a tank that
reads as aware of the player's aim — it jinks when you're lined up,
forces you to re-aim, and punishes sitting at range.

States:

  idle           → one-tick stub. ``tick_tank`` kicks it into
                   ``patrol`` on the first tick.
  patrol         → drive forward on current heading for N ticks,
                   then rotate to a new random heading. Drops into
                   ``chase`` if the player closes within
                   ``ENGAGE_DISTANCE``. Also drops into
                   ``patrolrotate`` early if forward move is blocked.
  patrolrotate   → turn toward ``ai_target_heading``. Returns to
                   ``patrol`` when aligned. Safety tick-cap.
  chase          → turn toward player AND advance (aim-gated). Drops
                   into ``lookchase`` stochastically or if too close.
                   **New in slice 2:** drops into ``evade`` if the
                   player's gun-sight cone covers the tank.
  lookchase      → turn toward player, hold position. Slice 3 fires
                   here. **New in slice 2:** also checks cone → evade.
  evade          → turn perpendicular to the player→tank bearing and
                   advance. Exits back to chase when the cone check
                   clears (or to patrol if the player escapes past
                   ``DISENGAGE_DISTANCE``). Minimum duration prevents
                   oscillation at the cone edge.

Coordinate convention: ``heading = 0`` faces -Z, positive heading
rotates clockwise from above. ``atan2(dx, -dz)`` for bearings —
verified against ``Camera.forward``.

Tunables are module-level constants. Tune freely against arcade
reference; copy keepers back into this file.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .battlefield import Battlefield
    from .tank import Tank


# --- Tunables ----------------------------------------------------------------

# Per-chassis handling now lives on the Tank (M1 increment 4): ``move_speed``
# (top/chase speed, u/tick), ``turn_speed_deg``, and ``engage_distance``. The
# pre-increment-4 single-tank reference was move 0.35 / turn 0.65 / engage 600,
# which remain the Tank field defaults — so an unspecified tank drives exactly
# as before, and a VehicleDef makes a Sedan quick or a Pickup ponderous by
# overriding those three.
#
# Patrol speed, evade speed, evade turn rate, and the disengage range stay fixed
# FRACTIONS of the chassis knobs rather than separate per-vehicle numbers, so a
# fast chassis is fast in every state. The ratios below reproduce the old
# absolutes exactly against the reference chassis (0.22/0.35, 0.30/0.35,
# 0.90/0.65, 800/600).
PATROL_SPEED_RATIO = 0.22 / 0.35    # patrol ≈ 63% of top speed
EVADE_SPEED_RATIO = 0.30 / 0.35     # evade  ≈ 86% of top speed
EVADE_TURN_RATIO = 0.90 / 0.65      # evade turn ≈ 138% of base turn
DISENGAGE_RATIO = 800.0 / 600.0     # disengage hysteresis = 133% of engage

# Chase aim gate. A tank in chase only advances when its heading is
# within this tolerance of the bearing-to-player. Above tolerance,
# the tick is turn-only — pivot in place until the gun lines up,
# then drive. Mirrors tracked-vehicle physics (you can't drive
# sideways while still pivoting), and avoids the "tank strafes
# toward the player" look that comes from slewing-while-advancing.
# 30° is forgiving enough that small heading wobble doesn't stall
# forward motion, tight enough that a fresh-engaged tank with a
# 90°+ aim delta sits and turns first.
CHASE_AIM_TOLERANCE_DEG = 30.0

# State durations (ticks). Picked at state-entry from a uniform
# distribution between min/max, except ``patrolrotate`` which is a
# safety cap (it normally exits early once aligned).
PATROL_TICKS_MIN = 60          # 1.0 sec
PATROL_TICKS_MAX = 240         # 4.0 sec
PATROLROTATE_TICKS_MAX = 180   # 3.0 sec safety cap
LOOKCHASE_TICKS_MIN = 30       # 0.5 sec
LOOKCHASE_TICKS_MAX = 90       # 1.5 sec

# Engagement distance is now per-chassis (``tank.engage_distance``); the
# disengage threshold is ``engage * DISENGAGE_RATIO`` (hysteresis is intentional
# — without it a tank chasing at exactly the engage distance would oscillate
# between chase and patrol as the distance jitters around the threshold).
CHASE_MIN_DISTANCE = 60.0      # if closer, switch to lookchase so the
                               # tank doesn't drive *through* the player.

# Per-tick probability of pausing mid-chase to "aim" (drop into
# lookchase). Engagement (patrol → chase) is deterministic on
# distance, not probabilistic — see tick_tank docstring for why.
P_CHASE_TO_LOOKCHASE = 0.01

# --- Evade (slice 2: setavoid() cone-projection) ---
#
# The gun-sight cone is the narrow forward wedge where the player's
# crosshair could plausibly land. Not the full 75° viewport FOV —
# that's too wide; a tank at the screen edge isn't really aimed at.
# 15° half-angle covers roughly the gun-sight bracket reticle width.
# A tank inside this cone is *in the crosshairs* and should dodge.
EVADE_CONE_HALF_DEG = 15.0

# Evade speed and turn are fractions of the chassis knobs (EVADE_SPEED_RATIO /
# EVADE_TURN_RATIO above), so a fast chassis dodges fast. The point is lateral
# displacement (clearing the cone), not raw distance; evade turn runs a touch
# above the chassis turn rate so the tank snaps to its escape heading promptly
# and spends its evade ticks moving, not pivoting.

# Minimum ticks in evade before re-checking the cone. Prevents
# oscillation at the cone boundary — without this, a tank at the
# edge of the cone would enter evade, take one step out, clear the
# cone, re-enter chase, turn back toward player, re-enter the cone,
# and repeat at ~2 Hz (reads as jittering in place).
EVADE_MIN_TICKS = 45           # ~0.7 sec commitment

# --- Enemy firing (milestone 6) ---
#
# Tanks fire from ``lookchase`` — the stance where they pause to aim.
# Same one-bullet-at-a-time rule as the player: if the tank's bullet
# is still in flight, it can't fire another. The fire decision has two
# gates:
#
#   1. Aim tolerance — the tank's heading must be within this many
#      degrees of the bearing-to-player. Wider = more forgiving (fires
#      sooner, less accurate), narrower = more precise (delays fire
#      until well-aimed). 10° keeps shots threatening without being
#      pixel-perfect — the arcade tank misses a lot, which is the point
#      (gives the player time to react and dodge behind cover).
#
#   2. Per-tick fire probability — even when aimed, the tank doesn't
#      fire every single frame. This adds the arcade's hesitation beat:
#      the tank lines up, pauses, *then* fires. At 62.5 Hz, 0.03/tick
#      averages ~1.9 sec between fire-ready and actual shot, which
#      matches the arcade's feel of "you have a beat to get behind
#      cover once you see the tank aiming at you."
#
ENEMY_FIRE_AIM_TOLERANCE_DEG = 10.0   # heading-to-player tolerance
ENEMY_FIRE_PROBABILITY = 0.03         # per-tick probability once aimed

# Fire-then-evade probability. When the cone check forces a lookchase
# tank into evade, it gets ONE chance to fire a parting shot. This
# probability is higher than the per-tick ENEMY_FIRE_PROBABILITY
# because it's checked exactly once (the transition tick), not over
# many frames. 0.35 means roughly 1 in 3 cone-triggered lookchase
# exits produce a shot — enough to be threatening, not so high that
# every encounter starts with an undodgeable bullet.
ENEMY_FIRE_THEN_EVADE_PROBABILITY = 0.35

# Set True to emit one-line state-transition logs to stdout while
# tuning. Off by default — flips on without code change.
DEBUG_AI = False


# --- Public entry point ------------------------------------------------------

def tick_tank(
    tank: Tank,
    battlefield: Battlefield,
    player_x: float,
    player_z: float,
    player_heading: float = 0.0,
    enemy_bullet_in_flight: bool = False,
) -> None:
    """Advance one tank by one game tick.

    Mutates the tank's state in place: ``ai_mode``, ``ai_state_ticks``,
    ``heading``, ``x``, ``z``, ``ai_wants_fire``. Reads obstacle list
    from the battlefield for collision-driven direction changes. Does
    not allocate.

    Called once per tank per tick from ``Battlefield.step_tanks``.

    ``enemy_bullet_in_flight`` gates the one-bullet-at-a-time rule
    (passed down to ``_tick_lookchase``). Since there's one enemy tank
    at a time in canonical Battlezone, this is a single bool covering
    "any enemy bullet alive?" — if we later support multiple concurrent
    tanks, it'll need to become per-tank (track owner on each bullet).

    Engagement transitions (patrol/patrolrotate → chase, chase/lookchase
    → patrol) are evaluated at the top of the tick before per-state
    dispatch — they're deterministic on distance with hysteresis
    (ENGAGE_DISTANCE 600 / DISENGAGE_DISTANCE 800). The arcade enemy
    tank doesn't ambivalate: when the player closes in range, it
    commits immediately.

    Slice 2 addition: the cone-projection check (``_in_player_cone``)
    runs after engagement transitions but before per-state dispatch.
    If a tank in chase or lookchase is inside the player's gun-sight
    cone, it drops into evade. If a tank already in evade has served
    its minimum duration and is no longer in the cone, it returns to
    chase. The cone check uses ``player_heading`` — added to the
    signature for this purpose.
    """
    # Clear the fire flag at the top of every tick — the AI sets it
    # fresh if conditions are met this frame. game.py reads it after
    # step_tanks() returns.
    tank.ai_wants_fire = False

    if tank.ai_mode == 'idle':
        _enter_patrol(tank)
        return  # behavior begins next tick — fine, one frame of stillness

    # Player-relative geometry, computed once per tick.
    # bearing_to_player is the heading value the tank would need to
    # point straight at the player. atan2(dx, -dz) follows from
    # Camera.forward = (sin(h), -cos(h)) — see module docstring.
    dx = player_x - tank.x
    dz = player_z - tank.z
    dist_to_player = math.hypot(dx, dz)
    bearing_to_player = math.atan2(dx, -dz)

    # Engagement / disengagement transitions, deterministic on distance.
    # Hysteresis (engage < disengage) prevents thrashing at the boundary.
    if (
        tank.ai_mode in ('patrol', 'patrolrotate')
        and dist_to_player < tank.engage_distance
    ):
        _enter_chase(tank)
    elif (
        tank.ai_mode in ('chase', 'lookchase', 'evade')
        and dist_to_player > tank.engage_distance * DISENGAGE_RATIO
    ):
        _enter_patrol(tank)

    # Slice 2: cone-projection check (setavoid).
    # If the tank is in the player's gun-sight cone while chasing or
    # aiming, break into evade. If already evading and the minimum
    # commitment has elapsed and the cone is clear, return to chase.
    #
    # Milestone 6 addition: fire-then-evade. When the cone check
    # triggers on a tank in lookchase (it's aiming and the player is
    # aiming back), the tank gets a fire opportunity BEFORE entering
    # evade. This is the arcade's most dangerous moment — both you and
    # the tank are lined up, it fires a parting shot, then dodges.
    # Without this, the tank can never fire when the player is aimed at
    # it (the cone check preempts _tick_lookchase every time).
    in_cone = _in_player_cone(
        tank.x, tank.z,
        player_x, player_z, player_heading,
        math.radians(EVADE_CONE_HALF_DEG),
    )

    if (
        tank.ai_mode in ('chase', 'lookchase')
        and in_cone
        and dist_to_player < tank.engage_distance * DISENGAGE_RATIO
    ):
        # Fire-then-evade: lookchase tank gets one fire check before
        # breaking into evade. The aim tolerance is already met (it's
        # in the player's cone, which is ±15°, and lookchase was
        # turning toward the player), so we only gate on the one-bullet
        # rule and the probability roll.
        if (
            tank.ai_mode == 'lookchase'
            and not enemy_bullet_in_flight
        ):
            aim_error = abs(_angle_diff(bearing_to_player, tank.heading))
            if aim_error <= math.radians(ENEMY_FIRE_AIM_TOLERANCE_DEG):
                if tank._rng.random() < ENEMY_FIRE_THEN_EVADE_PROBABILITY:
                    tank.ai_wants_fire = True
                    if DEBUG_AI:
                        print(
                            f"[tank@{tank.x:+.0f},{tank.z:+.0f}] "
                            f"FIRE-THEN-EVADE"
                        )

        _enter_evade(tank, bearing_to_player, player_heading)
    elif (
        tank.ai_mode == 'evade'
        and tank.ai_state_ticks <= 0
        and not in_cone
    ):
        # Cone clear and commitment served — re-engage.
        _enter_chase(tank)

    # Per-state dispatch.
    if tank.ai_mode == 'patrol':
        _tick_patrol(tank, battlefield)
    elif tank.ai_mode == 'patrolrotate':
        _tick_patrolrotate(tank)
    elif tank.ai_mode == 'chase':
        _tick_chase(tank, battlefield, dist_to_player, bearing_to_player)
    elif tank.ai_mode == 'lookchase':
        _tick_lookchase(tank, bearing_to_player, enemy_bullet_in_flight)
    elif tank.ai_mode == 'evade':
        _tick_evade(tank, battlefield, bearing_to_player)


# --- State entry helpers -----------------------------------------------------

def _enter_patrol(tank: Tank) -> None:
    duration = tank._rng.randint(PATROL_TICKS_MIN, PATROL_TICKS_MAX)
    _set_state(tank, 'patrol', state_ticks=duration)


def _enter_patrolrotate(tank: Tank, target_heading: float) -> None:
    tank.ai_target_heading = target_heading
    _set_state(tank, 'patrolrotate', state_ticks=PATROLROTATE_TICKS_MAX)


def _enter_chase(tank: Tank) -> None:
    # Chase has no fixed duration — it ends on distance trigger,
    # collision, or stochastic drop-to-lookchase. Set ticks=0 so any
    # accidental decrement just stays at 0.
    _set_state(tank, 'chase', state_ticks=0)


def _enter_lookchase(tank: Tank) -> None:
    duration = tank._rng.randint(LOOKCHASE_TICKS_MIN, LOOKCHASE_TICKS_MAX)
    _set_state(tank, 'lookchase', state_ticks=duration)


def _enter_evade(
    tank: Tank,
    bearing_to_player: float,
    player_heading: float,
) -> None:
    """Enter evade: pick a perpendicular escape heading and commit.

    The escape heading is perpendicular to the bearing FROM the player
    TO the tank — i.e. 90° off the player's line of fire. We pick
    whichever perpendicular (left or right) is closer to the tank's
    current heading, so the tank pivots the shorter way and starts
    displacing sooner. If both are equidistant (tank heading is exactly
    on-axis or anti-axis), break the tie randomly.

    The bearing from player to tank is the *reverse* of
    ``bearing_to_player`` (which is tank-to-player), so we add π.
    Then ±π/2 gives the two perpendicular headings.
    """
    # Bearing from player to this tank (reverse of tank→player).
    bearing_from_player = (bearing_to_player + math.pi) % (2.0 * math.pi)

    perp_cw = (bearing_from_player + math.pi / 2.0) % (2.0 * math.pi)
    perp_ccw = (bearing_from_player - math.pi / 2.0) % (2.0 * math.pi)

    delta_cw = abs(_angle_diff(perp_cw, tank.heading))
    delta_ccw = abs(_angle_diff(perp_ccw, tank.heading))

    if delta_cw < delta_ccw:
        escape_heading = perp_cw
    elif delta_ccw < delta_cw:
        escape_heading = perp_ccw
    else:
        # Equidistant — random tiebreak.
        escape_heading = tank._rng.choice([perp_cw, perp_ccw])

    tank.ai_target_heading = escape_heading
    _set_state(tank, 'evade', state_ticks=EVADE_MIN_TICKS)


def _set_state(tank: Tank, mode: str, state_ticks: int) -> None:
    """One-line state transition; emits a debug log if DEBUG_AI is on."""
    if DEBUG_AI and tank.ai_mode != mode:
        print(
            f"[tank@{tank.x:+.0f},{tank.z:+.0f}] "
            f"{tank.ai_mode} → {mode}"
        )
    tank.ai_mode = mode
    tank.ai_state_ticks = state_ticks


# --- Per-state ticks ---------------------------------------------------------

def _tick_patrol(
    tank: Tank,
    battlefield: Battlefield,
) -> None:
    """Drive forward; periodically rotate. Engagement is handled at
    the top of ``tick_tank`` (deterministic on distance), so this
    state's only job is wandering."""
    tank.ai_state_ticks -= 1
    if tank.ai_state_ticks <= 0:
        _enter_patrolrotate(tank, _random_heading(tank))
        return

    if not _try_move_forward(tank, battlefield,
                             tank.move_speed * PATROL_SPEED_RATIO):
        # Blocked by obstacle or world bound. Pivot — picking a new
        # random heading rather than e.g. "the heading away from the
        # blocker" because the random pick reads more like the arcade
        # AI ("tank just changed its mind"), and the cost of a slightly
        # silly pivot direction is low (next tick's _try_move_forward
        # will block again and re-pivot if needed).
        _enter_patrolrotate(tank, _random_heading(tank))


def _tick_patrolrotate(tank: Tank) -> None:
    """Rotate toward ai_target_heading; resume patrol when aligned."""
    step = math.radians(tank.turn_speed_deg)
    delta = _angle_diff(tank.ai_target_heading, tank.heading)

    if abs(delta) <= step:
        # Snap to the target — avoids one-tick overshoot oscillation.
        tank.heading = tank.ai_target_heading
        _enter_patrol(tank)
        return

    if delta > 0:
        tank.heading = (tank.heading + step) % (2.0 * math.pi)
    else:
        tank.heading = (tank.heading - step) % (2.0 * math.pi)

    tank.ai_state_ticks -= 1
    if tank.ai_state_ticks <= 0:
        # Safety bail — should not fire in practice given the tick cap
        # is comfortably larger than a half-turn at TANK_TURN_SPEED_DEG.
        # Better than spinning forever if numeric drift conspires.
        _enter_patrol(tank)


def _tick_chase(
    tank: Tank,
    battlefield: Battlefield,
    dist_to_player: float,
    bearing_to_player: float,
) -> None:
    """Turn toward player + advance, with the aim gate.

    Disengagement (player escapes past DISENGAGE_DISTANCE) is handled
    at the top of ``tick_tank``, not here. This state's job is purely
    "close on the player": pivot until aimed, then advance, with an
    occasional pause to settle (lookchase).

    Forward movement is gated on aim alignment — see
    ``CHASE_AIM_TOLERANCE_DEG``. Above tolerance, this tick is
    turn-only. That's the fix for the "tank strafes toward the
    player" look that an earlier version had: when chase first
    engaged from patrol with a 90°+ aim delta, the tank advanced
    in its old heading direction for ~1.5s while slowly slewing
    toward the player, which read on screen as moving sideways or
    in reverse. Real tracked vehicles pivot first and drive second;
    so does ours now.
    """
    if dist_to_player < CHASE_MIN_DISTANCE:
        _enter_lookchase(tank)
        return
    if tank._rng.random() < P_CHASE_TO_LOOKCHASE:
        _enter_lookchase(tank)
        return

    # Always turn toward player.
    _turn_toward(tank, bearing_to_player)

    # Advance only if the gun's pointing close to the player. Check is
    # against post-turn heading, so the tick on which alignment crosses
    # the threshold also gets the forward step (no extra dead frame).
    aim_error = abs(_angle_diff(bearing_to_player, tank.heading))
    if aim_error <= math.radians(CHASE_AIM_TOLERANCE_DEG):
        # Blocked-move just stalls the tick. The tank keeps slewing
        # toward the player on subsequent ticks; either it finds an
        # unblocked angle or it stays glued to cover. Obstacle-aware
        # path-around routing would be a slice 1.5+ feature.
        _try_move_forward(tank, battlefield, tank.move_speed)


def _tick_lookchase(
    tank: Tank,
    bearing_to_player: float,
    enemy_bullet_in_flight: bool,
) -> None:
    """Turn toward player, hold position, and fire when aimed.

    The tank pauses in lookchase to line up a shot. Firing gates:
      1. No enemy bullet already in flight (one-at-a-time rule).
      2. Heading within ``ENEMY_FIRE_AIM_TOLERANCE_DEG`` of the
         bearing to the player (the tank is actually aimed).
      3. Per-tick probability roll (adds the arcade hesitation beat —
         the tank doesn't fire the instant it's aimed, it takes a
         moment, giving the player a beat to react).

    When all three gates pass, ``ai_wants_fire`` is set. The game loop
    reads this flag after ``step_tanks()`` and spawns the bullet. The
    tank then transitions back to chase (it fired, now close again).
    """
    _turn_toward(tank, bearing_to_player)

    # Fire decision — only when aimed and the gun is free.
    if not enemy_bullet_in_flight:
        aim_error = abs(_angle_diff(bearing_to_player, tank.heading))
        if aim_error <= math.radians(ENEMY_FIRE_AIM_TOLERANCE_DEG):
            if tank._rng.random() < ENEMY_FIRE_PROBABILITY:
                tank.ai_wants_fire = True
                if DEBUG_AI:
                    print(
                        f"[tank@{tank.x:+.0f},{tank.z:+.0f}] "
                        f"FIRE (aim_err={math.degrees(aim_error):.1f}°)"
                    )
                # After firing, return to chase — the tank shot, now
                # it should close distance again (or get evaded out by
                # the cone check on the next tick).
                _enter_chase(tank)
                return

    tank.ai_state_ticks -= 1
    if tank.ai_state_ticks <= 0:
        _enter_chase(tank)


def _tick_evade(
    tank: Tank,
    battlefield: Battlefield,
    bearing_to_player: float,
) -> None:
    """Dodge perpendicular to the player's line of fire.

    Turn toward the escape heading (set at evade entry) and advance.
    The escape heading is perpendicular to the player→tank bearing,
    so the tank displaces laterally relative to the player's aim —
    exiting the gun-sight cone as fast as possible.

    Uses ``EVADE_TURN_SPEED_DEG`` (slightly faster than normal) so the
    tank snaps to the escape heading promptly and spends most of its
    evade ticks actually moving, not pivoting.

    If a forward move is blocked (obstacle or world bound), flip to the
    other perpendicular — the tank is cornered on this side, try the
    other. This prevents the "tank evades into a cube and stalls"
    degenerate case.

    ``ai_state_ticks`` counts down the minimum commitment. The exit
    check (cone clear + commitment served) is in ``tick_tank``, not
    here — this function just moves.
    """
    # Turn toward escape heading at the boosted evade turn rate.
    step = math.radians(tank.turn_speed_deg * EVADE_TURN_RATIO)
    delta = _angle_diff(tank.ai_target_heading, tank.heading)

    if abs(delta) <= step:
        tank.heading = tank.ai_target_heading
    elif delta > 0:
        tank.heading = (tank.heading + step) % (2.0 * math.pi)
    else:
        tank.heading = (tank.heading - step) % (2.0 * math.pi)

    # Advance along current heading (not target — lets the tank start
    # displacing even while still pivoting, as long as the heading is
    # close enough to perpendicular that forward motion is useful).
    if not _try_move_forward(tank, battlefield,
                             tank.move_speed * EVADE_SPEED_RATIO):
        # Blocked — flip escape heading to the other perpendicular.
        # The bearing from player to tank gives the axis; the current
        # target is one perp, the other is 180° away from it along
        # the perpendicular ring (equivalently: reflect through the
        # player→tank axis).
        tank.ai_target_heading = (
            tank.ai_target_heading + math.pi
        ) % (2.0 * math.pi)

    # Count down minimum commitment.
    if tank.ai_state_ticks > 0:
        tank.ai_state_ticks -= 1


# --- Helpers -----------------------------------------------------------------

def _in_player_cone(
    tank_x: float,
    tank_z: float,
    player_x: float,
    player_z: float,
    player_heading: float,
    half_cone_rad: float,
) -> bool:
    """True if the tank is inside the player's forward gun-sight cone.

    The cone is centered on ``player_heading`` with half-width
    ``half_cone_rad``. A tank at the cone edge is considered inside
    (``<=`` not ``<``). Distance doesn't matter here — the cone is
    infinite; distance gating is the caller's job (engagement range
    already covers it).

    This is the ``setavoid()`` test from ``player.js:83-86``: the
    original checks whether the enemy is within the player's forward
    arc and sets an evade flag on the tank. Our implementation is
    equivalent but expressed as a pure function rather than a
    side-effecting method on the player.
    """
    dx = tank_x - player_x
    dz = tank_z - player_z
    if dx == 0.0 and dz == 0.0:
        return True  # on top of player — definitely in cone
    bearing_to_tank = math.atan2(dx, -dz)
    delta = abs(_angle_diff(bearing_to_tank, player_heading))
    return delta <= half_cone_rad


def _random_heading(tank: Tank) -> float:
    return tank._rng.uniform(0.0, 2.0 * math.pi)


def _turn_toward(tank: Tank, target_heading: float) -> None:
    """Step the tank's heading toward target by at most its turn rate.

    Snap-to-target if the remaining delta is smaller than one step
    (otherwise the tank one-tick-oscillates around the target).
    """
    step = math.radians(tank.turn_speed_deg)
    delta = _angle_diff(target_heading, tank.heading)

    if abs(delta) <= step:
        tank.heading = target_heading
    elif delta > 0:
        tank.heading = (tank.heading + step) % (2.0 * math.pi)
    else:
        tank.heading = (tank.heading - step) % (2.0 * math.pi)


def _angle_diff(target: float, current: float) -> float:
    """Shortest signed angular distance from ``current`` to ``target`` (rad).

    Result is in ``[-π, π]``. Positive means ``target`` is clockwise
    from ``current`` (right turn in our heading convention). Used by
    ``_turn_toward`` and ``_tick_patrolrotate`` to pick the rotation
    direction without going the long way around.
    """
    d = (target - current) % (2.0 * math.pi)
    if d > math.pi:
        d -= 2.0 * math.pi
    return d


def _try_move_forward(
    tank: Tank,
    battlefield: Battlefield,
    distance: float,
) -> bool:
    """Try to advance the tank by ``distance`` along its forward vector.

    Mutates the tank's position if the move is clear; returns True.
    Returns False (and leaves position unchanged) if the move would
    overlap an obstacle or leave the play square. Caller decides what
    to do about a blocked move — patrol pivots, chase just stalls.

    Mirrors ``Battlefield._bullet_hits_obstacle``'s sweep + per-candidate
    check so the AI's idea of "blocked" matches the bullet engine's
    idea of "hit". Tank-on-tank collision is intentionally not
    checked here (single-tank scenes only for slice 1; with multiple
    tanks we'd check against ``self.tanks`` excluding self).
    """
    fx = math.sin(tank.heading)
    fz = -math.cos(tank.heading)
    new_x = tank.x + fx * distance
    new_z = tank.z + fz * distance

    if not battlefield.in_bounds(new_x, new_z):
        return False

    # Sweep big enough to catch the worst-case obstacle radius (cube
    # at ~26 in-play). 200 is comfortably conservative; matches the
    # value used in Battlefield._bullet_hits_obstacle and
    # BattlezoneGame._collides_at.
    sweep = tank.bounding_radius + 200.0
    for obs in battlefield.obstacles_near(new_x, new_z, sweep):
        r = tank.bounding_radius + obs.bounding_radius
        ddx = new_x - obs.x
        ddz = new_z - obs.z
        if ddx * ddx + ddz * ddz < r * r:
            return False

    tank.x = new_x
    tank.z = new_z
    return True
