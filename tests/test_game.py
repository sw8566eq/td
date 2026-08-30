"""Tests for the Game state machine, input handling, and update loop.

Game() opens a real pygame window, so this module forces the SDL dummy
video driver before pygame ever gets touched -- these tests must be able
to run headless in CI/sandboxes with no real display, same as the manual
smoke tests this project has been relying on during development.
"""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

import achievements  # noqa: E402
import difficulty  # noqa: E402
import player_settings  # noqa: E402
import progress  # noqa: E402
import save_state  # noqa: E402
import settings  # noqa: E402
import ui  # noqa: E402
from editor import EditorTool  # noqa: E402
from game import Game, GameState  # noqa: E402
from levels import LEVELS, Level  # noqa: E402
from tower import TOWER_TYPES, BasicTower  # noqa: E402
from waves import WaveState  # noqa: E402


@pytest.fixture
def game(tmp_path):
    # progress_path/settings_path/achievements_path/save_path all pinned to
    # throwaway files -- Game writes real progress on VICTORY (see
    # progress.py), real settings on set_fullscreen()/set_difficulty() (see
    # player_settings.py), real achievement counters on nearly every tower/
    # kill/wave/level event (see achievements.py), and a real in-progress
    # save on save_run() (see save_state.py), and this must never touch (or
    # leave behind) any of those real repo-root files.
    g = Game(
        progress_path=tmp_path / "progress.json", settings_path=tmp_path / "player_settings.json",
        achievements_path=tmp_path / "achievements.json", save_path=tmp_path / "save_state.json",
    )
    yield g
    pygame.quit()


@pytest.fixture
def playing_game(game):
    game.state = GameState.PLAYING
    return game


def find_buildable_anchor(game, *, adjacent_to_path=False):
    """A buildable placement anchor (tile-aligned, i.e. (col, row) *
    SUBTILES_PER_TILE); optionally one touching the path, for tests that
    care about tower coverage rather than just placement."""
    n = settings.SUBTILES_PER_TILE
    for row in range(settings.GRID_ROWS):
        for col in range(settings.GRID_COLS):
            if not game.grid.is_buildable(col * n, row * n):
                continue
            if not adjacent_to_path:
                return col * n, row * n
            for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                if game.grid.is_path(col + dc, row + dr):
                    return col * n, row * n
    raise AssertionError("no matching buildable cell found")


_REAL_MOUSE_GET_POS = pygame.mouse.get_pos  # saved once, before anything monkeypatches it


def mock_mouse_pos(pos):
    """Context-manager-free mouse mock: pygame.mouse.set_pos() is inert
    under the headless dummy driver, so tests that need a specific hover
    position monkeypatch get_pos() directly instead."""
    pygame.mouse.get_pos = lambda: pos


def clear_mouse_mock():
    # Restore the real get_pos rather than del'ing the attribute -- del
    # would just remove it outright (mock_mouse_pos *replaces* the dict
    # entry, it doesn't shadow it), leaving pygame.mouse with no get_pos
    # at all for every test that runs after this one in the same session.
    pygame.mouse.get_pos = _REAL_MOUSE_GET_POS


_REAL_KEY_GET_MODS = pygame.key.get_mods  # saved once, before anything monkeypatches it


def mock_key_mods(mods):
    """Same idea as mock_mouse_pos -- pygame.key.get_mods() reads real
    global keyboard state, which a headless test can't hold Ctrl/Shift/etc.
    on, so tests needing a specific modifier state (Ctrl+Z/Ctrl+Y) mock it
    directly instead."""
    pygame.key.get_mods = lambda: mods


def clear_key_mods():
    pygame.key.get_mods = _REAL_KEY_GET_MODS


# --- Initialization ---

def test_starts_at_the_menu_on_level_one(game):
    assert game.state == GameState.MENU
    assert game.running is True
    assert game.current_level_id == 1
    assert game.level.id == 1


def test_window_size_matches_settings(game):
    assert game.screen.get_size() == (settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)


def test_economy_matches_the_loaded_levels_starting_values(game):
    assert game.economy.gold == game.level.starting_gold
    assert game.economy.lives == game.level.starting_lives


def test_unlimited_gold_defaults_to_off(game):
    assert game.economy.unlimited_gold is False


def test_unlimited_gold_flag_flows_through_to_the_economy(tmp_path):
    g = Game(unlimited_gold=True, progress_path=tmp_path / "progress.json",
             settings_path=tmp_path / "player_settings.json", achievements_path=tmp_path / "achievements.json",
             save_path=tmp_path / "save_state.json")
    try:
        assert g.economy.unlimited_gold is True
    finally:
        pygame.quit()


def test_unlimited_gold_flag_survives_a_level_reload(tmp_path):
    g = Game(unlimited_gold=True, progress_path=tmp_path / "progress.json",
             settings_path=tmp_path / "player_settings.json", achievements_path=tmp_path / "achievements.json",
             save_path=tmp_path / "save_state.json")
    try:
        g.load_level(g.current_level_id)
        assert g.economy.unlimited_gold is True
    finally:
        pygame.quit()


def test_starts_with_no_entities_or_selection(game):
    assert game.enemies == []
    assert game.towers == []
    assert game.projectiles == []
    assert game.selected_tower_name is None


# --- Difficulty modes ---

def test_defaults_to_normal_difficulty(game):
    assert game.difficulty == "normal"


def test_set_difficulty_accepts_a_known_key(game):
    game.set_difficulty("hard")
    assert game.difficulty == "hard"


def test_set_difficulty_ignores_an_unknown_key(game):
    game.set_difficulty("nonsense")
    assert game.difficulty == "normal"


def test_hard_difficulty_yields_fewer_starting_lives_and_tougher_enemies_than_easy(tmp_path):
    hard = Game(progress_path=tmp_path / "hard.json", settings_path=tmp_path / "hard_settings.json",
                achievements_path=tmp_path / "hard_achievements.json", save_path=tmp_path / "hard_save.json")
    easy = Game(progress_path=tmp_path / "easy.json", settings_path=tmp_path / "easy_settings.json",
                achievements_path=tmp_path / "easy_achievements.json", save_path=tmp_path / "easy_save.json")
    try:
        hard.set_difficulty("hard")
        hard.load_level(1)
        easy.set_difficulty("easy")
        easy.load_level(1)

        assert hard.economy.lives < easy.economy.lives
        assert hard.economy.gold < easy.economy.gold

        hard.wave_manager.skip_delay()
        easy.wave_manager.skip_delay()
        hard_spawned = hard.wave_manager.update(dt=1.0, active_enemies=[])
        while not hard_spawned:
            hard_spawned = hard.wave_manager.update(dt=0.1, active_enemies=[])
        easy_spawned = easy.wave_manager.update(dt=1.0, active_enemies=[])
        while not easy_spawned:
            easy_spawned = easy.wave_manager.update(dt=0.1, active_enemies=[])

        assert hard_spawned[0].max_hp > easy_spawned[0].max_hp
    finally:
        pygame.quit()


# --- State machine: keydown handling ---

def test_menu_any_key_starts_playing(game):
    game._handle_keydown(pygame.K_SPACE)  # not one of the menu's own bound keys (E/L/S/A)
    assert game.state == GameState.PLAYING


def test_menu_escape_quits_without_starting(game):
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.running is False
    assert game.state == GameState.MENU


def test_playing_p_pauses(playing_game):
    playing_game._handle_keydown(pygame.K_p)
    assert playing_game.state == GameState.PAUSED


def test_playing_escape_opens_the_pause_menu(playing_game):
    playing_game._handle_keydown(pygame.K_ESCAPE)
    assert playing_game.state == GameState.PAUSED
    assert playing_game.running is True


def test_playing_space_skips_the_wave_delay(playing_game):
    assert playing_game.wave_manager.between_wave_timer > 0
    playing_game._handle_keydown(pygame.K_SPACE)
    assert playing_game.wave_manager.between_wave_timer <= 0


def test_playing_unbound_key_is_a_no_op(playing_game):
    playing_game._handle_keydown(pygame.K_z)
    assert playing_game.state == GameState.PLAYING
    assert playing_game.running is True


def test_playing_number_keys_set_time_scale(playing_game):
    playing_game._handle_keydown(pygame.K_3)
    assert playing_game.time_scale == 3.0
    playing_game._handle_keydown(pygame.K_1)
    assert playing_game.time_scale == 1.0
    playing_game._handle_keydown(pygame.K_2)
    assert playing_game.time_scale == 2.0


def test_cycle_time_scale_wraps_around(game):
    assert game.time_scale == 1.0
    game.cycle_time_scale()
    assert game.time_scale == 2.0
    game.cycle_time_scale()
    assert game.time_scale == 3.0
    game.cycle_time_scale()
    assert game.time_scale == 1.0


def test_set_time_scale_ignores_an_invalid_value(game):
    game.set_time_scale(2.0)
    game.set_time_scale(1.5)  # not one of TIME_SCALES -- silently ignored
    assert game.time_scale == 2.0


def test_time_scale_speeds_up_enemy_movement(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]
    baseline_distance = enemy.distance_traveled

    playing_game.set_time_scale(3.0)
    playing_game.update(dt=0.1)
    scaled_distance = enemy.distance_traveled - baseline_distance

    assert scaled_distance == pytest.approx(enemy.speed * 0.1 * 3.0)


def test_speed_button_click_cycles_time_scale(playing_game):
    assert playing_game.time_scale == 1.0
    playing_game._handle_click(playing_game.speed_button_rect.center)
    assert playing_game.time_scale == 2.0


def test_paused_p_resumes(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_p)
    assert playing_game.state == GameState.PLAYING


def test_paused_escape_also_resumes(playing_game):
    # Esc opens the pause menu from PLAYING and closes it again from
    # PAUSED -- symmetric with P, not a second way to quit.
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_ESCAPE)
    assert playing_game.state == GameState.PLAYING
    assert playing_game.running is True


def test_paused_r_restarts_the_level_and_resumes_playing(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game.economy.gold = 0
    playing_game.economy.lives = 1
    playing_game.towers = ["fake"]

    playing_game._handle_keydown(pygame.K_r)

    assert playing_game.state == GameState.PLAYING
    assert playing_game.economy.gold == playing_game.level.starting_gold
    assert playing_game.economy.lives == playing_game.level.starting_lives
    assert playing_game.towers == []


def test_paused_q_quits(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_q)
    assert playing_game.running is False


def test_paused_unbound_key_is_a_no_op(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_z)
    assert playing_game.state == GameState.PAUSED
    assert playing_game.running is True


def test_paused_e_returns_to_the_map_editor_on_a_custom_level(game):
    game.load_custom_level(make_custom_level())
    game.state = GameState.PAUSED

    game._handle_keydown(pygame.K_e)

    assert game.state == GameState.EDITOR


def test_paused_e_is_a_no_op_on_a_built_in_level(playing_game):
    # "Return to Map Editor" is only offered (see ui.draw_pause_menu) for
    # a custom level -- a built-in one has no corresponding paint buffer
    # to go back to.
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_e)
    assert playing_game.state == GameState.PAUSED


def test_game_over_unbound_key_is_a_no_op(game):
    game.state = GameState.GAME_OVER
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.GAME_OVER
    assert game.running is True


def test_game_over_r_resets_the_same_level_and_resumes_playing(game):
    game.state = GameState.GAME_OVER
    game.economy.gold = 0
    game.economy.lives = 0
    game._handle_keydown(pygame.K_r)
    assert game.state == GameState.PLAYING
    assert game.current_level_id == 1
    assert game.economy.lives == game.level.starting_lives
    assert game.economy.gold == game.level.starting_gold


def test_game_over_escape_quits(game):
    game.state = GameState.GAME_OVER
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.running is False


def test_handle_keydown_on_an_unrecognized_state_is_a_no_op(game):
    # Not reachable through real play -- GameState's if/elif chain already
    # covers every one of its members, VICTORY included, so this only
    # exercises the chain's final fallthrough as a safety net against a
    # future state ever being added without a matching branch.
    game.state = "not-a-real-game-state"
    game._handle_keydown(pygame.K_r)
    assert game.state == "not-a-real-game-state"
    assert game.running is True


def test_victory_unbound_key_is_a_no_op(game):
    game.state = GameState.VICTORY
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.VICTORY
    assert game.running is True


def test_victory_r_advances_to_the_next_level(game):
    game.state = GameState.VICTORY
    assert game.current_level_id == 1
    game._handle_keydown(pygame.K_r)
    assert game.state == GameState.PLAYING
    assert game.current_level_id == 2


def test_victory_r_replays_the_last_level_when_none_is_next(game):
    last_id = max(LEVELS.keys())
    game.current_level_id = last_id
    game.load_level(last_id)
    game.state = GameState.VICTORY

    game._handle_keydown(pygame.K_r)

    assert game.state == GameState.PLAYING
    assert game.current_level_id == last_id


def test_victory_escape_quits(game):
    game.state = GameState.VICTORY
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.running is False


# --- Click handling: build menu / skip button ---

def test_clicking_a_tower_button_selects_it(playing_game):
    rect = playing_game.button_rects["basic"]
    playing_game._handle_click(rect.center)
    assert playing_game.selected_tower_name == "basic"


def test_clicking_the_same_tower_button_again_deselects_it(playing_game):
    rect = playing_game.button_rects["basic"]
    playing_game._handle_click(rect.center)
    playing_game._handle_click(rect.center)
    assert playing_game.selected_tower_name is None


def test_clicking_a_different_tower_button_switches_selection(playing_game):
    playing_game._handle_click(playing_game.button_rects["basic"].center)
    playing_game._handle_click(playing_game.button_rects["cannon"].center)
    assert playing_game.selected_tower_name == "cannon"


def test_clicking_the_skip_button_skips_the_wave_delay(playing_game):
    playing_game._handle_click(playing_game.skip_button_rect.center)
    assert playing_game.wave_manager.between_wave_timer <= 0


def test_clicking_empty_hud_area_does_nothing(playing_game):
    # Somewhere in the HUD bar but not on any button.
    pos = (playing_game.button_rects["basic"].right + 200, settings.SCREEN_HEIGHT - 10)
    playing_game.selected_tower_name = "basic"
    playing_game._handle_click(pos)
    assert playing_game.towers == []
    assert playing_game.selected_tower_name == "basic"  # unchanged, not cleared


def test_clicks_are_ignored_entirely_outside_playing(game):
    game.state = GameState.PAUSED
    rect = game.button_rects["basic"]
    game._handle_click(rect.center)
    assert game.selected_tower_name is None


# --- Click handling: placing towers ---

def test_clicking_a_buildable_cell_with_a_tower_selected_places_it(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game.selected_tower_name = "basic"

    playing_game._handle_click((int(center.x), int(center.y)))

    assert len(playing_game.towers) == 1
    assert playing_game.grid.is_occupied(anchor_col, anchor_row)
    assert playing_game.economy.gold == playing_game.level.starting_gold - BasicTower.cost


def test_clicking_a_buildable_cell_with_nothing_selected_does_nothing(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)

    playing_game._handle_click((int(center.x), int(center.y)))

    assert playing_game.towers == []


def test_clicking_a_path_cell_never_places_a_tower(playing_game):
    path_col, path_row = next(iter(playing_game.grid.path_cells))
    center = playing_game.grid.tile_to_pixel_center(path_col, path_row)
    playing_game.selected_tower_name = "basic"

    playing_game._handle_click((int(center.x), int(center.y)))

    assert playing_game.towers == []


def test_clicking_to_place_an_unaffordable_tower_does_nothing(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game.economy.gold = 0
    playing_game.selected_tower_name = "basic"

    playing_game._handle_click((int(center.x), int(center.y)))

    assert playing_game.towers == []


# --- Click handling: upgrading towers ---

def test_clicking_a_towers_badge_upgrades_it(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    gold_before = playing_game.economy.gold
    upgrade_cost = tower.upgrade_cost()

    badge = tower.upgrade_badge_center()
    playing_game._handle_click((int(badge[0]), int(badge[1])))

    assert tower.level == 2
    assert playing_game.economy.gold == gold_before - upgrade_cost


def test_clicking_elsewhere_on_a_placed_tower_does_not_upgrade_it(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)

    playing_game._handle_click((int(center.x), int(center.y)))  # tile center, not the badge

    assert tower.level == 1


# --- Click handling: selecting and selling placed towers ---

def test_clicking_a_placed_tower_pins_it_as_selected(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)

    playing_game._handle_click((int(center.x), int(center.y)))  # tile center, not the badge

    assert playing_game.selected_tower is tower


def test_selection_stays_pinned_in_the_panel_after_the_mouse_moves_away(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))

    mock_mouse_pos((0, 0))  # nowhere near the tower
    try:
        subject = playing_game._stats_panel_subject(playing_game._hovered_tower())
    finally:
        clear_mouse_mock()

    assert subject is tower


def test_clicking_a_different_placed_tower_switches_the_selection(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    first_tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    assert playing_game.selected_tower is first_tower

    other_anchor_col, other_anchor_row = find_buildable_anchor(playing_game)
    other_center = playing_game.grid.anchor_to_pixel_center(other_anchor_col, other_anchor_row)
    playing_game.selected_tower_name = "cannon"
    playing_game._handle_click((int(other_center.x), int(other_center.y)))
    second_tower = playing_game.grid.get_tower(other_anchor_col, other_anchor_row)
    playing_game._handle_click((int(other_center.x), int(other_center.y)))

    assert playing_game.selected_tower is second_tower


def test_selecting_a_build_menu_tower_clears_the_pinned_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    playing_game._handle_click((int(center.x), int(center.y)))
    assert playing_game.selected_tower is not None

    playing_game._handle_click(playing_game.button_rects["cannon"].center)

    assert playing_game.selected_tower is None


def test_clicking_empty_ground_with_nothing_selected_clears_the_pinned_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.anchor_to_pixel_center(anchor_col, anchor_row)
    playing_game._handle_click((int(center.x), int(center.y)))
    playing_game._handle_click((int(center.x), int(center.y)))
    playing_game.selected_tower_name = None
    assert playing_game.selected_tower is not None

    empty_col, empty_row = find_buildable_anchor(playing_game)  # skips the now-occupied tile
    empty_center = playing_game.grid.anchor_to_pixel_center(empty_col, empty_row)
    playing_game._handle_click((int(empty_center.x), int(empty_center.y)))

    assert playing_game.selected_tower is None


def test_clicking_inert_panel_text_does_not_deselect_the_pinned_tower(playing_game):
    # Regression test: the "click missed every button" fallback only
    # checked pos[1] against the HUD strip, never pos[0] against the
    # panel's left edge (settings.PLAY_WIDTH), so a click anywhere in the
    # panel that wasn't a button -- e.g. on the tower's name or stat text
    # -- fell through to the same "clicked empty ground" case as a click
    # on the actual grid, silently closing the pinned tower's panel.
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower
    playing_game.selected_tower_name = None  # not in build mode

    inert_panel_point = (settings.PLAY_WIDTH + 20, 50)  # panel title/stat text, not a button
    playing_game._handle_click(inert_panel_point)

    assert playing_game.selected_tower is tower


def test_try_sell_tower_removes_it_and_refunds_gold(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    gold_before = playing_game.economy.gold
    refund = tower.sell_value()

    assert playing_game.try_sell_tower(tower) is True

    assert tower not in playing_game.towers
    assert playing_game.economy.gold == gold_before + refund
    assert playing_game.grid.is_buildable(anchor_col, anchor_row)


def test_try_sell_tower_keeps_it_in_sold_towers_for_the_results_screen(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)

    playing_game.try_sell_tower(tower)

    assert tower not in playing_game.towers
    assert tower in playing_game.sold_towers


def test_tower_results_includes_a_sold_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    tower.damage_dealt = 42.0
    playing_game.try_sell_tower(tower)

    results = playing_game._tower_results()

    assert any(row["damage_dealt"] == 42.0 for row in results)


def test_try_sell_tower_clears_a_matching_pinned_selection(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower

    playing_game.try_sell_tower(tower)

    assert playing_game.selected_tower is None


def test_try_sell_tower_fails_for_a_tower_not_on_the_field(playing_game):
    stray_tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    assert playing_game.try_sell_tower(stray_tower) is False


def test_loading_a_new_level_clears_sold_towers_from_the_previous_one(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.try_sell_tower(tower)
    assert playing_game.sold_towers != []

    playing_game.load_level(2)

    assert playing_game.sold_towers == []


def test_render_victory_screen_with_tower_stats_does_not_crash(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    playing_game.grid.get_tower(anchor_col, anchor_row).damage_dealt = 99.0
    playing_game.state = GameState.VICTORY
    playing_game.render()


def test_render_game_over_screen_with_tower_stats_does_not_crash(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    playing_game.grid.get_tower(anchor_col, anchor_row).damage_dealt = 99.0
    playing_game.state = GameState.GAME_OVER
    playing_game.render()


def test_clicking_the_upgrade_button_upgrades_the_pinned_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower
    gold_before = playing_game.economy.gold
    upgrade_cost = tower.upgrade_cost()

    mock_mouse_pos(playing_game.upgrade_button_rect.center)  # nowhere near the tower on the grid
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.upgrade_button_rect.center)
    finally:
        clear_mouse_mock()

    assert tower.level == 2
    assert playing_game.economy.gold == gold_before - upgrade_cost


def test_clicking_the_targeting_button_cycles_the_pinned_towers_mode(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower
    assert tower.targeting_mode == "first"

    mock_mouse_pos(playing_game.targeting_button_rect.center)
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.targeting_button_rect.center)
    finally:
        clear_mouse_mock()

    assert tower.targeting_mode == "last"


def test_clicking_the_targeting_button_with_nothing_selected_does_nothing(playing_game):
    assert playing_game._last_panel_subject is None
    # Must not raise -- and there's no tower to have changed a mode on.
    playing_game._handle_click(playing_game.targeting_button_rect.center)


def test_clicking_the_targeting_button_on_a_pinned_support_tower_is_a_no_op(playing_game):
    # Regression test for the click-routing gotcha: the targeting row
    # isn't drawn for a support tower (see ui.draw_tower_stats_panel's
    # IS_SUPPORT guard), but targeting_button_rect still occupies that
    # screen position regardless of subject.
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "support"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower
    assert tower.targeting_mode == "first"

    mock_mouse_pos(playing_game.targeting_button_rect.center)
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.targeting_button_rect.center)
    finally:
        clear_mouse_mock()

    assert tower.targeting_mode == "first"  # unchanged


def test_clicking_the_upgrade_button_with_nothing_selected_does_nothing(playing_game):
    gold_before = playing_game.economy.gold
    playing_game._handle_click(playing_game.upgrade_button_rect.center)
    assert playing_game.economy.gold == gold_before


def test_clicking_the_upgrade_button_when_unaffordable_does_nothing(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower
    playing_game.economy.gold = 0

    mock_mouse_pos(playing_game.upgrade_button_rect.center)
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.upgrade_button_rect.center)
    finally:
        clear_mouse_mock()

    assert tower.level == 1


def test_clicking_the_upgrade_buttons_rect_at_max_level_specializes_instead(playing_game):
    # Regression test for a real bug: the Upgrade button and the first
    # Specialize button intentionally share a rect (see
    # ui.build_specialize_button_rects -- the two are mutually exclusive
    # states), but Game._handle_click checked the Upgrade rect first and
    # always returned there, so a maxed tower's click on that rect used
    # to silently call try_upgrade_tower (a no-op once maxed) and never
    # reach the specialize handling below it -- "Power" looked dead.
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.selected_tower = tower

    mock_mouse_pos(playing_game.upgrade_button_rect.center)
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.upgrade_button_rect.center)
    finally:
        clear_mouse_mock()

    expected_key = list(tower.SPECIALIZATIONS.keys())[0]
    assert tower.specialization == expected_key


def test_clicking_that_shared_rect_does_nothing_once_already_specialized(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.try_specialize_tower(tower, "power")
    playing_game.selected_tower = tower
    gold_before = playing_game.economy.gold

    mock_mouse_pos(playing_game.upgrade_button_rect.center)
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.upgrade_button_rect.center)
    finally:
        clear_mouse_mock()

    assert tower.specialization == "power"  # unchanged
    assert playing_game.economy.gold == gold_before


def test_action_buttons_act_on_the_tower_shown_when_rendered_not_a_stale_pin(playing_game):
    # Regression test for a real bug: _handle_panel_action_click used to
    # re-derive "which tower is this click for?" from _hovered_tower() at
    # click time -- but by the time the mouse is actually over a panel
    # button, it's not over any tower's tile_rect() on the grid, so that
    # lookup always reads as "not hovering anything" and silently falls
    # back to whatever's pinned. So: player hovers tower_a (panel renders
    # showing tower_a's Upgrade button), moves the mouse onto that exact
    # button and clicks -- all before another render() happens, matching
    # how mouse-motion events and a click can land in the same frame's
    # event batch ahead of the next render(). The click must act on
    # tower_a (what was shown), not tower_b (what's pinned).
    anchor_a = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(*anchor_a)
    tower_a = playing_game.grid.get_tower(*anchor_a)

    anchor_b = find_buildable_anchor(playing_game)
    playing_game.try_place_tower(*anchor_b)
    tower_b = playing_game.grid.get_tower(*anchor_b)

    playing_game.selected_tower = tower_b  # tower_b is pinned
    a_center = playing_game.grid.anchor_to_pixel_center(*anchor_a)

    mock_mouse_pos((int(a_center.x), int(a_center.y)))
    try:
        playing_game.render()  # panel shows tower_a's button -- hover beats the pin
        mock_mouse_pos(playing_game.upgrade_button_rect.center)  # mouse moves onto that button...
        playing_game._handle_click(playing_game.upgrade_button_rect.center)  # ...and clicks
    finally:
        clear_mouse_mock()

    assert tower_a.level == 2  # the tower whose button was actually shown and clicked
    assert tower_b.level == 1  # not the stale pinned tower


def test_hovered_specialize_key_is_none_when_not_hovering_either_button(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)

    mock_mouse_pos((0, 0))  # nowhere near either specialize button
    try:
        assert playing_game._hovered_specialize_key(tower) is None
    finally:
        clear_mouse_mock()


def test_hovered_specialize_key_matches_the_hovered_button(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)

    second_button = playing_game.specialize_button_rects[1]
    mock_mouse_pos(second_button.center)
    try:
        expected_key = list(tower.SPECIALIZATIONS.keys())[1]
        assert playing_game._hovered_specialize_key(tower) == expected_key
    finally:
        clear_mouse_mock()


def test_hovered_specialize_key_is_none_once_already_specialized(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.try_specialize_tower(tower, "power")

    second_button = playing_game.specialize_button_rects[1]
    mock_mouse_pos(second_button.center)
    try:
        assert playing_game._hovered_specialize_key(tower) is None
    finally:
        clear_mouse_mock()


def test_hovered_specialize_key_is_none_for_a_non_tower_subject(playing_game):
    mock_mouse_pos(playing_game.specialize_button_rects[1].center)
    try:
        assert playing_game._hovered_specialize_key(None) is None
        assert playing_game._hovered_specialize_key(BasicTower) is None
    finally:
        clear_mouse_mock()


def test_try_specialize_tower_succeeds_and_deducts_gold(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    gold_before = playing_game.economy.gold
    cost = tower.specialization_cost()

    assert playing_game.try_specialize_tower(tower, "power") is True

    assert tower.specialization == "power"
    assert playing_game.economy.gold == gold_before - cost


def test_try_specialize_tower_records_the_towers_specialized_achievement_counter(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)

    playing_game.try_specialize_tower(tower, "power")

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["towers_specialized"] == 1


def test_try_specialize_tower_fails_before_max_level(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)

    assert playing_game.try_specialize_tower(tower, "power") is False
    assert tower.specialization is None


def test_try_specialize_tower_fails_when_unaffordable(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.economy.gold = 0

    assert playing_game.try_specialize_tower(tower, "power") is False
    assert tower.specialization is None


def test_try_specialize_tower_fails_for_an_unknown_key(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)

    assert playing_game.try_specialize_tower(tower, "not-a-real-key") is False
    assert tower.specialization is None


def test_try_specialize_tower_fails_for_a_tower_not_on_the_field(playing_game):
    stray_tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    playing_game.economy.gold = 10_000
    while not stray_tower.is_max_level:
        stray_tower.upgrade()
    gold_before = playing_game.economy.gold

    assert playing_game.try_specialize_tower(stray_tower, "power") is False

    assert stray_tower.specialization is None
    assert playing_game.economy.gold == gold_before


def test_clicking_a_specialize_button_specializes_the_pinned_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.selected_tower = tower
    gold_before = playing_game.economy.gold

    second_button = playing_game.specialize_button_rects[1]
    mock_mouse_pos(second_button.center)  # nowhere near the tower on the grid
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(second_button.center)
    finally:
        clear_mouse_mock()

    expected_key = list(tower.SPECIALIZATIONS.keys())[1]
    assert tower.specialization == expected_key
    assert playing_game.economy.gold < gold_before


def test_clicking_a_specialize_button_before_max_level_does_nothing(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower

    # Rect 0 intentionally shares the Upgrade button's position (the two
    # are mutually exclusive states); rect 1 is unambiguous.
    second_button = playing_game.specialize_button_rects[1]
    mock_mouse_pos(second_button.center)
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(second_button.center)
    finally:
        clear_mouse_mock()

    assert tower.level == 1
    assert tower.specialization is None


def test_clicking_a_specialize_button_beyond_the_towers_own_options_does_nothing(playing_game, monkeypatch):
    # Defensive guard: every registered tower actually has exactly two
    # SPECIALIZATIONS (see test_tower_leveling.py), so this can't happen
    # through real content today, but _handle_panel_action_click's index
    # bounds-check still has to hold if a tower were ever registered with
    # fewer than len(specialize_button_rects) options.
    monkeypatch.setattr(BasicTower, "SPECIALIZATIONS", {"only_one": BasicTower.SPECIALIZATIONS["power"]})

    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.selected_tower = tower

    second_button = playing_game.specialize_button_rects[1]  # index 1 -- out of range for 1 key
    mock_mouse_pos(second_button.center)
    try:
        playing_game.render()
        playing_game._handle_click(second_button.center)
    finally:
        clear_mouse_mock()

    assert tower.specialization is None


def test_clicking_a_specialize_button_with_nothing_selected_does_nothing(playing_game):
    gold_before = playing_game.economy.gold
    second_button = playing_game.specialize_button_rects[1]
    playing_game._handle_click(second_button.center)
    assert playing_game.economy.gold == gold_before


def test_clicking_the_sell_button_sells_the_pinned_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower = tower
    gold_before = playing_game.economy.gold
    refund = tower.sell_value()

    mock_mouse_pos(playing_game.sell_button_rect.center)  # nowhere near the tower on the grid
    try:
        playing_game.render()  # populates _last_panel_subject, as a real frame would first
        playing_game._handle_click(playing_game.sell_button_rect.center)
    finally:
        clear_mouse_mock()

    assert tower not in playing_game.towers
    assert playing_game.economy.gold == gold_before + refund


def test_clicking_the_sell_button_with_nothing_selected_does_nothing(playing_game):
    gold_before = playing_game.economy.gold
    playing_game._handle_click(playing_game.sell_button_rect.center)
    assert playing_game.economy.gold == gold_before
    assert playing_game.towers == []


# --- Right-click handling ---

def test_right_click_clears_the_selected_tower_name(playing_game):
    playing_game.selected_tower_name = "basic"
    playing_game._handle_right_click()
    assert playing_game.selected_tower_name is None


def test_right_click_clears_the_pinned_tower(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    playing_game.selected_tower = playing_game.grid.get_tower(anchor_col, anchor_row)

    playing_game._handle_right_click()

    assert playing_game.selected_tower is None


def test_right_click_with_nothing_selected_is_a_no_op(playing_game):
    playing_game._handle_right_click()
    assert playing_game.selected_tower_name is None


def test_right_click_is_ignored_outside_playing(game):
    game.state = GameState.PAUSED
    game.selected_tower_name = "basic"
    game._handle_right_click()
    assert game.selected_tower_name == "basic"  # unchanged


# --- try_place_tower / try_upgrade_tower directly ---

def test_try_place_tower_succeeds_and_deducts_gold(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    assert playing_game.try_place_tower(anchor_col, anchor_row) is True
    assert playing_game.economy.gold == playing_game.level.starting_gold - BasicTower.cost


def test_try_place_tower_fails_on_non_buildable_cell(playing_game):
    path_col, path_row = next(iter(playing_game.grid.path_cells))
    n = settings.SUBTILES_PER_TILE
    playing_game.selected_tower_name = "basic"
    assert playing_game.try_place_tower(path_col * n, path_row * n) is False
    assert playing_game.economy.gold == playing_game.level.starting_gold


def test_try_place_tower_fails_when_unaffordable(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.economy.gold = 0
    playing_game.selected_tower_name = "basic"
    assert playing_game.try_place_tower(anchor_col, anchor_row) is False
    assert not playing_game.grid.is_occupied(anchor_col, anchor_row)


def test_try_place_tower_succeeds_with_zero_gold_under_unlimited_gold(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.economy.unlimited_gold = True
    playing_game.economy.gold = 0
    playing_game.selected_tower_name = "basic"

    assert playing_game.try_place_tower(anchor_col, anchor_row) is True

    assert playing_game.grid.is_occupied(anchor_col, anchor_row)
    assert playing_game.economy.gold == 0  # not actually deducted


def test_try_place_tower_records_the_towers_built_achievement_counter(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"

    playing_game.try_place_tower(anchor_col, anchor_row)

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["towers_built"] == 1


def test_try_place_tower_does_not_record_an_achievement_in_sandbox_mode(playing_game):
    playing_game.sandbox = True
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"

    playing_game.try_place_tower(anchor_col, anchor_row)

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert "towers_built" not in counters


def test_try_place_tower_fails_when_nothing_selected(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    assert playing_game.selected_tower_name is None

    assert playing_game.try_place_tower(anchor_col, anchor_row) is False

    assert not playing_game.grid.is_occupied(anchor_col, anchor_row)
    assert playing_game.economy.gold == playing_game.level.starting_gold


def test_try_upgrade_tower_succeeds_and_deducts_gold(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    gold_before = playing_game.economy.gold
    cost = tower.upgrade_cost()

    assert playing_game.try_upgrade_tower(tower) is True
    assert tower.level == 2
    assert playing_game.economy.gold == gold_before - cost


def test_maxing_a_tower_records_the_towers_maxed_achievement_counter_once(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000

    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)  # only the final upgrade should record

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["towers_maxed"] == 1


def test_try_upgrade_tower_fails_when_unaffordable(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 0

    assert playing_game.try_upgrade_tower(tower) is False
    assert tower.level == 1


def test_try_upgrade_tower_fails_for_a_tower_not_on_the_field(playing_game):
    stray_tower = BasicTower(anchor_col=0, anchor_row=0, pixel_pos=(0, 0))
    playing_game.economy.gold = 10_000
    gold_before = playing_game.economy.gold

    assert playing_game.try_upgrade_tower(stray_tower) is False

    assert stray_tower.level == 1
    assert playing_game.economy.gold == gold_before


def test_try_upgrade_tower_fails_at_max_level(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)

    gold_before = playing_game.economy.gold
    assert playing_game.try_upgrade_tower(tower) is False
    assert playing_game.economy.gold == gold_before


# --- update(): the frame loop ---

def test_update_is_a_no_op_outside_playing(game):
    game.state = GameState.PAUSED
    game.enemies = ["sentinel"]
    game.update(dt=1.0)
    assert game.enemies == ["sentinel"]  # untouched


def test_update_spawns_and_moves_enemies(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)  # processes the now-zeroed delay, begins the wave
    playing_game.update(dt=0.01)  # spawns an enemy (added to self.enemies at the end of this frame)
    assert len(playing_game.enemies) >= 1
    playing_game.update(dt=1.0)  # now it actually gets to move
    assert playing_game.enemies[0].distance_traveled > 0


def test_killing_an_enemy_grants_its_gold_reward(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    assert playing_game.enemies, "expected at least one enemy to have spawned"
    enemy = playing_game.enemies[0]
    gold_before = playing_game.economy.gold
    reward = enemy.gold_reward

    enemy.take_damage(enemy.max_hp)
    playing_game.update(dt=0.01)

    assert playing_game.economy.gold == gold_before + reward
    assert enemy not in playing_game.enemies


def test_killing_an_enemy_records_the_kills_achievement_counter(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(enemy.max_hp)
    playing_game.update(dt=0.01)

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["kills"] == 1


def test_killing_an_enemy_in_sandbox_mode_records_no_achievement(playing_game):
    playing_game.sandbox = True
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(enemy.max_hp)
    playing_game.update(dt=0.01)

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert "kills" not in counters


def test_unlocking_an_achievement_queues_a_toast(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(enemy.max_hp)  # first ever kill -- unlocks "first_blood"
    playing_game.update(dt=0.01)

    assert len(playing_game.achievement_toasts) == 1
    assert "First Blood" in playing_game.achievement_toasts[0].text


def test_achievement_toasts_are_pruned_once_expired(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]
    enemy.take_damage(enemy.max_hp)
    playing_game.update(dt=0.01)
    assert playing_game.achievement_toasts

    playing_game.update(dt=10.0)  # comfortably past any toast's lifetime

    assert playing_game.achievement_toasts == []


def test_clearing_a_wave_records_the_waves_survived_achievement_counter(playing_game):
    playing_game.wave_manager.state = WaveState.SPAWNING
    playing_game.wave_manager._spawn_queues = []  # nothing left queued this wave
    playing_game.enemies = []  # and nothing still alive -- the wave is about to clear

    playing_game.update(dt=0.01)

    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["waves_survived"] == 1


def test_clearing_a_levels_final_wave_still_records_waves_survived(playing_game):
    # Regression test: _advance_after_clear's non-endless DONE branch used
    # to never bump wave_index, so current_wave_number never rose on the
    # very last wave and this counter silently missed it.
    wave_manager = playing_game.wave_manager
    wave_manager.wave_index = wave_manager.total_waves - 1  # on the level's last wave
    wave_manager.state = WaveState.SPAWNING
    wave_manager._spawn_queues = []
    playing_game.enemies = []

    playing_game.update(dt=0.01)

    assert wave_manager.all_waves_complete
    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["waves_survived"] == 1


def test_clearing_a_level_records_the_levels_cleared_achievement_counter(playing_game):
    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []

    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.VICTORY
    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["levels_cleared"] == 1
    assert counters["distinct_levels_cleared"] == len(playing_game.progress)


def test_clearing_a_custom_level_still_records_the_levels_cleared_achievement(playing_game):
    # Regression guard: the levels_cleared achievement bump used to live
    # inside the isinstance(current_level_id, int) guard meant only for
    # progress.mark_level_cleared() (which genuinely only applies to a
    # LEVELS registry entry) -- a custom, editor-authored level was never
    # able to unlock "First Victory" no matter how many times it was won.
    playing_game.load_custom_level(make_custom_level())
    assert playing_game.current_level_id is None
    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []

    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.VICTORY
    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters["levels_cleared"] == 1
    # A custom level has no registry entry to unlock progress against, and
    # doesn't count toward "every built-in level" either.
    assert "distinct_levels_cleared" not in counters


def test_clearing_a_level_in_sandbox_mode_records_no_levels_cleared_achievement(playing_game):
    playing_game.sandbox = True
    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []

    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.VICTORY
    counters = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert "levels_cleared" not in counters


def test_taking_damage_spawns_a_floating_damage_number(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(7)
    playing_game.update(dt=0.01)

    assert len(playing_game.damage_numbers) == 1
    assert playing_game.damage_numbers[0].text == "7"
    # The enemy's own damage_events queue is drained every frame, whether or
    # not it died -- see Game.update()'s ordering relative to the
    # alive-filter loop.
    assert enemy.damage_events == []


def test_floating_damage_numbers_are_pruned_once_expired(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(7)
    playing_game.update(dt=0.01)
    assert playing_game.damage_numbers

    playing_game.update(dt=10.0)  # comfortably past any FloatingText's lifetime

    assert playing_game.damage_numbers == []


def test_a_projectile_hit_spawns_an_impact_effect_sized_to_its_splash_radius(playing_game):
    from projectile import Projectile
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    # Positioned to resolve immediately -- distance to target is 0.
    projectile = Projectile(pos=enemy.pos, target=enemy, speed=1000, damage=1, splash_radius=30)
    playing_game.projectiles.append(projectile)

    playing_game.update(dt=0.01)

    assert len(playing_game.impact_effects) == 1
    assert playing_game.impact_effects[0].max_radius == 30
    assert projectile.impact_events == []  # drained the same frame it was populated


def test_a_dying_enemy_spawns_a_death_poof_impact_effect(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(enemy.max_hp)
    playing_game.update(dt=0.01)

    assert len(playing_game.impact_effects) == 1
    assert playing_game.impact_effects[0].max_radius == enemy.radius * 1.8


def test_impact_effects_are_pruned_once_expired(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.take_damage(enemy.max_hp)
    playing_game.update(dt=0.01)
    assert playing_game.impact_effects

    playing_game.update(dt=10.0)  # comfortably past any ExpandingRing's duration

    assert playing_game.impact_effects == []


def test_enemy_reaching_the_goal_costs_a_life_and_is_removed(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]
    lives_before = playing_game.economy.lives

    enemy.wp_index = len(enemy.waypoints)  # force it to the end of the path
    playing_game.update(dt=0.01)

    assert playing_game.economy.lives == lives_before - 1
    assert enemy not in playing_game.enemies


def test_lives_reaching_zero_triggers_game_over(playing_game):
    playing_game.economy.lives = 1
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    enemy = playing_game.enemies[0]

    enemy.wp_index = len(enemy.waypoints)
    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.GAME_OVER


def test_clearing_all_waves_with_no_enemies_left_triggers_victory(playing_game):
    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []
    playing_game.update(dt=0.01)
    assert playing_game.state == GameState.VICTORY


def test_all_waves_complete_but_enemies_still_alive_does_not_trigger_victory(playing_game):
    playing_game.wave_manager.skip_delay()
    playing_game.update(dt=0.01)
    playing_game.update(dt=0.1)
    assert playing_game.enemies
    playing_game.wave_manager.all_waves_complete = True

    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.PLAYING


def test_dead_projectiles_never_linger_in_the_list(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game, adjacent_to_path=True)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    playing_game.wave_manager.skip_delay()

    # 600 frames (10 simulated seconds) -- comfortably more than wave 1's
    # first enemies need to walk from the spawn to an adjacent-to-path
    # tower and get shot at; without ever_fired, this assertion would pass
    # vacuously on an empty (never-fired) projectile list every frame.
    ever_fired = False
    for _ in range(600):
        playing_game.update(dt=1 / 60)
        assert all(not p.dead for p in playing_game.projectiles)
        ever_fired = ever_fired or bool(playing_game.projectiles)

    assert ever_fired


# --- Level loading / progression ---

def test_load_level_switches_level_and_resets_entities(game):
    game.towers = ["fake"]
    game.enemies = ["fake"]
    game.selected_tower_name = "basic"

    game.load_level(2)

    assert game.level.id == 2
    assert game.towers == []
    assert game.enemies == []
    assert game.selected_tower_name is None
    assert game.economy.gold == game.level.starting_gold


def test_reset_reloads_the_current_level_and_returns_to_menu(playing_game):
    playing_game.economy.gold = 0
    playing_game.economy.lives = 0
    playing_game.towers = ["fake"]

    playing_game.reset()

    assert playing_game.state == GameState.MENU
    assert playing_game.economy.gold == playing_game.level.starting_gold
    assert playing_game.economy.lives == playing_game.level.starting_lives
    assert playing_game.towers == []


def test_has_next_level_true_when_a_later_level_is_registered(game):
    game.current_level_id = 1
    assert game.has_next_level() is True


def test_has_next_level_false_on_the_last_registered_level(game):
    game.current_level_id = max(LEVELS.keys())
    assert game.has_next_level() is False


def test_advance_or_replay_level_advances_when_possible(game):
    game.current_level_id = 1
    game.advance_or_replay_level()
    assert game.current_level_id == 2
    assert game.level.id == 2


def test_advance_or_replay_level_replays_when_no_next_level(game):
    last_id = max(LEVELS.keys())
    game.current_level_id = last_id
    game.load_level(last_id)
    game.towers = ["fake"]

    game.advance_or_replay_level()

    assert game.current_level_id == last_id
    assert game.towers == []  # freshly reloaded


# --- Map editor / level select ---

def cell_center_px(cell, tile_size=64):
    col, row = cell
    return col * tile_size + tile_size // 2, row * tile_size + tile_size // 2


def make_custom_level(level_id="custom-slug", name="Custom Level"):
    return Level(
        id=level_id,
        name=name,
        path_cells=frozenset({(0, 0), (1, 0), (2, 0)}),
        spawn_cells=((0, 0),),
        goal_cells=((2, 0),),
        wave_specs=[{(0, 0): {"grunt": 2}}],
    )


def test_game_starts_with_an_empty_unplayable_editor(game):
    assert game.editor.path_cells == set()
    assert not game.editor.can_play()


def test_menu_e_key_enters_the_editor(game):
    game._handle_keydown(pygame.K_e)
    assert game.state == GameState.EDITOR


def test_menu_l_key_enters_level_select(game):
    game._handle_keydown(pygame.K_l)
    assert game.state == GameState.LEVEL_SELECT


def test_menu_s_key_enters_settings(game):
    game._handle_keydown(pygame.K_s)
    assert game.state == GameState.SETTINGS


def test_settings_escape_returns_to_menu(game):
    game.state = GameState.SETTINGS
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


def test_settings_unbound_key_is_a_no_op(game):
    game.state = GameState.SETTINGS
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.SETTINGS


def test_settings_click_toggles_fullscreen(game):
    assert game.fullscreen is False
    game._handle_settings_click(game.settings_rects["fullscreen"].center)
    assert game.fullscreen is True
    game._handle_settings_click(game.settings_rects["fullscreen"].center)
    assert game.fullscreen is False


def test_settings_click_picks_a_difficulty(game):
    game._handle_settings_click(game.settings_rects["hard"].center)
    assert game.difficulty == "hard"


def test_settings_click_on_back_returns_to_menu(game):
    game.state = GameState.SETTINGS
    game._handle_settings_click(game.settings_rects["back"].center)
    assert game.state == GameState.MENU


def test_settings_click_off_any_button_is_a_no_op(game):
    game._handle_settings_click((0, 0))
    assert game.fullscreen is False
    assert game.difficulty == "normal"


# --- Achievements screen ---

def test_menu_a_key_enters_achievements(game):
    game._handle_keydown(pygame.K_a)
    assert game.state == GameState.ACHIEVEMENTS


def test_achievements_escape_returns_to_menu(game):
    game.state = GameState.ACHIEVEMENTS
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


def test_achievements_unbound_key_is_a_no_op(game):
    game.state = GameState.ACHIEVEMENTS
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.ACHIEVEMENTS


def test_achievements_click_on_back_returns_to_menu(game):
    game.state = GameState.ACHIEVEMENTS
    game._handle_achievements_click(game.achievements_back_rect.center)
    assert game.state == GameState.MENU


def test_achievements_click_off_the_back_button_is_a_no_op(game):
    game.state = GameState.ACHIEVEMENTS
    game._handle_achievements_click((0, 0))
    assert game.state == GameState.ACHIEVEMENTS


def test_entering_achievements_reloads_state_from_disk(game):
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.state = GameState.PLAYING
    game.selected_tower_name = "basic"
    game.try_place_tower(anchor_col, anchor_row)  # unlocks "groundbreaker" on disk

    game._enter_achievements()

    assert "groundbreaker" in game.achievements_state["unlocked"]


def test_render_achievements_screen_does_not_crash(game):
    game._enter_achievements()
    game.render()


def test_fullscreen_setting_persists_to_the_settings_file(game):
    game.set_fullscreen(True)
    reloaded = player_settings.load_settings(game.settings_path)
    assert reloaded["fullscreen"] is True


def test_difficulty_setting_persists_to_the_settings_file(game):
    game.set_difficulty("easy")
    reloaded = player_settings.load_settings(game.settings_path)
    assert reloaded["difficulty"] == "easy"


def test_a_fresh_game_instance_picks_up_previously_persisted_settings(tmp_path):
    settings_path = tmp_path / "player_settings.json"
    achievements_path = tmp_path / "achievements.json"
    save_path = tmp_path / "save_state.json"
    first = Game(progress_path=tmp_path / "progress.json", settings_path=settings_path,
                 achievements_path=achievements_path, save_path=save_path)
    try:
        first.set_fullscreen(True)
        first.set_difficulty("hard")
    finally:
        pygame.quit()

    second = Game(progress_path=tmp_path / "progress.json", settings_path=settings_path,
                   achievements_path=achievements_path, save_path=save_path)
    try:
        assert second.fullscreen is True
        assert second.difficulty == "hard"
    finally:
        pygame.quit()


def test_editor_escape_returns_to_menu(game):
    game.state = GameState.EDITOR
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


def test_editor_unbound_key_is_a_no_op(game):
    game.state = GameState.EDITOR
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.EDITOR


def test_ctrl_z_undoes_in_the_editor(game):
    game.state = GameState.EDITOR
    game.editor.paint_at(*cell_center_px((3, 4)))
    assert (3, 4) in game.editor.path_cells

    mock_key_mods(pygame.KMOD_CTRL)
    try:
        game._handle_keydown(pygame.K_z)
    finally:
        clear_key_mods()

    assert (3, 4) not in game.editor.path_cells


def test_z_without_ctrl_does_not_undo_in_the_editor(game):
    game.state = GameState.EDITOR
    game.editor.paint_at(*cell_center_px((3, 4)))

    game._handle_keydown(pygame.K_z)  # no Ctrl mocked -- real (unheld) modifier state

    assert (3, 4) in game.editor.path_cells


def test_ctrl_y_redoes_in_the_editor(game):
    game.state = GameState.EDITOR
    game.editor.paint_at(*cell_center_px((3, 4)))
    game.editor.undo()
    assert (3, 4) not in game.editor.path_cells

    mock_key_mods(pygame.KMOD_CTRL)
    try:
        game._handle_keydown(pygame.K_y)
    finally:
        clear_key_mods()

    assert (3, 4) in game.editor.path_cells


def test_ctrl_z_undoes_in_the_wave_editor(game):
    game.state = GameState.WAVE_EDITOR
    _paint_valid_path(game)
    game.editor.validate()
    game.editor.set_active_spawn((0, 2))
    game.editor.adjust_unit_count("grunt", +1)
    assert game.editor.wave_specs[0][(0, 2)]["grunt"] == 1

    mock_key_mods(pygame.KMOD_CTRL)
    try:
        game._handle_keydown(pygame.K_z)
    finally:
        clear_key_mods()

    assert game.editor.wave_specs[0].get((0, 2)) is None


def test_level_select_escape_returns_to_menu(game):
    game.state = GameState.LEVEL_SELECT
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


def test_level_select_unbound_key_is_a_no_op(game):
    game.state = GameState.LEVEL_SELECT
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.LEVEL_SELECT


def test_clicking_an_editor_tool_button_switches_the_active_tool(game):
    game.state = GameState.EDITOR
    game._handle_editor_click(game.editor_tool_rects["spawn"].center)
    assert game.editor.active_tool == EditorTool.SPAWN


def test_clicking_the_grid_paints_a_path_cell(game):
    game.state = GameState.EDITOR
    game._handle_editor_click(cell_center_px((3, 4)))
    assert (3, 4) in game.editor.path_cells


def test_dragging_with_the_left_button_held_paints_a_stroke_of_cells(game):
    game.state = GameState.EDITOR
    for col in range(3):
        game._handle_editor_motion(cell_center_px((col, 2)), (True, False, False))
    assert {(0, 2), (1, 2), (2, 2)} <= game.editor.path_cells


def test_motion_without_the_left_button_held_does_not_paint(game):
    game.state = GameState.EDITOR
    game._handle_editor_motion(cell_center_px((5, 5)), (False, False, False))
    assert game.editor.path_cells == set()


# --- Map editor: undo/redo, Line/Rect/Select tools, copy/paste ---

def test_editor_mouse_up_ends_a_freeform_stroke(game):
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.PAINT)
    game._handle_editor_click(cell_center_px((0, 0)))
    assert game.editor._stroke_active is True

    game._handle_editor_mouse_up(cell_center_px((0, 0)))

    assert game.editor._stroke_active is False


def test_clicking_the_grid_with_the_line_tool_begins_a_shape_not_a_paint(game):
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.LINE)
    game._handle_editor_click(cell_center_px((3, 3)))

    assert game.editor.path_cells == set()  # not painted yet -- only a drag started
    assert game.editor._shape_start == (3, 3)


def test_dragging_with_the_line_tool_updates_the_preview(game):
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.LINE)
    game._handle_editor_click(cell_center_px((0, 0)))
    game._handle_editor_motion(cell_center_px((3, 0)), (True, False, False))

    assert game.editor.pending_shape_cells() == {(0, 0), (1, 0), (2, 0), (3, 0)}
    assert game.editor.path_cells == set()  # still just a preview


def test_releasing_the_line_tool_commits_the_shape(game):
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.LINE)
    game._handle_editor_click(cell_center_px((0, 0)))
    game._handle_editor_motion(cell_center_px((3, 0)), (True, False, False))

    game._handle_editor_mouse_up(cell_center_px((3, 0)))

    assert game.editor.path_cells == {(0, 0), (1, 0), (2, 0), (3, 0)}


def test_releasing_the_select_tool_commits_a_selection_not_a_paint(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.editor.set_tool(EditorTool.SELECT)
    game._handle_editor_click(cell_center_px((0, 2)))
    game._handle_editor_mouse_up(cell_center_px((2, 2)))

    assert game.editor.selection_bounds == (0, 2, 2, 2)


def test_clicking_the_undo_action_button_undoes_the_last_edit(game):
    game.state = GameState.EDITOR
    game.editor.paint_at(*cell_center_px((3, 4)))
    game._handle_editor_click(game.editor_action_rects["undo"].center)
    assert (3, 4) not in game.editor.path_cells


def test_clicking_the_redo_action_button_redoes_the_last_undo(game):
    game.state = GameState.EDITOR
    game.editor.paint_at(*cell_center_px((3, 4)))
    game.editor.undo()
    game._handle_editor_click(game.editor_action_rects["redo"].center)
    assert (3, 4) in game.editor.path_cells


def test_wave_editor_undo_action_button_undoes_the_last_edit(game):
    game.state = GameState.WAVE_EDITOR
    _paint_valid_path(game)
    game.editor.adjust_unit_count("grunt", +1)
    count_before = game.editor.wave_specs[0][(0, 2)]["grunt"]

    game._handle_wave_editor_action("undo")

    assert game.editor.wave_specs[0].get((0, 2), {}).get("grunt", 0) != count_before


def test_clicking_copy_then_paste_stamps_the_selection_at_a_new_anchor(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.editor.set_tool(EditorTool.SELECT)
    game._handle_editor_click(cell_center_px((0, 2)))
    game._handle_editor_mouse_up(cell_center_px((2, 2)))

    game._handle_editor_click(game.editor_action_rects["copy"].center)
    game._handle_editor_click(game.editor_action_rects["paste"].center)
    assert game.editor.paste_pending is True

    game._handle_editor_click(cell_center_px((10, 5)))  # consumes paste_pending

    assert (10, 5) in game.editor.path_cells
    assert game.editor.paste_pending is False


def test_paste_pending_takes_priority_over_the_active_tool(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.editor.set_tool(EditorTool.SELECT)
    game._handle_editor_click(cell_center_px((0, 2)))
    game._handle_editor_mouse_up(cell_center_px((2, 2)))
    game.editor.copy_selection()
    game.editor.paste_pending = True
    game.editor.set_tool(EditorTool.LINE)  # switch tools before the paste click lands

    game._handle_editor_click(cell_center_px((10, 5)))

    assert (10, 5) in game.editor.path_cells
    assert game.editor._shape_start is None  # never started a Line drag


def test_waves_action_is_a_no_op_while_the_editors_path_is_invalid(game):
    game.state = GameState.EDITOR
    assert not game.editor.path_is_valid()
    game._handle_editor_click(game.editor_action_rects["waves"].center)
    assert game.state == GameState.EDITOR  # never left -- path isn't ready yet


def _paint_valid_path(game, row=2):
    game.editor.set_tool(EditorTool.PAINT)
    for col in range(3):
        game.editor.paint_at(*cell_center_px((col, row)))
    game.editor.set_tool(EditorTool.SPAWN)
    game.editor.paint_at(*cell_center_px((0, row)))
    game.editor.set_tool(EditorTool.GOAL)
    game.editor.paint_at(*cell_center_px((2, row)))


def test_waves_action_switches_to_the_wave_editor_once_the_path_is_valid(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    assert game.editor.path_is_valid()

    game._handle_editor_click(game.editor_action_rects["waves"].center)

    assert game.state == GameState.WAVE_EDITOR


def test_back_action_returns_to_menu_without_touching_the_paint_buffer(game):
    game.state = GameState.EDITOR
    game.editor.paint_at(*cell_center_px((0, 0)))
    game._handle_editor_click(game.editor_action_rects["back"].center)
    assert game.state == GameState.MENU
    assert (0, 0) in game.editor.path_cells  # still there next time the editor opens


# --- Wave editor ---

def test_wave_editor_escape_returns_to_the_path_editor(game):
    game.state = GameState.WAVE_EDITOR
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.EDITOR


def test_wave_editor_unbound_key_is_a_no_op(game):
    game.state = GameState.WAVE_EDITOR
    game._handle_keydown(pygame.K_z)
    assert game.state == GameState.WAVE_EDITOR


def test_clicking_add_wave_tab_appends_a_wave(game):
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game._wave_tab_rects()["add"].center)
    assert len(game.editor.wave_specs) == 2
    assert game.editor.active_wave_index == 1


def test_clicking_remove_wave_tab_removes_the_active_wave(game):
    game.state = GameState.WAVE_EDITOR
    game.editor.add_wave()
    game._handle_wave_editor_click(game._wave_tab_rects()["remove"].center)
    assert len(game.editor.wave_specs) == 1


def test_clicking_a_wave_number_tab_selects_it(game):
    game.state = GameState.WAVE_EDITOR
    game.editor.add_wave()
    game.editor.add_wave()
    game._handle_wave_editor_click(game._wave_tab_rects()[0].center)
    assert game.editor.active_wave_index == 0


def test_clicking_plus_increments_the_active_waves_unit_count(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    spawn = game.editor.active_spawn_cell

    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)

    assert game.editor.wave_specs[0][spawn]["grunt"] == 2


def test_clicking_minus_decrements_and_floors_at_zero(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    spawn = game.editor.active_spawn_cell
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)

    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "minus")].center)
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "minus")].center)

    assert game.editor.wave_specs[0].get(spawn, {}) == {}


def test_clicking_plus_with_no_spawn_selected_is_a_no_op(game):
    # Fresh editor -- no path painted yet, so there's no active spawn for
    # +/- to target.
    game.state = GameState.WAVE_EDITOR
    assert game.editor.active_spawn_cell is None
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    assert game.editor.wave_specs == [{}]


def _paint_two_spawn_path(game):
    game.editor.set_tool(EditorTool.PAINT)
    for cell in [(0, 0), (0, 1), (0, 2), (1, 1)]:
        game.editor.paint_at(*cell_center_px(cell))
    game.editor.set_tool(EditorTool.SPAWN)
    game.editor.paint_at(*cell_center_px((0, 0)))
    game.editor.paint_at(*cell_center_px((0, 2)))
    game.editor.set_tool(EditorTool.GOAL)
    game.editor.paint_at(*cell_center_px((1, 1)))


def test_clicking_a_spawn_marker_switches_the_active_spawn(game):
    game.state = GameState.EDITOR
    _paint_two_spawn_path(game)
    game.state = GameState.WAVE_EDITOR
    assert game.editor.active_spawn_cell == (0, 0)  # min() of the two, auto-selected

    game._handle_wave_editor_click(cell_center_px((0, 2)))

    assert game.editor.active_spawn_cell == (0, 2)


def test_clicking_a_non_spawn_grid_cell_in_the_wave_editor_is_a_no_op(game):
    game.state = GameState.EDITOR
    _paint_two_spawn_path(game)
    game.state = GameState.WAVE_EDITOR
    active_before = game.editor.active_spawn_cell

    game._handle_wave_editor_click(cell_center_px((0, 1)))  # a plain path cell, not a spawn

    assert game.editor.active_spawn_cell == active_before


def test_plus_after_switching_spawns_targets_the_newly_active_one(game):
    game.state = GameState.EDITOR
    _paint_two_spawn_path(game)
    game.state = GameState.WAVE_EDITOR

    game._handle_wave_editor_click(cell_center_px((0, 2)))
    game._handle_wave_editor_click(game.wave_unit_rects[("tank", "plus")].center)

    assert game.editor.wave_specs[0] == {(0, 2): {"tank": 1}}


def test_wave_editor_playtest_is_a_no_op_until_every_wave_has_units(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    assert not game.editor.can_play()  # path ready, but the one wave is empty

    game._handle_wave_editor_click(game.wave_editor_action_rects["playtest"].center)

    assert game.state == GameState.WAVE_EDITOR  # never left


def test_wave_editor_playtest_loads_the_level_and_switches_to_playing(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    assert game.editor.can_play()

    game._handle_wave_editor_click(game.wave_editor_action_rects["playtest"].center)

    assert game.state == GameState.PLAYING
    assert game.current_level_id is None
    assert game.level.path_cells == frozenset({(0, 2), (1, 2), (2, 2)})
    assert game.level.wave_specs == [{(0, 2): {"grunt": 1}}]


def test_wave_editor_back_action_returns_to_the_path_editor(game):
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_editor_action_rects["back"].center)
    assert game.state == GameState.EDITOR


def test_wave_editor_save_action_saves_the_level_when_playable(game, monkeypatch):
    saved = []

    def fake_save_level(level):
        saved.append(level)
        return "/fake/custom_levels/custom-level.json"

    monkeypatch.setattr("persistence.save_level", fake_save_level)

    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    assert game.editor.can_play()
    assert game.last_saved_path is None

    game._handle_wave_editor_click(game.wave_editor_action_rects["save"].center)

    assert len(saved) == 1
    assert saved[0].wave_specs == [{(0, 2): {"grunt": 1}}]
    assert game.state == GameState.WAVE_EDITOR  # saving doesn't navigate away
    assert game.last_saved_path == "/fake/custom_levels/custom-level.json"


def test_wave_editor_save_action_is_a_no_op_while_unplayable(game, monkeypatch):
    saved = []
    monkeypatch.setattr("persistence.save_level", lambda level: saved.append(level))

    game.state = GameState.WAVE_EDITOR
    assert not game.editor.can_play()
    game._handle_wave_editor_click(game.wave_editor_action_rects["save"].center)

    assert saved == []
    assert game.last_saved_path is None


def test_level_select_click_outside_the_viewport_is_a_no_op(game):
    game._enter_level_select()
    game._handle_level_select_click((-1000, -1000))
    assert game.state == GameState.LEVEL_SELECT  # never left


def test_level_select_click_inside_the_viewport_but_off_every_row_is_a_no_op(game):
    # Distinct from the viewport-fence case above -- this is a click that
    # passes the fence (a real y within LEVEL_SELECT_TOP..LEVEL_SELECT_BOTTOM)
    # but still doesn't land on any row's Rect.
    game._enter_level_select()
    game._handle_level_select_click((settings.SCREEN_WIDTH - 1, ui.LEVEL_SELECT_TOP + 5))
    assert game.state == GameState.LEVEL_SELECT  # never left


# --- Level select scrolling ---

def _make_many_custom_levels(count):
    return [make_custom_level(level_id=f"level-{i}", name=f"Level {i}") for i in range(count)]


def test_scrolling_down_moves_the_level_select_rows_up(game, monkeypatch):
    levels = _make_many_custom_levels(10)
    monkeypatch.setattr("persistence.list_custom_levels", lambda: levels)
    game._enter_level_select()
    assert game.level_select_scroll_offset == 0

    first_row_y_before = game.level_select_rects[levels[0].id].y
    game._scroll_level_select(-1)  # wheel "down" gesture
    first_row_y_after = game.level_select_rects[levels[0].id].y

    assert game.level_select_scroll_offset > 0
    assert first_row_y_after < first_row_y_before


def test_scroll_offset_clamps_at_zero_and_at_max(game, monkeypatch):
    levels = _make_many_custom_levels(10)
    monkeypatch.setattr("persistence.list_custom_levels", lambda: levels)
    game._enter_level_select()

    game._scroll_level_select(1)  # can't scroll up past the top
    assert game.level_select_scroll_offset == 0

    max_scroll = ui.level_select_max_scroll(len(game.level_select_entries))
    for _ in range(50):
        game._scroll_level_select(-1)
    assert game.level_select_scroll_offset == max_scroll


def test_enter_level_select_resets_scroll_to_the_top(game, monkeypatch):
    levels = _make_many_custom_levels(10)
    monkeypatch.setattr("persistence.list_custom_levels", lambda: levels)
    game._enter_level_select()
    game._scroll_level_select(-3)
    assert game.level_select_scroll_offset > 0

    game._enter_level_select()  # re-entering (e.g. via L again) starts back at the top
    assert game.level_select_scroll_offset == 0


def test_clicking_a_scrolled_row_still_loads_the_right_level(game, monkeypatch):
    levels = _make_many_custom_levels(10)
    monkeypatch.setattr("persistence.list_custom_levels", lambda: levels)
    game._enter_level_select()
    max_scroll = ui.level_select_max_scroll(len(game.level_select_entries))
    for _ in range(50):
        game._scroll_level_select(-1)
    assert game.level_select_scroll_offset == max_scroll

    target = levels[-1]
    rect = game.level_select_rects[target.id]
    assert ui.LEVEL_SELECT_TOP <= rect.centery <= ui.LEVEL_SELECT_BOTTOM  # sanity: actually visible now

    game._handle_level_select_click(rect.center)

    assert game.state == GameState.PLAYING
    assert game.level.id == target.id


def test_clicking_a_partially_scrolled_off_row_above_the_viewport_is_a_no_op(game, monkeypatch):
    levels = _make_many_custom_levels(10)
    monkeypatch.setattr("persistence.list_custom_levels", lambda: levels)
    game._enter_level_select()
    game.level_select_scroll_offset = 50
    game._rebuild_level_select_rects()

    first_key = game.level_select_entries[0][0]
    row_rect = game.level_select_rects[first_key]
    assert row_rect.top < ui.LEVEL_SELECT_TOP < row_rect.bottom  # straddles the fence

    click_pos = (row_rect.centerx, ui.LEVEL_SELECT_TOP - 10)  # inside the rect, above the viewport
    assert row_rect.collidepoint(click_pos)  # sanity: the rect really does cover this point

    game._handle_level_select_click(click_pos)
    assert game.state == GameState.LEVEL_SELECT  # rejected by the viewport fence


def test_enter_level_select_builds_one_thumbnail_per_entry(game):
    game._enter_level_select()
    assert set(game.level_select_thumbnails.keys()) == {key for key, _level in game.level_select_entries}
    for thumbnail in game.level_select_thumbnails.values():
        assert thumbnail.get_size() == (ui.LEVEL_THUMBNAIL_WIDTH, ui.LEVEL_THUMBNAIL_HEIGHT)


def test_has_next_level_is_false_for_a_custom_level(game):
    game.load_custom_level(make_custom_level())
    assert game.current_level_id is None
    assert game.has_next_level() is False


def test_reset_on_a_custom_level_reloads_it_without_a_registry_lookup(game):
    game.load_custom_level(make_custom_level())
    game.towers = ["fake"]

    game.reset()

    assert game.state == GameState.MENU
    assert game.current_level_id is None
    assert game.towers == []
    assert game.level.path_cells == frozenset({(0, 0), (1, 0), (2, 0)})


def test_advance_or_replay_level_on_a_custom_level_replays_it(game):
    game.load_custom_level(make_custom_level())
    game.towers = ["fake"]

    game.advance_or_replay_level()

    assert game.current_level_id is None
    assert game.towers == []


def test_level_select_click_on_a_built_in_entry_loads_it(game):
    game._enter_level_select()
    rect = game.level_select_rects[1]
    game._handle_level_select_click(rect.center)
    assert game.state == GameState.PLAYING
    assert game.current_level_id == 1


def test_level_select_click_on_a_custom_entry_loads_it(game, monkeypatch):
    custom = make_custom_level()
    monkeypatch.setattr("persistence.list_custom_levels", lambda: [custom])

    game._enter_level_select()
    assert (custom.id, custom) in game.level_select_entries

    # Custom entries are listed after every built-in one -- with as many
    # built-ins as there are now, this one is scrolled below the fold, so
    # scroll all the way down (like the player would) before clicking it.
    game._scroll_level_select(-9999)
    game._handle_level_select_click(game.level_select_rects[custom.id].center)

    assert game.state == GameState.PLAYING
    assert game.current_level_id is None
    assert game.level.id == custom.id


# --- Endless/Survival mode ---

def test_v_key_arms_endless_only_while_browsing_to_play(game):
    game._enter_level_select(purpose="play")
    assert game.level_select_endless_armed is False
    game._handle_keydown(pygame.K_v)
    assert game.level_select_endless_armed is True
    game._handle_keydown(pygame.K_v)
    assert game.level_select_endless_armed is False


def test_v_key_is_a_no_op_while_browsing_to_edit(game):
    game._enter_level_select(purpose="edit")
    game._handle_keydown(pygame.K_v)
    assert game.level_select_endless_armed is False


def test_entering_level_select_resets_endless_armed(game):
    game._enter_level_select()
    game.level_select_endless_armed = True
    game._enter_level_select()
    assert game.level_select_endless_armed is False


def test_picking_a_level_while_endless_armed_starts_it_in_endless_mode(game):
    game._enter_level_select()
    game.level_select_endless_armed = True
    rect = game.level_select_rects[1]
    game._handle_level_select_click(rect.center)
    assert game.wave_manager.endless is True


def test_picking_a_level_while_not_armed_starts_it_normally(game):
    game._enter_level_select()
    rect = game.level_select_rects[1]
    game._handle_level_select_click(rect.center)
    assert game.wave_manager.endless is False


def test_endless_run_never_reaches_victory_but_still_reaches_game_over(game):
    game.load_level(1, endless=True)
    game.state = GameState.PLAYING
    game.wave_manager.all_waves_complete = False
    game.economy.lives = 1
    game.enemies = []
    game.economy.lose_life()
    game.update(dt=0.01)
    assert game.state == GameState.GAME_OVER


def test_endless_mode_never_mutates_the_shared_levels_registry(game):
    # Regression guard: WaveManager.level is a live reference, and LEVELS
    # is a module-level singleton every Game/test in the process shares --
    # entering endless mode must hand WaveManager a private copy, or an
    # endless run's generated waves would permanently leak into every
    # future non-endless playthrough of the same built-in level (and into
    # other tests run afterward in this same process).
    original_wave_count = len(LEVELS[1].wave_specs)

    game.load_level(1, endless=True)
    game.wave_manager.level.wave_specs.append({(0, 0): {"grunt": 1}})

    assert len(LEVELS[1].wave_specs) == original_wave_count
    assert game.level is not LEVELS[1]


def test_endless_flag_survives_a_reset(game):
    game.load_level(1, endless=True)
    game.reset()
    assert game.endless is True
    assert game.wave_manager.endless is True


def test_reset_without_endless_stays_non_endless(game):
    game.load_level(1)
    game.reset()
    assert game.endless is False
    assert game.wave_manager.endless is False


# --- Sandbox/Creative mode ---

def test_b_key_arms_sandbox_only_while_browsing_to_play(game):
    game._enter_level_select(purpose="play")
    assert game.level_select_sandbox_armed is False
    game._handle_keydown(pygame.K_b)
    assert game.level_select_sandbox_armed is True
    game._handle_keydown(pygame.K_b)
    assert game.level_select_sandbox_armed is False


def test_b_key_is_a_no_op_while_browsing_to_edit(game):
    game._enter_level_select(purpose="edit")
    game._handle_keydown(pygame.K_b)
    assert game.level_select_sandbox_armed is False


def test_entering_level_select_resets_sandbox_armed(game):
    game._enter_level_select()
    game.level_select_sandbox_armed = True
    game._enter_level_select()
    assert game.level_select_sandbox_armed is False


def test_picking_a_level_while_sandbox_armed_starts_it_in_sandbox_mode(game):
    game._enter_level_select()
    game.level_select_sandbox_armed = True
    rect = game.level_select_rects[1]
    game._handle_level_select_click(rect.center)
    assert game.sandbox is True
    assert game.economy.unlimited_gold is True
    assert game.economy.invulnerable is True


def test_picking_a_level_while_not_armed_starts_it_without_sandbox(game):
    game._enter_level_select()
    rect = game.level_select_rects[1]
    game._handle_level_select_click(rect.center)
    assert game.sandbox is False
    assert game.economy.invulnerable is False


def test_sandbox_and_endless_are_independently_combinable(game):
    # Infinite lives plus escalating waves is a legitimate "just mess
    # around" combo -- arming both must not make either a no-op.
    game._enter_level_select()
    game.level_select_endless_armed = True
    game.level_select_sandbox_armed = True
    rect = game.level_select_rects[1]
    game._handle_level_select_click(rect.center)
    assert game.wave_manager.endless is True
    assert game.economy.invulnerable is True


def test_sandbox_run_never_reaches_game_over_from_lost_lives(playing_game):
    playing_game.load_level(1, sandbox=True)
    playing_game.state = GameState.PLAYING
    playing_game.economy.lives = 1
    playing_game.economy.lose_life()
    playing_game.update(dt=0.01)
    assert playing_game.state == GameState.PLAYING
    assert not playing_game.economy.is_out_of_lives


def test_sandbox_victory_does_not_mark_progress_cleared(game):
    # A trivial (unlimited-gold, invulnerable) clear shouldn't pollute real
    # best-lives-remaining progress, same reasoning already applied to an
    # endless run never reaching all_waves_complete at all.
    game.load_level(1, sandbox=True)
    game.state = GameState.PLAYING
    game.wave_manager.all_waves_complete = True
    game.enemies = []
    game.update(dt=0.01)
    assert game.state == GameState.VICTORY
    assert 1 not in progress.load_progress(game.progress_path)


def test_sandbox_flag_survives_a_reset(game):
    game.load_level(1, sandbox=True)
    game.reset()
    assert game.sandbox is True
    assert game.economy.invulnerable is True


def test_reset_without_sandbox_stays_non_sandbox(game):
    game.load_level(1)
    game.reset()
    assert game.sandbox is False
    assert game.economy.invulnerable is False


# --- Save/resume a run in progress ---

def test_can_save_run_true_while_awaiting_start(playing_game):
    assert playing_game.wave_manager.state == WaveState.AWAITING_START
    assert playing_game.can_save_run() is True


def test_can_save_run_true_during_between_waves(playing_game):
    playing_game.wave_manager.state = WaveState.BETWEEN_WAVES
    assert playing_game.can_save_run() is True


def test_can_save_run_false_while_spawning(playing_game):
    playing_game.wave_manager.state = WaveState.SPAWNING
    assert playing_game.can_save_run() is False


def test_can_save_run_false_once_done(playing_game):
    playing_game.wave_manager.state = WaveState.DONE
    assert playing_game.can_save_run() is False


def test_save_run_writes_a_file_and_returns_true(playing_game):
    assert playing_game.save_run() is True
    assert save_state.has_saved_run(playing_game.save_path)


def test_save_run_fails_and_writes_nothing_while_spawning(playing_game):
    playing_game.wave_manager.state = WaveState.SPAWNING
    assert playing_game.save_run() is False
    assert not save_state.has_saved_run(playing_game.save_path)


def test_s_key_while_paused_saves_and_returns_to_menu(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_s)
    assert playing_game.state == GameState.MENU
    assert save_state.has_saved_run(playing_game.save_path)


def test_s_key_while_paused_is_a_no_op_mid_wave(playing_game):
    playing_game.wave_manager.state = WaveState.SPAWNING
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_s)
    assert playing_game.state == GameState.PAUSED
    assert not save_state.has_saved_run(playing_game.save_path)


def test_c_key_at_the_menu_is_a_no_op_without_a_saved_run(game):
    game._handle_keydown(pygame.K_c)
    assert game.state == GameState.PLAYING  # falls through to the generic "any key" case


def _place_and_max_a_tower(game, tower_name="lightning", specialize_key="overcharge"):
    anchor_col, anchor_row = find_buildable_anchor(game)
    game.selected_tower_name = tower_name
    game.economy.gold = 10_000
    game.try_place_tower(anchor_col, anchor_row)
    tower = game.grid.get_tower(anchor_col, anchor_row)
    while not tower.is_max_level:
        game.try_upgrade_tower(tower)
    game.try_specialize_tower(tower, specialize_key)
    tower.cycle_targeting_mode()
    return anchor_col, anchor_row, tower


def test_c_key_at_the_menu_resumes_a_saved_run(playing_game):
    anchor_col, anchor_row, tower = _place_and_max_a_tower(playing_game)
    gold_before, lives_before = playing_game.economy.gold, playing_game.economy.lives
    playing_game.save_run()
    playing_game.state = GameState.MENU

    playing_game._handle_keydown(pygame.K_c)

    assert playing_game.state == GameState.PLAYING
    assert playing_game.economy.gold == gold_before
    assert playing_game.economy.lives == lives_before
    resumed_tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    assert resumed_tower.level == tower.level
    assert resumed_tower.specialization == tower.specialization
    assert resumed_tower.targeting_mode == tower.targeting_mode


def test_resuming_does_not_recharge_gold_for_reconstructed_towers(playing_game):
    _place_and_max_a_tower(playing_game)
    gold_after_building = playing_game.economy.gold
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    assert playing_game.economy.gold == gold_after_building


def test_resuming_restores_tower_lifetime_stats(playing_game):
    # Regression guard: resume_saved_run() used to rebuild every tower via
    # a fresh Tower.__init__, silently zeroing shots_fired/shots_hit/
    # damage_dealt/kills even though real combat history existed before
    # the save -- the post-level results table would show 0 for
    # everything after resuming.
    anchor_col, anchor_row, tower = _place_and_max_a_tower(playing_game)
    tower.shots_fired, tower.shots_hit, tower.damage_dealt, tower.kills = 12, 9, 145.0, 4
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    resumed_tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    assert resumed_tower.shots_fired == 12
    assert resumed_tower.shots_hit == 9
    assert resumed_tower.damage_dealt == 145.0
    assert resumed_tower.kills == 4


def test_resuming_restores_sold_towers_for_the_results_table(playing_game):
    # Regression guard: resume_saved_run() used to never repopulate
    # sold_towers at all, so a tower sold before saving would silently
    # vanish from the post-level results table after resuming.
    _anchor_col, _anchor_row, tower = _place_and_max_a_tower(playing_game)
    tower.kills = 7
    playing_game.try_sell_tower(tower)
    assert playing_game.sold_towers == [tower]
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    assert len(playing_game.sold_towers) == 1
    assert playing_game.sold_towers[0].kills == 7
    assert playing_game.sold_towers[0] not in playing_game.towers


def test_continuing_a_run_that_cannot_be_resumed_stays_on_the_menu(playing_game):
    # Regression guard: a semantically-invalid-but-syntactically-fine save
    # file (an unresumable wave_state, here) used to reach
    # resume_saved_run() and crash instead of leaving the player on the
    # menu -- see save_state.load_run()'s own validation.
    playing_game.save_run()
    with open(playing_game.save_path) as f:
        data = json.load(f)
    data["wave_state"] = "spawning"
    with open(playing_game.save_path, "w") as f:
        json.dump(data, f)
    playing_game.state = GameState.MENU

    playing_game._handle_keydown(pygame.K_c)  # must not raise

    assert playing_game.state == GameState.MENU


def test_resuming_does_not_rebump_achievement_counters(playing_game):
    _place_and_max_a_tower(playing_game)
    counters_after_building = dict(achievements.load_achievements(playing_game.achievements_path)["counters"])
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    counters_after_resume = achievements.load_achievements(playing_game.achievements_path)["counters"]
    assert counters_after_resume == counters_after_building


def test_resuming_reconstructs_a_custom_levels_identity(playing_game):
    custom = make_custom_level()
    playing_game.load_custom_level(custom)
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    assert playing_game.current_level_id is None
    assert playing_game.level.id == custom.id


def test_resuming_continues_an_endless_runs_escalation(playing_game):
    playing_game.load_level(1, endless=True)
    original_wave_count = len(playing_game.level.wave_specs)
    spawn_cell = playing_game.level.spawn_cells[0]
    playing_game.level.wave_specs.append({spawn_cell: {"grunt": 99}})  # simulate an endless-generated wave
    playing_game.wave_manager.wave_index = original_wave_count  # "on" that generated wave
    playing_game.wave_manager.state = WaveState.BETWEEN_WAVES
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    assert playing_game.wave_manager.endless is True
    assert len(playing_game.level.wave_specs) == original_wave_count + 1
    assert playing_game.wave_manager.wave_index == original_wave_count
    # Regression guard, same as the non-resume endless test: the shared
    # LEVELS registry entry must never see the generated wave either.
    assert len(LEVELS[1].wave_specs) == original_wave_count


def test_resuming_honors_the_saved_runs_own_difficulty_even_if_the_player_setting_changed(playing_game):
    playing_game.difficulty = "hard"
    playing_game.load_level(1)  # rebuild wave_manager under "hard"
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.difficulty = "easy"  # the player changes their setting afterward
    playing_game.resume_saved_run(save_data)

    hard_multiplier = difficulty.DIFFICULTY_MODES["hard"].enemy_hp_multiplier
    assert playing_game.wave_manager.enemy_hp_multiplier == hard_multiplier
    assert playing_game.difficulty == "easy"  # the sticky player pref itself is untouched


def test_resuming_a_sandbox_run_restores_invulnerability_and_unlimited_gold(playing_game):
    playing_game.load_level(1, sandbox=True)
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)

    playing_game.resume_saved_run(save_data)

    assert playing_game.sandbox is True
    assert playing_game.economy.invulnerable is True
    assert playing_game.economy.unlimited_gold is True


def test_game_over_after_resuming_deletes_the_save_file(playing_game):
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)
    playing_game.resume_saved_run(save_data)
    assert save_state.has_saved_run(playing_game.save_path)

    playing_game.economy.lives = 1
    playing_game.economy.lose_life()
    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.GAME_OVER
    assert not save_state.has_saved_run(playing_game.save_path)


def test_victory_after_resuming_deletes_the_save_file(playing_game):
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)
    playing_game.resume_saved_run(save_data)
    assert save_state.has_saved_run(playing_game.save_path)

    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []
    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.VICTORY
    assert not save_state.has_saved_run(playing_game.save_path)


def test_a_fresh_unrelated_run_reaching_victory_does_not_delete_someone_elses_save(playing_game):
    # A save left over from a *different*, still-unresumed run must survive
    # this instance's own, entirely separate victory.
    save_state.save_run(playing_game, playing_game.save_path)
    assert playing_game._resumed_from_save is False

    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []
    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.VICTORY
    assert save_state.has_saved_run(playing_game.save_path)  # untouched


def test_restarting_a_resumed_run_stops_treating_it_as_resumed(playing_game):
    playing_game.save_run()
    save_data = save_state.load_run(playing_game.save_path)
    playing_game.resume_saved_run(save_data)
    assert playing_game._resumed_from_save is True

    playing_game.reset()

    assert playing_game._resumed_from_save is False


def test_render_menu_shows_no_continue_hint_without_a_saved_run(game):
    game.render()  # must not crash either way; nothing to assert on pixels here


def test_render_menu_with_a_saved_run_does_not_crash(playing_game):
    playing_game.save_run()
    playing_game.state = GameState.MENU
    playing_game.render()


def test_render_pause_menu_with_save_available_does_not_crash(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game.render()


# --- Level unlocking (progress.py) ---

def test_level_2_is_locked_until_level_1_is_cleared(game):
    game._enter_level_select()
    assert 1 not in game.level_select_locked_ids  # the lowest id is always unlocked
    assert 2 in game.level_select_locked_ids

    rect = game.level_select_rects[2]
    game._handle_level_select_click(rect.center)

    assert game.state == GameState.LEVEL_SELECT  # a locked row's click is a no-op


def test_clearing_level_1_unlocks_level_2(playing_game):
    assert playing_game.current_level_id == 1
    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []
    playing_game.update(dt=0.01)
    assert playing_game.state == GameState.VICTORY

    playing_game._enter_level_select()
    assert 2 not in playing_game.level_select_locked_ids

    rect = playing_game.level_select_rects[2]
    playing_game._handle_level_select_click(rect.center)

    assert playing_game.state == GameState.PLAYING
    assert playing_game.current_level_id == 2


def test_clearing_a_level_persists_across_a_fresh_game_instance(playing_game):
    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []
    playing_game.update(dt=0.01)
    assert playing_game.state == GameState.VICTORY

    # A brand-new Game pointed at the same progress file should see level 2
    # already unlocked -- progress persists across sessions, not just for
    # the instance that earned it.
    reloaded = Game(progress_path=playing_game.progress_path, settings_path=playing_game.settings_path,
                     achievements_path=playing_game.achievements_path, save_path=playing_game.save_path)
    try:
        reloaded._enter_level_select()
        assert 2 not in reloaded.level_select_locked_ids
    finally:
        pygame.quit()


def test_clearing_a_custom_level_does_not_touch_progress(playing_game):
    custom = make_custom_level()
    playing_game.load_custom_level(custom)
    assert playing_game.current_level_id is None

    playing_game.wave_manager.all_waves_complete = True
    playing_game.enemies = []
    playing_game.update(dt=0.01)

    assert playing_game.state == GameState.VICTORY
    assert progress.load_progress(playing_game.progress_path) == {}


def test_custom_levels_are_never_locked_regardless_of_progress(game, monkeypatch):
    custom = make_custom_level()
    monkeypatch.setattr("persistence.list_custom_levels", lambda: [custom])

    game._enter_level_select()

    assert custom.id not in game.level_select_locked_ids


# --- Loading a saved map back into the editor ---

def test_editor_load_action_enters_level_select_for_editing(game):
    game.state = GameState.EDITOR
    game._handle_editor_click(game.editor_action_rects["load"].center)
    assert game.state == GameState.LEVEL_SELECT
    assert game.level_select_purpose == "edit"


def test_level_select_for_editing_lists_only_custom_levels(game, monkeypatch):
    custom = make_custom_level()
    monkeypatch.setattr("persistence.list_custom_levels", lambda: [custom])

    game._enter_level_select(purpose="edit")

    assert game.level_select_entries == [(custom.id, custom)]
    assert all(isinstance(key, str) for key, _level in game.level_select_entries)


def test_level_select_click_while_editing_loads_the_level_into_the_editor(game, monkeypatch):
    custom = make_custom_level()
    monkeypatch.setattr("persistence.list_custom_levels", lambda: [custom])
    game._enter_level_select(purpose="edit")

    game._handle_level_select_click(game.level_select_rects[custom.id].center)

    assert game.state == GameState.EDITOR
    assert game.editor.path_cells == set(custom.path_cells)
    assert game.editor.wave_specs == custom.wave_specs


def test_level_select_escape_returns_to_editor_when_entered_to_load_a_map(game):
    game._enter_level_select(purpose="edit")
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.EDITOR


def test_level_select_escape_still_returns_to_menu_when_entered_to_play(game):
    game._enter_level_select(purpose="play")
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


# --- render(): smoke tests across every state ---

@pytest.mark.parametrize("state", list(GameState))
def test_render_does_not_crash_in_any_state(playing_game, state):
    playing_game.state = state
    playing_game.render()  # just must not raise


def test_render_with_a_tower_selected_does_not_crash(playing_game):
    playing_game.selected_tower_name = "basic"
    playing_game.render()


def test_render_with_a_tower_selected_that_has_extra_stats_does_not_crash(playing_game):
    # "basic" (used by most render tests above) has no EXTRA_STATS -- pick
    # one that does, so the panel's EXTRA_STATS row-drawing loop actually
    # runs at least once.
    playing_game.selected_tower_name = "cannon"
    playing_game.render()


def test_render_with_a_placed_support_tower_pinned_does_not_crash(playing_game):
    # Exercises the panel's IS_SUPPORT-gated branches: no Damage/Range/
    # Fire-rate rows, no targeting row -- just its own EXTRA_STATS.
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "support"
    playing_game.try_place_tower(anchor_col, anchor_row)
    playing_game.selected_tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.render()


def test_render_with_a_maxed_specializable_tower_pinned_does_not_crash(playing_game):
    # Exercises the stats panel's "not currently hovering either specialize
    # button" branch -- distinct from a fresh, unmaxed tower's plain
    # Upgrade-button panel every other render test above leaves it in.
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.economy.gold = 10_000
    while not tower.is_max_level:
        playing_game.try_upgrade_tower(tower)
    playing_game.selected_tower = tower

    mock_mouse_pos((0, 0))  # nowhere near either specialize button
    try:
        playing_game.render()
    finally:
        clear_mouse_mock()


def test_render_with_all_waves_complete_does_not_crash(playing_game):
    playing_game.wave_manager.all_waves_complete = True
    playing_game.render()


def test_render_during_the_between_waves_countdown_does_not_crash(playing_game):
    playing_game.wave_manager.skip_delay()  # AWAITING_START -> BETWEEN_WAVES, timer 0
    assert playing_game.wave_manager.state == WaveState.BETWEEN_WAVES
    playing_game.render()


def test_render_with_invulnerable_economy_shows_infinite_lives_does_not_crash(playing_game):
    playing_game.economy.invulnerable = True
    playing_game.render()


def test_render_draws_impact_effects_without_crashing(playing_game):
    import effects
    playing_game.impact_effects.append(effects.ExpandingRing((100, 100), max_radius=30))
    playing_game.render()


def test_render_victory_screen_without_a_next_level_does_not_crash(playing_game):
    playing_game.load_level(max(LEVELS.keys()))  # the last built-in level -- has_next_level() is False
    playing_game.state = GameState.VICTORY
    assert not playing_game.has_next_level()
    playing_game.render()


def test_render_draws_live_enemies_projectiles_and_damage_numbers_without_crashing(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game, adjacent_to_path=True)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    playing_game.wave_manager.skip_delay()

    for _ in range(600):  # see test_dead_projectiles_never_linger_in_the_list
        playing_game.update(dt=1 / 60)
        if playing_game.enemies and playing_game.projectiles and playing_game.damage_numbers:
            break

    assert playing_game.enemies and playing_game.projectiles and playing_game.damage_numbers
    playing_game.render()  # must not raise with all three actually populated


def test_render_with_the_placement_preview_hovering_the_hud_does_not_crash(playing_game):
    playing_game.selected_tower_name = "basic"
    hud_pos = (10, settings.SCREEN_HEIGHT - 5)  # inside the HUD band, below the grid
    mock_mouse_pos(hud_pos)
    try:
        playing_game.render()
    finally:
        clear_mouse_mock()


def test_render_while_hovering_a_placed_tower_does_not_crash(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    mock_mouse_pos((int(tower.pos.x), int(tower.pos.y)))
    try:
        playing_game.render()
    finally:
        clear_mouse_mock()


def test_render_editor_with_a_branching_path_does_not_crash(game):
    # An empty editor never draws a junction/spawn/goal marker at all --
    # paint a branch (so there's a junction) plus spawn/goal markers so
    # render() actually exercises that drawing code, not just the empty-
    # grid case every other render smoke test leaves it in.
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.PAINT)
    for cell in [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)]:
        game.editor.paint_at(*cell_center_px(cell))
    game.editor.set_tool(EditorTool.SPAWN)
    game.editor.paint_at(*cell_center_px((1, 0)))
    game.editor.set_tool(EditorTool.GOAL)
    game.editor.paint_at(*cell_center_px((2, 1)))
    game.editor.paint_at(*cell_center_px((1, 2)))
    assert game.editor.junctions  # sanity: the branch was actually detected

    game.render()


def test_render_editor_with_an_in_progress_line_drag_does_not_crash(game):
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.LINE)
    game._handle_editor_click(cell_center_px((0, 0)))
    game._handle_editor_motion(cell_center_px((3, 0)), (True, False, False))
    assert game.editor.pending_shape_cells()  # sanity: a drag is actually in progress

    game.render()


def test_render_editor_with_the_rect_tool_active_shows_the_loop_hint(game):
    # Exercises ui._draw_editor_path_sidebar's RECT-specific hint line.
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.RECT)

    game.render()


def test_render_wave_editor_with_units_added_does_not_crash(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game.editor.adjust_unit_count("grunt", +2)
    game.editor.add_wave()

    game.render()


def test_render_wave_editor_with_multiple_spawns_does_not_crash(game):
    # A single-spawn editor never draws the active-spawn highlight ring or
    # more than one numbered marker -- paint a second spawn so render()
    # actually exercises that code, not just the single-spawn case every
    # other wave editor render test leaves it in.
    game.state = GameState.EDITOR
    _paint_two_spawn_path(game)
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(cell_center_px((0, 2)))  # a non-default active spawn

    game.render()


def test_render_wave_editor_after_saving_does_not_crash(game):
    # last_saved_path is None until a save actually happens -- the "Saved
    # to:" status line never renders in any other wave-editor test.
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    game.last_saved_path = "/fake/custom_levels/a-fairly-long-level-name-to-test-wrapping.json"

    game.render()


def test_render_level_select_with_entries_does_not_crash(game):
    # An empty level_select_entries list never exercises the per-row
    # drawing loop -- populate it the same way _enter_level_select() does.
    game._enter_level_select()
    game.render()


def test_render_level_select_for_editing_does_not_crash(game, monkeypatch):
    # purpose="edit" changes the title/back-hint/tag text and (usually)
    # lists only custom levels -- exercise both the populated and the
    # "no custom levels saved yet" empty-state branches.
    game._enter_level_select(purpose="edit")
    game.render()

    custom = make_custom_level()
    monkeypatch.setattr("persistence.list_custom_levels", lambda: [custom])
    game._enter_level_select(purpose="edit")
    game.render()


def test_render_level_select_with_more_levels_than_fit_does_not_crash(game, monkeypatch):
    # Fewer than this always fits without scrolling, so the clipped
    # viewport and "more above"/"more below" hints never actually draw
    # in any other render test.
    levels = _make_many_custom_levels(10)
    monkeypatch.setattr("persistence.list_custom_levels", lambda: levels)
    game._enter_level_select()
    game.render()  # scrolled to the top -- only "more below" should show

    game._scroll_level_select(-3)
    game.render()  # scrolled partway -- both hints should show

    max_scroll = ui.level_select_max_scroll(len(game.level_select_entries))
    for _ in range(50):
        game._scroll_level_select(-1)
    assert game.level_select_scroll_offset == max_scroll
    game.render()  # scrolled to the bottom -- only "more above" should show


def test_render_paused_on_a_custom_level_does_not_crash(game):
    # test_render_does_not_crash_in_any_state only ever pauses on a
    # built-in level, so the pause menu's extra "Return to Map Editor"
    # option (is_custom_level=True) never actually gets drawn there.
    game.load_custom_level(make_custom_level())
    game.state = GameState.PAUSED
    game.render()


# --- Hover helpers ---

def test_hovered_tower_is_none_when_mouse_is_far_from_every_tower(playing_game):
    mock_mouse_pos((0, 0))
    try:
        assert playing_game._hovered_tower() is None
    finally:
        clear_mouse_mock()


def test_hovered_tower_matches_the_tower_under_the_mouse(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)

    mock_mouse_pos((int(tower.pos.x), int(tower.pos.y)))
    try:
        assert playing_game._hovered_tower() is tower
    finally:
        clear_mouse_mock()


def test_stats_panel_subject_prefers_hovered_tower_over_selection(playing_game):
    anchor_col, anchor_row = find_buildable_anchor(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(anchor_col, anchor_row)
    tower = playing_game.grid.get_tower(anchor_col, anchor_row)
    playing_game.selected_tower_name = "cannon"  # still "selected" for building

    assert playing_game._stats_panel_subject(hovered_tower=tower) is tower


def test_stats_panel_subject_falls_back_to_selected_build_type(playing_game):
    playing_game.selected_tower_name = "cannon"
    assert playing_game._stats_panel_subject(hovered_tower=None) is TOWER_TYPES["cannon"]


def test_stats_panel_subject_is_none_with_nothing_hovered_or_selected(playing_game):
    assert playing_game._stats_panel_subject(hovered_tower=None) is None


# --- handle_events(): dispatch from real pygame events ---
#
# monkeypatches pygame.event.get() to return one canned Event, then checks
# the real side effect the matching branch should have caused -- proving
# handle_events() actually routes to the right handler, not just mocking
# the handler itself and trusting it was called correctly.

_REAL_EVENT_GET = pygame.event.get  # saved once, before anything monkeypatches it


def _fire_event(game, event):
    # Restores the real get() afterward rather than del'ing the attribute --
    # same gotcha as mock_mouse_pos/clear_mouse_mock above.
    pygame.event.get = lambda: [event]
    try:
        game.handle_events()
    finally:
        pygame.event.get = _REAL_EVENT_GET


def test_handle_events_quit_stops_the_game(playing_game):
    _fire_event(playing_game, pygame.event.Event(pygame.QUIT))
    assert playing_game.running is False


def test_handle_events_keydown_dispatches_to_handle_keydown(playing_game):
    _fire_event(playing_game, pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
    assert playing_game.state == GameState.PAUSED


def test_handle_events_left_click_dispatches_to_editor_click(game):
    game.state = GameState.EDITOR
    rect = game.editor_tool_rects[EditorTool.ERASE]
    _fire_event(game, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
    assert game.editor.active_tool == EditorTool.ERASE


def test_handle_events_left_click_dispatches_to_wave_editor_click(game):
    game.editor.path_cells = {(0, 0), (1, 0)}
    game.editor.spawn_cells = {(0, 0)}
    game.editor.goal_cells = {(1, 0)}
    game.editor.validate()
    game.state = GameState.WAVE_EDITOR
    rect = game.wave_editor_action_rects["back"]
    _fire_event(game, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
    assert game.state == GameState.EDITOR


def test_handle_events_left_click_dispatches_to_level_select_click(game):
    game._enter_level_select()
    rect = game.level_select_rects[1]
    _fire_event(game, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
    assert game.state == GameState.PLAYING
    assert game.current_level_id == 1


def test_handle_events_left_click_dispatches_to_playing_click(playing_game):
    rect = playing_game.button_rects["cannon"]
    _fire_event(playing_game, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
    assert playing_game.selected_tower_name == "cannon"


def test_handle_events_right_click_dispatches_to_handle_right_click(playing_game):
    playing_game.selected_tower_name = "basic"
    _fire_event(playing_game, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(0, 0), button=3))
    assert playing_game.selected_tower_name is None


def test_handle_events_mousemotion_in_editor_paints_while_dragging(game):
    game.state = GameState.EDITOR
    game.editor.set_tool(EditorTool.PAINT)
    _fire_event(game, pygame.event.Event(
        pygame.MOUSEMOTION, pos=(10, 10), buttons=(1, 0, 0), rel=(0, 0),
    ))
    assert game.editor.pixel_to_tile(10, 10) in game.editor.path_cells


def test_handle_events_mousewheel_in_level_select_scrolls(game, monkeypatch):
    monkeypatch.setattr("ui.level_select_max_scroll", lambda n: 1000)
    game._enter_level_select()
    _fire_event(game, pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0, flipped=False))
    assert game.level_select_scroll_offset > 0


def test_handle_events_videoresize_while_windowed_resizes_the_screen(game):
    _fire_event(game, pygame.event.Event(pygame.VIDEORESIZE, size=(1000, 600), w=1000, h=600))
    assert game.screen.get_size() == (1000, 600)


def test_handle_events_videoresize_while_fullscreen_is_ignored(game):
    # A fullscreen window resizing away from the desktop resolution isn't
    # something the player actually did -- e.g. a display mode change --
    # so it must not shrink self.screen out from under a fullscreen game.
    game.set_fullscreen(True)
    original_size = game.screen.get_size()

    _fire_event(game, pygame.event.Event(pygame.VIDEORESIZE, size=(1000, 600), w=1000, h=600))

    assert game.screen.get_size() == original_size


def test_handle_events_ignores_events_that_match_no_branch(playing_game):
    # e.g. a mousewheel scroll while not in LEVEL_SELECT -- handle_events()
    # has no branch for it at all, so it's just silently skipped.
    before = playing_game.level_select_scroll_offset
    _fire_event(playing_game, pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0, flipped=False))
    assert playing_game.state == GameState.PLAYING
    assert playing_game.level_select_scroll_offset == before


# --- run(): the top-level frame loop ---

def test_run_calls_the_frame_loop_methods_once_per_iteration_until_stopped(game, monkeypatch):
    calls = []
    monkeypatch.setattr(game, "handle_events", lambda: calls.append("handle_events"))
    monkeypatch.setattr(game, "update", lambda dt: calls.append("update"))

    def fake_render():
        calls.append("render")
        game.running = False  # stop after exactly one iteration

    monkeypatch.setattr(game, "render", fake_render)

    class FakeClock:
        def tick(self, fps):  # pygame.time.Clock's own tick is read-only, can't be patched directly
            return 16

    monkeypatch.setattr(game, "clock", FakeClock())
    monkeypatch.setattr(pygame, "quit", lambda: calls.append("pygame.quit"))
    monkeypatch.setattr(sys, "exit", lambda: calls.append("sys.exit"))

    game.run()

    assert calls == ["handle_events", "update", "render", "pygame.quit", "sys.exit"]
