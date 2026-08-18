"""Level definitions.

A Level is a pure data object: the enemy path, per-wave enemy composition,
starting economy, and any extra non-buildable tiles. Grid, WaveManager, and
Game are all written generically against this shape, so adding a new level
is just adding a new Level(...) entry to LEVELS -- no changes needed to the
systems that consume it.
"""

from dataclasses import dataclass, field

from enemy import ENEMY_TYPES


@dataclass
class Level:
    id: int
    name: str
    waypoints_tiles: list  # [(col, row), ...] -- axis-aligned segments
    wave_specs: list  # [{enemy_type_name: count}, ...], one dict per wave
    starting_gold: int = 150
    starting_lives: int = 20
    blocked_cells: frozenset = field(default_factory=frozenset)  # extra non-buildable tiles

    def __post_init__(self):
        for wave_number, wave in enumerate(self.wave_specs, start=1):
            for enemy_name in wave:
                if enemy_name not in ENEMY_TYPES:
                    raise ValueError(
                        f"Level {self.id!r} wave {wave_number} references unknown "
                        f"enemy type {enemy_name!r} (known: {sorted(ENEMY_TYPES)})"
                    )


def generate_default_waves(total_waves, enemy_type="grunt", base_count=5, count_step=2):
    """Auto-generate a simple ramping wave list: wave N has
    base_count + count_step * (N - 1) enemies, all of one species.

    Handy for a new level that doesn't need mixed-species waves yet -- a
    level wanting a specific composition (like LEVEL_1_WAVE_SPECS below)
    just builds `wave_specs` directly instead of calling this helper.
    """
    return [
        {enemy_type: base_count + count_step * wave_index}
        for wave_index in range(total_waves)
    ]


LEVEL_1_WAYPOINTS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]

# Hand-authored rather than generate_default_waves(), so it can introduce
# the other species partway through: grunts alone to start, scouts joining
# at wave 3, tanks at wave 5, all three mixed and ramping after that.
LEVEL_1_WAVE_SPECS = [
    {"grunt": 5},
    {"grunt": 7},
    {"grunt": 6, "scout": 4},
    {"grunt": 8, "scout": 5},
    {"grunt": 6, "scout": 4, "tank": 2},
    {"grunt": 8, "scout": 6, "tank": 2},
    {"grunt": 8, "scout": 6, "tank": 3},
    {"grunt": 10, "scout": 8, "tank": 3},
    {"grunt": 10, "scout": 8, "tank": 4},
    {"grunt": 12, "scout": 10, "tank": 5},
]

LEVELS = {
    1: Level(
        id=1,
        name="Winding Road",
        waypoints_tiles=LEVEL_1_WAYPOINTS,
        wave_specs=LEVEL_1_WAVE_SPECS,
        starting_gold=150,
        starting_lives=20,
    ),
}
