"""
shell/player_state.py — the one place player progress lives (POC design sec 3).

The single most important rule in the project: health, lives, inventory,
score, and cleared-district flags live in the **shell**, in one PlayerState.
Neither world owns them; both read and write through it. A tank shell outdoors
and a knifeman's slash indoors are two damage sources mutating one pool — if
either world owned health we would be doing surgery on a working game to share
it later. Establishing the ownership now means the indoor world slots in with
nothing to reconcile.

This consolidates what the two source codebases carried separately: Castle of
Bane's ``PlayerHealth`` (hp / max / damage-flash) and Battlezone's lives and
score (``PLAYER_STARTING_LIVES``, ``TANK_SCORE``). It is the only thing that
crosses the portal seam — coordinates explicitly do not (see shell/portal.py).

Pure data + small methods. No GL, no Qt. The HUD reads it; it never draws.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Consolidated from the two source engines.
STARTING_MAX_HEALTH = 100.0
STARTING_LIVES = 3                 # Battlezone PLAYER_STARTING_LIVES
RESPAWN_INVULN_TICKS = 90          # ~1.5 s of grace at 60 Hz (BZ concept)
DAMAGE_FLASH_TICKS = 18            # red-edge feedback duration, in ticks


@dataclass
class PlayerState:
    """Player progress, owned by the shell and shared by both worlds."""

    max_health: float = STARTING_MAX_HEALTH
    health: float = STARTING_MAX_HEALTH
    lives: int = STARTING_LIVES
    score: int = 0

    # keys / artifacts / upgrades as simple counts; upgrades as a flag set
    inventory: dict[str, int] = field(default_factory=dict)
    upgrades: set[str] = field(default_factory=set)

    # cleared building / district identifiers — the cross-seam progress flags
    cleared: set[str] = field(default_factory=set)

    # transient per-tick feedback
    invuln_ticks: int = 0
    damage_flash_ticks: int = 0

    # --- health ----------------------------------------------------------

    @property
    def hp_fraction(self) -> float:
        """0.0–1.0, for the HUD health bar."""
        if self.max_health <= 0:
            return 0.0
        return max(0.0, min(1.0, self.health / self.max_health))

    @property
    def is_dead(self) -> bool:
        return self.health <= 0.0

    @property
    def is_invulnerable(self) -> bool:
        return self.invuln_ticks > 0

    @property
    def is_game_over(self) -> bool:
        """True once every life is spent — a terminal state. The world freezes
        on it; only a shell-level restart (a fresh PlayerState) clears it."""
        return self.lives <= 0

    def take_damage(self, amount: float) -> float:
        """Apply ``amount`` of damage unless in post-respawn grace. Returns the
        damage actually applied (0.0 if ignored). Triggers the HUD flash."""
        if amount <= 0 or self.is_invulnerable or self.is_dead:
            return 0.0
        applied = min(amount, self.health)
        self.health -= applied
        self.damage_flash_ticks = DAMAGE_FLASH_TICKS
        return applied

    def heal(self, amount: float) -> None:
        if amount <= 0:
            return
        self.health = min(self.max_health, self.health + amount)

    def lose_life(self) -> bool:
        """Spend a life and respawn at full health with grace. Returns True if
        the game is over (no lives left).

        Idempotent at the terminal: once lives are spent, calling it again is a
        no-op that keeps returning True. This is what stops a damage source that
        connects every tick — enemy fire outdoors, a hazard indoors — from
        re-entering on a corpse (``is_dead`` stays true at 0 lives) and driving
        lives negative. The guard lives here, in the shared pool, so every
        caller across both worlds inherits it."""
        if self.lives <= 0:
            return True
        self.lives -= 1
        if self.lives <= 0:
            self.health = 0.0
            return True
        self.health = self.max_health
        self.invuln_ticks = RESPAWN_INVULN_TICKS
        return False

    # --- score / inventory / progress -----------------------------------

    def add_score(self, points: int) -> None:
        self.score += points

    def add_item(self, name: str, count: int = 1) -> None:
        self.inventory[name] = self.inventory.get(name, 0) + count

    def take_item(self, name: str, count: int = 1) -> bool:
        """Consume ``count`` of an item if available. Returns success."""
        have = self.inventory.get(name, 0)
        if have < count:
            return False
        self.inventory[name] = have - count
        return True

    def has_item(self, name: str) -> bool:
        return self.inventory.get(name, 0) > 0

    def mark_cleared(self, ident: str) -> None:
        self.cleared.add(ident)

    def has_cleared(self, ident: str) -> bool:
        return ident in self.cleared

    # --- per-tick housekeeping ------------------------------------------

    def tick(self) -> None:
        """Advance transient timers one frame. The shell calls this once per
        tick, after the active world has updated."""
        if self.invuln_ticks > 0:
            self.invuln_ticks -= 1
        if self.damage_flash_ticks > 0:
            self.damage_flash_ticks -= 1
