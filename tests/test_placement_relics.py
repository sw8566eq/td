"""Placement relics -- Combined Arms (variety of nearby tower types) and
Lone Sentinel (no tower nearby), resolved by Tower.set_nearby_tower_bonus."""

import pygame
import pytest

from entities.tower import (
    ISOLATION_RADIUS,
    TOWER_TYPES,
    VARIETY_BONUS_CAP,
    VARIETY_RADIUS,
)


def _tower(name, x, variety=0.0, isolation=0.0):
    tower = TOWER_TYPES[name](0, 0, pygame.Vector2(x, 0))
    tower.relic_variety_damage_bonus_per_type = variety
    tower.relic_isolation_damage_bonus = isolation
    return tower


def test_combined_arms_counts_distinct_other_types_in_reach():
    me = _tower("basic", 0, variety=0.05)
    board = [me, _tower("basic", 10), _tower("cannon", 20), _tower("cannon", 30), _tower("frost", 40),
             _tower("sniper", VARIETY_RADIUS + 50)]
    base = me.effective_damage()
    me.set_nearby_tower_bonus(board)
    assert me.placement_damage_bonus == pytest.approx(0.10)  # cannon + frost; same type and far ones don't count
    assert me.effective_damage() == pytest.approx(base + me.damage * 0.10)


def test_combined_arms_is_capped():
    me = _tower("basic", 0, variety=0.05)
    others = [_tower(name, 5) for name in TOWER_TYPES if name != "basic"]
    me.set_nearby_tower_bonus([me, *others])
    assert me.placement_damage_bonus == pytest.approx(VARIETY_BONUS_CAP)


def test_lone_sentinel_needs_empty_surroundings():
    me = _tower("sniper", 0, isolation=0.3)
    me.set_nearby_tower_bonus([me, _tower("basic", ISOLATION_RADIUS + 1)])
    assert me.placement_damage_bonus == pytest.approx(0.3)
    me.set_nearby_tower_bonus([me, _tower("basic", ISOLATION_RADIUS - 1)])
    assert me.placement_damage_bonus == 0.0


def test_no_relic_no_bonus():
    me = _tower("basic", 0)
    me.set_nearby_tower_bonus([me, _tower("cannon", 5)])
    assert me.placement_damage_bonus == 0.0


def test_the_relics_reach_towers_through_a_real_run(game):
    from conftest import find_buildable_anchor
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"], relics=["lone_sentinel"])
    game._enter_node("0-0")
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    assert game.towers[0].placement_damage_bonus == pytest.approx(0.3)
