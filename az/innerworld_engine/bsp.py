"""
Wireframe Engine - BSP Tree
---------------------------
Binary Space Partitioning for correct draw order without runtime sorting.

How it works:
    1. BUILD TIME: Recursively partition walls using splitting planes
    2. RENDER TIME: Traverse tree based on camera position
       - Visit far side first, then splitter, then near side
       - Guarantees back-to-front order (or front-to-back if reversed)

This is the algorithm Doom used. For a grid dungeon it might be overkill,
but it's mathematically correct and eliminates all sorting artifacts.

Coordinate system matches the engine:
    -Z = North (forward)
    +X = East (right)
"""

from dataclasses import dataclass, field
from typing import Optional, Iterator
from enum import IntEnum
import math

from .dungeon import Wall, WallFace


class Side(IntEnum):
    """Which side of a splitting plane a point/wall is on."""
    FRONT = 1   # In front of the plane (normal direction)
    BACK = -1   # Behind the plane
    ON = 0      # On the plane (within epsilon)
    SPANNING = 2  # Wall crosses the plane


# Tolerance for floating point comparisons
EPSILON = 0.001


@dataclass
class BSPNode:
    """
    A node in the BSP tree.

    Each node has:
        - A splitting wall (the partition)
        - Front subtree (walls in front of splitter)
        - Back subtree (walls behind splitter)
        - Coplanar walls (walls on the same plane as splitter)
    """
    splitter: Wall
    front: Optional['BSPNode'] = None
    back: Optional['BSPNode'] = None
    coplanar: list[Wall] = field(default_factory=list)


@dataclass
class SplitLine:
    """
    A 2D line used for partitioning (we only care about XZ plane).

    Defined by a point (x, z) and a normal (nx, nz).
    The "front" side is where the normal points.
    """
    x: float      # Point on line
    z: float
    nx: float     # Normal direction (unit vector)
    nz: float

    @classmethod
    def from_wall(cls, wall: Wall) -> 'SplitLine':
        """
        Create a split line from a wall's front face.

        The line runs along the wall, and the normal points
        in the direction the wall faces (into the room).
        """
        # Wall endpoints
        x1, z1 = wall.x1, wall.z1
        x2, z2 = wall.x2, wall.z2

        # Direction along wall
        dx = x2 - x1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dz * dz)

        if length < EPSILON:
            # Degenerate wall - use face direction
            if wall.face == WallFace.NORTH:
                return cls(x1, z1, 0, 1)  # Points south
            elif wall.face == WallFace.SOUTH:
                return cls(x1, z1, 0, -1)  # Points north
            elif wall.face == WallFace.EAST:
                return cls(x1, z1, -1, 0)  # Points west
            else:  # WEST
                return cls(x1, z1, 1, 0)  # Points east

        # Normal is perpendicular to wall direction
        # Rotate direction 90 degrees: (dx, dz) -> (-dz, dx) for left normal
        # But we want the normal to match the wall's face direction

        # For a NORTH wall (on north edge), front faces SOUTH (+Z)
        # For a SOUTH wall, front faces NORTH (-Z)
        # etc.

        if wall.face == WallFace.NORTH:
            nx, nz = 0, 1
        elif wall.face == WallFace.SOUTH:
            nx, nz = 0, -1
        elif wall.face == WallFace.EAST:
            nx, nz = -1, 0
        elif wall.face == WallFace.WEST:
            nx, nz = 1, 0
        else:
            # Fallback: compute from geometry
            nx = -dz / length
            nz = dx / length

        return cls(x1, z1, nx, nz)

    def point_side(self, px: float, pz: float) -> Side:
        """
        Determine which side of the line a point is on.

        Returns FRONT if point is in normal direction, BACK if opposite.
        """
        # Vector from line point to test point
        dx = px - self.x
        dz = pz - self.z

        # Dot product with normal
        dot = dx * self.nx + dz * self.nz

        if dot > EPSILON:
            return Side.FRONT
        elif dot < -EPSILON:
            return Side.BACK
        else:
            return Side.ON

    def wall_side(self, wall: Wall) -> Side:
        """
        Determine which side of the line a wall is on.

        A wall can be FRONT, BACK, ON, or SPANNING (crosses the line).
        """
        side1 = self.point_side(wall.x1, wall.z1)
        side2 = self.point_side(wall.x2, wall.z2)

        if side1 == Side.ON and side2 == Side.ON:
            return Side.ON
        elif side1 == Side.ON:
            return side2
        elif side2 == Side.ON:
            return side1
        elif side1 == side2:
            return side1
        else:
            return Side.SPANNING

    def split_wall(self, wall: Wall) -> tuple[Optional[Wall], Optional[Wall]]:
        """
        Split a wall that spans this line.

        Returns (front_piece, back_piece).
        """
        # Find intersection point
        # Line equation: (p - line_point) · normal = 0
        # Wall parametric: p = p1 + t * (p2 - p1), t in [0, 1]

        dx = wall.x2 - wall.x1
        dz = wall.z2 - wall.z1

        # Denominator: direction · normal
        denom = dx * self.nx + dz * self.nz

        if abs(denom) < EPSILON:
            # Wall is parallel to line - shouldn't happen if SPANNING
            return None, None

        # Numerator: (line_point - wall_start) · normal
        num = (self.x - wall.x1) * self.nx + (self.z - wall.z1) * self.nz
        t = num / denom

        # Intersection point
        ix = wall.x1 + t * dx
        iz = wall.z1 + t * dz

        # Determine which endpoint is on which side
        side1 = self.point_side(wall.x1, wall.z1)

        if side1 == Side.FRONT or side1 == Side.ON:
            # p1 is front, p2 is back
            front_wall = Wall(
                x1=wall.x1, z1=wall.z1,
                x2=ix, z2=iz,
                floor_y=wall.floor_y,
                ceiling_y=wall.ceiling_y,
                thickness=wall.thickness,
                face=wall.face,
                is_door=wall.is_door,
                is_secret=wall.is_secret
            )
            back_wall = Wall(
                x1=ix, z1=iz,
                x2=wall.x2, z2=wall.z2,
                floor_y=wall.floor_y,
                ceiling_y=wall.ceiling_y,
                thickness=wall.thickness,
                face=wall.face,
                is_door=wall.is_door,
                is_secret=wall.is_secret
            )
        else:
            # p1 is back, p2 is front
            back_wall = Wall(
                x1=wall.x1, z1=wall.z1,
                x2=ix, z2=iz,
                floor_y=wall.floor_y,
                ceiling_y=wall.ceiling_y,
                thickness=wall.thickness,
                face=wall.face,
                is_door=wall.is_door,
                is_secret=wall.is_secret
            )
            front_wall = Wall(
                x1=ix, z1=iz,
                x2=wall.x2, z2=wall.z2,
                floor_y=wall.floor_y,
                ceiling_y=wall.ceiling_y,
                thickness=wall.thickness,
                face=wall.face,
                is_door=wall.is_door,
                is_secret=wall.is_secret
            )

        return front_wall, back_wall


class BSPTree:
    """
    Binary Space Partition tree for a set of walls.

    Usage:
        tree = BSPTree(dungeon.walls)
        tree.build()

        # Each frame:
        for wall in tree.traverse_back_to_front(camera.x, camera.z):
            render(wall)
    """

    def __init__(self, walls: list[Wall]):
        self.walls = walls.copy()
        self.root: Optional[BSPNode] = None
        self.stats = {
            'nodes': 0,
            'splits': 0,
            'depth': 0
        }

    def build(self):
        """Build the BSP tree from the wall list."""
        self.stats = {'nodes': 0, 'splits': 0, 'depth': 0}
        self.root = self._build_recursive(self.walls, 0)

    def _build_recursive(self, walls: list[Wall], depth: int) -> Optional[BSPNode]:
        """Recursively build BSP tree."""
        if not walls:
            return None

        self.stats['depth'] = max(self.stats['depth'], depth)

        # Choose a splitter - for simplicity, just use the first wall
        # A smarter heuristic would minimize splits
        splitter = self._choose_splitter(walls)
        split_line = SplitLine.from_wall(splitter)

        front_walls = []
        back_walls = []
        coplanar = [splitter]

        for wall in walls:
            if wall is splitter:
                continue

            side = split_line.wall_side(wall)

            if side == Side.FRONT:
                front_walls.append(wall)
            elif side == Side.BACK:
                back_walls.append(wall)
            elif side == Side.ON:
                coplanar.append(wall)
            else:  # SPANNING
                front_piece, back_piece = split_line.split_wall(wall)
                if front_piece:
                    front_walls.append(front_piece)
                if back_piece:
                    back_walls.append(back_piece)
                self.stats['splits'] += 1

        self.stats['nodes'] += 1

        node = BSPNode(
            splitter=splitter,
            coplanar=coplanar,
            front=self._build_recursive(front_walls, depth + 1),
            back=self._build_recursive(back_walls, depth + 1)
        )

        return node

    def _choose_splitter(self, walls: list[Wall]) -> Wall:
        """
        Choose the best wall to use as a splitter.

        A good splitter:
            - Balances the tree (similar # of walls on each side)
            - Minimizes splits (walls crossing the plane)

        For now, we use a simple heuristic: pick the wall that
        causes the fewest splits, with balance as tiebreaker.
        """
        if len(walls) <= 3:
            return walls[0]

        best_wall = walls[0]
        best_score = float('inf')

        # Only test a subset for performance
        candidates = walls[:min(10, len(walls))]

        for candidate in candidates:
            split_line = SplitLine.from_wall(candidate)
            front_count = 0
            back_count = 0
            split_count = 0

            for wall in walls:
                if wall is candidate:
                    continue

                side = split_line.wall_side(wall)
                if side == Side.FRONT:
                    front_count += 1
                elif side == Side.BACK:
                    back_count += 1
                elif side == Side.SPANNING:
                    split_count += 1

            # Score: splits are very bad, imbalance is less bad
            imbalance = abs(front_count - back_count)
            score = split_count * 10 + imbalance

            if score < best_score:
                best_score = score
                best_wall = candidate

        return best_wall

    def traverse_back_to_front(self, px: float, pz: float) -> Iterator[Wall]:
        """
        Traverse tree yielding walls from back to front relative to point.

        This is the classic BSP render order for painter's algorithm.
        Far things first, near things last (so they paint over).
        """
        if self.root is None:
            return

        yield from self._traverse_b2f(self.root, px, pz)

    def _traverse_b2f(self, node: BSPNode, px: float, pz: float) -> Iterator[Wall]:
        """Back-to-front traversal helper."""
        split_line = SplitLine.from_wall(node.splitter)
        side = split_line.point_side(px, pz)

        if side == Side.FRONT:
            # Camera is in front - draw back first, then splitter, then front
            if node.back:
                yield from self._traverse_b2f(node.back, px, pz)
            for wall in node.coplanar:
                yield wall
            if node.front:
                yield from self._traverse_b2f(node.front, px, pz)
        else:
            # Camera is behind or on - draw front first, then splitter, then back
            if node.front:
                yield from self._traverse_b2f(node.front, px, pz)
            for wall in node.coplanar:
                yield wall
            if node.back:
                yield from self._traverse_b2f(node.back, px, pz)

    def traverse_front_to_back(self, px: float, pz: float) -> Iterator[Wall]:
        """
        Traverse tree yielding walls from front to back.

        Useful for early-out rendering with a coverage buffer,
        or for collision detection (check nearest first).
        """
        if self.root is None:
            return

        yield from self._traverse_f2b(self.root, px, pz)

    def _traverse_f2b(self, node: BSPNode, px: float, pz: float) -> Iterator[Wall]:
        """Front-to-back traversal helper."""
        split_line = SplitLine.from_wall(node.splitter)
        side = split_line.point_side(px, pz)

        if side == Side.FRONT:
            # Camera is in front - draw front first
            if node.front:
                yield from self._traverse_f2b(node.front, px, pz)
            for wall in node.coplanar:
                yield wall
            if node.back:
                yield from self._traverse_f2b(node.back, px, pz)
        else:
            # Camera is behind
            if node.back:
                yield from self._traverse_f2b(node.back, px, pz)
            for wall in node.coplanar:
                yield wall
            if node.front:
                yield from self._traverse_f2b(node.front, px, pz)

    def get_stats(self) -> dict:
        """Return build statistics."""
        return self.stats.copy()


def build_bsp_from_dungeon(dungeon) -> BSPTree:
    """
    Convenience function to build a BSP tree from a DungeonMap.

    Args:
        dungeon: A DungeonMap with generated walls

    Returns:
        A built BSP tree ready for traversal
    """
    tree = BSPTree(dungeon.walls)
    tree.build()
    return tree