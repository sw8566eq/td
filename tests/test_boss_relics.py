"""Tests for boss relics (relics.Relic.is_boss_relic) -- offered only on
an act boss's reward, each pairing an upside with a real downside."""

import random

import pygame
from conftest import make_linear_run_map

from run import potions, relics, rewards, shop
from run.card_pool import STARTER_TOWERS
from run.relics import BOSS_RELICS, RELICS
from run.run_state import RunState


def _run(**overrides):
    kwargs = {"seed": 1, "map": make_linear_run_map(["combat", "rest", "combat"]), "difficulty": "normal",
              "unlocked_towers": list(STARTER_TOWERS), "lives": 10}
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_boss_relics_describe_themselves_and_stay_out_of_normal_offers(tmp_path):
    assert len(BOSS_RELICS) >= 5
    for key in BOSS_RELICS:
        assert RELICS[key].description.startswith("Boss relic: ")
    path = str(tmp_path / "m.json")
    for seed in range(30):
        assert not set(relics.relic_offer(random.Random(seed), _run(), count=10, meta_progression_path=path)) & set(BOSS_RELICS)


def test_boss_relic_offer_prefers_boss_relics_then_tops_up(tmp_path):
    path = str(tmp_path / "m.json")
    offer = relics.boss_relic_offer(random.Random(1), _run(), 3, meta_progression_path=path)
    assert len(offer) == 3 and set(offer) <= set(BOSS_RELICS)
    nearly_all = _run(relics=BOSS_RELICS[:-1])
    offer = relics.boss_relic_offer(random.Random(1), nearly_all, 3, meta_progression_path=path)
    assert offer[0] == BOSS_RELICS[-1] and len(offer) == 3
    assert not set(offer[1:]) & set(BOSS_RELICS)


def test_act_boss_reward_offers_boss_relics(tmp_path):
    reward = rewards.build_combat_reward(random.Random(2), _run(), is_elite=False,
                                         meta_progression_path=str(tmp_path / "m"), is_boss=True)
    assert set(reward.boss_relic_choices) <= set(BOSS_RELICS)


def test_sealed_cask_blocks_new_potions_only():
    run = _run(relics=["sealed_cask"], potions=["fire_bomb"])
    assert not potions.has_free_slot(run)


def test_overcharged_core_blocks_resting_but_not_smithing(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "rest"], relics=["overcharged_core"], lives=10)
    game._enter_node("1-0")
    assert game.rest_heal_blocked
    game.render()
    game._choose_rest_option(0)
    assert game.rest_phase == "choose" and run.lives == 10
    game._choose_rest_option(1)
    assert game.rest_phase == "smith"


def test_gilded_ledger_stops_floor_income(game):
    from conftest import finish_all_waves
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], relics=["gilded_ledger"], lives=10)
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    assert run.shop_currency == 0
    assert shop.income_for_floor(0, 0) > 0  # it really is the relic


def test_reckless_arsenal_costs_lives_but_never_the_last_one(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], lives=10)
    game._grant_relic("reckless_arsenal")
    assert run.lives == 5
    run.relics.remove("reckless_arsenal")
    run.lives = 3
    game._grant_relic("reckless_arsenal")
    assert run.lives == 1
    pygame.display.flip()


def test_rest_is_never_a_softlock_when_neither_rest_nor_smith_is_possible(game):
    from test_run import _begin_run_with_map

    from core.game import GameState

    run = _begin_run_with_map(game, ["combat", "rest"], relics=["overcharged_core"],
                              forged_towers=list(STARTER_TOWERS), lives=5)
    game._enter_node("1-0")
    game.render()
    game._handle_rest_click(game.rest_option_rects[2].center)  # Move on
    assert game.rest_phase == "resolved" and game.rest_moved_on
    game.render()
    game._handle_keydown(pygame.K_SPACE)
    assert game.state == GameState.MAP and run.lives == 5 and run.visited_node_ids == ["1-0"]
