"""Level definitions.

A Level is a pure data object: the enemy path (a painted set of cells plus
explicit spawn/goal cells), per-wave enemy composition, starting economy,
and any extra non-buildable tiles. Grid, WaveManager, and Game are all
written generically against this shape, so adding a new level -- whether
hand-authored below or painted in the map editor -- is just adding a new
Level(...) entry to LEVELS (or, for a player's saved custom level, a file
on disk -- see persistence.py) -- no changes needed to the systems that
consume it.

The path is a *set of painted cells*, not a single ordered route: it can
branch (one lane fanning out into several) and merge (several spawns
converging on shared lanes), same as anything the map editor's freeform
brush can produce -- see pathing.py for the shape's rules (must form a
forest; see its module docstring for why) and how a concrete per-enemy
route gets sampled out of it at spawn time.
"""

from dataclasses import dataclass, field

import pathing
import settings
from enemy import ENEMY_TYPES


@dataclass
class Level:
    id: object  # int for a built-in registry entry, str slug for a saved custom level
    name: str
    path_cells: frozenset  # every tile the path covers -- {(col, row), ...}
    spawn_cells: tuple  # >=1 of path_cells enemies start on
    goal_cells: tuple  # >=1 of path_cells; reaching one costs a life
    wave_specs: list  # [{enemy_type_name: count}, ...], one dict per wave
    starting_gold: int = 150
    starting_lives: int = 20
    blocked_cells: frozenset = field(default_factory=frozenset)  # extra non-buildable tiles
    # Per-branch routing weight, keyed (from_cell, to_cell); a pair missing
    # here defaults to 1.0 (uniform) -- see pathing.sample_route.
    branch_weights: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.wave_specs:
            # WaveManager assumes at least one wave -- _begin_wave() indexes
            # wave_specs[0] unconditionally the moment the first wave starts,
            # so an empty list would crash deep inside WaveManager instead of
            # failing clearly here at Level-definition time.
            raise ValueError(f"Level {self.id!r} has no waves in wave_specs")
        for wave_number, wave in enumerate(self.wave_specs, start=1):
            if sum(wave.values()) <= 0:
                # A wave with nothing in it isn't a crash (WaveManager's
                # spawn queue just comes out empty and the wave immediately
                # counts as cleared), but it's never what a level actually
                # wants -- fail clearly here rather than let a silently
                # skipped wave slip through unnoticed (e.g. one left empty
                # by the wave editor).
                raise ValueError(f"Level {self.id!r} wave {wave_number} has no enemies in it")
            for enemy_name in wave:
                if enemy_name not in ENEMY_TYPES:
                    raise ValueError(
                        f"Level {self.id!r} wave {wave_number} references unknown "
                        f"enemy type {enemy_name!r} (known: {sorted(ENEMY_TYPES)})"
                    )

        problems = pathing.validate_topology(
            self.path_cells, self.spawn_cells, self.goal_cells,
            settings.GRID_COLS, settings.GRID_ROWS,
        )
        if problems:
            raise ValueError(f"Level {self.id!r} has an invalid path: {'; '.join(problems)}")


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


# Hand-written levels are authored as a simple ordered corner list -- terser
# than spelling out every tile -- and converted to the shared path_cells/
# spawn_cells/goal_cells shape via pathing.path_cells_from_corners. A
# player's editor-painted level builds that same shape directly instead,
# with no corner list involved at all.
LEVEL_1_CORNERS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]

# Hand-authored rather than generate_default_waves(), so it can introduce
# the other species partway through and cap off with a boss: grunts alone
# to start, scouts joining wave 2, tanks wave 3, and a single BossEnemy
# alongside a smaller support wave on the final wave.
LEVEL_1_WAVE_SPECS = [
    {"grunt": 6},
    {"grunt": 8, "scout": 5},
    {"grunt": 8, "scout": 6, "tank": 3},
    {"grunt": 10, "scout": 8, "tank": 4},
    {"grunt": 8, "scout": 6, "tank": 4, "boss": 1},
]

LEVEL_2_CORNERS = [(0, 1), (6, 1), (6, 6), (10, 6), (10, 2), (14, 2)]

# A tighter, more switchback-heavy path than level 1 -- slightly larger
# waves throughout to read as "the next level up."
LEVEL_2_WAVE_SPECS = [
    {"grunt": 7},
    {"grunt": 8, "scout": 6},
    {"grunt": 9, "scout": 7, "tank": 4},
    {"grunt": 11, "scout": 9, "tank": 5},
    {"grunt": 9, "scout": 7, "tank": 5, "boss": 1},
]

LEVELS = {
    1: Level(
        id=1,
        name="Winding Road",
        path_cells=pathing.path_cells_from_corners(LEVEL_1_CORNERS),
        spawn_cells=(LEVEL_1_CORNERS[0],),
        goal_cells=(LEVEL_1_CORNERS[-1],),
        wave_specs=LEVEL_1_WAVE_SPECS,
        starting_gold=150,
        starting_lives=20,
    ),
    2: Level(
        id=2,
        name="Serpentine Pass",
        path_cells=pathing.path_cells_from_corners(LEVEL_2_CORNERS),
        spawn_cells=(LEVEL_2_CORNERS[0],),
        goal_cells=(LEVEL_2_CORNERS[-1],),
        wave_specs=LEVEL_2_WAVE_SPECS,
        starting_gold=150,
        starting_lives=20,
    ),
}
