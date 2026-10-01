"""Tests for potions -- run/potions.py's registry and each potion's own
effect, plus Game.use_potion, the sidebar potion belt, and potions
surviving a save/resume. How potions are *earned* (post-combat rewards)
is covered in test_rewards.py/test_run.py."""

import random

import pygame
import pytest
from conftest import clear_mouse_mock, mock_mouse_pos, spy_on_audio, start_first_floor

from core.game import GameState
from entities.enemy import BossEnemy, GruntEnemy
from persistence import save_state
from progression import achievements
from run import potions
from run.potions import POTION_SLOTS, POTIONS


def _enemy(cls=GruntEnemy):
    return cls([pygame.Vector2(0, 0), pygame.Vector2(500, 0)], wave_number=1)


def _floor_with_potions(game, held):
    start_first_floor(game, seed=1)
    game.active_run.potions = list(held)
    return game.active_run


def test_every_potion_has_a_name_description_and_belt_color():
    from presentation import ui

    for key, potion in POTIONS.items():
        assert potion.key == key
        assert potion.display_name and potion.description
        assert key in ui.POTION_COLORS


def test_random_potion_is_deterministic_and_always_a_real_key():
    assert potions.random_potion(random.Random(3)) == potions.random_potion(random.Random(3))
    for seed in range(20):
        assert potions.random_potion(random.Random(seed)) in POTIONS


def test_has_free_slot():
    assert potions.has_free_slot([])
    assert not potions.has_free_slot(["fire_bomb"] * POTION_SLOTS)


def test_fire_bomb_hits_every_enemy_for_a_fraction_of_max_hp_and_bosses_less(game):
    _floor_with_potions(game, ["fire_bomb"])
    grunt, boss = _enemy(), _enemy(BossEnemy)
    game.enemies = [grunt, boss]

    game.use_potion(0)

    assert grunt.hp == pytest.approx(grunt.max_hp * (1 - potions.FIRE_BOMB_HP_FRACTION))
    assert boss.hp < boss.max_hp
    assert boss.max_hp - boss.hp <= boss.max_hp * potions.FIRE_BOMB_BOSS_HP_FRACTION + 1e-6
    assert game.active_run.potions == []


def test_frost_flask_slows_and_marking_dust_marks_every_enemy(game):
    _floor_with_potions(game, ["frost_flask", "marking_dust"])
    enemy = _enemy()
    game.enemies = [enemy]

    game.use_potion(0)
    game.use_potion(0)  # marking_dust has shifted into slot 0

    assert enemy.slow_multiplier == potions.FROST_FLASK_SLOW_FACTOR
    assert enemy.slow_timer == potions.FROST_FLASK_DURATION
    assert enemy.mark_damage_multiplier == potions.MARKING_DUST_MULTIPLIER


def test_liquid_gold_and_mending_salve(game):
    run = _floor_with_potions(game, ["liquid_gold", "mending_salve"])
    gold, lives = game.economy.gold, game.economy.lives

    game.use_potion(0)
    game.use_potion(0)

    assert game.economy.gold == gold + potions.liquid_gold_amount(run.current_row)
    assert game.economy.lives == lives + potions.MENDING_SALVE_LIVES


def test_liquid_gold_amount_grows_with_depth():
    assert potions.liquid_gold_amount(3) > potions.liquid_gold_amount(0)


def test_overclock_speeds_up_every_tower_until_it_expires(game):
    from conftest import find_buildable_anchor

    _floor_with_potions(game, ["overclock_elixir"])
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    tower = game.towers[0]
    base_rate = tower.effective_fire_rate()

    game.use_potion(0)
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == pytest.approx(base_rate * potions.OVERCLOCK_FIRE_RATE_MULTIPLIER)

    game.update(dt=potions.OVERCLOCK_DURATION)
    game.update(dt=0.01)
    assert game.overclock_timer == 0.0
    assert tower.effective_fire_rate() == pytest.approx(base_rate)


def test_overclock_timer_resets_on_a_fresh_floor_load(game):
    _floor_with_potions(game, ["overclock_elixir"])
    game.use_potion(0)
    assert game.overclock_timer > 0
    game.reset()
    assert game.overclock_timer == 0.0


def test_use_potion_plays_a_sound_and_bumps_the_achievement_counter(game):
    _floor_with_potions(game, ["mending_salve"])
    played = spy_on_audio(game)

    game.use_potion(0)

    assert "potion_used" in played
    assert achievements.load_achievements(game.achievements_path)["counters"]["potions_used"] == 1


@pytest.mark.parametrize("slot", [-1, 1, 5])
def test_use_potion_on_an_empty_or_invalid_slot_is_a_no_op(game, slot):
    _floor_with_potions(game, ["mending_salve"])
    game.use_potion(slot)
    assert game.active_run.potions == ["mending_salve"]


def test_use_potion_does_nothing_while_paused_or_outside_a_run(game):
    _floor_with_potions(game, ["mending_salve"])
    game.state = GameState.PAUSED
    game.use_potion(0)
    assert game.active_run.potions == ["mending_salve"]

    game.load_level(1)  # Practice-style load -- no active run
    game.state = GameState.PLAYING
    game.use_potion(0)  # must not crash


def test_clicking_a_belt_slot_uses_that_potion(game):
    _floor_with_potions(game, ["fire_bomb", "mending_salve"])
    lives = game.economy.lives

    game._handle_click(game.potion_slot_rects[1].center)

    assert game.active_run.potions == ["fire_bomb"]
    assert game.economy.lives == lives + potions.MENDING_SALVE_LIVES


def test_belt_slots_sit_inside_the_sidebar_below_the_sell_button():
    from presentation import ui
    from support import settings

    rects = ui.build_potion_slot_rects()
    assert len(rects) == POTION_SLOTS
    sell_bottom = ui.build_sell_button_rect().bottom
    for rect in rects:
        assert rect.left >= settings.PLAY_WIDTH and rect.right <= settings.SCREEN_WIDTH
        assert rect.top > sell_bottom and rect.bottom <= settings.SCREEN_HEIGHT


def test_render_with_a_hovered_potion_and_running_overclock_does_not_crash(game):
    _floor_with_potions(game, ["fire_bomb", "overclock_elixir"])
    game.use_potion(1)
    mock_mouse_pos(game.potion_slot_rects[0].center)
    try:
        assert game._hovered_potion_slot() == 0
        game.render()
    finally:
        clear_mouse_mock()


def test_potions_survive_a_save_and_resume(game):
    _floor_with_potions(game, ["fire_bomb", "liquid_gold"])
    game.save_run()

    data = save_state.load_run(game.save_path)
    game.resume_saved_run(data)

    assert game.active_run.potions == ["fire_bomb", "liquid_gold"]


def test_a_save_with_an_unknown_potion_is_not_resumable(game):
    _floor_with_potions(game, ["not_a_potion"])
    game.save_run()
    assert save_state.load_run(game.save_path) is None
