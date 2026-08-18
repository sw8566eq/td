"""Tests for the Game state machine, input handling, and update loop.

Game() opens a real pygame window, so this module forces the SDL dummy
video driver before pygame ever gets touched -- these tests must be able
to run headless in CI/sandboxes with no real display, same as the manual
smoke tests this project has been relying on during development.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

import settings  # noqa: E402
from game import Game, GameState  # noqa: E402
from levels import LEVELS  # noqa: E402
from tower import TOWER_TYPES, BasicTower  # noqa: E402


@pytest.fixture
def game():
    g = Game()
    yield g
    pygame.quit()


@pytest.fixture
def playing_game(game):
    game.state = GameState.PLAYING
    return game


def find_buildable_cell(game, *, adjacent_to_path=False):
    """A buildable (col, row); optionally one touching the path, for
    tests that care about tower coverage rather than just placement."""
    for row in range(settings.GRID_ROWS):
        for col in range(settings.GRID_COLS):
            if not game.grid.is_buildable(col, row):
                continue
            if not adjacent_to_path:
                return col, row
            for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                if game.grid.is_path(col + dc, row + dr):
                    return col, row
    raise AssertionError("no matching buildable cell found")


def mock_mouse_pos(pos):
    """Context-manager-free mouse mock: pygame.mouse.set_pos() is inert
    under the headless dummy driver, so tests that need a specific hover
    position monkeypatch get_pos() directly instead."""
    pygame.mouse.get_pos = lambda: pos


def clear_mouse_mock():
    if "get_pos" in pygame.mouse.__dict__:
        del pygame.mouse.get_pos


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


def test_starts_with_no_entities_or_selection(game):
    assert game.enemies == []
    assert game.towers == []
    assert game.projectiles == []
    assert game.selected_tower_name is None


# --- State machine: keydown handling ---

def test_menu_any_key_starts_playing(game):
    game._handle_keydown(pygame.K_a)
    assert game.state == GameState.PLAYING


def test_menu_escape_quits_without_starting(game):
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.running is False
    assert game.state == GameState.MENU


def test_playing_p_pauses(playing_game):
    playing_game._handle_keydown(pygame.K_p)
    assert playing_game.state == GameState.PAUSED


def test_playing_escape_quits(playing_game):
    playing_game._handle_keydown(pygame.K_ESCAPE)
    assert playing_game.running is False


def test_playing_space_skips_the_wave_delay(playing_game):
    assert playing_game.wave_manager.between_wave_timer > 0
    playing_game._handle_keydown(pygame.K_SPACE)
    assert playing_game.wave_manager.between_wave_timer <= 0


def test_playing_unbound_key_is_a_no_op(playing_game):
    playing_game._handle_keydown(pygame.K_z)
    assert playing_game.state == GameState.PLAYING
    assert playing_game.running is True


def test_paused_p_resumes(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_p)
    assert playing_game.state == GameState.PLAYING


def test_paused_escape_quits(playing_game):
    playing_game.state = GameState.PAUSED
    playing_game._handle_keydown(pygame.K_ESCAPE)
    assert playing_game.running is False


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
    col, row = find_buildable_cell(playing_game)
    center = playing_game.grid.tile_to_pixel_center(col, row)
    playing_game.selected_tower_name = "basic"

    playing_game._handle_click((int(center.x), int(center.y)))

    assert len(playing_game.towers) == 1
    assert playing_game.grid.is_occupied(col, row)
    assert playing_game.economy.gold == playing_game.level.starting_gold - BasicTower.cost


def test_clicking_a_buildable_cell_with_nothing_selected_does_nothing(playing_game):
    col, row = find_buildable_cell(playing_game)
    center = playing_game.grid.tile_to_pixel_center(col, row)

    playing_game._handle_click((int(center.x), int(center.y)))

    assert playing_game.towers == []


def test_clicking_a_path_cell_never_places_a_tower(playing_game):
    path_col, path_row = next(iter(playing_game.grid.path_cells))
    center = playing_game.grid.tile_to_pixel_center(path_col, path_row)
    playing_game.selected_tower_name = "basic"

    playing_game._handle_click((int(center.x), int(center.y)))

    assert playing_game.towers == []


def test_clicking_to_place_an_unaffordable_tower_does_nothing(playing_game):
    col, row = find_buildable_cell(playing_game)
    center = playing_game.grid.tile_to_pixel_center(col, row)
    playing_game.economy.gold = 0
    playing_game.selected_tower_name = "basic"

    playing_game._handle_click((int(center.x), int(center.y)))

    assert playing_game.towers == []


# --- Click handling: upgrading towers ---

def test_clicking_a_towers_badge_upgrades_it(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.tile_to_pixel_center(col, row)
    playing_game._handle_click((int(center.x), int(center.y)))
    tower = playing_game.grid.get_tower(col, row)
    gold_before = playing_game.economy.gold
    upgrade_cost = tower.upgrade_cost()

    badge = tower.upgrade_badge_center()
    playing_game._handle_click((int(badge[0]), int(badge[1])))

    assert tower.level == 2
    assert playing_game.economy.gold == gold_before - upgrade_cost


def test_clicking_elsewhere_on_a_placed_tower_does_not_upgrade_it(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    center = playing_game.grid.tile_to_pixel_center(col, row)
    playing_game._handle_click((int(center.x), int(center.y)))
    tower = playing_game.grid.get_tower(col, row)

    playing_game._handle_click((int(center.x), int(center.y)))  # tile center, not the badge

    assert tower.level == 1


# --- Right-click handling ---

def test_right_click_clears_the_selected_tower(playing_game):
    playing_game.selected_tower_name = "basic"
    playing_game._handle_right_click()
    assert playing_game.selected_tower_name is None


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
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    assert playing_game.try_place_tower(col, row) is True
    assert playing_game.economy.gold == playing_game.level.starting_gold - BasicTower.cost


def test_try_place_tower_fails_on_non_buildable_cell(playing_game):
    path_col, path_row = next(iter(playing_game.grid.path_cells))
    playing_game.selected_tower_name = "basic"
    assert playing_game.try_place_tower(path_col, path_row) is False
    assert playing_game.economy.gold == playing_game.level.starting_gold


def test_try_place_tower_fails_when_unaffordable(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.economy.gold = 0
    playing_game.selected_tower_name = "basic"
    assert playing_game.try_place_tower(col, row) is False
    assert not playing_game.grid.is_occupied(col, row)


def test_try_upgrade_tower_succeeds_and_deducts_gold(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    tower = playing_game.grid.get_tower(col, row)
    gold_before = playing_game.economy.gold
    cost = tower.upgrade_cost()

    assert playing_game.try_upgrade_tower(tower) is True
    assert tower.level == 2
    assert playing_game.economy.gold == gold_before - cost


def test_try_upgrade_tower_fails_when_unaffordable(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    tower = playing_game.grid.get_tower(col, row)
    playing_game.economy.gold = 0

    assert playing_game.try_upgrade_tower(tower) is False
    assert tower.level == 1


def test_try_upgrade_tower_fails_at_max_level(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    tower = playing_game.grid.get_tower(col, row)
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
    col, row = find_buildable_cell(playing_game, adjacent_to_path=True)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    playing_game.wave_manager.skip_delay()

    for _ in range(300):
        playing_game.update(dt=1 / 60)
        assert all(not p.dead for p in playing_game.projectiles)


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


# --- render(): smoke tests across every state ---

@pytest.mark.parametrize("state", list(GameState))
def test_render_does_not_crash_in_any_state(playing_game, state):
    playing_game.state = state
    playing_game.render()  # just must not raise


def test_render_with_a_tower_selected_does_not_crash(playing_game):
    playing_game.selected_tower_name = "basic"
    playing_game.render()


def test_render_while_hovering_a_placed_tower_does_not_crash(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    tower = playing_game.grid.get_tower(col, row)
    mock_mouse_pos((int(tower.pos.x), int(tower.pos.y)))
    try:
        playing_game.render()
    finally:
        clear_mouse_mock()


# --- Hover helpers ---

def test_hovered_tower_is_none_when_mouse_is_far_from_every_tower(playing_game):
    mock_mouse_pos((0, 0))
    try:
        assert playing_game._hovered_tower() is None
    finally:
        clear_mouse_mock()


def test_hovered_tower_matches_the_tower_under_the_mouse(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    tower = playing_game.grid.get_tower(col, row)

    mock_mouse_pos((int(tower.pos.x), int(tower.pos.y)))
    try:
        assert playing_game._hovered_tower() is tower
    finally:
        clear_mouse_mock()


def test_stats_panel_subject_prefers_hovered_tower_over_selection(playing_game):
    col, row = find_buildable_cell(playing_game)
    playing_game.selected_tower_name = "basic"
    playing_game.try_place_tower(col, row)
    tower = playing_game.grid.get_tower(col, row)
    playing_game.selected_tower_name = "cannon"  # still "selected" for building

    assert playing_game._stats_panel_subject(hovered_tower=tower) is tower


def test_stats_panel_subject_falls_back_to_selected_build_type(playing_game):
    playing_game.selected_tower_name = "cannon"
    assert playing_game._stats_panel_subject(hovered_tower=None) is TOWER_TYPES["cannon"]


def test_stats_panel_subject_is_none_with_nothing_hovered_or_selected(playing_game):
    assert playing_game._stats_panel_subject(hovered_tower=None) is None
