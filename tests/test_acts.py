"""Tests for multi-act runs -- beating an earlier act's boss clears it like
a floor, offers a pick-one boss relic, and moves the run onto a fresh,
deeper map; only the last act's boss is the endless score chase."""

import random

import pygame
import pytest
from conftest import finish_all_waves, make_linear_run_map, start_first_floor

from core.game import ACT_HEAL_LIVES, GameState
from persistence import save_state
from progression import achievements, meta_progression
from run import rewards, run_escalation
from run.card_pool import STARTER_TOWERS
from run.relics import RELICS
from run.run_map import ACT_COUNT, ROW_COUNT
from run.run_state import RunState


def _run_on(game, node_types, act=0, **overrides):
    kwargs = {
        "seed": 1, "map": make_linear_run_map(node_types), "difficulty": "normal",
        "unlocked_towers": list(STARTER_TOWERS), "act": act, "lives": 15,
    }
    kwargs.update(overrides)
    game.active_run = RunState(**kwargs)
    game._enter_map()
    return game.active_run


def _beat_act_boss(game, act=0):
    run = _run_on(game, ["combat", "boss"], act=act)
    run.visited_node_ids = ["0-0"]
    game._enter_node("1-0")
    assert game.wave_manager.endless is False
    finish_all_waves(game)
    game.update(dt=0.01)
    return run


def test_depth_counts_rows_across_acts():
    run = RunState(seed=1, map=make_linear_run_map(["combat", "combat"]), difficulty="normal",
                   unlocked_towers=[], current_node_id="1-0", act=2)
    assert run.depth == 2 * ROW_COUNT + 1
    assert run.depth_of(0) == 2 * ROW_COUNT


def test_floors_cleared_includes_prior_acts_and_beaten_act_bosses():
    run = RunState(seed=1, map=make_linear_run_map(["combat", "boss"]), difficulty="normal",
                   unlocked_towers=[], floors_cleared_prior_acts=4, visited_node_ids=["0-0", "1-0"])
    assert run.floors_cleared == 6


def test_an_earlier_acts_boss_clears_like_a_floor(game):
    run = _beat_act_boss(game)
    assert game.state == GameState.FLOOR_CLEARED
    assert run.visited_node_ids == ["0-0", "1-0"]
    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters["bosses_defeated"] == 1
    assert achievements.load_achievements(game.achievements_path)["counters"]["acts_cleared"] == 1
    game.render()  # "Act 1 cleared!" overlay


def test_act_boss_reward_is_a_pick_one_relic_choice_plus_a_potion(game):
    run = _beat_act_boss(game)
    game._handle_keydown(pygame.K_SPACE)

    assert game.state == GameState.REWARD
    assert game.reward.tower_choices == ()
    assert len(game.reward.boss_relic_choices) == rewards.BOSS_RELIC_CHOICES
    assert game.reward.potion is not None
    game.render()

    first = game._reward_cards().index(("boss_relic", game.reward.boss_relic_choices[0]))
    game._take_reward_card(first)
    game._take_reward_card(first + 1)  # forfeited -- only one boss relic

    assert run.relics == [game.reward.boss_relic_choices[0]]


def test_leaving_an_act_boss_reward_starts_the_next_act(game):
    run = _beat_act_boss(game)
    old_map = run.map
    lives = run.lives
    game._handle_keydown(pygame.K_SPACE)
    game._handle_keydown(pygame.K_RETURN)

    assert game.state == GameState.MAP
    assert run.act == 1
    assert run.map is not old_map
    assert run.visited_node_ids == [] and run.current_node_id is None
    assert run.floors_cleared_prior_acts == 2
    assert run.floors_cleared == 2
    assert run.lives == lives + ACT_HEAL_LIVES
    assert any("Act 2 begins" in toast.text for toast in game.achievement_toasts)
    game.render()


def test_a_later_acts_first_node_keeps_the_runs_lives(game):
    run = _run_on(game, ["combat", "combat"], act=1, lives=7)
    game._enter_node("0-0")
    assert game.economy.lives == 7 == run.lives


def test_later_acts_escalate_from_their_whole_run_depth(game):
    _run_on(game, ["combat", "combat"], act=0)
    game._enter_node("0-0")
    act_one_hp = game.wave_manager.enemy_hp_multiplier

    _run_on(game, ["combat", "combat"], act=1)
    game._enter_node("0-0")

    expected = run_escalation.escalation_for_floor(ROW_COUNT).enemy_hp_multiplier
    assert game.wave_manager.enemy_hp_multiplier > act_one_hp
    assert game.wave_manager.enemy_hp_multiplier == pytest.approx(expected)  # "normal" difficulty is 1.0x


def test_run_rng_folds_in_the_act_only_after_act_one():
    from core.game import Game

    act_zero = RunState(seed=5, map=make_linear_run_map(["combat"]), difficulty="normal", unlocked_towers=[])
    act_one = RunState(seed=5, map=make_linear_run_map(["combat"]), difficulty="normal", unlocked_towers=[], act=1)
    assert Game._run_rng(None, act_zero, "s", "0-0").random() == random.Random("5:s:0-0").random()
    assert Game._run_rng(None, act_one, "s", "0-0").random() != Game._run_rng(None, act_zero, "s", "0-0").random()


def test_the_final_acts_boss_is_still_endless(game):
    _run_on(game, ["combat", "boss"], act=ACT_COUNT - 1)
    game._enter_node("1-0")
    assert game.wave_manager.endless is True
    game.render()


def test_act_survives_save_and_resume(game):
    _run_on(game, ["combat", "combat"], act=1, floors_cleared_prior_acts=5)
    game._enter_node("0-0")
    game.save_run()

    game.resume_saved_run(save_state.load_run(game.save_path))

    assert game.active_run.act == 1
    assert game.active_run.floors_cleared_prior_acts == 5


def test_a_save_with_an_out_of_range_act_is_not_resumable(game):
    _run_on(game, ["combat", "combat"], act=ACT_COUNT)
    game._enter_node("0-0")
    game.save_run()
    assert save_state.load_run(game.save_path) is None


def test_boss_reward_degrades_to_potion_only_once_every_relic_is_held(tmp_path):
    run = RunState(seed=1, map=make_linear_run_map(["boss"]), difficulty="normal",
                   unlocked_towers=[], relics=list(RELICS))
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=False, meta_progression_path=str(tmp_path / "m.json"), is_boss=True,
    )
    assert reward.boss_relic_choices == ()
    assert reward.potion is not None and not reward.is_empty


def test_an_ordinary_floor_reward_still_returns_to_the_map(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._handle_keydown(pygame.K_SPACE)
    game._leave_reward_screen()
    assert game.state == GameState.MAP
    assert game.active_run.act == 0


def _final_boss(game):
    run = _run_on(game, ["combat", "boss"], act=ACT_COUNT - 1)
    game._enter_node("1-0")
    return run


def test_endless_score_counts_waves_past_the_authored_ones(game):
    from world.levels import LEVELS

    run = _final_boss(game)
    authored = len(LEVELS[run.current_level_id].wave_specs)
    game.wave_manager.wave_index = authored - 1
    game._update_endless_score()
    assert run.endless_waves_cleared == 0
    game.wave_manager.wave_index = authored + 3
    game._update_endless_score()
    assert run.endless_waves_cleared == 3
    game.wave_manager.wave_index = authored + 1  # a restart can't lower (or farm) it
    game._update_endless_score()
    assert run.endless_waves_cleared == 3


def test_endless_score_ignores_ordinary_floors(game):
    run = _run_on(game, ["combat", "combat"])
    game._enter_node("0-0")
    game.wave_manager.wave_index = 99
    game._update_endless_score()
    assert run.endless_waves_cleared == 0


def test_endless_score_is_saved_shown_and_recorded(game):
    from presentation import ui
    from progression import run_history

    run = _final_boss(game)
    run.endless_waves_cleared = 4
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_run.endless_waves_cleared == 4
    assert "+4 endless waves" in ui.run_summary_lines(game.active_run)[0]
    game.economy.lives = 0
    game.update(dt=0.01)
    assert run_history.load_run_records(game.run_history_path)[0]["endless_waves"] == 4
    assert "+4 endless" in ui.run_history_lines({}, run_history.load_run_records(game.run_history_path))[0]
