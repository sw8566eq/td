"""Tests for run_map.py's map-generation algorithm -- pure, no Game/pygame
needed (mirrors the retired test_run_floors.py's own style). Structural
invariants are checked over many seeds rather than trusted by construction
alone, since _generate_edges' own connectivity argument is an inductive
proof about the algorithm, not a runtime guarantee -- a bug in the
implementation could still violate it.
"""

import random
from collections import deque

from levels import LEVELS
from run_map import (
    GUARANTEED_REST_ROW,
    MAX_SAME_TYPE_PER_ROW_FRACTION,
    MIN_ELITE_ROW,
    NODE_TYPES,
    ROW_COUNT,
    START_ROW_WIDTH,
    _level_pool_for_row,
    generate_run_map,
    heal_amount_for_row,
    treasure_shop_currency_for_row,
)

_SEEDS = range(50)


def _reachable_from_start(game_map):
    """BFS forward from every row-0 node -- the set of node ids reachable
    at all."""
    reachable = set(game_map.start_node_ids)
    queue = deque(reachable)
    while queue:
        node_id = queue.popleft()
        for target_id in game_map.edges.get(node_id, ()):
            if target_id not in reachable:
                reachable.add(target_id)
                queue.append(target_id)
    return reachable


def _reverse_edges(game_map):
    reverse = {}
    for node_id, targets in game_map.edges.items():
        for target_id in targets:
            reverse.setdefault(target_id, []).append(node_id)
    return reverse


def _can_reach_boss(game_map):
    """BFS backward from the boss node, over the reversed edge graph -- the
    set of node ids that can reach it."""
    reverse = _reverse_edges(game_map)
    boss_id = game_map.boss_node_id
    can_reach = {boss_id}
    queue = deque([boss_id])
    while queue:
        node_id = queue.popleft()
        for predecessor_id in reverse.get(node_id, ()):
            if predecessor_id not in can_reach:
                can_reach.add(predecessor_id)
                queue.append(predecessor_id)
    return can_reach


def test_generate_run_map_is_deterministic_for_a_fixed_seed():
    first = generate_run_map(random.Random(42))
    second = generate_run_map(random.Random(42))
    assert first == second


def test_row_count_is_fixed():
    game_map = generate_run_map(random.Random(1))
    assert len(game_map.rows) == ROW_COUNT


def test_row_zero_is_always_combat_at_the_fixed_start_width():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        assert len(game_map.rows[0]) == START_ROW_WIDTH
        assert all(node.node_type == "combat" for node in game_map.rows[0])


def test_final_row_is_a_single_combat_boss_node():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        assert len(game_map.rows[-1]) == 1
        assert game_map.rows[-1][0].node_type == "combat"
        assert game_map.boss_node_id == game_map.rows[-1][0].id


def test_every_non_final_node_has_at_least_one_outgoing_edge():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        for row in game_map.rows[:-1]:
            for node in row:
                assert game_map.edges.get(node.id), f"seed {seed}: {node.id} has no outgoing edge"


def test_every_non_start_node_has_at_least_one_incoming_edge():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        incoming = {target for targets in game_map.edges.values() for target in targets}
        for row in game_map.rows[1:]:
            for node in row:
                assert node.id in incoming, f"seed {seed}: {node.id} has no incoming edge"


def test_every_start_node_can_reach_the_boss():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        can_reach_boss = _can_reach_boss(game_map)
        for node_id in game_map.start_node_ids:
            assert node_id in can_reach_boss, f"seed {seed}: {node_id} can't reach the boss"


def test_every_node_is_reachable_from_a_start_node():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        reachable = _reachable_from_start(game_map)
        for row in game_map.rows:
            for node in row:
                assert node.id in reachable, f"seed {seed}: {node.id} is unreachable"


def test_no_elite_node_before_min_elite_row():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        for row_index in range(MIN_ELITE_ROW):
            assert all(node.node_type != "elite" for node in game_map.rows[row_index])


def test_guaranteed_rest_row_always_has_at_least_one_rest_node():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        assert any(node.node_type == "rest" for node in game_map.rows[GUARANTEED_REST_ROW])


def test_no_row_exceeds_the_same_type_cap():
    import math
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        for row in game_map.rows[1:-1]:  # row 0/final row are fixed all-combat, exempt by construction
            width = len(row)
            max_per_type = max(1, math.ceil(width * MAX_SAME_TYPE_PER_ROW_FRACTION))
            counts = {}
            for node in row:
                counts[node.node_type] = counts.get(node.node_type, 0) + 1
            assert all(count <= max_per_type for count in counts.values())


def test_combat_and_elite_nodes_have_a_real_level_id_from_the_right_tier():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        for row in game_map.rows:
            for node in row:
                if node.node_type in ("combat", "elite"):
                    assert node.level_id in LEVELS
                    assert node.level_id in _level_pool_for_row(node.row, LEVELS)
                else:
                    assert node.level_id is None


def test_level_tiers_partition_by_spawn_count_and_dont_overlap():
    simple_pool = _level_pool_for_row(0, LEVELS)
    complex_pool = _level_pool_for_row(ROW_COUNT - 1, LEVELS)
    assert set(simple_pool) & set(complex_pool) == set()
    assert set(simple_pool) | set(complex_pool) == set(LEVELS.keys())
    assert all(len(LEVELS[lid].spawn_cells) == 1 for lid in simple_pool)
    assert all(len(LEVELS[lid].spawn_cells) > 1 for lid in complex_pool)


def test_all_node_types_are_within_the_registered_set():
    for seed in _SEEDS:
        game_map = generate_run_map(random.Random(seed))
        for row in game_map.rows:
            for node in row:
                assert node.node_type in NODE_TYPES


def test_heal_amount_for_row_grows_with_row():
    assert heal_amount_for_row(3) > heal_amount_for_row(0)


def test_treasure_shop_currency_for_row_grows_with_row():
    assert treasure_shop_currency_for_row(3) > treasure_shop_currency_for_row(0)
