from editor import Editor, EditorTool


def cell_center_px(cell, tile_size=64):
    col, row = cell
    return col * tile_size + tile_size // 2, row * tile_size + tile_size // 2


def test_a_fresh_editor_has_no_cells_and_is_not_playable():
    editor = Editor()
    assert editor.path_cells == set()
    assert editor.spawn_cells == set()
    assert editor.goal_cells == set()
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


def test_clear_resets_every_buffer():
    editor = Editor()
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((1, 0)))

    editor.clear()

    assert editor.path_cells == set()
    assert editor.spawn_cells == set()
    assert editor.goal_cells == set()
    assert not editor.can_play()


# --- Live validation/junction feedback ---

def _paint_corridor(editor, cells):
    editor.set_tool(EditorTool.PAINT)
    for cell in cells:
        editor.paint_at(*cell_center_px(cell))


def test_a_straight_corridor_with_spawn_and_goal_is_playable():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0), (3, 0)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((3, 0)))

    assert editor.can_play()
    assert editor.validation_problems == []


def test_a_path_with_no_spawn_or_goal_yet_is_not_playable():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0)])
    assert not editor.can_play()
    assert editor.validation_problems


def test_a_painted_loop_is_flagged_invalid_live():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 1)))

    assert not editor.can_play()
    assert any("loop" in problem for problem in editor.validation_problems)


def test_junctions_are_detected_live_as_the_player_paints():
    editor = Editor()
    _paint_corridor(editor, [(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)])
    assert editor.junctions == frozenset({(1, 1)})


# --- to_level() ---

def test_to_level_builds_a_playable_level_from_a_valid_buffer():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 0)))

    level = editor.to_level(name="My Level")
    assert level.name == "My Level"
    assert level.path_cells == frozenset({(0, 0), (1, 0), (2, 0)})
    assert level.spawn_cells == ((0, 0),)
    assert level.goal_cells == ((2, 0),)
    assert level.wave_specs  # generate_default_waves() fills this in by default


def test_to_level_raises_for_an_invalid_buffer():
    editor = Editor()  # nothing painted -- no spawn, no goal
    import pytest
    with pytest.raises(ValueError):
        editor.to_level()
