"""Tests for the editor-facing screens Game drives: the map editor
(GameState.EDITOR), the wave editor (GameState.WAVE_EDITOR), and the level
browser (GameState.LEVEL_SELECT) in both of its purposes -- browsing to
play and browsing to reopen a saved map for editing.

Editor itself is tested directly in test_editor.py; this module is about
how Game wires it to input, screens, and the level files on disk. Game's
own state machine tests are in test_game.py; shared fixtures and helpers
for both are in conftest.py.
"""

import json

import pygame

import persistence
import settings
import ui
from editor import EditorTool
from game import GameState
from levels import Level

from conftest import (
    cell_center_px,
    make_custom_level,
    mock_key_mods,
    clear_key_mods,
)


# --- Entering the map editor ---


def test_game_starts_with_an_empty_unplayable_editor(game):
    assert game.editor.path_cells == set()
    assert not game.editor.can_play()


# --- Editor/wave-editor/level-select keyboard and click dispatch ---


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


# --- Wave editor scrolling ---
#
# The per-species row list (unit_rects) has grown past what a fixed sidebar
# budget can show all at once -- see ui.WAVE_UNIT_ROWS_TOP/_BOTTOM -- so it
# scrolls, mirroring the level browser's own scroll mechanism (see the
# "Level select scrolling" tests above this module for the template these
# follow).


def test_scrolling_down_moves_the_wave_unit_rows_up(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    first_name = ui.ENEMY_ORDER[0]
    first_row_y_before = game.wave_unit_rects[(first_name, "minus")].y

    game._scroll_wave_unit_list(-1)  # wheel "down" gesture
    first_row_y_after = game.wave_unit_rects[(first_name, "minus")].y

    assert game.wave_unit_scroll_offset > 0
    assert first_row_y_after < first_row_y_before


def test_wave_unit_scroll_offset_clamps_at_zero_and_at_max(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR

    game._scroll_wave_unit_list(1)  # can't scroll up past the top
    assert game.wave_unit_scroll_offset == 0

    max_scroll = ui.wave_unit_max_scroll(len(ui.ENEMY_ORDER))
    assert max_scroll > 0  # sanity: today's real registry actually overflows
    for _ in range(50):
        game._scroll_wave_unit_list(-1)
    assert game.wave_unit_scroll_offset == max_scroll


def test_entering_wave_editor_resets_scroll_to_the_top(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game._handle_editor_action("waves")
    game._scroll_wave_unit_list(-3)
    assert game.wave_unit_scroll_offset > 0

    game._handle_editor_action("waves")  # re-entering (e.g. via the button again) starts back at the top
    assert game.wave_unit_scroll_offset == 0


def test_clicking_a_scrolled_wave_unit_row_still_adjusts_the_right_species(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    max_scroll = ui.wave_unit_max_scroll(len(ui.ENEMY_ORDER))
    for _ in range(50):
        game._scroll_wave_unit_list(-1)
    assert game.wave_unit_scroll_offset == max_scroll

    last_name = ui.ENEMY_ORDER[-1]
    rect = game.wave_unit_rects[(last_name, "plus")]
    assert ui.WAVE_UNIT_ROWS_TOP <= rect.centery <= ui.WAVE_UNIT_ROWS_BOTTOM  # sanity: actually visible now

    game._handle_wave_editor_click(rect.center)

    composition = game.editor.wave_specs[game.editor.active_wave_index][game.editor.active_spawn_cell]
    assert composition.get(last_name, 0) == 1


def test_clicking_an_action_button_is_not_intercepted_by_an_overflowing_wave_unit_row(game):
    # Regression guard for the exact bug class CLAUDE.md documents for the
    # level browser: even unscrolled, today's real ENEMY_ORDER registry (8
    # species) overflows the sidebar's fixed vertical budget, so the last
    # row's raw Rect spills past WAVE_UNIT_ROWS_BOTTOM into the action-
    # button area (clipped from view when drawn, but a real Rect there
    # regardless -- see build_wave_unit_rects' docstring). Without the
    # pos-fence in _handle_wave_editor_click, a click on a real action
    # button could be intercepted by that spilled-over row instead.
    assert ui.wave_unit_content_height(len(ui.ENEMY_ORDER)) > ui.WAVE_UNIT_ROWS_BOTTOM - ui.WAVE_UNIT_ROWS_TOP

    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR

    back_rect = game.wave_editor_action_rects["back"]
    game._handle_wave_editor_click(back_rect.center)
    assert game.state == GameState.EDITOR


def test_render_wave_editor_while_scrolled_does_not_crash(game):
    game.state = GameState.EDITOR
    _paint_valid_path(game)
    game.state = GameState.WAVE_EDITOR
    game._scroll_wave_unit_list(-1)

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
    # test_game.py's own test_render_does_not_crash_in_any_state only ever
    # pauses on a built-in level, so the pause menu's extra "Return to Map
    # Editor" option (is_custom_level=True) never actually gets drawn
    # there.
    game.load_custom_level(make_custom_level())
    game.state = GameState.PAUSED
    game.render()


# --- Import Level ---


def _write_external_level_file(tmp_path, name="Imported Level"):
    """A small, valid, standalone level JSON file sitting somewhere other
    than custom_levels/ -- standing in for "a file someone else handed
    you," the way sharing a level actually works today (see CLAUDE.md)."""
    level = Level(
        id="external",
        name=name,
        path_cells=frozenset({(0, 0), (0, 1), (0, 2)}),
        spawn_cells=((0, 0),),
        goal_cells=((0, 2),),
        wave_specs=[{(0, 0): {"grunt": 3}}],
    )
    return persistence.save_level(level, directory=tmp_path / "source")


def test_import_level_from_path_copies_a_valid_level_into_the_target_directory(game, tmp_path):
    source_path = _write_external_level_file(tmp_path, name="Imported Level")
    target_dir = tmp_path / "custom_levels"

    result = game._import_level_from_path(source_path, directory=target_dir)

    assert result is True
    assert game.import_status_is_error is False
    imported = persistence.list_custom_levels(target_dir)
    assert len(imported) == 1
    assert imported[0].name == "Imported Level"


def test_import_level_from_path_sets_a_success_status_message(game, tmp_path):
    source_path = _write_external_level_file(tmp_path)

    game._import_level_from_path(source_path, directory=tmp_path / "custom_levels")

    assert game.import_status_message is not None
    assert game.import_status_is_error is False


def test_import_level_from_path_rejects_a_corrupt_file(game, tmp_path):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json")
    target_dir = tmp_path / "custom_levels"

    result = game._import_level_from_path(str(bad_path), directory=target_dir)

    assert result is False
    assert game.import_status_message is not None
    assert game.import_status_is_error is True
    assert persistence.list_custom_levels(target_dir) == []


def test_import_level_from_path_rejects_a_file_with_an_invalid_topology(game, tmp_path):
    # Well-formed JSON, but semantically invalid (Level.__post_init__
    # rejects it -- here, a wave referencing a spawn cell that isn't one of
    # spawn_cells). Confirms the exact same validation
    # persistence.list_custom_levels() already relies on actually runs
    # during import, not just a JSON-parses-at-all check.
    bad_path = tmp_path / "bad_topology.json"
    bad_path.write_text(json.dumps({
        "schema_version": persistence.SCHEMA_VERSION,
        "id": "bad",
        "name": "Bad Level",
        "path_cells": [[0, 0], [0, 1]],
        "spawn_cells": [[0, 0]],
        "goal_cells": [[0, 1]],
        "blocked_cells": [],
        "branch_weights": [],
        "wave_specs": [[[[9, 9], {"grunt": 1}]]],
        "starting_gold": 150,
        "starting_lives": 20,
    }))
    target_dir = tmp_path / "custom_levels"

    result = game._import_level_from_path(str(bad_path), directory=target_dir)

    assert result is False
    assert persistence.list_custom_levels(target_dir) == []


def test_import_level_from_path_leaves_other_saved_levels_alone_on_failure(game, tmp_path):
    target_dir = tmp_path / "custom_levels"
    good_source = _write_external_level_file(tmp_path, name="Already There")
    game._import_level_from_path(good_source, directory=target_dir)
    assert len(persistence.list_custom_levels(target_dir)) == 1

    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json")
    game._import_level_from_path(str(bad_path), directory=target_dir)

    assert len(persistence.list_custom_levels(target_dir)) == 1


def test_editor_import_action_calls_import_level(game, monkeypatch):
    called = []
    monkeypatch.setattr(game, "_import_level", lambda: called.append(True))
    game.state = GameState.EDITOR

    game._handle_editor_action("import")

    assert called == [True]


def test_render_editor_with_an_import_status_message_does_not_crash(game):
    game.state = GameState.EDITOR
    game.import_status_message = "Level imported."
    game.import_status_is_error = False
    game.render()

    game.import_status_message = "Import failed."
    game.import_status_is_error = True
    game.render()
