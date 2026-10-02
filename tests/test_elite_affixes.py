"""Tests for Elite affixes -- run/elite_affixes.py and how Game rolls,
applies, saves and shows them."""

import random

import pygame
import pytest
from conftest import clear_mouse_mock, make_linear_run_map, mock_mouse_pos

from persistence import save_state
from run import elite_affixes
from run.card_pool import STARTER_TOWERS
from run.elite_affixes import AFFIXES
from run.run_escalation import FloorEscalation
from run.run_state import RunState
from world.levels import LEVELS


def _run_on(game, node_types, seed=1):
    game.active_run = RunState(
        seed=seed, map=make_linear_run_map(node_types), difficulty="normal",
        unlocked_towers=list(STARTER_TOWERS), lives=20,
    )
    game._enter_map()
    return game.active_run


def _seed_with_affix(game, key):
    """A seed whose row-0 Elite rolls `key` -- searched, not hardcoded, so
    this doesn't silently depend on the rng stream's exact values."""
    for seed in range(200):
        run = _run_on(game, ["elite", "combat"], seed=seed)
        if game._elite_affix(run, run.map.node("0-0")).key == key:
            return run
    raise AssertionError(f"no seed in range rolls {key}")


def test_every_affix_is_described_and_keyed_consistently():
    for key, affix in AFFIXES.items():
        assert affix.key == key and affix.display_name and affix.description


def test_roll_affix_is_deterministic():
    assert elite_affixes.roll_affix(random.Random(9)) == elite_affixes.roll_affix(random.Random(9))


def test_apply_to_escalation_multiplies_each_field():
    affix = elite_affixes.EliteAffix("x", "X", "x", hp_multiplier=2.0, speed_multiplier=3.0, gold_multiplier=4.0)
    result = elite_affixes.apply_to_escalation(FloorEscalation(1.5, 1.0, 1.0, 1.2), affix)
    assert (result.enemy_hp_multiplier, result.enemy_speed_multiplier, result.enemy_gold_multiplier) == (3.0, 3.0, 4.0)
    assert result.starting_gold_multiplier == 1.2


def test_scale_wave_counts_rounds_up_and_skips_bosses():
    specs = [{(0, 0): {"grunt": 3, "boss": 1}}]
    scaled = elite_affixes.scale_wave_counts(specs, 1.5, frozenset({"boss"}))
    assert scaled == [{(0, 0): {"grunt": 5, "boss": 1}}]
    assert specs == [{(0, 0): {"grunt": 3, "boss": 1}}]  # never mutates the original


def test_only_elite_nodes_have_an_affix(game):
    run = _run_on(game, ["combat", "elite"])
    assert game._elite_affix(run, run.map.node("0-0")) is None
    assert game._elite_affix(run, run.map.node("1-0")) in AFFIXES.values()
    assert set(game.map_node_affixes) == {"1-0"}


def test_affix_scales_the_elite_floors_enemies(game):
    run = _seed_with_affix(game, "swift")
    plain = _run_on(game, ["combat", "combat"], seed=run.seed)
    game._enter_node("0-0")
    combat_speed = game.wave_manager.enemy_speed_multiplier

    game.active_run = run
    game._enter_map()
    game._enter_node("0-0")

    from run import run_escalation
    elite_bump = run_escalation.ELITE_SPEED_MULTIPLIER
    assert plain is not run
    assert game.wave_manager.enemy_speed_multiplier == pytest.approx(combat_speed * elite_bump * 1.25)


def test_swarming_loads_a_private_copy_with_more_enemies(game):
    _seed_with_affix(game, "swarming")
    game._enter_node("0-0")
    original = LEVELS[1].wave_specs
    assert game.level is not LEVELS[1]
    assert LEVELS[1].wave_specs is original  # the registry singleton is untouched
    original_total = sum(sum(c.values()) for wave in original for c in wave.values())
    scaled_total = sum(sum(c.values()) for wave in game.level.wave_specs for c in wave.values())
    assert scaled_total > original_total


def test_swarming_survives_save_and_resume(game):
    _seed_with_affix(game, "swarming")
    game._enter_node("0-0")
    scaled = game.level.wave_specs
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.level.wave_specs == scaled


def test_map_tooltip_and_sidebar_show_the_affix(game):
    run = _seed_with_affix(game, "gilded")
    run.ascension = 4
    mock_mouse_pos(game.map_node_rects["0-0"].center)
    try:
        game.render()  # hovered Elite tooltip
    finally:
        clear_mouse_mock()
    game._enter_node("0-0")
    assert game.renderer._run_modifiers_text() == "Ascension 4, Gilded elite"
    game.render()


def test_sidebar_modifiers_text_is_none_on_a_plain_floor(game):
    _run_on(game, ["combat", "combat"])
    game._enter_node("0-0")
    assert game.renderer._run_modifiers_text() is None
    pygame.display.flip()


def test_regenerating_enemies_heal_but_never_past_max_or_from_death():
    from entities.enemy import GruntEnemy

    enemy = GruntEnemy([pygame.Vector2(0, 0), pygame.Vector2(500, 0)], wave_number=1)
    enemy.regen_fraction_per_second = 0.5
    enemy.hp = enemy.max_hp / 2
    enemy.update(0.5)
    assert enemy.hp == pytest.approx(enemy.max_hp * 0.75)
    enemy.update(5.0)
    assert enemy.hp == enemy.max_hp
    enemy.take_damage(enemy.max_hp * 10)
    enemy.update(1.0)
    assert enemy.is_dead and enemy.hp == 0


def test_armored_enemies_take_less_from_every_hit():
    from entities.enemy import GruntEnemy

    enemy = GruntEnemy([pygame.Vector2(0, 0), pygame.Vector2(500, 0)], wave_number=1)
    enemy.damage_taken_multiplier = 0.75
    assert enemy.take_damage(10) == pytest.approx(7.5)


@pytest.mark.parametrize("key, attr, value", [
    ("regenerating", "regen_fraction_per_second", 0.04),
    ("armored", "damage_taken_multiplier", 0.75),
])
def test_trait_affixes_reach_every_spawned_enemy_and_survive_resume(game, key, attr, value):
    _seed_with_affix(game, key)
    game._enter_node("0-0")
    assert getattr(game.wave_manager, f"enemy_{attr}") == value
    from entities.enemy import GruntEnemy
    enemy = GruntEnemy([pygame.Vector2(0, 0), pygame.Vector2(500, 0)], wave_number=1)
    game.wave_manager.apply_spawn_multipliers(enemy)
    assert getattr(enemy, attr) == value

    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert getattr(game.wave_manager, f"enemy_{attr}") == value


def test_ordinary_floors_have_no_enemy_traits(game):
    _run_on(game, ["combat", "combat"])
    game._enter_node("0-0")
    assert game.wave_manager.enemy_regen_fraction_per_second == 0.0
    assert game.wave_manager.enemy_damage_taken_multiplier == 1.0
