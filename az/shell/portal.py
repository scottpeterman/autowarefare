"""
shell/portal.py — the hard-cut handoff between worlds (POC design section 6).

The portal is a hard cut, not a continuous walk-through, because the two worlds
are independent coordinate spaces (different unit scales; the indoor wall
pipeline is even -Y-up). The only thing that survives the seam is the shared
PlayerState; coordinates never cross.

What the portal does on a Transition:
  1. Ask the current world to hand back an opaque *pose* (its own coordinates),
     and remember it under the current world's name. Worlds that don't persist
     a pose (the indoor world always re-enters at its level start) return None.
  2. on_exit the current world, on_enter the target — carrying PlayerState and
     the transition payload straight through.
  3. If the target previously handed back a pose, restore it, so driving back
     out of a tower drops you exactly where you left the auto.

The pose is deliberately opaque to the portal (a plain object the world reads
back). The shell holds the registry and the active world; the portal only
moves the player between registered worlds.
"""

from __future__ import annotations

from typing import Any

from az.shell.mode import Transition, World
from az.shell.player_state import PlayerState


class Portal:
    def __init__(self, worlds: dict[str, World]) -> None:
        self._worlds = worlds
        self._saved_pose: dict[str, Any] = {}

    def resolve(self, name: str) -> World:
        try:
            return self._worlds[name]
        except KeyError:
            raise KeyError(
                f"portal target {name!r} is not a registered world "
                f"(have: {sorted(self._worlds)})") from None

    def transit(self, current: World, transition: Transition,
                state: PlayerState) -> World:
        """Hand the player from ``current`` to the transition target. Returns
        the new active world. PlayerState is mutated in place by the worlds'
        on_exit/on_enter; the portal never touches its contents."""
        target = self.resolve(transition.target)

        # 1. Save the outgoing world's pose, if it keeps one.
        pose = _save_pose(current)
        if pose is not None:
            self._saved_pose[current.name] = pose

        # 2. Swap.
        current.on_exit(state)
        target.on_enter(state, transition.payload)

        # 3. Restore the incoming world's pose, if we have one for it.
        saved = self._saved_pose.get(target.name)
        if saved is not None:
            _restore_pose(target, saved)

        return target


def _save_pose(world: World) -> Any:
    """A world opts into pose persistence by implementing ``save_pose()``.
    Outdoor returns its (x, z, heading); indoor doesn't implement it, so the
    auto's spot is remembered while the tower always restarts at its entry."""
    fn = getattr(world, "save_pose", None)
    return fn() if callable(fn) else None


def _restore_pose(world: World, pose: Any) -> None:
    fn = getattr(world, "restore_pose", None)
    if callable(fn):
        fn(pose)
