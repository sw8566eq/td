"""Relocating a placed tower (Game.try_move_tower and the panel's Move button)."""

import pygame
import pytest
from conftest import clear_mouse_mock, find_buildable_anchor, mock_mouse_pos

from entities.waves import WaveState
from support import settings


def _place(game, name="basic"):
    game.selected_tower_name = name
    anchor = find_buildable_anchor(game)
    assert game.try_place_tower(*anchor)
    game.selected_tower_name = None
    return game.towers[-1]


def _free_anchor(game, avoid):
    """A tile-aligned buildable anchor other than `avoid`'s own."""
    n = settings.SUBTILES_PER_TILE
    for row in range(settings.GRID_ROWS):
        for col in range(settings.GRID_COLS):
            if (col * n, row * n) != (avoid.anchor_col, avoid.anchor_row) and game.grid.is_buildable(col * n, row * n):
                return col * n, row * n
    raise AssertionError("no free anchor")


def _between_waves(game):
    game.wave_manager.state = WaveState.BETWEEN_WAVES
    game.wave_manager.between_wave_timer = 3.0


def test_moving_before_the_first_wave_is_free_and_keeps_the_tower(playing_game):
    tower = _place(playing_game)
    tower.upgrade()
    tower.kills = 7
    gold = playing_game.economy.gold
    old = (tower.anchor_col, tower.anchor_row)
    target = _free_anchor(playing_game, tower)

    assert playing_game.move_fee(tower) == 0
    assert playing_game.try_move_tower(tower, *target)

    assert playing_game.economy.gold == gold
    assert (tower.anchor_col, tower.anchor_row) == target
    assert tower.level == 2 and tower.kills == 7
    assert playing_game.grid.get_tower(*target) is tower
    assert not playing_game.grid.is_occupied(*old)
    expected = playing_game.grid.anchor_to_pixel_center(*target, footprint_subtiles=tower.footprint_subtiles)
    assert tower.pos == pygame.Vector2(expected)


def test_moving_between_waves_charges_a_fee(playing_game):
    tower = _place(playing_game)
    _between_waves(playing_game)
    fee = playing_game.move_fee(tower)
    assert fee == max(1, int(tower.total_invested * settings.MOVE_FEE_FRACTION))
    gold = playing_game.economy.gold

    assert playing_game.try_move_tower(tower, *_free_anchor(playing_game, tower))
    assert playing_game.economy.gold == gold - fee


def test_cannot_move_mid_wave_or_when_unaffordable(playing_game):
    tower = _place(playing_game)
    target = _free_anchor(playing_game, tower)
    playing_game.wave_manager.state = WaveState.SPAWNING
    assert not playing_game.can_move_towers()
    assert not playing_game.begin_moving_tower(tower)
    assert not playing_game.try_move_tower(tower, *target)

    _between_waves(playing_game)
    playing_game.economy.gold = 0
    assert not playing_game.begin_moving_tower(tower)
    assert not playing_game.try_move_tower(tower, *target)


def test_cannot_move_onto_the_path_or_onto_itself(playing_game):
    tower = _place(playing_game)
    n = settings.SUBTILES_PER_TILE
    col, row = next(iter(playing_game.level.path_cells))
    assert not playing_game.try_move_tower(tower, col * n, row * n)
    assert not playing_game.try_move_tower(tower, tower.anchor_col, tower.anchor_row)
    # The failed checks never leave the tower's own space unoccupied.
    assert playing_game.grid.get_tower(tower.anchor_col, tower.anchor_row) is tower


def test_a_short_nudge_overlapping_its_old_footprint_is_allowed(playing_game):
    tower = _place(playing_game)
    nudged = (tower.anchor_col + 1, tower.anchor_row)
    if not playing_game._is_buildable_for_move(tower, *nudged):
        pytest.skip("no room to nudge on this level")
    assert playing_game.try_move_tower(tower, *nudged)
    assert playing_game.grid.get_tower(*nudged) is tower


def test_a_path_trap_can_only_move_along_the_path(playing_game):
    n = settings.SUBTILES_PER_TILE
    cells = sorted(set(playing_game.level.path_cells) - set(playing_game.level.spawn_cells) - set(playing_game.level.goal_cells))
    playing_game.selected_tower_name = "spike_trap"
    assert playing_game.try_place_tower(cells[0][0] * n, cells[0][1] * n)
    trap = playing_game.towers[-1]
    ground = find_buildable_anchor(playing_game)
    assert not playing_game.try_move_tower(trap, *ground)
    assert playing_game.try_move_tower(trap, cells[1][0] * n, cells[1][1] * n)


def test_move_button_then_board_click_relocates_and_right_click_cancels(playing_game):
    tower = _place(playing_game)
    playing_game._last_panel_subject = tower
    playing_game._handle_click(playing_game.move_button_rect.center)
    assert playing_game.moving_tower is tower

    playing_game._handle_right_click()
    assert playing_game.moving_tower is None

    playing_game._handle_click(playing_game.move_button_rect.center)
    playing_game._handle_click(playing_game.move_button_rect.center)  # Move again = put it back
    assert playing_game.moving_tower is None

    playing_game._handle_click(playing_game.move_button_rect.center)
    target = _free_anchor(playing_game, tower)
    center = playing_game.grid.anchor_to_pixel_center(*target, footprint_subtiles=tower.footprint_subtiles)
    playing_game._handle_click(center)
    assert playing_game.moving_tower is None
    assert (tower.anchor_col, tower.anchor_row) == target


def test_picking_a_build_button_or_selling_drops_the_move(playing_game):
    tower = _place(playing_game)
    assert playing_game.begin_moving_tower(tower)
    playing_game._handle_click(playing_game.button_rects["basic"].center)
    assert playing_game.moving_tower is None

    assert playing_game.begin_moving_tower(tower)
    playing_game.try_sell_tower(tower)
    assert playing_game.moving_tower is None


def test_a_wave_starting_mid_move_cancels_it(playing_game):
    tower = _place(playing_game)
    assert playing_game.begin_moving_tower(tower)
    playing_game.wave_manager.state = WaveState.SPAWNING
    playing_game.update(0.01)
    assert playing_game.moving_tower is None


def test_move_label_and_preview_render(playing_game):
    tower = _place(playing_game)
    renderer = playing_game.renderer
    assert renderer._move_label(tower) == "Move free"
    assert renderer._move_label(None) is None
    assert not renderer._move_enabled(None)
    _between_waves(playing_game)
    assert renderer._move_label(tower) == f"Move {playing_game.move_fee(tower)}g"
    assert renderer._move_enabled(tower)
    playing_game.begin_moving_tower(tower)
    assert renderer._move_label(tower) == "Cancel"
    assert renderer._move_enabled(tower)
    playing_game.selected_tower = tower
    try:
        mock_mouse_pos((10, 10))
        playing_game.render()
        mock_mouse_pos((settings.PLAY_WIDTH + 5, 10))  # over the panel: no preview
        playing_game.render()
    finally:
        clear_mouse_mock()
