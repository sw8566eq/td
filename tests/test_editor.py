import pytest

from editor import Editor, EditorTool


def cell_center_px(cell, tile_size=64):
    col, row = cell
    return col * tile_size + tile_size // 2, row * tile_size + tile_size // 2


def _paint_corridor(editor, cells):
    editor.set_tool(EditorTool.PAINT)
    for cell in cells:
        editor.paint_at(*cell_center_px(cell))


def _paint_valid_corridor(editor):
    """A minimal straight corridor with a spawn, a goal, and one unit in
    its one wave -- fully ready to play."""
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 0)))
    editor.adjust_unit_count("grunt", +1)


def test_a_fresh_editor_has_no_cells_no_waves_and_is_not_playable():
    editor = Editor()
    assert editor.path_cells == set()
    assert editor.spawn_cells == set()
    assert editor.goal_cells == set()
    assert editor.wave_specs == [{}]
    assert editor.active_wave_index == 0
    assert not editor.can_play()
    assert editor.active_tool == EditorTool.PAINT


def test_paint_adds_a_path_cell_at_the_clicked_pixel():
    editor = Editor()
    editor.paint_at(*cell_center_px((3, 4)))
    assert (3, 4) in editor.path_cells


def test_erase_removes_a_previously_painted_cell():
    editor = Editor()
    editor.paint_at(*cell_center_px((3, 4)))
    editor.set_tool(EditorTool.ERASE)
    editor.paint_at(*cell_center_px((3, 4)))
    assert (3, 4) not in editor.path_cells


def test_erase_also_clears_a_spawn_or_goal_marker_on_that_cell():
    editor = Editor()
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    assert (0, 0) in editor.spawn_cells

    editor.set_tool(EditorTool.ERASE)
    editor.paint_at(*cell_center_px((0, 0)))
    assert (0, 0) not in editor.path_cells
    assert (0, 0) not in editor.spawn_cells


def test_spawn_tool_paints_the_cell_and_marks_it_a_spawn():
    editor = Editor()
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((1, 1)))
    assert (1, 1) in editor.path_cells
    assert (1, 1) in editor.spawn_cells


def test_goal_tool_paints_the_cell_and_marks_it_a_goal():
    editor = Editor()
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((1, 1)))
    assert (1, 1) in editor.path_cells
    assert (1, 1) in editor.goal_cells


def test_marking_a_goal_on_a_spawn_cell_replaces_the_spawn_marker():
    editor = Editor()
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((2, 2)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 2)))
    assert (2, 2) not in editor.spawn_cells
    assert (2, 2) in editor.goal_cells


def test_painting_outside_the_grid_is_a_silent_no_op():
    editor = Editor()
    editor.paint_at(-100, -100)
    editor.paint_at(999999, 999999)
    assert editor.path_cells == set()


def test_set_tool_ignores_an_unknown_tool_name():
    editor = Editor()
    editor.set_tool("not-a-real-tool")
    assert editor.active_tool == EditorTool.PAINT


def test_clear_resets_every_buffer_including_waves():
    editor = Editor()
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((1, 0)))
    editor.add_wave()
    editor.adjust_unit_count("grunt", +2)

    editor.clear()

    assert editor.path_cells == set()
    assert editor.spawn_cells == set()
    assert editor.goal_cells == set()
    assert editor.wave_specs == [{}]
    assert editor.active_wave_index == 0
    assert not editor.can_play()


# --- Live path validation/junction feedback ---

def test_a_straight_corridor_with_spawn_and_goal_but_no_waves_is_not_yet_playable():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 0)))

    assert editor.path_is_valid()
    assert not editor.can_play()  # the one wave is still empty
    assert any("wave" in problem for problem in editor.validation_problems)


def test_adding_a_unit_to_the_wave_makes_a_valid_path_playable():
    editor = Editor()
    _paint_valid_corridor(editor)
    assert editor.path_is_valid()
    assert editor.can_play()
    assert editor.validation_problems == []


def test_a_path_with_no_spawn_or_goal_yet_is_not_playable():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0)])
    assert not editor.path_is_valid()
    assert not editor.can_play()
    assert editor.validation_problems


def test_a_painted_loop_is_flagged_invalid_live():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 1)))

    assert not editor.path_is_valid()
    assert not editor.can_play()
    assert any("loop" in problem for problem in editor.path_problems)


def test_junctions_are_detected_live_as_the_player_paints():
    editor = Editor()
    _paint_corridor(editor, [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)])
    assert editor.junctions == frozenset({(1, 1)})


# --- Wave editing ---

def test_add_wave_appends_an_empty_wave_and_selects_it():
    editor = Editor()
    editor.add_wave()
    assert editor.wave_specs == [{}, {}]
    assert editor.active_wave_index == 1


def test_remove_wave_removes_the_active_wave_by_default():
    editor = Editor()
    editor.add_wave()
    editor.adjust_unit_count("grunt", +1)  # wave 2 (active) gets a grunt
    editor.remove_wave()
    assert len(editor.wave_specs) == 1
    assert editor.wave_specs[0] == {}  # wave 1 (untouched) remains


def test_remove_wave_refuses_to_drop_below_one_wave():
    editor = Editor()
    editor.remove_wave()
    assert len(editor.wave_specs) == 1


def test_remove_wave_clamps_active_index_after_removing_the_last_wave():
    editor = Editor()
    editor.add_wave()
    editor.add_wave()
    assert editor.active_wave_index == 2
    editor.remove_wave()  # removes wave 3 (the active one)
    assert editor.active_wave_index == 1
    assert len(editor.wave_specs) == 2


def test_set_active_wave_switches_which_wave_unit_edits_apply_to():
    editor = Editor()
    editor.add_wave()
    editor.set_active_wave(0)
    editor.adjust_unit_count("grunt", +3)
    assert editor.wave_specs[0] == {"grunt": 3}
    assert editor.wave_specs[1] == {}


def test_set_active_wave_ignores_an_out_of_range_index():
    editor = Editor()
    editor.set_active_wave(5)
    assert editor.active_wave_index == 0
    editor.set_active_wave(-1)
    assert editor.active_wave_index == 0


def test_adjust_unit_count_increments_and_decrements():
    editor = Editor()
    editor.adjust_unit_count("grunt", +1)
    editor.adjust_unit_count("grunt", +1)
    assert editor.wave_specs[0] == {"grunt": 2}
    editor.adjust_unit_count("grunt", -1)
    assert editor.wave_specs[0] == {"grunt": 1}


def test_adjust_unit_count_drops_the_key_at_zero_rather_than_storing_zero():
    editor = Editor()
    editor.adjust_unit_count("grunt", +1)
    editor.adjust_unit_count("grunt", -1)
    assert editor.wave_specs[0] == {}


def test_adjust_unit_count_does_not_go_negative():
    editor = Editor()
    editor.adjust_unit_count("grunt", -5)
    assert editor.wave_specs[0] == {}


def test_adjust_unit_count_ignores_an_unknown_enemy_name():
    editor = Editor()
    editor.adjust_unit_count("not-a-real-enemy", +1)
    assert editor.wave_specs[0] == {}


def test_an_empty_wave_is_reported_by_number_in_wave_problems():
    editor = Editor()
    editor.add_wave()
    editor.set_active_wave(0)
    editor.adjust_unit_count("grunt", +1)
    # Wave 1 has a unit, wave 2 (added, never touched) doesn't.
    assert any("wave 2" in problem for problem in editor.wave_problems)
    assert not any("wave 1" in problem for problem in editor.wave_problems)


# --- to_level() ---

def test_to_level_builds_a_playable_level_from_a_valid_buffer():
    editor = Editor()
    _paint_valid_corridor(editor)

    level = editor.to_level(name="My Level")
    assert level.name == "My Level"
    assert level.path_cells == frozenset({(0, 0), (1, 0), (2, 0)})
    assert level.spawn_cells == ((0, 0),)
    assert level.goal_cells == ((2, 0),)
    assert level.wave_specs == [{"grunt": 1}]


def test_to_level_carries_over_every_wave_including_multi_species_ones():
    editor = Editor()
    _paint_valid_corridor(editor)
    editor.adjust_unit_count("scout", +2)
    editor.add_wave()
    editor.adjust_unit_count("tank", +1)

    level = editor.to_level()
    assert level.wave_specs == [{"grunt": 1, "scout": 2}, {"tank": 1}]


def test_to_level_raises_for_an_invalid_path():
    editor = Editor()  # nothing painted -- no spawn, no goal, no waves
    with pytest.raises(ValueError):
        editor.to_level()


def test_to_level_raises_for_a_valid_path_with_an_empty_wave():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 0)))
    # No units ever added -- path is valid, but the one wave is empty.
    with pytest.raises(ValueError):
        editor.to_level()
