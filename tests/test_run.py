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

import achievements
import meta_progression
import progress
import run_history
import save_state
from card_pool import STARTER_TOWERS
from difficulty import DIFFICULTY_MODES
from game import GameState
from levels import LEVELS
from relics import RELICS
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


def test_start_new_run_captures_floor_zeros_starting_economy(game):
    game.start_new_run(seed=1)

    assert game.active_run.lives == game.economy.lives
    assert game.active_run.gold == game.economy.gold


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


def test_floor_clear_enters_floor_cleared_and_captures_gold_lives(game):
    game.start_new_run(seed=1)
    # Distinct from whatever floor 1's own authored starting_gold/
    # starting_lives happen to be -- proves these came from the run, not
    # from _load_level_object's usual per-level defaults.
    game.economy.gold = 9999
    game.economy.lives = 3
    finish_all_waves(game)

    game.update(dt=0.01)

    # The next floor isn't loaded yet -- that only happens once the player
    # advances through FLOOR_CLEARED and picks a draft choice (see below) --
    # so floor_index/self.economy still reflect the floor just cleared.
    assert game.state == GameState.FLOOR_CLEARED
    assert game.active_run.floor_index == 0
    assert game.active_run.gold == 9999
    assert game.active_run.lives == 3


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


# --- The draft: picking a tower card between floors ---


def test_picking_a_draft_choice_advances_to_the_next_floor(game):
    game.start_new_run(seed=1)
    game.economy.gold = 9999
    game.economy.lives = 3
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    picked = game.draft_choices[0]
    rect = game.draft_choice_rects[0]

    game._handle_draft_click(rect.center)

    assert game.state == GameState.PLAYING
    assert game.active_run.floor_index == 1
    assert picked in game.active_run.unlocked_towers
    # Carried from the just-cleared floor, not floor 1's own authored
    # starting_gold/starting_lives -- same proof test_floor_clear_enters_
    # floor_cleared_and_captures_gold_lives makes for the FLOOR_CLEARED
    # step, extended through the rest of the flow.
    assert game.economy.gold == 9999
    assert game.economy.lives == 3
    assert picked in game.button_rects  # menu reflects the newly-drafted tower too


def test_clicking_off_a_draft_card_does_nothing(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    unlocked_before = list(game.active_run.unlocked_towers)

    game._handle_draft_click((0, 0))  # nowhere near any card

    assert game.state == GameState.DRAFT
    assert game.active_run.unlocked_towers == unlocked_before


def test_draft_escape_quits(game):
    game.start_new_run(seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_draft()
    assert game.state == GameState.DRAFT

    game._handle_keydown(pygame.K_ESCAPE)

    assert game.running is False


def test_enter_draft_skips_the_draft_screen_once_the_pool_is_exhausted(game):
    game.start_new_run(seed=1)
    game.active_run.unlocked_towers = list(TOWER_TYPES.keys())  # every tower already drafted
    finish_all_waves(game)
    game.update(dt=0.01)

    game._enter_draft()

    assert game.state == GameState.PLAYING
    assert game.active_run.floor_index == 1


def test_run_seed_reproduces_the_same_draft_offer(game):
    # Floor-sequence reproducibility for a fixed seed is already covered by
    # test_start_new_run_is_deterministic_for_a_fixed_seed above -- this
    # covers the one additional fact that test can't: the draft offer
    # itself (derived via _run_rng, only reachable through Game)
    # reproduces too, so two players on the same seed see the same cards.
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


# --- The draft: relic cards, and the modifiers they compose in ---


def test_relic_floor_offers_relics_instead_of_towers(game):
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1  # next_floor = 2, an even (relic) floor

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert game.draft_kind == "relic"
    assert set(game.draft_choices).issubset(RELICS.keys())


def test_non_relic_floor_offers_towers(game):
    # Unlike a relic draft (never gated), a tower draft needs something
    # meta-progression-unlocked beyond STARTER_TOWERS to actually offer --
    # real gameplay always has this by the time _enter_draft runs
    # (_advance_run_floor bumps total_floors_cleared first), but this test
    # skips straight to _enter_draft without ever clearing a floor.
    meta_progression.bump("total_floors_cleared", 1, game.meta_progression_path)
    game.start_new_run(seed=1)
    game.active_run.floor_index = 0  # next_floor = 1, an odd (tower) floor

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert game.draft_kind == "tower"


def test_picking_a_relic_adds_it_to_the_runs_relics_and_advances(game):
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1
    game._enter_draft()
    picked = game.draft_choices[0]

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert picked in game.active_run.relics
    assert game.active_run.floor_index == 2
    assert game.state == GameState.PLAYING


def test_relic_gold_per_floor_bonus_is_applied_on_every_floor_load(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["prospectors_charm"]
    gold_before = game.active_run.gold

    game._load_floor(1)

    assert game.economy.gold == gold_before + RELICS["prospectors_charm"].gold_per_floor_bonus


def test_relic_gold_per_floor_bonus_is_reflected_in_run_gold_at_floor_zero(game):
    # Regression guard: run.gold is captured *after* the bonus is applied
    # at floor 0, not before -- otherwise the very next floor's carried-
    # forward gold would silently lose whatever bonus floor 0 already
    # credited to the live economy.
    game.start_new_run(seed=1)
    game.active_run.relics = ["prospectors_charm"]

    game._load_floor(0)

    assert game.active_run.gold == game.economy.gold


def test_relic_starting_gold_multiplier_applies_only_at_floor_zero(game):
    # war_chest is deliberately a one-time bonus (see relics.py's own
    # RelicModifiers docstring for why) -- carried-forward gold on floor
    # 1+ shouldn't get the multiplier applied a second time.
    game.start_new_run(seed=1)
    game.active_run.relics = ["war_chest"]

    game._load_floor(0)

    level = LEVELS[game.active_run.floor_sequence[0]]
    expected = round(level.starting_gold * RELICS["war_chest"].starting_gold_multiplier)
    assert game.economy.gold == expected

    game._load_floor(1)
    assert game.economy.gold == expected  # not reapplied past floor zero


def test_relic_starting_lives_bonus_applies_only_at_floor_zero(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["sturdy_gate"]

    game._load_floor(0)

    level = LEVELS[game.active_run.floor_sequence[0]]
    expected = level.starting_lives + RELICS["sturdy_gate"].starting_lives_bonus
    assert game.economy.lives == expected

    game._load_floor(1)
    assert game.economy.lives == expected  # not reapplied past floor zero


def test_relic_enemy_gold_multiplier_composes_into_wave_manager(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["bounty_hunters_ledger"]

    game._load_floor(0)

    assert game.wave_manager.enemy_gold_multiplier == RELICS["bounty_hunters_ledger"].enemy_gold_multiplier


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
    game._handle_draft_click(game.draft_choice_rects[0].center)  # -> floor 1, PLAYING
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
    assert "knockback" in game.draft_choices


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
    assert saved["run"].gold == run_before.gold
    assert saved["run"].lives == run_before.lives


def test_resuming_a_saved_run_restores_active_run(game):
    game.start_new_run(seed=1)
    game.active_run.unlocked_towers.append("sniper")  # a drafted card, carried across floors
    # active_run.gold/lives are only re-synced from economy at a floor's own
    # clear (_advance_run_floor) -- not live every frame -- so a save taken
    # mid-floor genuinely captures two different numbers here, same as it
    # would with no save/resume involved at all. economy.gold (350 after
    # this) is what a resume should restore live play to; active_run.gold
    # (still floor 0's original 150) is what the *next* floor load would
    # carry forward from, unaffected by this frame's spending.
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
    assert game.active_run.gold == run_before.gold
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
    game.active_run.floor_index = 1
    game._enter_draft()
    assert game.state == GameState.DRAFT
    assert game.draft_kind == "relic"

    game.render()
