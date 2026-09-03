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


def _corridor_level(level_id, name, corners, wave_specs, starting_gold=150, starting_lives=20):
    """Build a Level for the shape every hand-authored level below except
    Confluence shares: a single spawn (the corner list's first corner), a
    single goal (its last), and a path traced straight from the corners.
    `wave_specs` must already be in Level's own nested {spawn_cell: {...}}
    shape -- callers wrap a terse per-wave list with _single_spawn_waves()
    themselves first (generate_default_waves() already returns that shape
    directly, so a level built from it can just pass its result through)."""
    return Level(
        id=level_id,
        name=name,
        path_cells=pathing.path_cells_from_corners(corners),
        spawn_cells=(corners[0],),
        goal_cells=(corners[-1],),
        wave_specs=wave_specs,
        starting_gold=starting_gold,
        starting_lives=starting_lives,
    )


# Hand-written levels are authored as a simple ordered corner list -- terser
# than spelling out every tile -- and converted to the shared path_cells/
# spawn_cells/goal_cells shape via pathing.path_cells_from_corners. A
# player's editor-painted level builds that same shape directly instead,
# with no corner list involved at all.
LEVEL_1_CORNERS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]

# Hand-authored rather than generate_default_waves(), so it can introduce
# the other species partway through and cap off with a boss: grunts alone
# to start, scouts joining wave 2, tanks and splitters wave 3, flying and
# healers wave 4, and shielded alongside a single BossEnemy on the final
# wave -- every registered species gets introduced somewhere across this
# level's own waves (see test_levels.py's test_level_1_introduces_every_
# enemy_species_across_its_waves), since this is the first level a new
# player sees.
# Terse (unwrapped) form -- see _single_spawn_waves(), used below where
# this level's Level(...) is actually built, since this level (like every
# level below) has just the one spawn.
LEVEL_1_WAVE_SPECS = [
    {"grunt": 6},
    {"grunt": 8, "scout": 5},
    {"grunt": 8, "scout": 6, "tank": 3, "splitter": 3},
    {"grunt": 10, "scout": 8, "tank": 4, "flying": 4, "healer": 2},
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

LEVEL_3_CORNERS = [(0, 8), (3, 8), (3, 5), (7, 5), (7, 2), (11, 2), (11, 8), (14, 8)]

# More switchbacks than levels 1-2, and correspondingly larger waves.
LEVEL_3_WAVE_SPECS = [
    {"grunt": 9},
    {"grunt": 10, "scout": 7},
    {"grunt": 10, "scout": 8, "tank": 5},
    {"grunt": 12, "scout": 10, "tank": 6, "flying": 5},
    {"grunt": 10, "scout": 8, "tank": 6, "shielded": 4, "boss": 1},
]

LEVEL_4_CORNERS = [(0, 0), (0, 3), (13, 3), (13, 0)]

# Built from generate_default_waves() (a plain grunt ramp) for the first
# four waves -- this level is a quick, simple corridor, not a hand-tuned
# species showcase -- with one hand-built final wave appended for the
# mandatory boss (see test_levels.py's test_every_levels_final_wave_
# includes_a_boss, which checks every registered level, not just 1 and 2).
LEVEL_4_WAVE_SPECS = generate_default_waves(
    LEVEL_4_CORNERS[0], total_waves=4, enemy_type="grunt", base_count=10, count_step=4,
)
LEVEL_4_WAVE_SPECS.append({LEVEL_4_CORNERS[0]: {"grunt": 12, "scout": 8, "boss": 1}})

LEVEL_5_CORNERS = [(0, 2), (2, 2), (2, 7), (5, 7), (5, 1), (8, 1), (8, 7), (11, 7), (11, 1), (14, 1)]

# The hardest hand-tuned single-spawn level: six waves (one more than any
# other level), ramping through every species and finishing with two
# bosses at once.
LEVEL_5_WAVE_SPECS = [
    {"grunt": 10, "scout": 4},
    {"grunt": 10, "scout": 8, "tank": 4},
    {"grunt": 12, "scout": 9, "tank": 6, "flying": 6},
    {"grunt": 12, "scout": 10, "tank": 7, "shielded": 5},
    {"grunt": 14, "scout": 12, "tank": 8, "flying": 8, "shielded": 6},
    {"grunt": 12, "scout": 10, "tank": 8, "shielded": 6, "flying": 6, "boss": 2},
]

def _multi_lane_level(level_id, name, lane_corner_lists, spawn_cells, goal_cells, wave_specs,
                       starting_gold=150, starting_lives=20):
    """Build a Level whose path is the union of several straight-segment
    corner chains (see pathing.path_cells_from_corners) -- the shape any
    branching/merging level beyond a single corridor needs, since
    _corridor_level() only ever produces one spawn and one goal. Each entry
    in `lane_corner_lists` is its own corner list (e.g. a spawn-to-junction
    run, or a junction-to-goal run); together they union into one
    path_cells set -- Levels 6-9 below all use this. `wave_specs` must
    already be in Level's nested {spawn_cell: {...}} shape -- a multi-spawn
    level's per-wave composition genuinely differs per spawn, so there's no
    terse single-list shorthand to wrap here the way _single_spawn_waves()
    does for a corridor level."""
    path_cells = frozenset()
    for corners in lane_corner_lists:
        path_cells |= pathing.path_cells_from_corners(corners)
    return Level(
        id=level_id,
        name=name,
        path_cells=path_cells,
        spawn_cells=spawn_cells,
        goal_cells=goal_cells,
        wave_specs=wave_specs,
        starting_gold=starting_gold,
        starting_lives=starting_lives,
    )


# Level 6 is this campaign's one genuinely multi-spawn level, built from the
# full nested wave_specs shape directly (no corner-list shorthand, no
# _single_spawn_waves) -- two independent lanes converge at (6, 4) before a
# shared run to the goal, and each spawn sends a completely different
# species mix in every wave (grunt/tank from the top lane, scout/flying/
# shielded from the bottom one).
LEVEL_6_SPAWN_TOP = (0, 2)
LEVEL_6_SPAWN_BOTTOM = (0, 6)
LEVEL_6_GOAL = (14, 4)
LEVEL_6_LANE_CORNER_LISTS = [
    [LEVEL_6_SPAWN_TOP, (6, 2), (6, 4)],
    [LEVEL_6_SPAWN_BOTTOM, (6, 6), (6, 4)],
    [(6, 4), LEVEL_6_GOAL],
]
LEVEL_6_WAVE_SPECS = [
    {LEVEL_6_SPAWN_TOP: {"grunt": 6}, LEVEL_6_SPAWN_BOTTOM: {"scout": 6}},
    {LEVEL_6_SPAWN_TOP: {"grunt": 8, "tank": 2}, LEVEL_6_SPAWN_BOTTOM: {"scout": 8, "flying": 3}},
    {LEVEL_6_SPAWN_TOP: {"grunt": 8, "tank": 4}, LEVEL_6_SPAWN_BOTTOM: {"scout": 8, "flying": 5, "shielded": 2}},
    {LEVEL_6_SPAWN_TOP: {"grunt": 10, "tank": 6}, LEVEL_6_SPAWN_BOTTOM: {"scout": 10, "flying": 6, "shielded": 4}},
    {LEVEL_6_SPAWN_TOP: {"grunt": 10, "tank": 6, "boss": 1},
     LEVEL_6_SPAWN_BOTTOM: {"scout": 10, "flying": 6, "shielded": 4}},
]

LEVELS = {
    1: _corridor_level(1, "Winding Road", LEVEL_1_CORNERS,
                        _single_spawn_waves(LEVEL_1_CORNERS[0], LEVEL_1_WAVE_SPECS)),
    2: _corridor_level(2, "Serpentine Pass", LEVEL_2_CORNERS,
                        _single_spawn_waves(LEVEL_2_CORNERS[0], LEVEL_2_WAVE_SPECS)),
    3: _corridor_level(3, "Broken Switchback", LEVEL_3_CORNERS,
                        _single_spawn_waves(LEVEL_3_CORNERS[0], LEVEL_3_WAVE_SPECS)),
    # Already in the nested shape -- generate_default_waves() (see
    # LEVEL_4_WAVE_SPECS above) returns it directly, no _single_spawn_waves()
    # wrap needed here.
    4: _corridor_level(4, "Straight Cut", LEVEL_4_CORNERS, LEVEL_4_WAVE_SPECS),
    5: _corridor_level(5, "Twin Peaks", LEVEL_5_CORNERS,
                        _single_spawn_waves(LEVEL_5_CORNERS[0], LEVEL_5_WAVE_SPECS)),
    # Confluence doesn't fit _corridor_level's single-spawn/single-goal
    # shape -- built via _multi_lane_level instead, same as Levels 7-9
    # below.
    6: _multi_lane_level(
        6, "Confluence", LEVEL_6_LANE_CORNER_LISTS,
        spawn_cells=(LEVEL_6_SPAWN_TOP, LEVEL_6_SPAWN_BOTTOM),
        goal_cells=(LEVEL_6_GOAL,),
        wave_specs=LEVEL_6_WAVE_SPECS,
        starting_gold=180,
        starting_lives=20,
    ),
}

# Level 7: "Forked River" -- the campaign's first genuine *branch* (as
# opposed to Confluence's merge): one spawn, one shared trunk, then a
# junction fanning out into two independent goals. Built with
# _multi_lane_level rather than _corridor_level since the latter only ever
# produces a single goal.
LEVEL_7_SPAWN = (0, 4)
LEVEL_7_JUNCTION = (4, 4)
LEVEL_7_GOAL_TOP = (14, 1)
LEVEL_7_GOAL_BOTTOM = (14, 7)
LEVEL_7_WAVE_SPECS = _single_spawn_waves(LEVEL_7_SPAWN, [
    {"grunt": 8},
    {"grunt": 9, "scout": 6},
    {"grunt": 10, "scout": 7, "tank": 4},
    {"grunt": 11, "scout": 8, "tank": 5, "flying": 5},
    {"grunt": 10, "scout": 8, "tank": 6, "shielded": 4, "boss": 1},
])

# Level 8: "Twin Confluence" -- combines both shapes at once: two spawns
# merge into a shared trunk, which then itself branches into two goals.
# Still a forest (no diamond): each lane only ever touches the rest of the
# tree at its own single junction cell.
LEVEL_8_SPAWN_TOP = (0, 2)
LEVEL_8_SPAWN_BOTTOM = (0, 6)
LEVEL_8_MERGE_JUNCTION = (5, 4)
LEVEL_8_BRANCH_JUNCTION = (9, 4)
LEVEL_8_GOAL_TOP = (14, 1)
LEVEL_8_GOAL_BOTTOM = (14, 7)
LEVEL_8_WAVE_SPECS = [
    {LEVEL_8_SPAWN_TOP: {"grunt": 7}, LEVEL_8_SPAWN_BOTTOM: {"scout": 7}},
    {LEVEL_8_SPAWN_TOP: {"grunt": 9, "tank": 2}, LEVEL_8_SPAWN_BOTTOM: {"scout": 9, "flying": 3}},
    {LEVEL_8_SPAWN_TOP: {"grunt": 9, "tank": 5}, LEVEL_8_SPAWN_BOTTOM: {"scout": 9, "flying": 6, "shielded": 3}},
    {LEVEL_8_SPAWN_TOP: {"grunt": 11, "tank": 7}, LEVEL_8_SPAWN_BOTTOM: {"scout": 11, "flying": 7, "shielded": 5}},
    {LEVEL_8_SPAWN_TOP: {"grunt": 11, "tank": 7, "boss": 1},
     LEVEL_8_SPAWN_BOTTOM: {"scout": 11, "flying": 7, "shielded": 5}},
]

# Level 9: "Triple Crossing" -- three spawns merging into one shared trunk
# (a wider star than Confluence's two-lane merge) toward a single goal.
LEVEL_9_SPAWN_TOP = (0, 1)
LEVEL_9_SPAWN_MID = (0, 4)
LEVEL_9_SPAWN_BOTTOM = (0, 7)
LEVEL_9_JUNCTION = (6, 4)
LEVEL_9_GOAL = (14, 4)
LEVEL_9_WAVE_SPECS = [
    {LEVEL_9_SPAWN_TOP: {"grunt": 5}, LEVEL_9_SPAWN_MID: {"scout": 5}, LEVEL_9_SPAWN_BOTTOM: {"grunt": 5}},
    {LEVEL_9_SPAWN_TOP: {"grunt": 6, "tank": 2}, LEVEL_9_SPAWN_MID: {"scout": 7, "flying": 2},
     LEVEL_9_SPAWN_BOTTOM: {"grunt": 6, "tank": 2}},
    {LEVEL_9_SPAWN_TOP: {"grunt": 7, "tank": 4}, LEVEL_9_SPAWN_MID: {"scout": 8, "flying": 4, "shielded": 2},
     LEVEL_9_SPAWN_BOTTOM: {"grunt": 7, "tank": 4}},
    {LEVEL_9_SPAWN_TOP: {"grunt": 8, "tank": 5}, LEVEL_9_SPAWN_MID: {"scout": 9, "flying": 5, "shielded": 3},
     LEVEL_9_SPAWN_BOTTOM: {"grunt": 8, "tank": 5}},
    {LEVEL_9_SPAWN_TOP: {"grunt": 8, "tank": 6},
     LEVEL_9_SPAWN_MID: {"scout": 9, "flying": 5, "shielded": 4, "boss": 1},
     LEVEL_9_SPAWN_BOTTOM: {"grunt": 8, "tank": 6}},
]

LEVELS[7] = _multi_lane_level(
    7, "Forked River",
    lane_corner_lists=[
        [LEVEL_7_SPAWN, LEVEL_7_JUNCTION],
        [LEVEL_7_JUNCTION, (4, 1), LEVEL_7_GOAL_TOP],
        [LEVEL_7_JUNCTION, (4, 7), LEVEL_7_GOAL_BOTTOM],
    ],
    spawn_cells=(LEVEL_7_SPAWN,),
    goal_cells=(LEVEL_7_GOAL_TOP, LEVEL_7_GOAL_BOTTOM),
    wave_specs=LEVEL_7_WAVE_SPECS,
    starting_gold=160,
    starting_lives=20,
)

LEVELS[8] = _multi_lane_level(
    8, "Twin Confluence",
    lane_corner_lists=[
        [LEVEL_8_SPAWN_TOP, (5, 2), LEVEL_8_MERGE_JUNCTION],
        [LEVEL_8_SPAWN_BOTTOM, (5, 6), LEVEL_8_MERGE_JUNCTION],
        [LEVEL_8_MERGE_JUNCTION, LEVEL_8_BRANCH_JUNCTION],
        [LEVEL_8_BRANCH_JUNCTION, (9, 1), LEVEL_8_GOAL_TOP],
        [LEVEL_8_BRANCH_JUNCTION, (9, 7), LEVEL_8_GOAL_BOTTOM],
    ],
    spawn_cells=(LEVEL_8_SPAWN_TOP, LEVEL_8_SPAWN_BOTTOM),
    goal_cells=(LEVEL_8_GOAL_TOP, LEVEL_8_GOAL_BOTTOM),
    wave_specs=LEVEL_8_WAVE_SPECS,
    starting_gold=190,
    starting_lives=20,
)

LEVELS[9] = _multi_lane_level(
    9, "Triple Crossing",
    lane_corner_lists=[
        [LEVEL_9_SPAWN_TOP, (6, 1), LEVEL_9_JUNCTION],
        [LEVEL_9_SPAWN_MID, LEVEL_9_JUNCTION],
        [LEVEL_9_SPAWN_BOTTOM, (6, 7), LEVEL_9_JUNCTION],
        [LEVEL_9_JUNCTION, LEVEL_9_GOAL],
    ],
    spawn_cells=(LEVEL_9_SPAWN_TOP, LEVEL_9_SPAWN_MID, LEVEL_9_SPAWN_BOTTOM),
    goal_cells=(LEVEL_9_GOAL,),
    wave_specs=LEVEL_9_WAVE_SPECS,
    starting_gold=200,
    starting_lives=20,
)
