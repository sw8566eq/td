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
import ui
from card_pool import STARTER_TOWERS
from difficulty import DIFFICULTY_MODES
from game import GameState, _DRAFT_RNG_STREAM, _FLOOR_RNG_STREAM
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
    # same as any other "Restart Level" -- but restores to the run's own
    # carried-forward gold/lives for this floor, not the level's raw
    # starting_gold/starting_lives a classic reload would use.
    playing_game.start_new_run(seed=1)
    playing_game._load_floor(1)
    gold_at_floor_start = playing_game.active_run.gold
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


# --- The draft: relic cards, and the modifiers they compose in ---


def test_relic_floor_offers_relics_instead_of_towers(game):
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1  # next_floor = 2, an even (relic) floor

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert game.draft_kind == "relic"
    assert set(game.draft_choices).issubset(RELICS.keys())


def test_relic_floor_falls_back_to_a_tower_draft_once_every_relic_is_held(game):
    # Matches _is_relic_floor's own documented contract: unreachable at the
    # current RELICS/RELIC_FLOOR_INTERVAL tuning in real play (a run can
    # never hold more relics than it has relic-draft floors for), but
    # _enter_draft() used to skip the screen entirely here instead of
    # actually falling back, contradicting what it claimed to do.
    # (Same meta-progression bump test_non_relic_floor_offers_towers needs
    # and explains above -- without it there's nothing beyond STARTER_
    # TOWERS to fall back to either, and this test would prove nothing.)
    meta_progression.bump("total_floors_cleared", 1, game.meta_progression_path)
    game.start_new_run(seed=1)
    game.active_run.relics = list(RELICS.keys())  # every relic already held
    game.active_run.floor_index = 1  # next_floor = 2, a relic floor

    game._enter_draft()

    assert game.state == GameState.DRAFT
    assert game.draft_kind == "tower"
    assert game.draft_choices  # STARTER_TOWERS isn't the whole registry yet


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


def _force_relic_draft(game, relic_key):
    """Overrides whatever relic_offer() actually offered with a single
    forced choice, for tests that need to verify one specific relic's math
    rather than accept whichever ones a given seed happened to draw."""
    game.draft_choices = [relic_key]
    game.draft_choice_rects = ui.build_draft_choice_rects(1)


def test_war_chest_grants_a_one_time_gold_bonus_when_drafted(game):
    # war_chest can never be drafted before floor 2 (see _is_relic_floor),
    # by which point floor 0's own Economy construction -- the only place
    # a starting_gold_multiplier could otherwise act -- is long gone (see
    # relics.RelicModifiers' own docstring for the full reasoning). Its
    # bonus is applied directly, once, the instant the card is drafted
    # (Game._apply_one_time_relic_bonus), computed against what this run's
    # own starter floor's baseline actually was -- not whatever gold the
    # player happens to be carrying at pick time.
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1  # next_floor = 2, a relic floor
    game._enter_draft()
    _force_relic_draft(game, "war_chest")
    starter_level = LEVELS[game.active_run.floor_sequence[0]]
    mode = DIFFICULTY_MODES[game.active_run.difficulty]
    base_gold = round(starter_level.starting_gold * mode.starting_gold_multiplier)
    gold_before = game.active_run.gold

    game._handle_draft_click(game.draft_choice_rects[0].center)

    # One combined round(), not round(base_gold * (multiplier - 1.0)) --
    # see test_war_chests_bonus_matches_a_single_combined_rounding below
    # for why the two formulas can disagree once a difficulty multiplier
    # makes base_gold itself not already a whole number.
    expected_bonus = (
        round(starter_level.starting_gold * mode.starting_gold_multiplier * RELICS["war_chest"].starting_gold_multiplier)
        - base_gold
    )
    assert game.active_run.gold == gold_before + expected_bonus


def test_sturdy_gate_grants_a_one_time_lives_bonus_when_drafted(game):
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1
    game._enter_draft()
    _force_relic_draft(game, "sturdy_gate")
    lives_before = game.active_run.lives

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert game.active_run.lives == lives_before + RELICS["sturdy_gate"].starting_lives_bonus


def test_war_chests_bonus_is_not_reapplied_on_a_later_floor_load(game):
    # Regression guard for the bug this replaced: war_chest/sturdy_gate
    # used to be folded into Economy construction, which only ever fires
    # at floor 0 -- silently making them permanently inert, since no relic
    # can ever be held that early. Now that the bonus is a one-time,
    # direct addition at pick time instead, confirm it really is one-time:
    # loading (or restarting) a later floor after the draft that picked it
    # must not grant it again.
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1
    game._enter_draft()
    _force_relic_draft(game, "war_chest")
    game._handle_draft_click(game.draft_choice_rects[0].center)  # -> floor 2, bonus applied once
    gold_after_draft = game.active_run.gold

    game._load_floor(game.active_run.floor_index)  # restart the same floor

    assert game.active_run.gold == gold_after_draft


def test_war_chests_bonus_matches_a_single_combined_rounding(game):
    # Regression guard: _apply_one_time_relic_bonus used to compute
    # base_gold = round(starting_gold * mode_multiplier), then add
    # round(base_gold * (relic_multiplier - 1.0)) on top -- two separate
    # roundings that can disagree with the single round(starting_gold *
    # mode_multiplier * relic_multiplier) _load_level_object's own Economy
    # construction would produce had the relic's multiplier been present
    # from the start. Hard's 0.85 starting_gold_multiplier is what
    # actually exposes the gap (round(round(150*0.85)*1.25) == 160 vs.
    # round(150*0.85*1.25) == 159) -- Normal's 1.0 multiplier leaves
    # base_gold already a whole number, where both formulas coincide.
    game.set_difficulty("hard")
    game.start_new_run(seed=1)
    game.active_run.floor_index = 1
    game._enter_draft()
    _force_relic_draft(game, "war_chest")
    starter_level = LEVELS[game.active_run.floor_sequence[0]]
    mode = DIFFICULTY_MODES[game.active_run.difficulty]
    gold_before = game.active_run.gold

    game._handle_draft_click(game.draft_choice_rects[0].center)

    single_rounding_gold = round(
        starter_level.starting_gold * mode.starting_gold_multiplier * RELICS["war_chest"].starting_gold_multiplier
    )
    base_gold = round(starter_level.starting_gold * mode.starting_gold_multiplier)
    assert single_rounding_gold != round(base_gold * RELICS["war_chest"].starting_gold_multiplier)  # the gap is real
    assert game.active_run.gold == gold_before + (single_rounding_gold - base_gold)


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
    game._handle_draft_click(game.draft_choice_rects[0].center)  # -> _load_floor(1), still same run
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
    game.active_run.floor_index = 1
    game._enter_draft()
    assert game.state == GameState.DRAFT
    assert game.draft_kind == "relic"

    game.render()
