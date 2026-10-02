"""Tests for the between-nodes autosave (save_state.save_map_checkpoint,
Game._autosave_run/_resume_map_checkpoint)."""

import json
import pathlib

import pygame
from conftest import make_game

from core.game import GameState
from persistence import save_state


def _new_game(tmp_path):
    return make_game(tmp_path)


def test_the_map_autosaves_and_continue_resumes_onto_it(game, tmp_path):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "shop", "combat"], seed=5, relics=["lucky_strikes"],
                              potions=["fire_bomb"], shop_currency=9)
    assert game.has_saved_run
    data = save_state.load_run(game.save_path)
    assert data["kind"] == "map" and data["run"].seed == 5

    fresh = _new_game(tmp_path)
    assert fresh.has_saved_run
    fresh._handle_keydown(pygame.K_c)
    assert fresh.state == GameState.MAP
    assert fresh.active_run.relics == ["lucky_strikes"] and fresh.active_run.potions == ["fire_bomb"]
    assert fresh.active_run.shop_currency == 9 and fresh.active_run.current_node_id is None
    assert run is not fresh.active_run


def test_quitting_mid_fight_resumes_into_the_same_fight_from_the_start(game, tmp_path):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"], lives=12)
    game._enter_node("0-0")  # committed -- the autosave records it before the floor loads
    game.wave_manager.skip_delay()  # mid-fight: no manual save possible now

    fresh = _new_game(tmp_path)
    fresh._continue_saved_run()
    assert fresh.state == GameState.PLAYING
    assert fresh.active_run.current_node_id == "0-0"
    assert fresh.wave_manager.wave_index == 0


def test_resuming_after_a_cleared_node_returns_to_the_map(game, tmp_path):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "rest"])
    game._enter_node("1-0")
    game._choose_rest_option(0)
    game._handle_keydown(pygame.K_SPACE)  # finish the Rest -> map (autosaved, node visited)

    fresh = _new_game(tmp_path)
    fresh._continue_saved_run()
    assert fresh.state == GameState.MAP
    assert fresh.active_run.visited_node_ids == ["1-0"]


def test_permadeath_deletes_the_autosave(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"])
    game._enter_node("0-0")
    game.economy.lives = 0
    game.update(dt=0.01)
    assert game.state == GameState.GAME_OVER
    assert not save_state.has_saved_run(game.save_path)
    assert not game.has_saved_run


def test_a_mid_floor_save_still_takes_precedence(game, tmp_path):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"])
    game._enter_node("0-0")
    game.economy.gold = 777
    game.save_run()
    fresh = _new_game(tmp_path)
    fresh._continue_saved_run()
    assert fresh.economy.gold == 777


def test_invalid_map_checkpoints_are_not_resumable(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"])
    path = pathlib.Path(game.save_path)
    data = json.loads(path.read_text())
    data["run"]["current_node_id"] = "9-9"
    path.write_text(json.dumps(data))
    assert save_state.load_run(game.save_path) is None
