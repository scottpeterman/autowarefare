"""
Wireframe Engine - Dungeon Module
---------------------------------
Grid-based dungeon maps with wall rendering.

Coordinate system matches the core engine:
    -Z = North (forward)
    +X = East (right)
    +Y = Down
    
Grid cells are CELL_SIZE x CELL_SIZE world units.
"""

import math
from dataclasses import dataclass, field
from typing import Optional
from enum import IntEnum, auto


# Cell size in world units
CELL_SIZE = 50


class CellType(IntEnum):
    """What's in a dungeon cell."""
    SOLID = 0      # Impassable wall/rock
    FLOOR = 1      # Open floor, walkable
    DOOR = 2       # Door (can be open/closed)
    SECRET = 3     # Secret door (looks like wall)
    PIT = 4        # Pit/hole - can see through, can't walk
    STAIRS_UP = 5
    STAIRS_DOWN = 6


class WallFace(IntEnum):
    """Which face of a cell the wall is on."""
    NORTH = 0  # -Z face
    EAST = 1   # +X face
    SOUTH = 2  # +Z face
    WEST = 3   # -X face


@dataclass
class Wall:
    """
    A wall segment in the dungeon.
    
    Walls are thin 3D boxes defined by two floor points,
    a height, and a thickness.
    """
    # Floor endpoints of the FRONT face (x, z)
    x1: float
    z1: float
    x2: float
    z2: float
    
    # Vertical extent
    floor_y: float = 0.0      # Bottom (remember +Y is down)
    ceiling_y: float = -40.0  # Top (negative = up)
    
    # Wall thickness (extends backward from front face)
    thickness: float = 4.0
    
    # Which direction the wall faces (front face normal)
    face: WallFace = WallFace.NORTH
    
    # For doors/special walls
    is_door: bool = False
    is_secret: bool = False
    
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2
    
    def center_z(self) -> float:
        return (self.z1 + self.z2) / 2
    
    def distance_squared_to(self, px: float, pz: float) -> float:
        """Distance from point to wall center."""
        dx = self.center_x() - px
        dz = self.center_z() - pz
        return dx * dx + dz * dz
    
    def get_all_quads_with_normals(self) -> list[tuple[tuple, tuple]]:
        """
        Get all four vertical faces with their outward-facing normals.
        
        Returns list of (quad, normal) where:
            quad = 4 corner points (x, y, z)
            normal = (nx, ny, nz) unit vector pointing outward
            
        Note: A NORTH wall is on the north edge of a floor cell, so its
        front face points SOUTH (into the room), not north.
        """
        # Calculate back face offset based on facing direction
        # The "face" direction indicates which edge of the cell the wall is on
        # Front face points INTO the room (opposite of face direction)
        if self.face == WallFace.NORTH:
            dx, dz = 0, self.thickness
            front_normal = (0, 0, 1)    # Points south (into room)
            back_normal = (0, 0, -1)    # Points north (into rock)
            left_normal = (-1, 0, 0)
            right_normal = (1, 0, 0)
        elif self.face == WallFace.SOUTH:
            dx, dz = 0, -self.thickness
            front_normal = (0, 0, -1)   # Points north (into room)
            back_normal = (0, 0, 1)     # Points south (into rock)
            left_normal = (1, 0, 0)
            right_normal = (-1, 0, 0)
        elif self.face == WallFace.EAST:
            dx, dz = -self.thickness, 0
            front_normal = (-1, 0, 0)   # Points west (into room)
            back_normal = (1, 0, 0)     # Points east (into rock)
            left_normal = (0, 0, -1)
            right_normal = (0, 0, 1)
        elif self.face == WallFace.WEST:
            dx, dz = self.thickness, 0
            front_normal = (1, 0, 0)    # Points east (into room)
            back_normal = (-1, 0, 0)    # Points west (into rock)
            left_normal = (0, 0, 1)
            right_normal = (0, 0, -1)
        else:
            dx, dz = 0, 0
            front_normal = back_normal = left_normal = right_normal = (0, 1, 0)
        
        # Front face corners
        f_bl = (self.x1, self.floor_y, self.z1)
        f_br = (self.x2, self.floor_y, self.z2)
        f_tr = (self.x2, self.ceiling_y, self.z2)
        f_tl = (self.x1, self.ceiling_y, self.z1)
        
        # Back face corners
        b_bl = (self.x1 + dx, self.floor_y, self.z1 + dz)
        b_br = (self.x2 + dx, self.floor_y, self.z2 + dz)
        b_tr = (self.x2 + dx, self.ceiling_y, self.z2 + dz)
        b_tl = (self.x1 + dx, self.ceiling_y, self.z1 + dz)
        
        quads_with_normals = [
            ((f_bl, f_br, f_tr, f_tl), front_normal),  # Front face
            ((b_br, b_bl, b_tl, b_tr), back_normal),   # Back face
            ((f_bl, b_bl, b_tl, f_tl), left_normal),   # Left end cap
            ((f_br, f_tr, b_tr, b_br), right_normal),  # Right end cap
        ]
        
        return quads_with_normals
    
    def get_all_quads(self) -> list[tuple[tuple[float, float, float], ...]]:
        """
        Get all four vertical faces of the wall box as quads.
        
        Returns list of 4-tuples, each containing 4 corner points (x, y, z).
        Order: front, back, left-end, right-end
        """
        # For backward compatibility, return just the quads without normals
        return [quad for quad, normal in self.get_all_quads_with_normals()]
    
    def is_facing_point(self, px: float, pz: float) -> bool:
        """
        Check if wall's front face is toward a point.
        
        With thick walls, we always return True since the wall
        box has multiple faces that may be visible from any angle.
        """
        # For thick walls, always potentially visible
        # (individual quad culling happens at render time)
        return True


@dataclass 
class DungeonMap:
    """
    Grid-based dungeon map.
    
    The map is a 2D grid where each cell can be solid, floor, door, etc.
    Walls are automatically generated at the boundaries between 
    floor and solid cells.
    """
    width: int   # Grid width (X axis)
    height: int  # Grid height (Z axis)
    
    # The grid - row-major, so grid[z][x]
    cells: list[list[CellType]] = field(default_factory=list)
    
    # Generated walls - flat list (legacy)
    walls: list[Wall] = field(default_factory=list)
    
    # Walls organized by cell - dict of (gx, gz) -> list of walls
    cell_walls: dict[tuple[int, int], list[Wall]] = field(default_factory=dict)
    
    # Wall height settings
    wall_height: float = 60.0
    
    def __post_init__(self):
        """Initialize empty grid if not provided."""
        if not self.cells:
            self.cells = [
                [CellType.SOLID for _ in range(self.width)]
                for _ in range(self.height)
            ]
    
    def get_cell(self, gx: int, gz: int) -> CellType:
        """Get cell type at grid coordinates."""
        if 0 <= gx < self.width and 0 <= gz < self.height:
            return self.cells[gz][gx]
        return CellType.SOLID  # Out of bounds = solid
    
    def set_cell(self, gx: int, gz: int, cell_type: CellType):
        """Set cell type at grid coordinates."""
        if 0 <= gx < self.width and 0 <= gz < self.height:
            self.cells[gz][gx] = cell_type
    
    def is_walkable(self, gx: int, gz: int) -> bool:
        """Check if a cell can be walked through."""
        cell = self.get_cell(gx, gz)
        return cell in (CellType.FLOOR, CellType.DOOR, 
                       CellType.STAIRS_UP, CellType.STAIRS_DOWN)
    
    def is_solid(self, gx: int, gz: int) -> bool:
        """Check if a cell blocks movement and sight."""
        cell = self.get_cell(gx, gz)
        return cell in (CellType.SOLID, CellType.SECRET)
    
    def world_to_grid(self, wx: float, wz: float) -> tuple[int, int]:
        """Convert world coordinates to grid cell."""
        gx = int(wx / CELL_SIZE + self.width / 2)
        gz = int(wz / CELL_SIZE + self.height / 2)
        return gx, gz
    
    def grid_to_world(self, gx: int, gz: int) -> tuple[float, float]:
        """Convert grid cell to world coordinates (cell center)."""
        wx = (gx - self.width / 2 + 0.5) * CELL_SIZE
        wz = (gz - self.height / 2 + 0.5) * CELL_SIZE
        return wx, wz
    
    def generate_walls(self):
        """
        Generate wall segments from the grid.
        
        A wall is created wherever a floor cell meets a solid cell.
        Walls are stored both in a flat list and organized by cell.
        """
        self.walls.clear()
        self.cell_walls.clear()
        
        for gz in range(self.height):
            for gx in range(self.width):
                if not self.is_walkable(gx, gz):
                    continue
                
                # Initialize wall list for this cell
                self.cell_walls[(gx, gz)] = []
                
                # Cell center in world coords
                cx, cz = self.grid_to_world(gx, gz)
                half = CELL_SIZE / 2
                
                # Check each neighbor - if solid, add a wall
                
                # North wall (-Z direction)
                if self.is_solid(gx, gz - 1):
                    wall = Wall(
                        x1=cx - half, z1=cz - half,
                        x2=cx + half, z2=cz - half,
                        ceiling_y=-self.wall_height,
                        face=WallFace.NORTH
                    )
                    self.walls.append(wall)
                    self.cell_walls[(gx, gz)].append(wall)
                
                # South wall (+Z direction)
                if self.is_solid(gx, gz + 1):
                    wall = Wall(
                        x1=cx + half, z1=cz + half,
                        x2=cx - half, z2=cz + half,
                        ceiling_y=-self.wall_height,
                        face=WallFace.SOUTH
                    )
                    self.walls.append(wall)
                    self.cell_walls[(gx, gz)].append(wall)
                
                # East wall (+X direction)
                if self.is_solid(gx + 1, gz):
                    wall = Wall(
                        x1=cx + half, z1=cz - half,
                        x2=cx + half, z2=cz + half,
                        ceiling_y=-self.wall_height,
                        face=WallFace.EAST
                    )
                    self.walls.append(wall)
                    self.cell_walls[(gx, gz)].append(wall)
                
                # West wall (-X direction)
                if self.is_solid(gx - 1, gz):
                    wall = Wall(
                        x1=cx - half, z1=cz + half,
                        x2=cx - half, z2=cz - half,
                        ceiling_y=-self.wall_height,
                        face=WallFace.WEST
                    )
                    self.walls.append(wall)
                    self.cell_walls[(gx, gz)].append(wall)
    
    def carve_room(self, x1: int, z1: int, x2: int, z2: int):
        """Carve a rectangular room (set cells to FLOOR)."""
        for gz in range(min(z1, z2), max(z1, z2) + 1):
            for gx in range(min(x1, x2), max(x1, x2) + 1):
                self.set_cell(gx, gz, CellType.FLOOR)
    
    def carve_corridor(self, x1: int, z1: int, x2: int, z2: int):
        """Carve an L-shaped corridor between two points."""
        # Horizontal segment
        for gx in range(min(x1, x2), max(x1, x2) + 1):
            self.set_cell(gx, z1, CellType.FLOOR)
        
        # Vertical segment
        for gz in range(min(z1, z2), max(z1, z2) + 1):
            self.set_cell(x2, gz, CellType.FLOOR)


def create_test_dungeon() -> DungeonMap:
    """Create a simple test dungeon for development."""
    dungeon = DungeonMap(width=20, height=20)
    
    # Starting room (center of map)
    dungeon.carve_room(8, 8, 11, 11)
    
    # North corridor
    dungeon.carve_corridor(9, 8, 9, 4)
    dungeon.carve_room(8, 3, 11, 5)  # Room at end
    
    # East corridor
    dungeon.carve_corridor(11, 9, 15, 9)
    dungeon.carve_room(14, 8, 17, 11)  # Room at end
    
    # South corridor with a turn
    dungeon.carve_corridor(10, 11, 10, 15)
    dungeon.carve_corridor(10, 15, 5, 15)
    dungeon.carve_room(3, 14, 6, 17)  # Room at end
    
    # West corridor
    dungeon.carve_corridor(8, 10, 4, 10)
    dungeon.carve_room(2, 9, 5, 12)  # Room at end
    
    # Generate walls from the carved spaces
    dungeon.generate_walls()
    
    return dungeon
