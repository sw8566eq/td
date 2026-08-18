"""Level definitions.

A Level is a pure data object: the enemy path, per-wave enemy composition,
starting economy, and any extra non-buildable tiles. Grid, WaveManager, and
Game are all written generically against this shape, so adding a new level
is just adding a new Level(...) entry to LEVELS -- no changes needed to the
systems that consume it.
"""

from dataclasses import dataclass, field

import settings
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

    This is what level 1 uses so the MVP doesn't require hand-authoring 10
    waves. A hand-authored level with a specific, mixed-species wave list
    can just build `wave_specs` directly instead of calling this helper.
    """
    return [
        {enemy_type: base_count + count_step * wave_index}
        for wave_index in range(total_waves)
    ]


LEVEL_1_WAYPOINTS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]

LEVELS = {
    1: Level(
        id=1,
        name="Winding Road",
        waypoints_tiles=LEVEL_1_WAYPOINTS,
        wave_specs=generate_default_waves(total_waves=settings.TOTAL_WAVES),
        starting_gold=150,
        starting_lives=20,
    ),
}
