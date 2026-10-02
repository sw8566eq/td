"""Tests for Ascension -- run/ascension.py's stacked rule table, its
meta-progression unlock, the menu selector, and every point Game applies
an active run's ascension."""

import pygame
import pytest
from conftest import finish_all_waves, make_linear_run_map

from core.game import GameState
from persistence import save_state
from progression import meta_progression
from run import ascension, rewards, run_map
from run.ascension import ASCENSION_LEVELS, MAX_ASCENSION, AscensionModifiers
from run.card_pool import STARTER_TOWERS
from run.run_escalation import FloorEscalation
from run.run_state import RunState
from run.shop import ShopItem, price_for


def test_ascension_zero_is_a_no_op():
    assert ascension.modifiers_for(0) == AscensionModifiers()
    escalation = FloorEscalation(enemy_hp_multiplier=1.3)
    assert ascension.apply_to_escalation(escalation, 0, "combat") == escalation


def test_every_level_adds_exactly_one_described_rule():
    assert len(ASCENSION_LEVELS) == MAX_ASCENSION
    for level in ASCENSION_LEVELS:
        assert level.description and len(level.changes) == 1
        for name in level.changes:
            assert hasattr(AscensionModifiers(), name)


def test_rules_stack_multiplicatively_and_the_reward_delta_additively():
    top = ascension.modifiers_for(MAX_ASCENSION)
    assert top.enemy_hp_multiplier == pytest.approx(1.1 * 1.1)
    assert top.reward_tower_count_delta == -1
    assert isinstance(top.reward_tower_count_delta, int)
    assert ascension.modifiers_for(1).enemy_hp_multiplier == 1.0
    assert ascension.modifiers_for(1).elite_hp_multiplier == 1.2


def test_apply_to_escalation_singles_out_elite_and_boss_hp():
    base = FloorEscalation()
    combat = ascension.apply_to_escalation(base, MAX_ASCENSION, "combat")
    elite = ascension.apply_to_escalation(base, MAX_ASCENSION, "elite")
    boss = ascension.apply_to_escalation(base, MAX_ASCENSION, "boss")
    assert elite.enemy_hp_multiplier == pytest.approx(combat.enemy_hp_multiplier * 1.2)
    assert boss.enemy_hp_multiplier == pytest.approx(combat.enemy_hp_multiplier * 1.25)
    assert combat.enemy_speed_multiplier == pytest.approx(1.08)
    assert combat.starting_gold_multiplier == pytest.approx(0.9)


def test_clamp():
    assert ascension.clamp(-3) == 0
    assert ascension.clamp(99) == MAX_ASCENSION
    assert ascension.clamp(4) == 4


def test_meta_progression_unlock_only_ever_raises(tmp_path):
    path = str(tmp_path / "meta.json")
    assert meta_progression.highest_unlocked_ascension(path) == 0
    meta_progression.unlock_ascension(3, path)
    meta_progression.unlock_ascension(2, path)
    assert meta_progression.highest_unlocked_ascension(path) == 3


# --- Game integration ---


def _ascended_run(game, node_types, level, **overrides):
    kwargs = {
        "seed": 1, "map": make_linear_run_map(node_types), "difficulty": "normal",
        "unlocked_towers": list(STARTER_TOWERS), "ascension": level,
    }
    kwargs.update(overrides)
    game.active_run = RunState(**kwargs)
    game._enter_map()
    return game.active_run


def test_start_new_run_uses_the_selection_clamped_to_what_is_unlocked(game):
    game.highest_ascension = 4
    game.selected_ascension = 3
    game.start_new_run(seed=1)
    assert game.active_run.ascension == 3

    game.selected_ascension = 9  # stale, above what's unlocked
    game.start_new_run(seed=1)
    assert game.active_run.ascension == 4


def test_daily_run_is_always_ascension_zero(game):
    game.highest_ascension = game.selected_ascension = 5
    game.start_new_run(seed=1, is_daily=True)
    assert game.active_run.ascension == 0


def test_menu_left_right_changes_the_selection_within_bounds(game):
    game.highest_ascension, game.selected_ascension = 2, 2
    game._handle_keydown(pygame.K_RIGHT)
    assert game.selected_ascension == 2
    game._handle_keydown(pygame.K_LEFT)
    game._handle_keydown(pygame.K_LEFT)
    game._handle_keydown(pygame.K_LEFT)
    assert game.selected_ascension == 0
    assert game.state == GameState.MENU  # never starts a run
    game.render()
    game.selected_ascension = 2
    game.render()


def test_ascension_raises_enemy_hp_on_a_floor(game):
    _ascended_run(game, ["combat", "combat"], 0)
    game._enter_node("0-0")
    plain = game.wave_manager.enemy_hp_multiplier

    _ascended_run(game, ["combat", "combat"], MAX_ASCENSION)
    game._enter_node("0-0")

    assert game.wave_manager.enemy_hp_multiplier == pytest.approx(plain * 1.21)


def test_ascension_six_starts_the_run_with_fewer_lives(game):
    _ascended_run(game, ["combat", "combat"], 0)
    game._enter_node("0-0")
    plain_lives = game.economy.lives

    run = _ascended_run(game, ["combat", "combat"], 6)
    game._enter_node("0-0")

    assert run.lives == game.economy.lives == round(plain_lives * 0.75)


def test_ascension_five_heals_less_at_rest(game):
    _ascended_run(game, ["combat", "rest"], 5)
    game._enter_node("1-0")
    assert game.rest_heal_amount == round(run_map.heal_amount_for_row(1) * 0.6)


def test_ascension_eight_raises_shop_prices(game):
    _ascended_run(game, ["combat", "shop"], 8)
    assert game._shop_price_multiplier() == pytest.approx(1.25)
    item = ShopItem("relic", "lucky_strikes", 10)
    assert price_for(item, 0, game._shop_price_multiplier()) > price_for(item, 0)


def test_ascension_nine_offers_one_fewer_reward_tower(game, monkeypatch):
    from entities.tower import TOWER_TYPES
    from run import card_pool

    monkeypatch.setattr(card_pool, "_default_unlocked_pool", lambda _path: list(TOWER_TYPES))
    _ascended_run(game, ["combat", "combat"], 9)
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    game._handle_keydown(pygame.K_SPACE)

    assert len(game.reward.tower_choices) == rewards.TOWER_REWARD_COUNT - 1


def test_beating_the_boss_unlocks_the_next_ascension_once(game):
    run = _ascended_run(game, ["combat", "boss"], 2)
    game.highest_ascension = game.selected_ascension = 2
    run.current_node_id = "0-0"

    game._handle_boss_defeated()

    assert game.highest_ascension == 3
    assert game.selected_ascension == 3
    assert meta_progression.highest_unlocked_ascension(game.meta_progression_path) == 3
    assert any("Ascension 3 unlocked" in toast.text for toast in game.achievement_toasts)


def test_beating_the_boss_below_your_highest_unlocks_nothing_new(game):
    _ascended_run(game, ["combat", "boss"], 1)
    game.highest_ascension, game.selected_ascension = 5, 1
    game._handle_boss_defeated()
    assert game.highest_ascension == 5
    assert game.selected_ascension == 1


@pytest.mark.parametrize("overrides", [{"is_daily": True}, {"ascension": MAX_ASCENSION}])
def test_daily_runs_and_the_top_level_unlock_nothing(game, overrides):
    kwargs = {"ascension": 0, **overrides}
    level = kwargs.pop("ascension")
    _ascended_run(game, ["combat", "boss"], level, **kwargs)
    game.highest_ascension = level
    game._handle_boss_defeated()
    assert game.highest_ascension == level


def test_ascension_survives_save_and_resume_and_shows_in_the_hud(game):
    _ascended_run(game, ["combat", "combat"], 7)
    game._enter_node("0-0")
    game.render()
    game.save_run()

    game.resume_saved_run(save_state.load_run(game.save_path))

    assert game.active_run.ascension == 7


def test_a_save_with_an_out_of_range_ascension_is_not_resumable(game):
    _ascended_run(game, ["combat", "combat"], MAX_ASCENSION + 1)
    game._enter_node("0-0")
    game.save_run()
    assert save_state.load_run(game.save_path) is None


def test_map_screen_renders_with_an_ascension_title(game):
    _ascended_run(game, ["combat", "combat"], 3)
    game.render()
