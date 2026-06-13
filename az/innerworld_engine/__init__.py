"""
Wireframe Engine
----------------
A PyQt6/OpenGL engine for first-person wireframe dungeon crawlers.

Main components:
    - DungeonMap: Grid-based level structure
    - Wall: Wall segment geometry
    - BSPTree: Binary Space Partitioning for efficient rendering
    - Level: Data-driven level loading
    - create_test_dungeon: Sample dungeon generator
"""

from .dungeon import (
    DungeonMap,
    Wall,
    WallFace,
    CellType,
    CELL_SIZE,
    create_test_dungeon,
)

from .bsp import (
    BSPTree,
    BSPNode,
    build_bsp_from_dungeon,
)

from .level import (
    Level,
    Entity,
    load_level,
    parse_level,
    create_test_levels,
    save_test_levels,
)

__version__ = "0.4.0"
__all__ = [
    "DungeonMap",
    "Wall",
    "WallFace", 
    "CellType",
    "CELL_SIZE",
    "create_test_dungeon",
    "BSPTree",
    "BSPNode",
    "build_bsp_from_dungeon",
    "Level",
    "Entity",
    "load_level",
    "parse_level",
    "create_test_levels",
    "save_test_levels",
]
