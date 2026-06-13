"""
shell/mode.py — the World protocol and the shell<->world vocabulary.

The shell hosts exactly one World at a time and drives it through a tiny,
host-agnostic contract. A World owns everything private to itself (its
geometry, entities, coordinate space, units) and exposes only:

  - update(dt, input, state) -> Transition | None
        advance the simulation one tick, read normalized input, mutate the
        shared PlayerState, and optionally ask the shell to hand off.
  - draw(vp_w, vp_h)
        issue GL into the already-current context the shell owns. No clears
        of ownership beyond "the context is current and the viewport is mine."
  - on_enter(state) / on_exit(state)
        portal hooks for spin-up / teardown.
  - spatial  ->  SpatialQuery
        the world's collision/LOS implementation.

Input is **normalized to semantics here**, not passed as raw Qt key codes, so
worlds never import Qt and the same InputState drives either world. The shell
maps physical keys to these intents.

Transition is a world's request to be handed to another world; the actual
save-pose / swap / restore-pose mechanics live in shell/portal.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from az.common.spatial import SpatialQuery
from az.shell.player_state import PlayerState


@dataclass(frozen=True)
class InputState:
    """One frame of normalized input. Movement intents are *held* (level-
    triggered); action/fire are *edge* (true only on the frame they go down),
    so a single key press opens one door rather than spamming."""
    forward: bool = False
    back: bool = False
    left: bool = False        # turn left (heading decreases)
    right: bool = False       # turn right (heading increases)
    action: bool = False      # edge: enter / exit / interact
    fire: bool = False        # held: weapon fire (rate gated by the world)
    cycle: bool = False       # edge: cycle to the next weapon in the loadout


# A reusable no-input frame (e.g. when the window loses focus).
NO_INPUT = InputState()


@dataclass(frozen=True)
class Transition:
    """A world asking the shell to hand off. ``target`` is a registered world
    name; ``payload`` carries context the destination/portal may use (which
    building, an entry tag, etc.). Coordinates never travel in here — only
    PlayerState crosses the seam."""
    target: str
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class World(Protocol):
    name: str

    def on_enter(self, state: PlayerState, payload: dict[str, Any]) -> None:
        """Called as this world becomes active. Spin up / reset to entry."""
        ...

    def on_exit(self, state: PlayerState) -> None:
        """Called as this world stops being active."""
        ...

    def update(self, dt: float, inp: InputState,
               state: PlayerState) -> Transition | None:
        """Advance one tick. Return a Transition to request a handoff."""
        ...

    def draw(self, vp_w: int, vp_h: int) -> None:
        """Render into the shell's current GL context, sized to the viewport."""
        ...

    @property
    def spatial(self) -> SpatialQuery:
        ...
