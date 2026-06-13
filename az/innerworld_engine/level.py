"""
Level Loader
------------
Data-driven level loading from ASCII map files.

File format:
    name: Level Name Here
    next: level2.map
    ---
    ####################
    #@.......#....K....#
    #........D.........#
    #........#....E....#
    ####################

Legend:
    # = Solid wall
    . = Floor
    @ = Player start
    D = Door
    K = Key
    E = Enemy (skeleton)
    G = Ghost enemy
    T = Treasure
    U = Stairs up
    V = Stairs down
    S = Secret door (looks like wall, can open)
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from .dungeon import DungeonMap, CellType


@dataclass
class Entity:
    """An entity in the level (enemy, item, etc.)"""
    type: str       # 'key', 'skeleton', 'ghost', 'zombie', 'treasure', 'stairs_up', 'stairs_down'
    gx: int         # Grid X position
    gz: int         # Grid Z position
    properties: dict = field(default_factory=dict)  # Extra data (color, patrol route, etc.)


@dataclass
class Level:
    """A complete game level."""
    name: str
    dungeon: DungeonMap
    player_start: tuple[int, int]  # Grid coordinates
    entities: list[Entity] = field(default_factory=list)
    next_level: Optional[str] = None  # Filename of next level
    prev_level: Optional[str] = None  # Filename of previous level

    def get_entities_by_type(self, entity_type: str) -> list[Entity]:
        """Get all entities of a specific type."""
        return [e for e in self.entities if e.type == entity_type]

    def get_entity_at(self, gx: int, gz: int) -> Optional[Entity]:
        """Get entity at a grid position."""
        for e in self.entities:
            if e.gx == gx and e.gz == gz:
                return e
        return None

    def remove_entity(self, entity: Entity):
        """Remove an entity (e.g., when collected or killed)."""
        if entity in self.entities:
            self.entities.remove(entity)


# Character mappings for the ASCII map
CELL_CHARS = {
    '#': CellType.SOLID,
    '.': CellType.FLOOR,
    '@': CellType.FLOOR,    # Player start (also floor)
    'D': CellType.DOOR,
    'L': CellType.DOOR,     # Locked door (also door cell)
    'S': CellType.SECRET,
    'U': CellType.STAIRS_UP,
    'V': CellType.STAIRS_DOWN,
    '<': CellType.STAIRS_UP,   # Alternate stairs up
    '>': CellType.STAIRS_DOWN, # Alternate stairs down
    '~': CellType.PIT,         # Pit
    'K': CellType.FLOOR,    # Key (entity on floor)
    'k': CellType.FLOOR,    # Silver key (entity on floor)
    'E': CellType.FLOOR,    # Enemy / skeleton (entity on floor)
    'G': CellType.FLOOR,    # Ghost (entity on floor)
    'Z': CellType.FLOOR,    # Zombie (entity on floor)
    'T': CellType.FLOOR,    # Treasure (entity on floor)
    ' ': CellType.SOLID,    # Whitespace = solid
}

ENTITY_CHARS = {
    'K': 'key',
    'k': 'key_silver',
    'E': 'skeleton',
    'G': 'ghost',
    'Z': 'zombie',
    'T': 'treasure',
    'L': 'door_locked',
    'D': 'door',
    '<': 'stairs_up',
    '>': 'stairs_down',
    'U': 'stairs_up',
    'V': 'stairs_down',
}


def load_level(filepath: str) -> Level:
    """
    Load a level from an ASCII map file.

    Args:
        filepath: Path to the .map file

    Returns:
        Level object ready to play
    """
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"Level file not found: {filepath}")

    with open(path, 'r') as f:
        content = f.read()

    return parse_level(content, path.stem)


def parse_level(content: str, default_name: str = "Unnamed Level") -> Level:
    """
    Parse level content from a string.

    Args:
        content: The full file content
        default_name: Name to use if not specified in header

    Returns:
        Level object
    """
    lines = content.strip().split('\n')

    # Parse header
    name = default_name
    next_level = None
    prev_level = None
    map_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped == '---':
            map_start = i + 1
            break
        elif stripped.startswith('name:'):
            name = stripped[5:].strip()
        elif stripped.startswith('next:'):
            next_level = stripped[5:].strip()
        elif stripped.startswith('prev:'):
            prev_level = stripped[5:].strip()
        else:
            # No header, start from beginning
            map_start = 0
            break

    # Parse map
    map_lines = lines[map_start:]

    # Remove empty lines
    map_lines = [l for l in map_lines if l.strip()]

    if not map_lines:
        raise ValueError("No map data found in level file")

    # Determine dimensions
    height = len(map_lines)
    width = max(len(line) for line in map_lines)

    # Create dungeon
    dungeon = DungeonMap(width=width, height=height)

    # Parse cells and find entities/player
    player_start = (width // 2, height // 2)  # Default to center
    entities = []

    for gz, line in enumerate(map_lines):
        # Pad line to full width
        line = line.ljust(width)

        for gx, char in enumerate(line):
            # Set cell type
            cell_type = CELL_CHARS.get(char, CellType.SOLID)
            dungeon.set_cell(gx, gz, cell_type)

            # Check for player start
            if char == '@':
                player_start = (gx, gz)

            # Check for entities
            if char in ENTITY_CHARS:
                entity = Entity(
                    type=ENTITY_CHARS[char],
                    gx=gx,
                    gz=gz
                )
                entities.append(entity)

    # Generate wall geometry
    dungeon.generate_walls()

    return Level(
        name=name,
        dungeon=dungeon,
        player_start=player_start,
        entities=entities,
        next_level=next_level,
        prev_level=prev_level
    )


def create_test_levels() -> dict[str, str]:
    """
    Create a set of test level strings.
    Returns dict of filename -> content.
    """
    levels = {}

    levels['level1.map'] = """\
name: The Dungeon Entrance
next: level2.map
---
####################
#@.......#.........#
#........#.........#
#........#....K....#
#........#.........#
####D###############
#........#.........#
#...T....#....E....#
#........#.........#
#........D.........#
#........#.........#
####################
"""

    levels['level2.map'] = """\
name: The Dark Corridors
next: level3.map
---
####################
#..................#
#.###.########.###.#
#.#@...#....#....#.#
#.#....D....D....#.#
#.#....#....#....#.#
#.###.##.##.##.###.#
#......#.KK.#......#
#.###.##.##.##.###.#
#.#....#....#....#.#
#.#....D....D....#.#
#.#..E.#....#.E..#.#
#.###.########.###.#
#.........V........#
####################
"""

    levels['level3.map'] = """\
name: The Treasure Vault
---
####################
####################
###....TTTTTT....###
###..T........T..###
###.T..........T.###
###T....G..G....T###
###T............T###
###T....@.......T###
###.T..........T.###
###..T........T..###
###....TTTTTT....###
###......U.......###
####################
####################
####################
"""

    return levels


def save_test_levels(directory: str = "."):
    """Save test levels to files."""
    levels = create_test_levels()
    path = Path(directory)
    path.mkdir(exist_ok=True)

    for filename, content in levels.items():
        filepath = path / filename
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Created: {filepath}")