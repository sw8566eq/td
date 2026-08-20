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
from editor import EditorTool  # noqa: E402
from game import Game, GameState  # noqa: E402
from levels import LEVELS, Level  # noqa: E402
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


def test_unlimited_gold_flag_flows_through_to_the_economy():
    g = Game(unlimited_gold=True)
    try:
        assert g.economy.unlimited_gold is True
    finally:
        pygame.quit()


def test_unlimited_gold_flag_survives_a_level_reload():
    g = Game(unlimited_gold=True)
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
        wave_specs=[{"grunt": 2}],
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


def test_editor_escape_returns_to_menu(game):
    game.state = GameState.EDITOR
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


def test_level_select_escape_returns_to_menu(game):
    game.state = GameState.LEVEL_SELECT
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


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
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    assert game.editor.wave_specs[0]["grunt"] == 2


def test_clicking_minus_decrements_and_floors_at_zero(game):
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "minus")].center)
    assert game.editor.wave_specs[0] == {}


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
    assert game.level.wave_specs == [{"grunt": 1}]


def test_wave_editor_back_action_returns_to_the_path_editor(game):
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_editor_action_rects["back"].center)
    assert game.state == GameState.EDITOR


def test_wave_editor_save_action_saves_the_level_when_playable(game, monkeypatch):
    saved = []
    monkeypatch.setattr("persistence.save_level", lambda level: saved.append(level))

    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game._handle_wave_editor_click(game.wave_unit_rects[("grunt", "plus")].center)
    assert game.editor.can_play()

    game._handle_wave_editor_click(game.wave_editor_action_rects["save"].center)

    assert len(saved) == 1
    assert saved[0].wave_specs == [{"grunt": 1}]
    assert game.state == GameState.WAVE_EDITOR  # saving doesn't navigate away


def test_wave_editor_save_action_is_a_no_op_while_unplayable(game, monkeypatch):
    saved = []
    monkeypatch.setattr("persistence.save_level", lambda level: saved.append(level))

    game.state = GameState.WAVE_EDITOR
    assert not game.editor.can_play()
    game._handle_wave_editor_click(game.wave_editor_action_rects["save"].center)

    assert saved == []


def test_level_select_click_on_empty_space_is_a_no_op(game):
    game._enter_level_select()
    game._handle_level_select_click((-1000, -1000))
    assert game.state == GameState.LEVEL_SELECT  # never left


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
    assert (custom.id, f"{custom.name} (custom)") in game.level_select_entries

    game._handle_level_select_click(game.level_select_rects[custom.id].center)

    assert game.state == GameState.PLAYING
    assert game.current_level_id is None
    assert game.level.id == custom.id


# --- render(): smoke tests across every state ---

@pytest.mark.parametrize("state", list(GameState))
def test_render_does_not_crash_in_any_state(playing_game, state):
    playing_game.state = state
    playing_game.render()  # just must not raise


def test_render_with_a_tower_selected_does_not_crash(playing_game):
    playing_game.selected_tower_name = "basic"
    playing_game.render()


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


def test_render_wave_editor_with_units_added_does_not_crash(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game.editor.adjust_unit_count("grunt", +2)
    game.editor.add_wave()

    game.render()


def test_render_level_select_with_entries_does_not_crash(game):
    # An empty level_select_entries list never exercises the per-row
    # drawing loop -- populate it the same way _enter_level_select() does.
    game._enter_level_select()
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
