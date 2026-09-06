"""Tests for the roguelike run loop -- the game's primary mode.

A run is a seeded sequence of floors (run_floors.py) played with a
run-scoped tower pool grown by drafting between floors, carrying gold and
lives forward, ending only by permadeath. This module covers that whole
lifecycle end to end: starting a run, loading and clearing floors, the
tower and relic drafts, permadeath and the run history it records,
meta-progression accumulating across runs, saving and resuming a run
mid-flight, the Daily Run, and Practice mode (the standalone,
deliberately run-less way to play a single level).

Game's own state machine/input/render tests are in test_game.py; shared
fixtures and helpers for both are in conftest.py.
"""

import pygame
import pytest

import achievements
import meta_progression
import progress
import run_history
import save_state
import shop
import ui
from card_pool import STARTER_TOWERS
from difficulty import DIFFICULTY_MODES
from game import GameState, _DRAFT_RNG_STREAM, _FLOOR_RNG_STREAM
from levels import LEVELS
from relics import RELICS
from shop import ShopItem
from tower import TOWER_TYPES

from conftest import (
    finish_all_waves,
    find_buildable_anchor,
    mock_mouse_pos,
    clear_mouse_mock,
)


# --- Starting a run ---


def test_start_new_run_populates_active_run_and_loads_floor_zero(game):
    game.start_new_run(seed=1)

    assert game.active_run is not None
    assert game.active_run.floor_index == 0
    assert game.active_run.unlocked_towers == list(STARTER_TOWERS)
    assert game.current_level_id == game.active_run.floor_sequence[0]
    assert game.state == GameState.PLAYING


def test_start_new_run_captures_floor_zeros_starting_lives(game):
    # No equivalent gold assertion -- battle gold is never captured onto
    # RunState at all any more (see CLAUDE.md's "Two currencies" section).
    game.start_new_run(seed=1)

    assert game.active_run.lives == game.economy.lives


def test_start_new_run_is_deterministic_for_a_fixed_seed(game):
    game.start_new_run(seed=1234)
    first_sequence = game.active_run.floor_sequence

    game.start_new_run(seed=1234)
    second_sequence = game.active_run.floor_sequence

    assert first_sequence == second_sequence


def test_start_new_run_without_a_seed_still_produces_a_playable_run(game):
    game.start_new_run()

    assert game.active_run.seed is not None
    assert game.state == GameState.PLAYING


# --- The run-scoped tower pool (what the build menu offers) ---


def test_starting_a_run_restricts_the_build_menu_to_the_starter_towers(game):
    game.start_new_run(seed=1)
    assert set(game.button_rects.keys()) == set(STARTER_TOWERS)


def test_try_place_tower_rejects_a_tower_not_in_the_active_runs_pool(game):
    game.start_new_run(seed=1)
    anchor_col, anchor_row = find_buildable_anchor(game)
    # Bypasses the build menu entirely -- selected_tower_name would never
    # actually reach this value through a real click, since button_rects
    # only ever offers _active_tower_names() (see try_place_tower's own
    # defense-in-depth comment).
    game.selected_tower_name = "sniper"  # not in STARTER_TOWERS

    assert game.try_place_tower(anchor_col, anchor_row) is False
    assert game.grid.get_tower(anchor_col, anchor_row) is None


def test_a_classic_level_load_restores_the_full_build_menu(game):
    game.start_new_run(seed=1)
    game.load_level(1)
    assert set(game.button_rects.keys()) == set(TOWER_TYPES.keys())


def test_any_direct_load_level_object_call_restores_the_full_build_menu(game):
    # Regression guard: the build-menu reset lives inside _load_level_object
    # itself (see its own comment), not hand-repeated at every wrapper that
    # calls it -- so this holds even for reset()/advance_or_replay_level()'s
    # own direct _load_level_object() calls for a custom/playtested level,
    # not just the load_level/load_custom_level/resume_saved_run/
    # _start_daily_challenge/_load_floor call sites that have their own
    # test coverage above.
    game.start_new_run(seed=1)
    game._load_level_object(LEVELS[1])
    assert set(game.button_rects.keys()) == set(TOWER_TYPES.keys())


# --- Leaving a run: any level load outside one clears it ---


def test_a_classic_level_load_clears_any_active_run(game):
    game.start_new_run(seed=1)
    assert game.active_run is not None

    game.load_level(1)

    assert game.active_run is None


def test_a_custom_level_load_clears_any_active_run(game):
    game.start_new_run(seed=1)
    game.load_custom_level(LEVELS[1])
    assert game.active_run is None


def test_starting_a_daily_run_replaces_any_active_run(game):
    # Unlike load_level/load_custom_level (which clear out to a non-run
    # classic load), _start_daily_challenge is itself a run entry point --
    # starting one replaces whatever run/floor a player was previously on
    # with a fresh Daily Run, rather than clearing active_run to None.
    game.start_new_run(seed=1)

    game._start_daily_challenge(seed=20260101)

    assert game.active_run is not None
    assert game.active_run.seed == 20260101
    assert game.active_run.is_daily is True


def test_resuming_a_saved_classic_run_clears_any_active_run(playing_game):
    # Regression guard: active_run is reset inside _load_level_object
    # itself (the one choke point every loader funnels through) precisely
    # so a caller like resume_saved_run -- which never mentions active_run
    # at all -- can't leak a stale RunState from an unrelated earlier run
    # into a resumed classic save.
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)
    playing_game.start_new_run(seed=1)

    playing_game.resume_saved_run(save_data)

    assert playing_game.active_run is None


# --- Clearing a floor ---


def test_floor_clear_enters_floor_cleared_and_captures_lives_and_shop_currency(game):
    game.start_new_run(seed=1)
    # Distinct from whatever floor 0's own authored starting_lives happens
    # to be -- proves this came from the run, not from _load_level_object's
    # usual per-level defaults. Battle gold is deliberately NOT carried the
    # same way (see CLAUDE.md's "Two currencies" section) -- instead it
    # converts into shop currency (see shop.income_for_floor), asserted
    # below via that exact formula rather than a hardcoded number, so this
    # test doesn't silently drift from shop.py's own tuning.
    game.economy.gold = 9999
    game.economy.lives = 3
    finish_all_waves(game)

    game.update(dt=0.01)

    # The next floor isn't loaded yet -- that only happens once the player
    # leaves the shop (see below) -- so floor_index/self.economy still
    # reflect the floor just cleared.
    assert game.state == GameState.FLOOR_CLEARED
    assert game.active_run.floor_index == 0
    assert game.active_run.lives == 3
    assert game.active_run.shop_currency == shop.income_for_floor(0, 9999)


def test_floor_clear_never_reaches_classic_victory(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    assert game.state != GameState.VICTORY
    assert game.state == GameState.FLOOR_CLEARED


def test_floor_cleared_any_key_enters_draft(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)

    game._handle_keydown(pygame.K_SPACE)

    assert game.state == GameState.DRAFT
    assert len(game.draft_choices) == len(game.draft_choice_rects)
    assert game.draft_choices  # STARTER_TOWERS isn't the whole registry yet


def test_floor_cleared_escape_quits(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.FLOOR_CLEARED

    game._handle_keydown(pygame.K_ESCAPE)

    assert game.running is False


def test_last_floor_of_a_run_loads_endless(game):
    game.start_new_run(seed=1)
    last_index = len(game.active_run.floor_sequence) - 1

    game._load_floor(last_index)

    assert game.wave_manager.endless is True


def test_escalation_composes_with_difficulty_rather_than_replacing_it(game):
    # The run-loop equivalent of test_game.py's own
    # test_hard_difficulty_yields_fewer_starting_lives_and_tougher_enemies_than_easy
    # -- one integration test proving the wiring multiplies
    # mode.X * escalation.X rather than one replacing the other;
    # escalation_for_floor's own formula (no-op at floor 0, strictly
    # increasing after) is already exhaustively covered by
    # tests/test_run_escalation.py, so it isn't re-proven here.
    game.difficulty = "hard"
    game.start_new_run(seed=1)
    game._load_floor(3)

    from run_escalation import escalation_for_floor

    hard = DIFFICULTY_MODES["hard"]
    escalation = escalation_for_floor(3)
    assert game.wave_manager.enemy_hp_multiplier == hard.enemy_hp_multiplier * escalation.enemy_hp_multiplier
    assert game.wave_manager.enemy_speed_multiplier == hard.enemy_speed_multiplier * escalation.enemy_speed_multiplier
    assert game.wave_manager.enemy_gold_multiplier == hard.enemy_gold_multiplier * escalation.enemy_gold_multiplier


def test_clearing_a_floor_records_the_level_as_cleared(game):
    # A cleared floor is a genuinely cleared level, and in normal play it
    # is now the *only* way progress.py is ever written: a run never
    # reaches the classic VICTORY branch (see
    # test_floor_clear_never_reaches_classic_victory) and Practice is
    # always sandbox (see that section below), so before
    # Game._record_level_cleared() existed, nothing recorded progress at
    # all.
    game.start_new_run(seed=1)
    level_id = game.current_level_id
    game.economy.lives = 7
    finish_all_waves(game)

    game.update(dt=0.01)

    assert progress.load_progress(game.progress_path) == {level_id: 7}


def test_clearing_a_floor_bumps_the_level_clear_achievement_counters(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    counters = achievements.load_achievements(game.achievements_path)["counters"]
    assert counters["levels_cleared"] == 1
    assert counters["distinct_levels_cleared"] == 1


def test_distinct_levels_cleared_counts_a_repeated_level_once_across_runs(game):
    # levels_cleared is a naive +1 per clear; distinct_levels_cleared is
    # re-derived from progress.py's own keys each time, which is what keeps
    # "Campaign Complete" from being farmable by replaying one floor -- see
    # achievements.py's own note on the two counters. A fixed seed samples
    # the same floor sequence twice (see run_floors.sample_floor_sequence),
    # so both runs clear the identical level.
    for _ in range(2):
        game.start_new_run(seed=1)
        finish_all_waves(game)
        game.update(dt=0.01)

    counters = achievements.load_achievements(game.achievements_path)["counters"]
    assert counters["levels_cleared"] == 2
    assert counters["distinct_levels_cleared"] == 1
    assert len(progress.load_progress(game.progress_path)) == 1


def test_progress_earned_in_a_run_persists_across_a_fresh_game_instance(game):
    game.start_new_run(seed=1)
    level_id = game.current_level_id
    finish_all_waves(game)
    game.update(dt=0.01)

    # progress.json is a plain file on disk -- Game keeps no in-memory copy
    # of it (see _record_level_cleared's own docstring), so proving this
    # persists means reading the file itself, not some other Game
    # instance's cached attribute.
    assert level_id in progress.load_progress(game.progress_path)


# --- Restarting mid-run (the pause menu's "Restart Level") ---


def test_restarting_mid_run_reloads_the_current_floor_without_discarding_the_run(playing_game):
    # Regression guard: reset() used to call _load_level_object() with no
    # active_run at all (its own default), silently discarding the entire
    # run -- drafted tower pool, relics, carried gold/lives, floor
    # position -- and dropping the player into a plain classic reload of
    # whatever level they happened to be on, with no warning shown.
    playing_game.start_new_run(seed=1)
    playing_game._load_floor(2)
    run_before = playing_game.active_run
    playing_game.towers = ["fake"]
    playing_game.economy.gold = 999999
    playing_game.state = GameState.PAUSED  # reset()'s own restart-the-run branch checks this directly

    playing_game.reset()

    assert playing_game.active_run is run_before  # same RunState, not discarded
    assert playing_game.active_run.floor_index == 2  # still on the floor it restarted
    assert playing_game.current_level_id == run_before.floor_sequence[2]
    assert playing_game.towers == []  # the floor itself still reloads fresh
    assert set(playing_game.button_rects.keys()) == set(run_before.unlocked_towers)  # menu stays run-narrowed
    # Regression guard: reset()'s own trailing "classic reload" branch
    # used to unconditionally set self.state = MENU afterward, clobbering
    # _load_floor()'s own PLAYING right back to MENU -- harmless for
    # reset()'s two real callers (both reassign PLAYING themselves right
    # after), but wrong for a direct call like this one.
    assert playing_game.state == GameState.PLAYING


def test_restarting_mid_run_restores_the_floors_own_starting_gold_and_lives(playing_game):
    # A restart discards whatever was spent/earned since this floor began,
    # same as any other "Restart Level" -- reloading a floor recomputes its
    # own starting gold fresh every time now (see CLAUDE.md's "Two
    # currencies" section: battle gold never carries between floor loads at
    # all any more), and restores lives from the run's own carried-forward
    # value, not the level's raw starting_lives a classic reload would use.
    playing_game.start_new_run(seed=1)
    playing_game._load_floor(1)
    gold_at_floor_start = playing_game.economy.gold
    lives_at_floor_start = playing_game.active_run.lives
    playing_game.economy.gold = 1
    playing_game.economy.lives = 1
    playing_game.state = GameState.PAUSED  # reset()'s own restart-the-run branch checks this directly

    playing_game.reset()

    assert playing_game.economy.gold == gold_at_floor_start
    assert playing_game.economy.lives == lives_at_floor_start


def test_restarting_after_permadeath_does_not_resurrect_the_run(playing_game):
    # A run that's already ended by permadeath has nothing left to restart
    # *into* -- its outcome is already recorded (_record_run_permadeath),
    # so GAME_OVER's own R still falls through to a plain, run-less reload,
    # same as it always has, rather than letting the player undo their
    # death for free.
    playing_game.start_new_run(seed=1)
    playing_game.economy.lives = 1
    playing_game.economy.lose_life()
    playing_game.update(dt=0.01)
    assert playing_game.state == GameState.GAME_OVER
    assert playing_game.active_run is not None  # _record_run_permadeath doesn't clear it

    playing_game.reset()

    assert playing_game.active_run is None


# --- The Shop: buying tower/relic cards between floors ---


def _force_relic_draft(game, relic_key):
    """Overrides whatever shop.build_offer() actually offered with a
    single forced relic choice, for tests that need to verify one specific
    relic's math rather than accept whichever ones a given seed happened to
    draw. Priced at 0 so the forced pick is always affordable regardless of
    shop_currency -- these tests are about the relic's own effect, not the
    shop's own economy (see tests/test_shop.py for that)."""
    game.draft_choices = [ShopItem("relic", relic_key, 0)]
    game.draft_choice_rects = ui.build_draft_choice_rects(1)
    game.shop_purchased_indices = set()


def test_buying_a_shop_item_then_continuing_advances_to_the_next_floor(game):
    game.start_new_run(seed=1)
    game.economy.lives = 3
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    picked = game.draft_choices[0]
    game.active_run.shop_currency = 9999  # affordability isn't this test's own concern

    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it

    assert 0 in game.shop_purchased_indices
    assert game.state == GameState.DRAFT  # buying alone doesn't leave the shop
    if picked.kind == "relic":
        assert picked.key in game.active_run.relics
    else:
        assert picked.key in game.active_run.unlocked_towers

    game._handle_draft_click(game.shop_continue_button_rect.center)  # leave the shop

    assert game.state == GameState.PLAYING
    assert game.active_run.floor_index == 1
    assert game.economy.lives == 3  # lives still carry from the just-cleared floor
    if picked.kind == "tower":
        assert picked.key in game.button_rects  # next floor's menu reflects the newly-bought tower


def test_buying_a_shop_item_deducts_its_escalated_price(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    assert len(game.draft_choices) >= 2  # a run this fresh always has at least 2 items to offer
    game.active_run.shop_currency = 9999
    first_price = shop.price_for(game.draft_choices[0], 0)
    second_price = shop.price_for(game.draft_choices[1], 1)  # escalated -- one purchase already made
    currency_before = game.active_run.shop_currency

    game._handle_draft_click(game.draft_choice_rects[0].center)
    assert game.active_run.shop_currency == currency_before - first_price

    game._handle_draft_click(game.draft_choice_rects[1].center)
    assert game.active_run.shop_currency == currency_before - first_price - second_price


def test_buying_an_unaffordable_shop_item_does_nothing(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    game.active_run.shop_currency = 0
    unlocked_before = list(game.active_run.unlocked_towers)
    relics_before = list(game.active_run.relics)

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert game.shop_purchased_indices == set()
    assert game.active_run.shop_currency == 0
    assert game.active_run.unlocked_towers == unlocked_before
    assert game.active_run.relics == relics_before


def test_unlimited_gold_makes_every_shop_item_free(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    game.economy.unlimited_gold = True
    game.active_run.shop_currency = 0

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert 0 in game.shop_purchased_indices
    assert game.active_run.shop_currency == 0  # never actually deducted, same as battle gold


def test_clicking_a_purchased_item_again_does_nothing(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    game.active_run.shop_currency = 9999
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it
    currency_after_first_buy = game.active_run.shop_currency

    game._handle_draft_click(game.draft_choice_rects[0].center)  # click the same, now-SOLD card again

    assert game.active_run.shop_currency == currency_after_first_buy


def test_clicking_off_a_draft_card_does_nothing(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    unlocked_before = list(game.active_run.unlocked_towers)

    game._handle_draft_click((0, 0))  # nowhere near any card or the Continue button

    assert game.state == GameState.DRAFT
    assert game.active_run.unlocked_towers == unlocked_before


def test_continue_button_advances_without_buying_anything(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    unlocked_before = list(game.active_run.unlocked_towers)
    relics_before = list(game.active_run.relics)

    game._handle_draft_click(game.shop_continue_button_rect.center)

    assert game.state == GameState.PLAYING
    assert game.active_run.floor_index == 1
    assert game.active_run.unlocked_towers == unlocked_before
    assert game.active_run.relics == relics_before


def test_draft_escape_quits(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    assert game.state == GameState.DRAFT

    game._handle_keydown(pygame.K_ESCAPE)

    assert game.running is False


def test_enter_draft_skips_the_shop_screen_once_both_pools_are_exhausted(game):
    game.start_new_run(seed=1)
    game.active_run.unlocked_towers = list(TOWER_TYPES.keys())  # every tower already unlocked
    game.active_run.relics = list(RELICS.keys())  # every relic already held
    finish_all_waves(game)
    game.update(dt=0.01)

    game._enter_draft()

    assert game.state == GameState.PLAYING
    assert game.active_run.floor_index == 1


def test_enter_draft_still_shows_up_with_only_relics_left_to_offer(game):
    # Regression guard: the old draft screen could fall all the way through
    # to PLAYING if towers specifically were exhausted (see _is_relic_floor's
    # former fallback logic) -- the Shop must still show up as long as
    # *either* pool has something left, since it offers both together now.
    game.start_new_run(seed=1)
    game.active_run.unlocked_towers = list(TOWER_TYPES.keys())  # every tower already unlocked
    finish_all_waves(game)
    game.update(dt=0.01)

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert all(item.kind == "relic" for item in game.draft_choices)


def test_run_seed_reproduces_the_same_shop_offer(game):
    # Floor-sequence reproducibility for a fixed seed is already covered by
    # test_start_new_run_is_deterministic_for_a_fixed_seed above -- this
    # covers the one additional fact that test can't: the shop offer itself
    # (derived via _run_rng, only reachable through Game) reproduces too, so
    # two players on the same seed see the same items.
    game.start_new_run(seed=99)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    first_offer = list(game.draft_choices)

    game.start_new_run(seed=99)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    second_offer = list(game.draft_choices)

    assert first_offer == second_offer


def test_enter_draft_uses_shop_build_offer(game, monkeypatch):
    # A thin wiring test: _enter_draft delegates entirely to shop.
    # build_offer for what to show, rather than assembling its own list --
    # towers and relics can come back mixed together in one offer now (see
    # shop.build_offer's own tests for that mixing behavior in isolation).
    game.start_new_run(seed=1)
    fake_offer = [ShopItem("tower", "sniper", 8), ShopItem("relic", "war_chest", 10)]
    monkeypatch.setattr(shop, "build_offer", lambda rng, run, meta_progression_path=None: fake_offer)

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert game.draft_choices == fake_offer
    assert len(game.draft_choice_rects) == len(fake_offer)


def test_floor_and_draft_rng_streams_dont_collide_even_for_a_zero_seed(game):
    # Regression guard: _run_rng used to derive both streams as
    # seed * stream + floor_index, which degenerates to plain floor_index
    # for *every* stream whenever seed == 0 -- start_new_run(seed=0) is
    # directly reachable, and even an unseeded run has a real (if tiny)
    # chance of drawing it -- silently collapsing the floor-routing and
    # draft-pick rng onto the exact same sequence.
    game.start_new_run(seed=0)
    run = game.active_run

    floor_rng = game._run_rng(run, _FLOOR_RNG_STREAM, 3)
    draft_rng = game._run_rng(run, _DRAFT_RNG_STREAM, 3)

    assert floor_rng.random() != draft_rng.random()


# --- Relic effects bought from the shop, and the modifiers they compose in ---


def test_relic_gold_per_floor_bonus_is_applied_on_every_floor_load(game):
    game.start_new_run(seed=1)
    game._load_floor(1)
    gold_without_relic = game.economy.gold

    game.start_new_run(seed=1)
    game.active_run.relics = ["prospectors_charm"]
    game._load_floor(1)

    assert game.economy.gold == gold_without_relic + RELICS["prospectors_charm"].gold_per_floor_bonus


def test_misers_coffer_bonus_stops_after_the_runs_first_spend(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["misers_coffer"]
    game._load_floor(0)
    gold_with_bonus = game.economy.gold

    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)  # this run's first spend

    assert game.active_run.has_spent_gold is True

    game._load_floor(0)  # restart the same floor -- re-derives relic_modifiers fresh

    assert game.economy.gold == gold_with_bonus - RELICS["misers_coffer"].gold_per_floor_bonus_while_unspent


def test_war_chest_multiplies_starting_gold_on_every_floor_not_just_once(game):
    # Regression guard for the redesign: war_chest used to be a one-time
    # bonus applied only at the moment it was bought (see relics.py's own
    # module docstring for the "why" -- back when battle gold carried
    # forward, "starting gold" only existed once, at floor 0). Now that
    # battle gold resets fresh every floor instead, it has to keep applying
    # on every single floor load, not just the one right after it's bought.
    game.start_new_run(seed=1)
    game._enter_draft()
    _force_relic_draft(game, "war_chest")
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> floor 1
    gold_floor_1 = game.economy.gold

    game._load_floor(2)
    gold_floor_2 = game.economy.gold

    mode = DIFFICULTY_MODES[game.active_run.difficulty]
    multiplier = RELICS["war_chest"].starting_gold_multiplier
    level_1 = LEVELS[game.active_run.floor_sequence[1]]
    level_2 = LEVELS[game.active_run.floor_sequence[2]]
    assert gold_floor_1 == round(level_1.starting_gold * mode.starting_gold_multiplier * multiplier)
    assert gold_floor_2 == round(level_2.starting_gold * mode.starting_gold_multiplier * multiplier)


def test_sturdy_gate_grants_a_one_time_lives_bonus_when_bought(game):
    game.start_new_run(seed=1)
    game._enter_draft()
    _force_relic_draft(game, "sturdy_gate")
    lives_before = game.active_run.lives

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert game.active_run.lives == lives_before + RELICS["sturdy_gate"].starting_lives_bonus


def test_relic_enemy_gold_multiplier_composes_into_wave_manager(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["bounty_hunters_ledger"]

    game._load_floor(0)

    assert game.wave_manager.enemy_gold_multiplier == RELICS["bounty_hunters_ledger"].enemy_gold_multiplier


def test_relic_enemy_speed_multiplier_composes_into_wave_manager(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["tangled_roots"]

    game._load_floor(0)

    assert game.wave_manager.enemy_speed_multiplier == RELICS["tangled_roots"].enemy_speed_multiplier


def test_spyglass_array_range_bonus_reaches_a_freshly_placed_tower(game):
    # Regression guard for the "no save_state.py schema changes needed"
    # claim: a tower-facing relic's bonus is re-derived fresh at
    # construction time (Game._construct_tower), not stored on RunState
    # itself -- so drafting the card, then placing a tower on a later
    # floor, must still see the bonus with no extra plumbing in between.
    game.start_new_run(seed=1)
    game._enter_draft()
    _force_relic_draft(game, "spyglass_array")
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> floor 1, relic_modifiers re-derived

    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_range_bonus_multiplier == RELICS["spyglass_array"].tower_range_multiplier


def test_resuming_a_run_rederives_a_placed_towers_relic_range_bonus(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["spyglass_array"]
    game._load_floor(0)  # re-derives self.relic_modifiers from the relics just set
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_range_bonus_multiplier == RELICS["spyglass_array"].tower_range_multiplier


def test_quickfire_rounds_fire_rate_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["quickfire_rounds"]
    game._load_floor(0)  # re-derives self.relic_modifiers from the relics just set
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_fire_rate_bonus_multiplier == RELICS["quickfire_rounds"].tower_fire_rate_multiplier


def test_overdrive_coils_damage_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["overdrive_coils"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_damage_bonus_multiplier == RELICS["overdrive_coils"].tower_damage_multiplier
    assert tower.relic_fire_rate_bonus_multiplier == RELICS["overdrive_coils"].tower_fire_rate_multiplier


def test_snipers_discipline_damage_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["snipers_discipline"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_damage_bonus_multiplier == RELICS["snipers_discipline"].tower_damage_multiplier
    assert tower.relic_fire_rate_bonus_multiplier == RELICS["snipers_discipline"].tower_fire_rate_multiplier


def test_veterans_momentum_damage_bonus_grows_with_floor_index(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["veterans_momentum"]
    game.active_run.floor_index = 3
    game._load_floor(3)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    growth = RELICS["veterans_momentum"].tower_damage_growth_per_floor
    assert tower.relic_damage_bonus_multiplier == pytest.approx(1.0 + growth * 3)


def test_venomous_coating_poison_chance_reaches_a_freshly_placed_towers_shots(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["venomous_coating"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    relic = RELICS["venomous_coating"]
    assert tower.relic_poison_chance == relic.poison_chance
    assert tower.relic_poison_effect == (relic.poison_damage_per_tick, relic.poison_tick_interval, relic.poison_duration)


def test_resuming_a_run_rederives_a_placed_towers_relic_poison_chance(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["venomous_coating"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_poison_chance == RELICS["venomous_coating"].poison_chance


def test_arcing_rounds_chain_chance_reaches_a_freshly_placed_towers_shots(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["arcing_rounds"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    relic = RELICS["arcing_rounds"]
    assert tower.relic_chain_chance == relic.chain_chance
    assert tower.relic_chain_effect == (relic.chain_damage_fraction, relic.chain_range)


def test_last_stand_charms_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["last_stand_charm"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_last_stand_bonus_multiplier == RELICS["last_stand_charm"].last_stand_damage_multiplier


def test_last_stand_charm_only_boosts_damage_while_down_to_the_last_life(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["last_stand_charm"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)
    tower = game.grid.get_tower(anchor_col, anchor_row)
    base_damage = tower.effective_damage()

    game.economy.lives = 2
    game.update(dt=0.01)
    assert tower.effective_damage() == base_damage  # not yet down to the last life

    game.economy.lives = 1
    game.update(dt=0.01)
    assert tower.effective_damage() == pytest.approx(
        base_damage * RELICS["last_stand_charm"].last_stand_damage_multiplier
    )

    game.economy.lives = 3  # a life regained turns the bonus back off
    game.update(dt=0.01)
    assert tower.effective_damage() == base_damage


def test_guardians_reprieve_saves_the_run_from_permadeath_once(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["guardians_reprieve"]
    game.economy.lives = 1
    game.wave_manager.skip_delay()
    game.update(dt=0.01)
    game.update(dt=0.1)
    enemy = game.enemies[0]

    enemy.wp_index = len(enemy.waypoints)  # force it to the end of the path
    game.update(dt=0.01)

    assert game.economy.lives == 1  # saved, not zeroed
    assert game.active_run.used_guardians_reprieve is True
    assert game.state != GameState.GAME_OVER

    # The charge is spent -- a second loss proceeds normally.
    game._lose_a_life()
    assert game.economy.lives == 0


def test_guardians_reprieve_does_nothing_in_sandbox_mode(game):
    # Sandbox's own invulnerable flag already makes lives never actually
    # drop -- Guardian's Reprieve has nothing to save there, and must not
    # burn its one-time charge on a leak that was never going to cost
    # anything anyway.
    game.start_new_run(seed=1)
    game.active_run.relics = ["guardians_reprieve"]
    game.economy.invulnerable = True
    game.economy.lives = 1

    game._lose_a_life()

    assert game.economy.lives == 1
    assert game.active_run.used_guardians_reprieve is False


def test_lucky_strikes_crit_chance_reaches_a_freshly_placed_towers_shots(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["lucky_strikes"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    relic = RELICS["lucky_strikes"]
    assert tower.relic_crit_chance == relic.crit_chance
    assert tower.relic_crit_damage_multiplier == relic.crit_damage_multiplier


def test_quartermasters_favor_discount_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["quartermasters_favor"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_upgrade_cost_multiplier == RELICS["quartermasters_favor"].tower_upgrade_cost_multiplier


def test_liquidation_rights_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["liquidation_rights"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_sell_refund_bonus == RELICS["liquidation_rights"].sell_refund_bonus


def test_resonant_field_bonus_reaches_a_freshly_placed_support_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["resonant_field"]
    game.active_run.unlocked_towers.append("support")  # a drafted card, not a starter tower
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = "support"

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    relic = RELICS["resonant_field"]
    assert tower.relic_aura_range_bonus_multiplier == relic.support_aura_range_multiplier
    assert tower.relic_aura_strength_bonus_multiplier == relic.support_aura_strength_multiplier


def test_compact_framework_shrinks_a_freshly_placed_towers_footprint(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["compact_framework"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    expected_size = 8 - RELICS["compact_framework"].tower_footprint_shrink
    assert tower.footprint_subtiles == expected_size
    assert len(game.grid.occupied_subtiles) == expected_size * expected_size


def test_resuming_a_run_rederives_a_placed_towers_footprint_size(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["compact_framework"]
    game._load_floor(0)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    tower = game.grid.get_tower(anchor_col, anchor_row)
    expected_size = 8 - RELICS["compact_framework"].tower_footprint_shrink
    assert tower.footprint_subtiles == expected_size


# --- Permadeath: the only way a run ends ---


def test_permadeath_ends_the_run_but_preserves_active_run_state(game):
    game.start_new_run(seed=1)
    seed = game.active_run.seed
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert game.active_run is not None
    assert game.active_run.seed == seed


def test_permadeath_in_sandbox_mode_records_no_run_history_or_meta_progress(game):
    # sandbox + an active run can't happen through any current UI path
    # (Practice never starts a run, start_new_run never sets sandbox) --
    # but resume_saved_run() restores both fields independently off a save
    # file with nothing enforcing they can't combine, so this stays
    # consistent with every other real-progress recorder in this codebase
    # (_record_achievement/_record_meta_progress/_record_level_cleared)
    # rather than leaving one silent gap that would trivialize a sandboxed
    # run's outcome into real run history.
    game.start_new_run(seed=1)
    game.sandbox = True
    game.economy.lives = 1

    game.economy.lose_life()
    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert run_history.load_run_history(game.run_history_path) == {}
    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters.get("runs_played", 0) == 0


def test_permadeath_bumps_runs_played_and_records_run_history(game):
    game.start_new_run(seed=1)
    seed = game.active_run.seed
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    assert meta_progression.load_meta_progression(game.meta_progression_path)["counters"]["runs_played"] == 1
    assert run_history.load_run_history(game.run_history_path) == {seed: 0}


def test_run_history_records_floors_cleared_at_time_of_death(game):
    game.start_new_run(seed=1)
    seed = game.active_run.seed
    finish_all_waves(game)
    game.update(dt=0.01)  # clears floor 0 -> FLOOR_CLEARED
    game._enter_draft()
    game.active_run.shop_currency = 9999
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy an item
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> floor 1, PLAYING
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    assert run_history.load_run_history(game.run_history_path) == {seed: 1}


def test_permadeath_on_a_non_final_floor_does_not_bump_runs_reached_endless(game):
    game.start_new_run(seed=1)
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters.get("runs_reached_endless", 0) == 0


def test_permadeath_on_the_final_floor_bumps_runs_reached_endless(game):
    game.start_new_run(seed=1)
    last_index = len(game.active_run.floor_sequence) - 1
    game._load_floor(last_index)
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters["runs_reached_endless"] == 1


# --- Meta-progression accumulating across runs ---


def test_floor_clear_bumps_total_floors_cleared(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters["total_floors_cleared"] == 1


def test_first_floor_clear_unlocks_a_tower_and_it_appears_in_the_draft(game):
    # Regression guard: unlock_knockback's goal is 1 specifically so a
    # brand new player's very first floor clear already has something to
    # draft -- see meta_progression.py's own comment on why.
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert any(item.key == "knockback" for item in game.draft_choices)


def test_first_floor_clear_queues_a_new_tower_unlocked_toast(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    assert any("New tower unlocked" in toast.text for toast in game.achievement_toasts)


# --- Saving and resuming a run mid-flight ---


def test_saving_mid_run_captures_the_active_run(game):
    game.start_new_run(seed=1)
    run_before = game.active_run

    assert game.save_run() is True
    saved = save_state.load_run(game.save_path)

    assert saved["run"].seed == run_before.seed
    assert saved["run"].floor_sequence == run_before.floor_sequence
    assert saved["run"].unlocked_towers == run_before.unlocked_towers
    assert saved["run"].floor_index == run_before.floor_index
    assert saved["run"].shop_currency == run_before.shop_currency
    assert saved["run"].lives == run_before.lives


def test_resuming_a_saved_run_restores_active_run(game):
    game.start_new_run(seed=1)
    game.active_run.unlocked_towers.append("sniper")  # a drafted card, carried across floors
    game.active_run.shop_currency = 42  # a run-level field, distinct from economy.gold below
    # economy.gold is never re-synced onto RunState at all now -- battle
    # gold doesn't carry between floors any more (see CLAUDE.md's "Two
    # currencies" section) -- so a save taken mid-floor genuinely captures
    # numbers from two unrelated places here: economy.gold (350 after this)
    # is what a resume should restore live play to; active_run.shop_
    # currency (42) is this run's own separately-persisted currency,
    # untouched by this frame's battle-gold spending.
    game.economy.gold += 200
    run_before = game.active_run
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    assert game.active_run is not run_before  # a fresh RunState, reconstructed from disk
    assert game.active_run.seed == run_before.seed
    assert game.active_run.floor_sequence == run_before.floor_sequence
    assert game.active_run.unlocked_towers == run_before.unlocked_towers
    assert game.active_run.floor_index == run_before.floor_index
    assert game.active_run.shop_currency == run_before.shop_currency
    assert game.active_run.lives == run_before.lives
    assert game.economy.gold == 350
    assert game.state == GameState.PLAYING


def test_resuming_a_saved_run_still_restricts_the_build_menu_to_its_unlocked_towers(game):
    game.start_new_run(seed=1)
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    assert set(game.button_rects.keys()) == set(game.active_run.unlocked_towers)


def test_saving_without_an_active_run_resumes_with_no_active_run(playing_game):
    # playing_game is a classic/Practice-shaped load (no active_run at
    # all) -- a save taken from one must round-trip that absence, not
    # somehow acquire a run on resume.
    assert playing_game.active_run is None
    playing_game.save_run()
    playing_game.state = GameState.MENU

    playing_game._continue_saved_run()

    assert playing_game.active_run is None


def test_resuming_a_run_rederives_the_same_floor_routing_rng(game):
    # WaveManager's own routing rng is never serialized (see _run_rng's own
    # docstring) -- resuming re-derives the identical (seed, floor_index)
    # rng a *fresh* (never-saved) load of this same floor would get, not
    # an unseeded random.Random() that would make routing non-deterministic
    # from the resume point on. This is narrower than "identical to an
    # uninterrupted playthrough" in general, though: since no rng state is
    # serialized, a save taken mid-floor -- after some waves have already
    # consumed draws from this same rng object -- resumes at that rng's
    # own start, not wherever the un-saved playthrough's consumption had
    # already left it. Later waves can route differently after such a
    # resume than they would have without one; this test only covers a
    # save taken before any wave (wave_index 0) has drawn anything, the
    # one case where "identical to fresh" and "identical to uninterrupted"
    # coincide. Serializing the rng's own consumed position would close
    # this gap but means carrying real RNG state in the save file, which
    # is the exact thing this whole re-derivation scheme exists to avoid.
    game.start_new_run(seed=1)
    game._load_floor(3)
    expected_first_draw = game.wave_manager.rng.random()

    game._load_floor(3)  # reload floor 3 fresh -- re-derives the same un-consumed rng
    game.save_run()
    game.state = GameState.MENU
    game._continue_saved_run()

    assert game.wave_manager.rng.random() == expected_first_draw


def test_resuming_a_run_reapplies_this_floors_own_escalation(game):
    # Regression guard: WaveManager's own multipliers aren't touched by
    # wave_manager.restore() (only wave_index/state/between_wave_timer
    # are) -- leaving escalation at _load_level_object's own no-op default
    # would silently understate this floor's difficulty for the rest of
    # the floor, only self-correcting once the *next* floor's own
    # _load_floor() call gets it right.
    game.start_new_run(seed=1)
    game._load_floor(3)
    expected_hp_multiplier = game.wave_manager.enemy_hp_multiplier
    assert expected_hp_multiplier != 1.0  # floor 3 genuinely escalates -- not a vacuous assertion
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    assert game.wave_manager.enemy_hp_multiplier == expected_hp_multiplier


def test_resuming_a_run_reapplies_its_held_relics_enemy_gold_multiplier(game):
    # Composed with floor 2's own escalation too (see run_escalation.py),
    # so the expected value is whatever this floor's multiplier actually
    # was just before saving, not the relic's own multiplier in isolation.
    game.start_new_run(seed=1)
    game.active_run.relics = ["bounty_hunters_ledger"]
    game._load_floor(2)
    expected_gold_multiplier = game.wave_manager.enemy_gold_multiplier
    assert expected_gold_multiplier != 1.0  # relic + escalation both contribute -- not a vacuous assertion
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    assert game.wave_manager.enemy_gold_multiplier == expected_gold_multiplier


def test_resuming_a_run_reapplies_its_held_relics_enemy_speed_multiplier(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["tangled_roots"]
    game._load_floor(2)
    expected_speed_multiplier = game.wave_manager.enemy_speed_multiplier
    assert expected_speed_multiplier != 1.0  # relic + escalation both contribute -- not a vacuous assertion
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    assert game.wave_manager.enemy_speed_multiplier == expected_speed_multiplier


def test_resuming_a_daily_run_keeps_its_pinned_difficulty_despite_a_different_live_setting(game):
    # Regression guard: save_run() used to write the live, sticky
    # game.difficulty into the save file's top-level "difficulty" field
    # instead of the run's own pinned one, and resume_saved_run() read
    # that field straight back as its WaveManager's difficulty_override --
    # silently replacing a Daily Run's fairness-guaranteeing "normal" pin
    # with whatever the player's difficulty setting happened to be at
    # resume time.
    game.set_difficulty("hard")
    game._start_daily_challenge(seed=20260903)
    assert game.active_run.difficulty == "normal"
    game.save_run()
    game.state = GameState.MENU
    game.set_difficulty("easy")  # the live preference changes again before resuming

    game._continue_saved_run()

    assert game.active_run.difficulty == "normal"
    assert game.wave_manager.enemy_hp_multiplier == DIFFICULTY_MODES["normal"].enemy_hp_multiplier


def test_a_resumed_runs_own_floor_transitions_still_count_as_resumed(game):
    # Regression guard: _load_level_object() resets _resumed_from_save to
    # False on every call, the right default for a genuinely new/unrelated
    # load -- but _load_floor() (what every floor transition after a
    # resume goes through) used to inherit that reset unconditionally too,
    # silently un-marking the run as resumed the moment its very next
    # floor loaded. That left _delete_save_if_this_run_was_resumed()
    # gated on an already-False flag by the time this run actually
    # concluded, so its now-stale save file was never cleaned up.
    game.start_new_run(seed=1)
    game.save_run()
    game.state = GameState.MENU
    game._continue_saved_run()
    assert game._resumed_from_save is True

    finish_all_waves(game)
    game.update(dt=0.01)  # -> FLOOR_CLEARED
    game._enter_draft()
    game.active_run.shop_currency = 9999
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy an item
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> _load_floor(1), still same run
    assert game._resumed_from_save is True

    game.economy.lives = 1
    game.economy.lose_life()
    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert not save_state.has_saved_run(game.save_path)  # the stale save is actually cleaned up now


# --- Daily Run ---


def test_menu_d_key_starts_daily_run(game):
    game._handle_keydown(pygame.K_d)
    assert game.state == GameState.PLAYING
    assert game.active_run is not None
    assert game.active_run.is_daily is True


def test_daily_run_seeds_reproducibly(game):
    game._start_daily_challenge(seed=20260903)
    # Nothing has drawn from the rng yet at this point (no enemy spawned) --
    # a fresh run seeded the same way must produce the identical next value.
    first_draw = game.wave_manager.rng.random()

    game._start_daily_challenge(seed=20260903)
    second_draw = game.wave_manager.rng.random()

    assert first_draw == second_draw


def test_daily_run_pins_difficulty_to_normal_regardless_of_player_setting(game):
    game.set_difficulty("hard")  # starting_gold_multiplier=0.85, see difficulty.py

    game._start_daily_challenge(seed=20260903)

    assert game.active_run.difficulty == "normal"
    level = LEVELS[game.current_level_id]
    assert game.economy.gold == level.starting_gold  # normal's 1.0x, not hard's 0.85x


def test_daily_run_records_floors_cleared_on_game_over_and_keeps_the_best_score(game):
    game._start_daily_challenge(seed=20260903)
    seed = game.active_run.seed
    game.active_run.floor_index = 3  # simulate having cleared several floors
    game.economy.lives = 1
    game.enemies = []
    game.economy.lose_life()

    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert run_history.load_run_history(game.run_history_path) == {seed: 3}
    first_score = 3

    # A second, worse attempt (dies on floor 0) must not overwrite the
    # better score already recorded.
    game._start_daily_challenge(seed=20260903)
    game.economy.lives = 1
    game.enemies = []
    game.economy.lose_life()
    game.update(dt=0.01)

    assert run_history.load_run_history(game.run_history_path)[seed] == first_score


def test_a_classic_game_over_does_not_record_a_run_history_score(game):
    game.load_level(1)
    game.state = GameState.PLAYING
    game.economy.lives = 1
    game.enemies = []
    game.economy.lose_life()

    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert run_history.load_run_history(game.run_history_path) == {}


# --- Practice mode: playing one level outside a run ---


def test_practice_mode_lets_you_play_any_built_in_level_immediately(game):
    # Practice (LEVEL_SELECT purpose="play") is always Sandbox, and
    # decoupled from real progress -- so the sequential unlock gating
    # progress.py used to apply here is gone outright (is_unlocked() was
    # retired with it), and any built-in level is playable immediately,
    # even one with nothing cleared ahead of it (a fresh `game` fixture
    # has no progress.json at all).
    game._enter_level_select()

    rect = game.level_select_rects[2]
    game._handle_level_select_click(rect.center)

    assert game.state == GameState.PLAYING
    assert game.current_level_id == 2


def test_clearing_a_practice_level_earns_no_progress(game):
    # Practice is always Sandbox (see
    # test_picking_a_level_to_play_always_starts_it_in_sandbox_mode in
    # test_game.py), and a sandbox win is deliberately not a real one --
    # unlimited gold and no losable lives trivialize it. So beating a level
    # here records nothing, in progress.py or in the achievement counters
    # derived from it; real progress comes from clearing run floors (see
    # the "Clearing a floor" section above).
    game._enter_level_select()
    game._handle_level_select_click(game.level_select_rects[1].center)
    assert game.sandbox is True

    finish_all_waves(game)
    game.update(dt=0.01)

    assert game.state == GameState.VICTORY
    assert progress.load_progress(game.progress_path) == {}
    assert "levels_cleared" not in achievements.load_achievements(game.achievements_path)["counters"]


# --- Rendering the run-specific screens ---


def test_render_floor_cleared_does_not_crash(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.FLOOR_CLEARED

    game.render()


def test_render_draft_does_not_crash(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    assert game.state == GameState.DRAFT

    mock_mouse_pos((0, 0))  # exercises _hovered_draft_choice's "over nothing" path
    try:
        game.render()
    finally:
        clear_mouse_mock()

    mock_mouse_pos(game.draft_choice_rects[0].center)  # and its "over a card" path
    try:
        game.render()
    finally:
        clear_mouse_mock()


def test_render_relic_draft_does_not_crash(game):
    game.start_new_run(seed=1)
    game._enter_draft()
    _force_relic_draft(game, "war_chest")
    assert game.state == GameState.DRAFT

    game.render()
