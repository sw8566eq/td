"""Tests for the roguelike run loop -- the game's primary mode.

A run is a full branching map (run_map.py) shown from the start, played
node by node with a run-scoped tower pool grown by shopping between combat
floors, carrying lives and shop currency forward, ending only by permadeath.
This module covers that whole lifecycle end to end: starting a run, picking
map nodes, loading and clearing combat/elite floors, the Shop/Event/Rest/
Treasure node types, permadeath and the run history it records,
meta-progression accumulating across runs, saving and resuming a run
mid-flight, the Daily Run, and Practice mode (the standalone, deliberately
run-less way to play a single level).

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
import settings
import shop
import ui
from card_pool import STARTER_TOWERS
from difficulty import DIFFICULTY_MODES
from enemy import SplitterEnemy
from events import EVENTS
from game import GameState, _DRAFT_RNG_STREAM, _FLOOR_RNG_STREAM
from levels import LEVELS
from relics import RELICS, Relic
from run_map import MapNode, RunMap
from run_state import RunState
from shop import ShopItem
from tower import TOWER_TYPES

from conftest import (
    finish_all_waves,
    find_buildable_anchor,
    make_linear_run_map,
    mock_mouse_pos,
    clear_mouse_mock,
    start_first_floor,
)


def _begin_run_with_map(game, node_types, seed=1, level_id=1, difficulty=None, **run_overrides):
    """Install a controlled, linear RunState (see conftest.
    make_linear_run_map) as game.active_run and show the map -- bypasses
    start_new_run()'s real map generation, for tests that need a specific
    node-type sequence at specific rows rather than whatever a real seed
    happens to produce (e.g. a guaranteed Shop/Event/Rest/Treasure node, or
    a guaranteed row depth without hunting for a seed)."""
    kwargs = dict(
        seed=seed, map=make_linear_run_map(node_types, level_id=level_id),
        difficulty=difficulty if difficulty is not None else game.difficulty,
        unlocked_towers=list(STARTER_TOWERS),
    )
    kwargs.update(run_overrides)
    game.active_run = RunState(**kwargs)
    game._enter_map()
    return game.active_run


def _enter_first_node(game):
    """Enter the first available row-0 node of game.active_run -- for tests
    that set up game.active_run.relics/etc. themselves first, then just
    want the run's very first node specifically (unlike start_first_floor,
    which starts the run itself too)."""
    game._enter_node(game.active_run.map.start_node_ids[0])


def _reload_current_node(game):
    """Reload whatever node game.active_run is already on, fresh -- the
    node-based equivalent of the old _load_floor(same_index) "restart this
    floor" idiom, used by tests that want to re-derive relic_modifiers/
    escalation after changing something about the run."""
    run = game.active_run
    game._load_combat_node(run.map.node(run.current_node_id))


def _find_buildable_row(game, count):
    """`count` buildable, tile-aligned anchors in the same row, consecutive
    columns (TILE_SIZE apart) -- for tests exercising Overcrowded Circuits'
    own live density check, which needs several real placed towers within
    a shared radius of each other, not just one."""
    n = settings.SUBTILES_PER_TILE
    for row in range(settings.GRID_ROWS):
        for col in range(settings.GRID_COLS - count + 1):
            anchors = [((col + i) * n, row * n) for i in range(count)]
            if all(game.grid.is_buildable(c, r) for c, r in anchors):
                return anchors
    raise AssertionError("no matching buildable row found")


def _enter_run_shop(game, seed=1):
    """Navigate `game` to a Shop screen via a controlled, guaranteed-shop
    map (row 0 combat -> row 1 shop -> row 2 boss combat) -- a real seeded
    map doesn't guarantee a Shop node is reachable at any particular row
    (see CLAUDE.md's "Shop cadence" design note), so tests exercising the
    shop screen's own mechanics use this fixed layout instead of hunting
    for a seed that happens to produce one."""
    _begin_run_with_map(game, ["combat", "shop", "combat"], seed=seed)
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_map()
    game._enter_node("1-0")
    return game.active_run


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


# --- Starting a run ---


def test_start_new_run_populates_active_run_and_shows_the_map(game):
    game.start_new_run(seed=1)

    assert game.active_run is not None
    assert game.active_run.current_node_id is None
    assert game.active_run.unlocked_towers == list(STARTER_TOWERS)
    assert game.state == GameState.MAP


def test_picking_a_row_zero_node_starts_playing_it(game):
    game.start_new_run(seed=1)
    node_id = game.active_run.map.start_node_ids[0]

    game._handle_map_click(game.map_node_rects[node_id].center)

    assert game.state == GameState.PLAYING
    assert game.active_run.current_node_id == node_id
    assert game.current_level_id == game.active_run.map.node(node_id).level_id


def test_clicking_an_unavailable_node_does_nothing(game):
    game.start_new_run(seed=1)
    # Row 1 is never available before any row-0 node has been picked.
    row_1_node_id = game.active_run.map.rows[1][0].id

    game._handle_map_click(game.map_node_rects[row_1_node_id].center)

    assert game.active_run.current_node_id is None
    assert game.state == GameState.MAP


def test_clicking_off_any_node_does_nothing(game):
    game.start_new_run(seed=1)

    game._handle_map_click((0, 0))

    assert game.active_run.current_node_id is None
    assert game.state == GameState.MAP


def test_start_new_run_captures_its_first_floors_starting_lives(game):
    # No equivalent gold assertion -- battle gold is never captured onto
    # RunState at all any more (see CLAUDE.md's "Two currencies" section).
    start_first_floor(game, seed=1)

    assert game.active_run.lives == game.economy.lives


def test_start_new_run_is_deterministic_for_a_fixed_seed(game):
    game.start_new_run(seed=1234)
    first_map = game.active_run.map

    game.start_new_run(seed=1234)
    second_map = game.active_run.map

    assert first_map == second_map


def test_start_new_run_without_a_seed_still_produces_a_playable_run(game):
    game.start_new_run()

    assert game.active_run.seed is not None
    assert game.state == GameState.MAP


# --- The run-scoped tower pool (what the build menu offers) ---


def test_starting_a_run_restricts_the_build_menu_to_the_starter_towers(game):
    start_first_floor(game, seed=1)
    assert set(game.button_rects.keys()) == set(STARTER_TOWERS)


def test_try_place_tower_rejects_a_tower_not_in_the_active_runs_pool(game):
    start_first_floor(game, seed=1)
    anchor_col, anchor_row = find_buildable_anchor(game)
    # Bypasses the build menu entirely -- selected_tower_name would never
    # actually reach this value through a real click, since button_rects
    # only ever offers _active_tower_names() (see try_place_tower's own
    # defense-in-depth comment).
    game.selected_tower_name = "sniper"  # not in STARTER_TOWERS

    assert game.try_place_tower(anchor_col, anchor_row) is False
    assert game.grid.get_tower(anchor_col, anchor_row) is None


def test_a_classic_level_load_restores_the_full_build_menu(game):
    start_first_floor(game, seed=1)
    game.load_level(1)
    assert set(game.button_rects.keys()) == set(TOWER_TYPES.keys())


def test_any_direct_load_level_object_call_restores_the_full_build_menu(game):
    # Regression guard: the build-menu reset lives inside _load_level_object
    # itself (see its own comment), not hand-repeated at every wrapper that
    # calls it -- so this holds even for reset()/advance_or_replay_level()'s
    # own direct _load_level_object() calls for a custom/playtested level,
    # not just the load_level/load_custom_level/resume_saved_run/
    # _start_daily_challenge/_load_combat_node call sites that have their
    # own test coverage above.
    start_first_floor(game, seed=1)
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
    start_first_floor(game, seed=1)
    # Distinct from whatever this floor's own authored starting_lives
    # happens to be -- proves this came from the run, not from
    # _load_level_object's usual per-level defaults. Battle gold is
    # deliberately NOT carried the same way (see CLAUDE.md's "Two
    # currencies" section) -- instead it converts into shop currency (see
    # shop.income_for_floor), asserted below via that exact formula rather
    # than a hardcoded number, so this test doesn't silently drift from
    # shop.py's own tuning.
    game.economy.gold = 9999
    game.economy.lives = 3
    finish_all_waves(game)

    game.update(dt=0.01)

    # The map isn't shown again until the player leaves this results
    # screen (see below) -- so self.economy still reflects the floor just
    # cleared.
    assert game.state == GameState.FLOOR_CLEARED
    assert game.active_run.current_row == 0
    assert game.active_run.lives == 3
    assert game.active_run.shop_currency == shop.income_for_floor(0, 9999, is_elite=False)


def test_floor_clear_never_reaches_classic_victory(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    assert game.state != GameState.VICTORY
    assert game.state == GameState.FLOOR_CLEARED


def test_floor_cleared_any_key_returns_to_the_map(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)

    game._handle_keydown(pygame.K_SPACE)

    assert game.state == GameState.MAP


def test_floor_cleared_escape_quits(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.FLOOR_CLEARED

    game._handle_keydown(pygame.K_ESCAPE)

    assert game.running is False


def test_boss_node_of_a_run_loads_endless(game):
    game.start_new_run(seed=1)
    boss_id = game.active_run.map.boss_node_id

    game._enter_node(boss_id)

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
    _begin_run_with_map(game, ["combat"] * 4)

    game._enter_node("3-0")

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
    start_first_floor(game, seed=1)
    level_id = game.current_level_id
    game.economy.lives = 7
    finish_all_waves(game)

    game.update(dt=0.01)

    assert progress.load_progress(game.progress_path) == {level_id: 7}


def test_clearing_a_floor_bumps_the_level_clear_achievement_counters(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    counters = achievements.load_achievements(game.achievements_path)["counters"]
    assert counters["levels_cleared"] == 1
    assert counters["distinct_levels_cleared"] == 1


def test_distinct_levels_cleared_counts_a_repeated_level_once_across_runs(game):
    # levels_cleared is a naive +1 per clear; distinct_levels_cleared is
    # re-derived from progress.py's own keys each time, which is what keeps
    # "Campaign Complete" from being farmable by replaying one floor -- see
    # achievements.py's own note on the two counters. A fixed seed produces
    # the same map both times (see run_map.generate_run_map's own
    # determinism), so picking the same row-0 node both times clears the
    # identical level.
    for _ in range(2):
        start_first_floor(game, seed=1)
        finish_all_waves(game)
        game.update(dt=0.01)

    counters = achievements.load_achievements(game.achievements_path)["counters"]
    assert counters["levels_cleared"] == 2
    assert counters["distinct_levels_cleared"] == 1
    assert len(progress.load_progress(game.progress_path)) == 1


def test_progress_earned_in_a_run_persists_across_a_fresh_game_instance(game):
    start_first_floor(game, seed=1)
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
    # run -- drafted tower pool, relics, carried gold/lives, map position
    # -- and dropping the player into a plain classic reload of whatever
    # level they happened to be on, with no warning shown.
    _begin_run_with_map(playing_game, ["combat"] * 3)
    playing_game._enter_node("2-0")
    run_before = playing_game.active_run
    playing_game.towers = ["fake"]
    playing_game.economy.gold = 999999
    playing_game.state = GameState.PAUSED  # reset()'s own restart-the-run branch checks this directly

    playing_game.reset()

    assert playing_game.active_run is run_before  # same RunState, not discarded
    assert playing_game.active_run.current_node_id == "2-0"  # still on the node it restarted
    assert playing_game.current_level_id == run_before.map.node("2-0").level_id
    assert playing_game.towers == []  # the floor itself still reloads fresh
    assert set(playing_game.button_rects.keys()) == set(run_before.unlocked_towers)  # menu stays run-narrowed
    # Regression guard: reset()'s own trailing "classic reload" branch
    # used to unconditionally set self.state = MENU afterward, clobbering
    # _load_combat_node()'s own PLAYING right back to MENU -- harmless for
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
    run = _begin_run_with_map(playing_game, ["combat", "combat"])
    run.visited_node_ids = ["0-0"]  # pretend the first floor already cleared
    run.lives = 12
    playing_game._enter_node("1-0")
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
    start_first_floor(playing_game, seed=1)
    playing_game.economy.lives = 1
    playing_game.economy.lose_life()
    playing_game.update(dt=0.01)
    assert playing_game.state == GameState.GAME_OVER
    assert playing_game.active_run is not None  # _record_run_permadeath doesn't clear it

    playing_game.reset()

    assert playing_game.active_run is None


# --- The Shop: buying tower/relic cards from a Shop map node ---


def test_buying_a_shop_item_then_continuing_returns_to_the_map(game):
    _begin_run_with_map(game, ["combat", "shop", "combat"])
    game._enter_node("0-0")
    game.economy.lives = 3
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_map()
    game._enter_node("1-0")  # the shop node
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

    assert game.state == GameState.MAP
    assert game.active_run.visited_node_ids == ["0-0", "1-0"]

    game._enter_node("2-0")  # the next (final) combat node

    assert game.state == GameState.PLAYING
    assert game.economy.lives == 3  # lives still carry from the just-cleared floor
    if picked.kind == "tower":
        assert picked.key in game.button_rects  # this floor's menu reflects the newly-bought tower


def test_buying_a_shop_item_deducts_its_escalated_price(game):
    _enter_run_shop(game)
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
    _enter_run_shop(game)
    game.active_run.shop_currency = 0
    unlocked_before = list(game.active_run.unlocked_towers)
    relics_before = list(game.active_run.relics)

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert game.shop_purchased_indices == set()
    assert game.active_run.shop_currency == 0
    assert game.active_run.unlocked_towers == unlocked_before
    assert game.active_run.relics == relics_before


def test_unlimited_gold_makes_every_shop_item_free(game):
    _enter_run_shop(game)
    game.economy.unlimited_gold = True
    game.active_run.shop_currency = 0

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert 0 in game.shop_purchased_indices
    assert game.active_run.shop_currency == 0  # never actually deducted, same as battle gold


def test_clicking_a_purchased_item_again_does_nothing(game):
    _enter_run_shop(game)
    game.active_run.shop_currency = 9999
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it
    currency_after_first_buy = game.active_run.shop_currency

    game._handle_draft_click(game.draft_choice_rects[0].center)  # click the same, now-SOLD card again

    assert game.active_run.shop_currency == currency_after_first_buy


def test_clicking_off_a_draft_card_does_nothing(game):
    _enter_run_shop(game)
    unlocked_before = list(game.active_run.unlocked_towers)

    game._handle_draft_click((0, 0))  # nowhere near any card or the Continue button

    assert game.state == GameState.DRAFT
    assert game.active_run.unlocked_towers == unlocked_before


def test_continue_button_returns_to_the_map_without_buying_anything(game):
    _enter_run_shop(game)
    unlocked_before = list(game.active_run.unlocked_towers)
    relics_before = list(game.active_run.relics)

    game._handle_draft_click(game.shop_continue_button_rect.center)

    assert game.state == GameState.MAP
    assert game.active_run.unlocked_towers == unlocked_before
    assert game.active_run.relics == relics_before


def test_draft_escape_quits(game):
    _enter_run_shop(game)
    assert game.state == GameState.DRAFT

    game._handle_keydown(pygame.K_ESCAPE)

    assert game.running is False


def test_enter_shop_node_skips_the_shop_screen_once_both_pools_are_exhausted(game):
    _begin_run_with_map(game, ["combat", "shop", "combat"])
    game.active_run.unlocked_towers = list(TOWER_TYPES.keys())  # every tower already unlocked
    game.active_run.relics = list(RELICS.keys())  # every relic already held
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_map()

    game._enter_node("1-0")  # the shop node

    assert game.state == GameState.MAP  # skipped straight through, no shop shown
    assert game.active_run.visited_node_ids == ["0-0", "1-0"]


def test_enter_shop_node_still_shows_up_with_only_relics_left_to_offer(game):
    # Regression guard: the old draft screen could fall all the way through
    # to PLAYING if towers specifically were exhausted (see _is_relic_floor's
    # former fallback logic) -- the Shop must still show up as long as
    # *either* pool has something left, since it offers both together now.
    _begin_run_with_map(game, ["combat", "shop", "combat"])
    game.active_run.unlocked_towers = list(TOWER_TYPES.keys())  # every tower already unlocked
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_map()

    game._enter_node("1-0")

    assert game.state == GameState.DRAFT
    assert all(item.kind == "relic" for item in game.draft_choices)


def test_run_seed_reproduces_the_same_shop_offer(game):
    _enter_run_shop(game, seed=99)
    first_offer = list(game.draft_choices)

    _enter_run_shop(game, seed=99)
    second_offer = list(game.draft_choices)

    assert first_offer == second_offer


def test_enter_shop_node_uses_shop_build_offer(game, monkeypatch):
    # A thin wiring test: _enter_shop_node delegates entirely to shop.
    # build_offer for what to show, rather than assembling its own list --
    # towers and relics can come back mixed together in one offer now (see
    # shop.build_offer's own tests for that mixing behavior in isolation).
    _begin_run_with_map(game, ["combat", "shop"])
    fake_offer = [ShopItem("tower", "sniper", 8), ShopItem("relic", "war_chest", 10)]
    monkeypatch.setattr(shop, "build_offer", lambda rng, run, meta_progression_path=None: fake_offer)

    game._enter_node("1-0")

    assert game.state == GameState.DRAFT
    assert game.draft_choices == fake_offer
    assert len(game.draft_choice_rects) == len(fake_offer)


def test_floor_and_draft_rng_streams_dont_collide_even_for_a_zero_seed(game):
    # Regression guard: _run_rng used to derive both streams as
    # seed * key + ..., which degenerates to plain `key` for *every* stream
    # whenever seed == 0 -- start_new_run(seed=0) is directly reachable, and
    # even an unseeded run has a real (if tiny) chance of drawing it --
    # silently collapsing the floor-routing and draft-pick rng onto the
    # exact same sequence.
    game.start_new_run(seed=0)
    run = game.active_run

    floor_rng = game._run_rng(run, _FLOOR_RNG_STREAM, 3)
    draft_rng = game._run_rng(run, _DRAFT_RNG_STREAM, 3)

    assert floor_rng.random() != draft_rng.random()


def test_sibling_nodes_in_the_same_row_derive_different_rng(game):
    # Regression guard for the row -> node-id rekey (see Game._run_rng's
    # own docstring): two different nodes at the same row of one seeded map
    # must not derive byte-identical routing rng, or branching would be
    # cosmetic -- every fork would actually play out identically.
    game.start_new_run(seed=1)
    run = game.active_run
    row_with_multiple_nodes = next(row for row in run.map.rows if len(row) > 1)
    node_a, node_b = row_with_multiple_nodes[0], row_with_multiple_nodes[1]

    rng_a = game._run_rng(run, _FLOOR_RNG_STREAM, node_a.id)
    rng_b = game._run_rng(run, _FLOOR_RNG_STREAM, node_b.id)

    assert rng_a.random() != rng_b.random()


# --- Relic effects bought from the shop, and the modifiers they compose in ---


def test_relic_gold_per_floor_bonus_is_applied_on_every_floor_load(game):
    _begin_run_with_map(game, ["combat", "combat"])
    game._enter_node("1-0")
    gold_without_relic = game.economy.gold

    _begin_run_with_map(game, ["combat", "combat"])
    game.active_run.relics = ["prospectors_charm"]
    game._enter_node("1-0")

    assert game.economy.gold == gold_without_relic + RELICS["prospectors_charm"].gold_per_floor_bonus


def test_misers_coffer_bonus_stops_after_the_runs_first_spend(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["misers_coffer"]
    _enter_first_node(game)
    gold_with_bonus = game.economy.gold

    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)  # this run's first spend

    assert game.active_run.has_spent_gold is True

    _reload_current_node(game)  # restart the same floor -- re-derives relic_modifiers fresh

    assert game.economy.gold == gold_with_bonus - RELICS["misers_coffer"].gold_per_floor_bonus_while_unspent


def test_war_chest_multiplies_starting_gold_on_every_floor_not_just_once(game):
    # Regression guard for the redesign: war_chest used to be a one-time
    # bonus applied only at the moment it was bought (see relics.py's own
    # module docstring for the "why" -- back when battle gold carried
    # forward, "starting gold" only existed once, at floor 0). Now that
    # battle gold resets fresh every floor instead, it has to keep applying
    # on every single floor load, not just the one right after it's bought.
    # Two different levels at the two floors checked below, proving the
    # multiplier is re-applied fresh each time rather than only happening
    # to look right for one specific level's own starting_gold.
    custom_map = RunMap(
        rows=(
            (MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),),
            (MapNode("1-0", row=1, col=0, node_type="shop"),),
            (MapNode("2-0", row=2, col=0, node_type="combat", level_id=2),),
            (MapNode("3-0", row=3, col=0, node_type="combat", level_id=3),),
        ),
        edges={"0-0": ("1-0",), "1-0": ("2-0",), "2-0": ("3-0",)},
    )
    game.active_run = RunState(
        seed=1, map=custom_map, difficulty=game.difficulty, unlocked_towers=list(STARTER_TOWERS),
    )
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_map()
    game._enter_node("1-0")  # the shop node
    _force_relic_draft(game, "war_chest")
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> back to the map

    game._enter_node("2-0")
    gold_floor_2 = game.economy.gold

    game._enter_node("3-0")
    gold_floor_3 = game.economy.gold

    mode = DIFFICULTY_MODES[game.active_run.difficulty]
    multiplier = RELICS["war_chest"].starting_gold_multiplier
    assert gold_floor_2 == round(LEVELS[2].starting_gold * mode.starting_gold_multiplier * multiplier)
    assert gold_floor_3 == round(LEVELS[3].starting_gold * mode.starting_gold_multiplier * multiplier)


def test_sturdy_gate_grants_a_one_time_lives_bonus_when_bought(game):
    _enter_run_shop(game)
    _force_relic_draft(game, "sturdy_gate")
    lives_before = game.active_run.lives

    game._handle_draft_click(game.draft_choice_rects[0].center)

    assert game.active_run.lives == lives_before + RELICS["sturdy_gate"].starting_lives_bonus


def test_relic_enemy_gold_multiplier_composes_into_wave_manager(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["bounty_hunters_ledger"]

    _enter_first_node(game)

    assert game.wave_manager.enemy_gold_multiplier == RELICS["bounty_hunters_ledger"].enemy_gold_multiplier


def test_relic_enemy_speed_multiplier_composes_into_wave_manager(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["tangled_roots"]

    _enter_first_node(game)

    assert game.wave_manager.enemy_speed_multiplier == RELICS["tangled_roots"].enemy_speed_multiplier


def test_spyglass_array_range_bonus_reaches_a_freshly_placed_tower(game):
    # Regression guard for the "no save_state.py schema changes needed"
    # claim: a tower-facing relic's bonus is re-derived fresh at
    # construction time (Game._construct_tower), not stored on RunState
    # itself -- so drafting the card, then placing a tower on a later
    # floor, must still see the bonus with no extra plumbing in between.
    _enter_run_shop(game)
    _force_relic_draft(game, "spyglass_array")
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy it
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> back to the map

    game._enter_node("2-0")  # the next combat node, relic_modifiers re-derived

    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_range_bonus_multiplier == RELICS["spyglass_array"].tower_range_multiplier


def test_resuming_a_run_rederives_a_placed_towers_relic_range_bonus(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["spyglass_array"]
    _enter_first_node(game)  # re-derives self.relic_modifiers from the relics just set
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
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_fire_rate_bonus_multiplier == RELICS["quickfire_rounds"].tower_fire_rate_multiplier


def test_overdrive_coils_damage_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["overdrive_coils"]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_damage_bonus_multiplier == RELICS["overdrive_coils"].tower_damage_multiplier
    assert tower.relic_fire_rate_bonus_multiplier == RELICS["overdrive_coils"].tower_fire_rate_multiplier


def test_snipers_discipline_damage_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["snipers_discipline"]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_damage_bonus_multiplier == RELICS["snipers_discipline"].tower_damage_multiplier
    assert tower.relic_fire_rate_bonus_multiplier == RELICS["snipers_discipline"].tower_fire_rate_multiplier


def test_veterans_momentum_damage_bonus_grows_with_floor_index(game):
    _begin_run_with_map(game, ["combat"] * 4)
    game.active_run.relics = ["veterans_momentum"]

    game._enter_node("3-0")

    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    growth = RELICS["veterans_momentum"].tower_damage_growth_per_floor
    assert tower.relic_damage_bonus_multiplier == pytest.approx(1.0 + growth * 3)


def test_venomous_coating_poison_chance_reaches_a_freshly_placed_towers_shots(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["venomous_coating"]
    _enter_first_node(game)
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
    _enter_first_node(game)
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
    _enter_first_node(game)
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
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_last_stand_bonus_multiplier == RELICS["last_stand_charm"].last_stand_damage_multiplier


def test_last_stand_charm_only_boosts_damage_while_down_to_the_last_life(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["last_stand_charm"]
    _enter_first_node(game)
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


def test_adrenaline_rushs_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["adrenaline_rush"]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_last_stand_fire_rate_bonus_multiplier == (
        RELICS["adrenaline_rush"].last_stand_fire_rate_multiplier
    )


def test_adrenaline_rush_only_boosts_fire_rate_while_down_to_the_last_life(game):
    # Mirrors last_stand_charm's own damage test above exactly -- both
    # relics key off the same Economy.is_on_last_life condition, resolved
    # in the same set_last_stand_multiplier() call.
    game.start_new_run(seed=1)
    game.active_run.relics = ["adrenaline_rush"]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)
    tower = game.grid.get_tower(anchor_col, anchor_row)
    base_fire_rate = tower.effective_fire_rate()

    game.economy.lives = 2
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == base_fire_rate  # not yet down to the last life

    game.economy.lives = 1
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == pytest.approx(
        base_fire_rate * RELICS["adrenaline_rush"].last_stand_fire_rate_multiplier
    )

    game.economy.lives = 3  # a life regained turns the bonus back off
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == base_fire_rate


def test_guardians_reprieve_saves_the_run_from_permadeath_once(game):
    start_first_floor(game, seed=1)
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
    _enter_first_node(game)
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
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_upgrade_cost_multiplier == RELICS["quartermasters_favor"].tower_upgrade_cost_multiplier


def test_liquidation_rights_bonus_reaches_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["liquidation_rights"]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_sell_refund_bonus == RELICS["liquidation_rights"].sell_refund_bonus


def test_resonant_field_bonus_reaches_a_freshly_placed_support_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["resonant_field"]
    game.active_run.unlocked_towers.append("support")  # a drafted card, not a starter tower
    _enter_first_node(game)
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
    _enter_first_node(game)
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
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    game.try_place_tower(anchor_col, anchor_row)
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    tower = game.grid.get_tower(anchor_col, anchor_row)
    expected_size = 8 - RELICS["compact_framework"].tower_footprint_shrink
    assert tower.footprint_subtiles == expected_size


def test_overcrowded_circuits_bonus_fields_reach_a_freshly_placed_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["overcrowded_circuits"]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    relic = RELICS["overcrowded_circuits"]
    assert tower.relic_tower_density_radius == relic.tower_density_radius
    assert tower.relic_tower_density_damage_bonus_per_neighbor == relic.tower_density_damage_bonus_per_neighbor
    assert tower.relic_tower_density_damage_bonus_cap == relic.tower_density_damage_bonus_cap


def test_relic_gap_filler_fields_reach_a_freshly_placed_tower(game):
    # containment_charges is deliberately absent here -- unlike every other
    # relic in this batch, its splitter_child_damage has no per-tower
    # variation, so it's never copied onto a Tower at all (see
    # test_containment_charges_damages_a_splitters_children_through_game_
    # update below for where it's actually exercised).
    game.start_new_run(seed=1)
    game.active_run.relics = [
        "concussive_rounds", "disorienting_flash", "flak_rounds",
        "breach_charges", "suppression_directive",
    ]
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]

    game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    assert tower.relic_knockback_chance == RELICS["concussive_rounds"].knockback_chance
    assert tower.relic_knockback_effect == RELICS["concussive_rounds"].knockback_duration
    assert tower.relic_mark_chance == RELICS["disorienting_flash"].mark_chance
    assert tower.relic_mark_effect == (
        RELICS["disorienting_flash"].mark_multiplier, RELICS["disorienting_flash"].mark_duration
    )
    assert tower.relic_damage_vs_flying_multiplier == RELICS["flak_rounds"].damage_vs_flying_multiplier
    assert tower.relic_damage_vs_shielded_multiplier == RELICS["breach_charges"].damage_vs_shielded_multiplier
    assert tower.relic_damage_vs_healer_multiplier == RELICS["suppression_directive"].damage_vs_healer_multiplier
    assert not hasattr(tower, "relic_splitter_child_damage")


def test_containment_charges_damages_a_splitters_children_through_game_update(game, monkeypatch):
    monkeypatch.setitem(RELICS, "containment_charges", Relic(
        "containment_charges", "", "", splitter_child_damage=5,
    ))
    game.start_new_run(seed=1)
    game.active_run.relics = ["containment_charges"]
    _enter_first_node(game)
    assert game.relic_modifiers.splitter_child_damage == 5

    waypoints = [pygame.Vector2(0, 0), pygame.Vector2(100, 0)]
    splitter = SplitterEnemy(waypoints, wave_number=1)
    splitter.take_damage(splitter.max_hp)  # a killing blow, queues pending_spawns
    assert splitter.is_dead
    children = list(splitter.pending_spawns)
    game.enemies = [splitter]

    game.update(dt=0.01)

    assert len(children) == SplitterEnemy.SPLIT_COUNT
    for child in children:
        assert child.hp == pytest.approx(child.max_hp - 5)
        assert child in game.enemies


def test_overcrowded_circuits_density_bonus_counts_neighboring_towers_through_game_update(game, monkeypatch):
    # A small-scale stand-in relic (monkeypatch.setitem, same precedent
    # test_relics.py's own artificial relics use) rather than the real
    # registry's own tuned 80px/2%/20% numbers -- an easier-to-reason-about
    # rate, and a radius (100px) wide enough to reach an orthogonal
    # neighbor one tile (64px) away but not one two tiles (128px) away, so
    # the three-in-a-row cluster below produces two different neighbor
    # counts to check.
    monkeypatch.setitem(RELICS, "overcrowded_circuits", Relic(
        "overcrowded_circuits", "", "", tower_density_radius=100,
        tower_density_damage_bonus_per_neighbor=0.10, tower_density_damage_bonus_cap=0.50,
    ))
    game.start_new_run(seed=1)
    game.active_run.relics = ["overcrowded_circuits"]
    _enter_first_node(game)
    anchors = _find_buildable_row(game, count=3)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    for anchor_col, anchor_row in anchors:
        assert game.try_place_tower(anchor_col, anchor_row)

    game.update(dt=0.01)

    center = game.grid.get_tower(*anchors[1])  # flanked by both other towers
    assert center.relic_tower_density_bonus_multiplier == pytest.approx(1.20)  # 2 neighbors * 0.10
    edge = game.grid.get_tower(*anchors[0])  # only one neighbor within range
    assert edge.relic_tower_density_bonus_multiplier == pytest.approx(1.10)


def test_overcrowded_circuits_density_bonus_is_capped_through_game_update(game, monkeypatch):
    monkeypatch.setitem(RELICS, "overcrowded_circuits", Relic(
        "overcrowded_circuits", "", "", tower_density_radius=200,
        tower_density_damage_bonus_per_neighbor=0.10, tower_density_damage_bonus_cap=0.15,
    ))
    game.start_new_run(seed=1)
    game.active_run.relics = ["overcrowded_circuits"]
    _enter_first_node(game)
    anchors = _find_buildable_row(game, count=3)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    for anchor_col, anchor_row in anchors:
        assert game.try_place_tower(anchor_col, anchor_row)

    game.update(dt=0.01)

    center = game.grid.get_tower(*anchors[1])
    assert center.relic_tower_density_bonus_multiplier == pytest.approx(1.15)  # capped, not 1.20


def test_beacon_tower_placement_populates_relic_fields_like_any_other_tower(game):
    game.start_new_run(seed=1)
    game.active_run.relics = ["lucky_strikes"]
    game.active_run.unlocked_towers.append("beacon")  # a drafted card, not a starter tower
    _enter_first_node(game)
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = "beacon"

    assert game.try_place_tower(anchor_col, anchor_row)

    tower = game.grid.get_tower(anchor_col, anchor_row)
    relic = RELICS["lucky_strikes"]
    assert tower.relic_crit_chance == relic.crit_chance
    assert tower.relic_crit_damage_multiplier == relic.crit_damage_multiplier


# --- Elite Combat nodes: harder, and a bigger payout ---


def test_elite_node_escalation_is_harder_than_combat_at_the_same_row(game):
    _begin_run_with_map(game, ["combat", "combat"])
    game._enter_node("1-0")
    normal_hp_multiplier = game.wave_manager.enemy_hp_multiplier

    _begin_run_with_map(game, ["combat", "elite"])
    game._enter_node("1-0")

    assert game.wave_manager.enemy_hp_multiplier > normal_hp_multiplier


def test_elite_node_clear_pays_out_more_shop_currency_than_combat(game):
    _begin_run_with_map(game, ["combat", "combat"])
    game._enter_node("1-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    normal_income = game.active_run.shop_currency

    _begin_run_with_map(game, ["combat", "elite"])
    game._enter_node("1-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    elite_income = game.active_run.shop_currency

    assert elite_income > normal_income


# --- Random Event nodes ---


def test_event_node_shows_the_event_screen(game):
    _begin_run_with_map(game, ["combat", "event"])

    game._enter_node("1-0")

    assert game.state == GameState.EVENT
    assert game.current_event.key in EVENTS
    assert game.event_phase == "choose"


def test_choosing_an_event_option_applies_its_effects_and_resolves(game):
    _begin_run_with_map(game, ["combat", "event"])
    game._enter_node("1-0")

    game._handle_event_click(game.event_option_rects[0].center)

    assert game.event_phase == "resolved"
    assert game.event_chosen_option is game.current_event.options[0]
    assert game.state == GameState.EVENT  # still on the event screen, showing the outcome


def test_finishing_a_resolved_event_returns_to_the_map(game):
    _begin_run_with_map(game, ["combat", "event"])
    game._enter_node("1-0")
    game._handle_event_click(game.event_option_rects[0].center)

    game._handle_event_click((0, 0))  # any click in the resolved phase finishes it

    assert game.state == GameState.MAP
    assert game.active_run.visited_node_ids == ["1-0"]


def test_event_escape_quits(game):
    _begin_run_with_map(game, ["combat", "event"])
    game._enter_node("1-0")

    game._handle_keydown(pygame.K_ESCAPE)

    assert game.running is False


# --- Rest nodes ---


def test_rest_node_heals_and_auto_resolves(game):
    _begin_run_with_map(game, ["combat", "rest"])
    game.active_run.lives = 10

    game._enter_node("1-0")

    assert game.state == GameState.REST
    assert game.active_run.lives == 10 + game.rest_heal_amount


def test_finishing_a_rest_node_returns_to_the_map(game):
    _begin_run_with_map(game, ["combat", "rest"])
    game._enter_node("1-0")

    game._handle_keydown(pygame.K_SPACE)

    assert game.state == GameState.MAP
    assert game.active_run.visited_node_ids == ["1-0"]


# --- Treasure nodes ---


def test_treasure_node_grants_currency_and_a_relic(game):
    _begin_run_with_map(game, ["combat", "treasure"])
    game.active_run.shop_currency = 0

    game._enter_node("1-0")

    assert game.state == GameState.TREASURE
    assert game.active_run.shop_currency == game.treasure_granted_currency
    assert game.treasure_granted_relic in game.active_run.relics


def test_treasure_node_relic_grant_degrades_once_exhausted(game):
    _begin_run_with_map(game, ["combat", "treasure"])
    game.active_run.relics = list(RELICS.keys())  # every relic already held

    game._enter_node("1-0")

    assert game.treasure_granted_relic is None
    assert game.active_run.relics == list(RELICS.keys())  # unchanged


def test_finishing_a_treasure_node_returns_to_the_map(game):
    _begin_run_with_map(game, ["combat", "treasure"])
    game._enter_node("1-0")

    game._handle_keydown(pygame.K_SPACE)

    assert game.state == GameState.MAP
    assert game.active_run.visited_node_ids == ["1-0"]


# --- Permadeath: the only way a run ends ---


def test_permadeath_ends_the_run_but_preserves_active_run_state(game):
    start_first_floor(game, seed=1)
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
    start_first_floor(game, seed=1)
    game.sandbox = True
    game.economy.lives = 1

    game.economy.lose_life()
    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert run_history.load_run_history(game.run_history_path) == {}
    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters.get("runs_played", 0) == 0


def test_permadeath_bumps_runs_played_and_records_run_history(game):
    start_first_floor(game, seed=1)
    seed = game.active_run.seed
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    assert meta_progression.load_meta_progression(game.meta_progression_path)["counters"]["runs_played"] == 1
    assert run_history.load_run_history(game.run_history_path) == {seed: 0}


def test_run_history_records_floors_cleared_at_time_of_death(game):
    _begin_run_with_map(game, ["combat", "combat"])
    game._enter_node("0-0")
    seed = game.active_run.seed
    finish_all_waves(game)
    game.update(dt=0.01)  # clears floor 0 -> FLOOR_CLEARED
    game._enter_map()
    game._enter_node("1-0")  # floor 1, PLAYING
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    assert run_history.load_run_history(game.run_history_path) == {seed: 1}


def test_permadeath_on_a_non_final_floor_does_not_bump_runs_reached_endless(game):
    start_first_floor(game, seed=1)
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters.get("runs_reached_endless", 0) == 0


def test_permadeath_on_the_final_floor_bumps_runs_reached_endless(game):
    game.start_new_run(seed=1)
    boss_id = game.active_run.map.boss_node_id
    game._enter_node(boss_id)
    game.economy.lives = 1
    game.enemies = []

    game.economy.lose_life()
    game.update(dt=0.01)

    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters["runs_reached_endless"] == 1


# --- Meta-progression accumulating across runs ---


def test_floor_clear_bumps_total_floors_cleared(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    counters = meta_progression.load_meta_progression(game.meta_progression_path)["counters"]
    assert counters["total_floors_cleared"] == 1


def test_first_floor_clear_unlocks_a_tower_and_it_appears_in_the_shop(game):
    # Regression guard: unlock_knockback's goal is 1 specifically so a
    # brand new player's very first floor clear already has something to
    # buy -- see meta_progression.py's own comment on why.
    _begin_run_with_map(game, ["combat", "shop"])
    game._enter_node("0-0")
    finish_all_waves(game)
    game.update(dt=0.01)
    game._enter_map()

    game._enter_node("1-0")  # the shop node

    assert game.state == GameState.DRAFT
    assert any(item.key == "knockback" for item in game.draft_choices)


def test_first_floor_clear_queues_a_new_tower_unlocked_toast(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)

    game.update(dt=0.01)

    assert any("New tower unlocked" in toast.text for toast in game.achievement_toasts)


# --- Saving and resuming a run mid-flight ---


def test_saving_mid_run_captures_the_active_run(game):
    start_first_floor(game, seed=1)
    run_before = game.active_run

    assert game.save_run() is True
    saved = save_state.load_run(game.save_path)

    assert saved["run"].seed == run_before.seed
    assert saved["run"].map == run_before.map
    assert saved["run"].unlocked_towers == run_before.unlocked_towers
    assert saved["run"].current_node_id == run_before.current_node_id
    assert saved["run"].shop_currency == run_before.shop_currency
    assert saved["run"].lives == run_before.lives


def test_resuming_a_saved_run_restores_active_run(game):
    start_first_floor(game, seed=1)
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
    assert game.active_run.map == run_before.map
    assert game.active_run.unlocked_towers == run_before.unlocked_towers
    assert game.active_run.current_node_id == run_before.current_node_id
    assert game.active_run.shop_currency == run_before.shop_currency
    assert game.active_run.lives == run_before.lives
    assert game.economy.gold == 350
    assert game.state == GameState.PLAYING


def test_resuming_a_saved_run_still_restricts_the_build_menu_to_its_unlocked_towers(game):
    start_first_floor(game, seed=1)
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
    # docstring) -- resuming re-derives the identical (seed, node id) rng a
    # *fresh* (never-saved) load of this same floor would get, not an
    # unseeded random.Random() that would make routing non-deterministic
    # from the resume point on. This is narrower than "identical to an
    # uninterrupted playthrough" in general, though: since no rng state is
    # serialized, a save taken mid-floor -- after some waves have already
    # consumed draws from this same rng object -- resumes at that rng's
    # own start, not wherever the un-saved playthrough's consumption had
    # already left it. Later waves can route differently after such a
    # resume than they would have without one. Serializing the rng's own
    # consumed position would close this gap but means carrying real RNG
    # state in the save file, which is the exact thing this whole
    # re-derivation scheme exists to avoid.
    _begin_run_with_map(game, ["combat"] * 4)
    game._enter_node("3-0")
    expected_first_draw = game.wave_manager.rng.random()

    game._enter_node("3-0")  # reload floor 3 fresh -- re-derives the same un-consumed rng
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
    # _load_combat_node() call gets it right.
    _begin_run_with_map(game, ["combat"] * 4)
    game._enter_node("3-0")
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
    _begin_run_with_map(game, ["combat"] * 3)
    game.active_run.relics = ["bounty_hunters_ledger"]
    game._enter_node("2-0")
    expected_gold_multiplier = game.wave_manager.enemy_gold_multiplier
    assert expected_gold_multiplier != 1.0  # relic + escalation both contribute -- not a vacuous assertion
    game.save_run()
    game.state = GameState.MENU

    game._continue_saved_run()

    assert game.wave_manager.enemy_gold_multiplier == expected_gold_multiplier


def test_resuming_a_run_reapplies_its_held_relics_enemy_speed_multiplier(game):
    _begin_run_with_map(game, ["combat"] * 3)
    game.active_run.relics = ["tangled_roots"]
    game._enter_node("2-0")
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
    game._enter_node(game.active_run.map.start_node_ids[0])
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
    # load -- but _load_combat_node() (what every floor transition after a
    # resume goes through) used to inherit that reset unconditionally too,
    # silently un-marking the run as resumed the moment its very next
    # floor loaded. That left _delete_save_if_this_run_was_resumed()
    # gated on an already-False flag by the time this run actually
    # concluded, so its now-stale save file was never cleaned up.
    _begin_run_with_map(game, ["combat", "shop", "combat"])
    game._enter_node("0-0")
    game.save_run()
    game.state = GameState.MENU
    game._continue_saved_run()
    assert game._resumed_from_save is True

    finish_all_waves(game)
    game.update(dt=0.01)  # -> FLOOR_CLEARED
    game._enter_map()
    game._enter_node("1-0")  # the shop node
    game.active_run.shop_currency = 9999
    game._handle_draft_click(game.draft_choice_rects[0].center)  # buy an item
    game._handle_draft_click(game.shop_continue_button_rect.center)  # -> back to the map, still same run
    assert game._resumed_from_save is True

    game._enter_node("2-0")  # the next combat node
    assert game._resumed_from_save is True

    game.economy.lives = 1
    game.economy.lose_life()
    game.update(dt=0.01)

    assert game.state == GameState.GAME_OVER
    assert not save_state.has_saved_run(game.save_path)  # the stale save is actually cleaned up now


# --- Daily Run ---


def test_menu_d_key_starts_daily_run(game):
    game._handle_keydown(pygame.K_d)
    assert game.state == GameState.MAP
    assert game.active_run is not None
    assert game.active_run.is_daily is True


def test_daily_run_seeds_reproducibly(game):
    game._start_daily_challenge(seed=20260903)
    game._enter_node(game.active_run.map.start_node_ids[0])
    # Nothing has drawn from the rng yet at this point (no enemy spawned) --
    # a fresh run seeded the same way must produce the identical next value.
    first_draw = game.wave_manager.rng.random()

    game._start_daily_challenge(seed=20260903)
    game._enter_node(game.active_run.map.start_node_ids[0])
    second_draw = game.wave_manager.rng.random()

    assert first_draw == second_draw


def test_daily_run_pins_difficulty_to_normal_regardless_of_player_setting(game):
    game.set_difficulty("hard")  # starting_gold_multiplier=0.85, see difficulty.py

    game._start_daily_challenge(seed=20260903)
    game._enter_node(game.active_run.map.start_node_ids[0])

    assert game.active_run.difficulty == "normal"
    level = LEVELS[game.current_level_id]
    assert game.economy.gold == level.starting_gold  # normal's 1.0x, not hard's 0.85x


def test_daily_run_records_floors_cleared_on_game_over_and_keeps_the_best_score(game):
    game._start_daily_challenge(seed=20260903)
    seed = game.active_run.seed
    game.active_run.map = make_linear_run_map(["combat"] * 5)
    game._enter_node("4-0")
    game.active_run.visited_node_ids = ["0-0", "1-0", "2-0"]  # simulate having cleared 3 floors
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
    game._enter_node(game.active_run.map.start_node_ids[0])
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


def test_render_map_does_not_crash(game):
    game.start_new_run(seed=1)
    assert game.state == GameState.MAP

    game.render()


def test_render_floor_cleared_does_not_crash(game):
    start_first_floor(game, seed=1)
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.FLOOR_CLEARED

    game.render()


def test_render_draft_does_not_crash(game):
    _enter_run_shop(game)
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
    _begin_run_with_map(game, ["combat", "shop"])
    game._enter_node("1-0")
    _force_relic_draft(game, "war_chest")
    assert game.state == GameState.DRAFT

    game.render()


def test_render_event_does_not_crash(game):
    _begin_run_with_map(game, ["combat", "event"])
    game._enter_node("1-0")

    game.render()  # the "choose" phase

    game._handle_event_click(game.event_option_rects[0].center)

    game.render()  # the "resolved" phase


def test_render_rest_does_not_crash(game):
    _begin_run_with_map(game, ["combat", "rest"])
    game._enter_node("1-0")

    game.render()


def test_render_treasure_does_not_crash(game):
    _begin_run_with_map(game, ["combat", "treasure"])
    game._enter_node("1-0")

    game.render()
