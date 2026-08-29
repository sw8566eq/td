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

Waves are a level-wide timeline (add/remove wave is level-wide -- see
Editor), but each wave's *composition* is per-spawn: wave_specs is
[{spawn_cell: {enemy_type_name: count}}, ...], one dict per wave, so a
multi-spawn level can send a completely different mix of enemies out of
each spawn point in the same wave. A single-spawn level's wave still needs
that one spawn_cell key -- see _single_spawn_waves() for the common case.
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
    wave_specs: list  # [{spawn_cell: {enemy_type_name: count}}, ...], one dict per wave
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
            total = sum(count for composition in wave.values() for count in composition.values())
            if total <= 0:
                # A wave with nothing in it isn't a crash (WaveManager's
                # spawn queue just comes out empty and the wave immediately
                # counts as cleared), but it's never what a level actually
                # wants -- fail clearly here rather than let a silently
                # skipped wave slip through unnoticed (e.g. one left empty,
                # across every spawn, by the wave editor).
                raise ValueError(f"Level {self.id!r} wave {wave_number} has no enemies in it")
            for spawn_cell, composition in wave.items():
                if spawn_cell not in self.spawn_cells:
                    raise ValueError(
                        f"Level {self.id!r} wave {wave_number} references spawn cell "
                        f"{spawn_cell!r}, which isn't one of this level's spawn_cells"
                    )
                for enemy_name in composition:
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


def _single_spawn_waves(spawn_cell, flat_wave_specs):
    """Wrap a terse [{enemy_name: count}, ...] wave list -- one dict per
    wave, no spawn split -- under a single spawn_cell, the shape every
    hand-authored, single-spawn level below actually needs. Spelling out
    {spawn_cell: {...}} by hand for every wave would be needless
    repetition for what's overwhelmingly the common case; a level that
    genuinely wants a different mix per spawn just builds the nested
    wave_specs shape directly instead."""
    return [{spawn_cell: dict(wave)} for wave in flat_wave_specs]


def generate_default_waves(spawn_cell, total_waves, enemy_type="grunt", base_count=5, count_step=2):
    """Auto-generate a simple ramping wave list, all from one spawn: wave N
    has base_count + count_step * (N - 1) enemies, all of one species.

    Handy for a new level that doesn't need mixed-species or per-spawn
    composition yet -- a level wanting something more specific (like
    LEVEL_1_WAVE_SPECS below, or a genuine multi-spawn split) just builds
    `wave_specs` directly instead of calling this helper.
    """
    flat = [
        {enemy_type: base_count + count_step * wave_index}
        for wave_index in range(total_waves)
    ]
    return _single_spawn_waves(spawn_cell, flat)


# Hand-written levels are authored as a simple ordered corner list -- terser
# than spelling out every tile -- and converted to the shared path_cells/
# spawn_cells/goal_cells shape via pathing.path_cells_from_corners. A
# player's editor-painted level builds that same shape directly instead,
# with no corner list involved at all.
LEVEL_1_CORNERS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]

# Hand-authored rather than generate_default_waves(), so it can introduce
# the other species partway through and cap off with a boss: grunts alone
# to start, scouts joining wave 2, tanks wave 3, flying wave 4, and
# shielded alongside a single BossEnemy on the final wave -- every
# registered species gets introduced somewhere across this level's own
# waves (see test_levels.py's test_level_1_introduces_every_enemy_species_
# across_its_waves), since this is the first level a new player sees.
# Terse (unwrapped) form -- see _single_spawn_waves(), used below where
# this level's Level(...) is actually built, since this level (like every
# level below) has just the one spawn.
LEVEL_1_WAVE_SPECS = [
    {"grunt": 6},
    {"grunt": 8, "scout": 5},
    {"grunt": 8, "scout": 6, "tank": 3},
    {"grunt": 10, "scout": 8, "tank": 4, "flying": 4},
    {"grunt": 8, "scout": 6, "tank": 4, "shielded": 3, "boss": 1},
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
        wave_specs=_single_spawn_waves(LEVEL_1_CORNERS[0], LEVEL_1_WAVE_SPECS),
        starting_gold=150,
        starting_lives=20,
    ),
    2: Level(
        id=2,
        name="Serpentine Pass",
        path_cells=pathing.path_cells_from_corners(LEVEL_2_CORNERS),
        spawn_cells=(LEVEL_2_CORNERS[0],),
        goal_cells=(LEVEL_2_CORNERS[-1],),
        wave_specs=_single_spawn_waves(LEVEL_2_CORNERS[0], LEVEL_2_WAVE_SPECS),
        starting_gold=150,
        starting_lives=20,
    ),
}
