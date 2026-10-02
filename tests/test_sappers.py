"""Sappers -- an enemy that batters Barricades five times as hard, joining
run waves from Act 2 on via run_escalation.add_species."""

from entities.enemy import ENEMY_TYPES, BossEnemy, GruntEnemy, SapperEnemy
from run import run_escalation


def test_breach_multipliers():
    assert GruntEnemy.BREACH_MULTIPLIER == 1.0
    assert SapperEnemy.BREACH_MULTIPLIER == 5.0
    assert BossEnemy.BREACH_MULTIPLIER == 6.0
    assert ENEMY_TYPES["sapper"] is SapperEnemy


def test_sapper_count_grows_with_depth():
    assert run_escalation.sapper_count_for_depth(run_escalation.SAPPER_MIN_DEPTH - 1) == 0
    assert run_escalation.sapper_count_for_depth(run_escalation.SAPPER_MIN_DEPTH) == 1
    deep = run_escalation.SAPPER_MIN_DEPTH + run_escalation.SAPPER_DEPTH_STEP
    assert run_escalation.sapper_count_for_depth(deep) == 2


def test_add_species_copies_and_adds_to_each_waves_first_cell():
    authored = [{(0, 0): {"grunt": 3}, (5, 0): {"scout": 2}}, {(0, 0): {"sapper": 1}}]
    result = run_escalation.add_species(authored, "sapper", 2)
    assert result == [{(0, 0): {"grunt": 3, "sapper": 2}, (5, 0): {"scout": 2}}, {(0, 0): {"sapper": 3}}]
    assert authored == [{(0, 0): {"grunt": 3}, (5, 0): {"scout": 2}}, {(0, 0): {"sapper": 1}}]


def test_act_two_floors_carry_sappers_and_act_one_floors_do_not(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"])
    node = run.map.node("0-0")
    plain = game._level_for_node(run, node)
    assert all("sapper" not in comp for wave in plain.wave_specs for comp in wave.values())
    run.act = 1
    deep = game._level_for_node(run, node)
    assert all(any("sapper" in comp for comp in wave.values()) for wave in deep.wave_specs)
    game._enter_node("0-0")
    assert any("sapper" in comp for comp in game.level.wave_specs[0].values())
