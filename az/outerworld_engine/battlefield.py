"""
Battlefield — the open-terrain world.

Replaces ``wireframe_engine.dungeon.DungeonMap`` from Castle of Bane.

Differences from DungeonMap:
  - No grid. No cells. No ``world_to_grid`` / ``grid_to_world``.
  - No walls. Obstacles are free-floating point entities with a model
    and a heading, not grid-aligned wall faces.
  - No BSP draw-order tree. Z-buffer + (later) sort-by-distance handles
    open-terrain rendering for the small obstacle counts we need
    (~25 in the original Battlezone scene).

The world is a square centered on the origin with bounds
``[-half_size, +half_size]`` on both X and Z. The player is clamped
to those bounds each tick (Battlezone original: ``stayinsidegame``
in ``helpers.js``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .bullet import Bullet
from .fragment import Fragment
from .obstacle import Obstacle
from .tank import Tank


@dataclass
class Battlefield:
    """Container for all free-floating obstacles + active projectiles + tanks.

    Three lists by entity type:
      - ``obstacles``: passive scenery (cubes, tetras, platforms, mountains).
      - ``bullets``:   active projectiles. Updated each tick via
                       ``step_bullets``; expire on range/bounds/hit.
      - ``tanks``:     destructible enemies. Will tick AI in milestone 4
                       (``step_tanks``); currently just sit there.

    Bullet hit-tests prioritize tanks over obstacles — a bullet
    overlapping both kills the tank, not gets absorbed by the cover
    behind it.
    """

    half_size: float = 1000.0
    obstacles: list[Obstacle] = field(default_factory=list)
    bullets: list[Bullet] = field(default_factory=list)
    tanks: list[Tank] = field(default_factory=list)
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def size(self) -> float:
        """Edge length of the play square."""
        return 2.0 * self.half_size

    def in_bounds(self, x: float, z: float) -> bool:
        return (
            -self.half_size <= x <= self.half_size
            and -self.half_size <= z <= self.half_size
        )

    def clamp(self, x: float, z: float) -> tuple[float, float]:
        """Clamp a point back inside the play square."""
        return (
            max(-self.half_size, min(self.half_size, x)),
            max(-self.half_size, min(self.half_size, z)),
        )

    def add(self, obstacle: Obstacle) -> None:
        self.obstacles.append(obstacle)

    def add_bullet(self, bullet: Bullet) -> None:
        self.bullets.append(bullet)

    def add_tank(self, tank: Tank) -> None:
        self.tanks.append(tank)

    def add_fragment(self, fragment: Fragment) -> None:
        self.fragments.append(fragment)

    def obstacles_near(self, x: float, z: float, radius: float) -> list[Obstacle]:
        """Brute-force radius query.

        For ~25 obstacles this is cheaper than maintaining a spatial index.
        Revisit if obstacle counts climb past a few hundred.
        """
        r2 = radius * radius
        return [
            o
            for o in self.obstacles
            if (o.x - x) ** 2 + (o.z - z) ** 2 <= r2
        ]

    def step_tanks(
        self,
        player_x: float,
        player_z: float,
        player_heading: float = 0.0,
    ) -> None:
        """Advance all tanks one tick of AI.

        Passes ``enemy_bullet_in_flight`` into each tank's tick so the
        AI can gate its one-bullet-at-a-time fire decision. Since
        canonical Battlezone is one enemy at a time, a single bool
        covering "any enemy bullet alive in the field?" suffices.

        ``player_heading`` (radians, same convention as Camera.heading)
        is needed for the ``setavoid()`` cone-projection test.
        """
        from .tank_ai import tick_tank

        enemy_bullet_in_flight = any(
            b.owner == 'enemy' for b in self.bullets
        )

        for tank in self.tanks:
            tick_tank(
                tank, self,
                player_x, player_z, player_heading,
                enemy_bullet_in_flight=enemy_bullet_in_flight,
            )

    def step_bullets(
        self,
        player_x: float = 0.0,
        player_z: float = 0.0,
        player_radius: float = 6.0,
    ) -> tuple[float, list[Tank], list[Tank]]:
        """Advance all bullets one tick, removing any that have expired.

        Returns ``(player_damage, killed_tanks, damaged_tanks)``:
          - ``player_damage`` — total HP worth of enemy fire that connected
            with the player this tick (0.0 if none). The caller routes this to
            ``PlayerState.take_damage`` — the shell pool, not the engine, owns
            what a hit *means* (grace, lives, game over).
          - ``killed_tanks`` — Tanks whose ``hp`` reached 0 this tick, with
            their death positions intact for the fragment burst + score.
          - ``damaged_tanks`` — Tanks that took a non-lethal hit this tick
            (for hit feedback: a small fragment spit / the damage tint reading
            off ``hp_fraction``). A tank may appear here once per connecting
            round; it never also appears in ``killed_tanks`` the same tick.

        Five expiry conditions, checked in order per bullet:
          1. Range exhausted (``range_remaining <= 0``)
          2. Out of world bounds (the play square)
          3. Player bullet → hit a tank (subtracts ``damage``; kills at hp<=0)
          4. Enemy bullet → hit the player (accumulates ``damage``)
          5. Hit an obstacle (indestructible — bullet just despawns)

        Ownership-aware: player bullets only test against tanks; enemy
        bullets only test against the player. Both despawn on obstacles.
        A bullet that connects (lethal or not) is consumed — one round, one
        hit, then it's gone, same as before; only the *effect* changed from
        instant-kill to damage subtraction.

        Mutates ``self.bullets`` and ``self.tanks`` in place.
        """
        surviving_bullets: list[Bullet] = []
        killed_tanks: set[int] = set()
        killed_tank_list: list[Tank] = []
        damaged_tank_list: list[Tank] = []
        player_damage = 0.0

        for b in self.bullets:
            b.step()

            if b.range_remaining <= 0:
                continue
            if not self.in_bounds(b.x, b.z):
                continue

            if b.owner == 'player':
                # Player bullets damage tanks (destructible targets).
                hit_tank = self._bullet_hits_tank(b, killed_tanks)
                if hit_tank is not None:
                    hit_tank.hp -= b.damage
                    if hit_tank.hp <= 0:
                        killed_tanks.add(id(hit_tank))
                        killed_tank_list.append(hit_tank)
                    else:
                        damaged_tank_list.append(hit_tank)
                    continue  # the round is spent on the hit either way
            elif b.owner == 'enemy':
                # Enemy bullets hit the player.
                dx = b.x - player_x
                dz = b.z - player_z
                r = b.bounding_radius + player_radius
                if dx * dx + dz * dz < r * r:
                    player_damage += b.damage
                    continue

            # Both player and enemy bullets despawn on obstacles.
            if self._bullet_hits_obstacle(b):
                continue

            surviving_bullets.append(b)

        self.bullets = surviving_bullets
        if killed_tanks:
            self.tanks = [t for t in self.tanks if id(t) not in killed_tanks]

        return player_damage, killed_tank_list, damaged_tank_list

    def step_fragments(self) -> None:
        """Advance all fragments one tick, removing expired ones."""
        for f in self.fragments:
            f.step()
        self.fragments = [f for f in self.fragments if f.alive]

    def _bullet_hits_tank(self, bullet: Bullet,
                          already_killed: set[int]) -> Tank | None:
        """Return the first tank the bullet's bounding circle overlaps, or None.

        Skips tanks already killed earlier in the same tick (the
        ``already_killed`` set carries id()s, since a bullet that flew
        through tank A in tick N shouldn't also "hit" tank B if A and B
        overlap geometrically — but practically tanks don't overlap each
        other, so this is belt-and-suspenders).

        Returns the Tank itself rather than a bool so the caller can
        track which tanks died this tick — sets up the milestone-5b
        explosion-spawn hook cleanly.
        """
        for tank in self.tanks:
            if id(tank) in already_killed:
                continue
            r = bullet.bounding_radius + tank.bounding_radius
            dx = bullet.x - tank.x
            dz = bullet.z - tank.z
            if dx * dx + dz * dz < r * r:
                return tank
        return None

    def _bullet_hits_obstacle(self, bullet: Bullet) -> bool:
        """True if the bullet's bounding circle overlaps any obstacle's.

        Sweep is large enough to catch the largest in-play obstacle's
        bounding radius (cube ~26, with comfortable headroom).
        """
        sweep = bullet.bounding_radius + 200.0
        for obs in self.obstacles_near(bullet.x, bullet.z, sweep):
            r = bullet.bounding_radius + obs.bounding_radius
            dx = bullet.x - obs.x
            dz = bullet.z - obs.z
            if dx * dx + dz * dz < r * r:
                return True
        return False
