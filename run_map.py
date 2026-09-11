"""A roguelike run's branching map: a row-based DAG of nodes (Combat/Elite/
Shop/Event/Rest/Treasure), generated once per run and shown to the player in
full from the start -- see CLAUDE.md's run-loop section. Replaces the old
run_floors.py's flat, ascending floor_sequence: instead of one fixed path
through LEVELS, a run now picks its own route through a graph of choices,
converging on a single boss node at the top.

Deliberately row-based rather than a free-form graph: edges only ever run
from one row to the next (never skip a row, never point backward), which is
what keeps "is every node reachable, and can every node reach the boss"
provable by simple induction rather than needing a general graph-reachability
pass. See _generate_edges' own docstring for the connectivity argument.

Generated once, at Game.start_new_run(), from a plain seeded random.Random --
never re-derived per node the way _run_rng's own per-floor streams are,
since the whole map (not just one floor of it) has to exist up front for a
"full map upfront" run. RunState.map holds the result directly (see
run_state.py) rather than only the seed, mirroring how floor_sequence itself
used to be stored directly rather than re-derived on demand.
"""

import math
from dataclasses import dataclass

from levels import LEVELS
from rng_sampling import sample_up_to

# Unchanged from the old run_floors.DEFAULT_FLOOR_COUNT -- this is what keeps
# run_escalation.py's own tuned per-floor growth constants (and veterans_
# momentum's escalating bonus) meaning the same thing they always did: a
# node at row 3 escalates exactly like floor_index=3 used to.
ROW_COUNT = 6
# The horizontal grid every row's node columns are drawn from -- not every
# row uses every column (see MIN_ROW_WIDTH/MAX_ROW_WIDTH), just enough to
# lay a row's actual nodes out with real gaps between them.
COLS = 4

# Row 0: the player's very first choice -- which of three same-difficulty
# Combat layouts to open the run on, not a difficulty choice at all (every
# row-0 node is "combat"). Fixed rather than randomized (unlike every other
# non-final row) so floor-loading's own lives-capture special case always
# has exactly one guaranteed combat node to capture from.
START_ROW_WIDTH = 3
MIN_ROW_WIDTH, MAX_ROW_WIDTH = 2, 4

# Edge generation: every node gets a "primary" edge to its nearest next-row
# node (by column distance) -- MAX_COL_JUMP is only a preference for how far
# that primary edge reaches before _generate_edges' connectivity fallback
# starts ignoring it; EXTRA_EDGE_CHANCE is the odds a node also gets a
# second edge, to a different nearby next-row node, so the map has genuine
# branches rather than one guaranteed edge per node in a strict lockstep.
MAX_COL_JUMP = 1
EXTRA_EDGE_CHANCE = 0.3

NODE_TYPES = ("combat", "elite", "shop", "event", "rest", "treasure")
# Placeholder weights, tunable once there's real playtesting to tune
# against (same "loose draft" spirit shop.py's own TOWER_PRICE/RELIC_PRICE
# comment already documents) -- combat stays the most common node by a wide
# margin, treasure the rarest.
NODE_TYPE_WEIGHTS = {"combat": 45, "elite": 15, "shop": 12, "event": 16, "rest": 8, "treasure": 4}
# A row can't be more than half of one node type -- keeps a wide row from
# degenerating into e.g. two Shops and nothing else, without needing a full
# shuffle-and-cap algorithm to enforce it.
MAX_SAME_TYPE_PER_ROW_FRACTION = 0.5
# No Elite node before this row -- a fresh run's opening rows stay a plain
# Combat/Shop/Event/Rest/Treasure mix, so a brand-new deck never has to face
# the harder escalation multiplier (see run_escalation.apply_elite_
# multiplier) before it's had a couple of floors to grow.
MIN_ELITE_ROW = 2
# This row always has at least one Rest node, forced onto it after the
# weighted draw if it didn't produce one on its own -- unlike Shop (left
# purely to chance, a deliberate design choice, see CLAUDE.md), a run should
# never be able to go the *entire* back half with zero chances to recover
# lost lives.
GUARANTEED_REST_ROW = ROW_COUNT - 2

# Rest node healing -- flat + a small per-row scale-up, so a Rest reached
# late in a run (when lives lost cost more to claw back) heals a bit more
# than one reached early.
REST_HEAL_BASE, REST_HEAL_GROWTH_PER_ROW = 3, 1
# Treasure's guaranteed shop-currency payout -- same "flat + per-row
# growth" shape as shop.income_for_floor's own flat half, on its own
# separate tuning (a Treasure node is a dedicated reward stop, not a floor
# clear, so it isn't keyed off shop.py's own constants).
TREASURE_SHOP_CURRENCY_BASE, TREASURE_SHOP_CURRENCY_GROWTH_PER_ROW = 15, 3


def heal_amount_for_row(row):
    """Lives restored by a Rest node at this row."""
    return REST_HEAL_BASE + REST_HEAL_GROWTH_PER_ROW * row


def treasure_shop_currency_for_row(row):
    """Guaranteed shop currency granted by a Treasure node at this row --
    it also always grants one relic, degrading gracefully to currency-only
    once every relic is already held (see Game._enter_treasure_node)."""
    return TREASURE_SHOP_CURRENCY_BASE + TREASURE_SHOP_CURRENCY_GROWTH_PER_ROW * row


@dataclass(frozen=True)
class MapNode:
    id: str  # f"{row}-{col}" -- unique within one RunMap
    row: int
    col: int
    node_type: str  # one of NODE_TYPES
    # A LEVELS key for a combat/elite node; None for every other type --
    # there's no level to load for a Shop/Event/Rest/Treasure stop.
    level_id: object = None


@dataclass(frozen=True)
class RunMap:
    rows: tuple  # tuple[tuple[MapNode, ...], ...], outer index == row
    edges: dict  # {node_id: (node_id, ...)}, row r -> row r+1 only

    def node(self, node_id):
        """The MapNode with this id. A RunMap is small (at most ROW_COUNT *
        MAX_ROW_WIDTH nodes -- well under 30) so a linear scan here is
        simpler than maintaining a second, derived id->node index that
        could in principle drift from `rows` itself."""
        for row in self.rows:
            for candidate in row:
                if candidate.id == node_id:
                    return candidate
        raise KeyError(node_id)

    @property
    def start_node_ids(self):
        return tuple(n.id for n in self.rows[0])

    @property
    def final_row_index(self):
        return len(self.rows) - 1

    @property
    def boss_node_id(self):
        """The single node in the final row -- see generate_run_map's own
        comment for why that row's width is always fixed at 1."""
        return self.rows[-1][0].id


def _level_pool_for_row(row_index, level_pool):
    """Which LEVELS ids a combat/elite node at this row draws from --
    partitioned by structure (single-spawn "corridor" levels vs.
    multi-spawn "multi-lane" ones), not a hardcoded id list, so this stays
    self-maintaining as levels are added. Mirrors the authored
    corridor-then-multi-lane ramp run_floors.py's own ascending-sorted
    sampling used to preserve, just expressed as row bands instead of a
    flat sequence: earlier rows draw from the simpler shape, later rows
    (elites and the boss included) from the more complex one."""
    simple_ids = sorted(lid for lid, level in level_pool.items() if len(level.spawn_cells) == 1)
    complex_ids = sorted(lid for lid, level in level_pool.items() if len(level.spawn_cells) > 1)
    return simple_ids if row_index < ROW_COUNT // 2 else complex_ids


def _assign_node_types(rng, row_index, width):
    """`width` node types for this row -- row 0 and the final row are
    always all-combat (see generate_run_map); every row between them is a
    weighted random draw from NODE_TYPES, capped at MAX_SAME_TYPE_PER_ROW_
    FRACTION of the row so one row can't degenerate into a single
    repeated type, with Elite excluded below MIN_ELITE_ROW and a Rest node
    forced in on GUARANTEED_REST_ROW if the draw didn't already produce
    one."""
    if row_index in (0, ROW_COUNT - 1):
        return ["combat"] * width

    allowed = {
        node_type: weight for node_type, weight in NODE_TYPE_WEIGHTS.items()
        if not (node_type == "elite" and row_index < MIN_ELITE_ROW)
    }
    # width <= MAX_ROW_WIDTH and len(allowed) * max_per_type is always >=
    # MAX_ROW_WIDTH for every NODE_TYPE_WEIGHTS/MAX_SAME_TYPE_PER_ROW_
    # FRACTION combination above, so `choices` below can never run dry.
    max_per_type = max(1, math.ceil(width * MAX_SAME_TYPE_PER_ROW_FRACTION))
    counts = {node_type: 0 for node_type in allowed}
    types = []
    for _ in range(width):
        choices = [node_type for node_type in allowed if counts[node_type] < max_per_type]
        picked = rng.choices(choices, weights=[allowed[node_type] for node_type in choices], k=1)[0]
        counts[picked] += 1
        types.append(picked)

    if row_index == GUARANTEED_REST_ROW and "rest" not in types:
        types[rng.randrange(width)] = "rest"
    return types


def _generate_edges(rng, rows):
    """Row-by-row edges: every node in row r gets a "primary" edge to its
    nearest node in row r+1 (by column distance), plus a second edge to a
    different nearby one with EXTRA_EDGE_CHANCE odds -- then a connectivity
    pass forces at least one incoming edge onto any row r+1 node the
    primary-edge pass left orphaned, by adding an edge from its own nearest
    row r node.

    This guarantees, by induction row by row, that every node is both
    reachable from some row-0 node and able to reach the boss: every node
    always gets >=1 outgoing edge (the primary one), and the connectivity
    pass guarantees every node (row 0 excepted, which needs no incoming
    edge at all) gets >=1 incoming edge too -- so there's never a dead end
    and never an orphaned node, without needing a general graph-
    reachability check to prove it after the fact (though tests do verify
    it with one anyway, over many seeds)."""
    edges = {}
    for row_index in range(len(rows) - 1):
        current_row, next_row = rows[row_index], rows[row_index + 1]
        incoming_count = {node.id: 0 for node in next_row}
        for node in current_row:
            candidates = [n for n in next_row if abs(n.col - node.col) <= MAX_COL_JUMP] or list(next_row)
            primary = min(candidates, key=lambda n: abs(n.col - node.col))
            targets = [primary.id]
            others = [n for n in candidates if n.id != primary.id]
            if others and rng.random() < EXTRA_EDGE_CHANCE:
                targets.append(rng.choice(others).id)
            edges[node.id] = tuple(targets)
            for target_id in targets:
                incoming_count[target_id] += 1
        for node in next_row:
            if incoming_count[node.id] == 0:
                nearest = min(current_row, key=lambda n: abs(n.col - node.col))
                edges[nearest.id] = edges[nearest.id] + (node.id,)
                incoming_count[node.id] += 1
    return edges


def generate_run_map(rng, level_pool=LEVELS):
    """A full RunMap for one run, generated deterministically from `rng` --
    the same object Game.start_new_run() seeds once from run.seed, mirroring
    the "generated once up front" shape a full-map-upfront run needs (unlike
    _run_rng's own per-floor-derived streams, there's no later point where
    re-deriving the map from scratch would make sense -- the whole graph has
    to exist before the player ever picks a row-0 node)."""
    rows = []
    for row_index in range(ROW_COUNT):
        if row_index == 0:
            width = START_ROW_WIDTH
        elif row_index == ROW_COUNT - 1:
            width = 1
        else:
            width = rng.randint(MIN_ROW_WIDTH, min(MAX_ROW_WIDTH, COLS))
        cols = [COLS // 2] if width == 1 else sorted(rng.sample(range(COLS), width))
        types = _assign_node_types(rng, row_index, width)

        level_ids_needed = sum(1 for node_type in types if node_type in ("combat", "elite"))
        level_pool_for_row = _level_pool_for_row(row_index, level_pool)
        picked_level_ids = iter(sample_up_to(rng, level_pool_for_row, level_ids_needed))

        rows.append(tuple(
            MapNode(
                id=f"{row_index}-{col}", row=row_index, col=col, node_type=node_type,
                level_id=next(picked_level_ids) if node_type in ("combat", "elite") else None,
            )
            for col, node_type in zip(cols, types)
        ))

    return RunMap(rows=tuple(rows), edges=_generate_edges(rng, rows))
