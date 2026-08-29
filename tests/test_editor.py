import pytest

from editor import Editor, EditorTool
from levels import Level


def cell_center_px(cell, tile_size=64):
    col, row = cell
    return col * tile_size + tile_size // 2, row * tile_size + tile_size // 2


def _paint_corridor(editor, cells):
    editor.set_tool(EditorTool.PAINT)
    for cell in cells:
        editor.paint_at(*cell_center_px(cell))


def _add_spawn(editor, cell=(0, 0)):
    """Paint just a spawn marker -- enough to give validate() an active
    spawn to auto-select, without needing a whole valid corridor. Restores
    the PAINT tool afterward so callers aren't surprised by a leftover
    active_tool."""
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px(cell))
    editor.set_tool(EditorTool.PAINT)


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
    assert editor.active_spawn_cell is None
    assert not editor.can_play()
    assert editor.active_tool == EditorTool.PAINT


def test_paint_adds_a_path_cell_at_the_clicked_pixel():
    editor = Editor()
    editor.paint_at(*cell_center_px((3, 4)))
    assert (3, 4) in editor.path_cells


def test_an_unrecognized_active_tool_paints_nothing():
    # Not reachable through set_tool() (it only accepts TOOL_ORDER members),
    # but _apply_tool()'s if/elif chain still needs a safe fallthrough for
    # any value that doesn't match one of the four known tools.
    editor = Editor()
    editor.active_tool = "bogus-tool"

    editor.paint_at(*cell_center_px((3, 4)))

    assert editor.path_cells == set()
    assert editor.spawn_cells == set()
    assert editor.goal_cells == set()


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
    assert editor.active_spawn_cell is None
    assert not editor.can_play()


# --- load_level() (reopening a saved level for further editing) ---

def _make_saved_level():
    return Level(
        id="saved-slug",
        name="Saved Level",
        path_cells=frozenset({(0, 0), (0, 1), (0, 2), (1, 1)}),
        spawn_cells=((0, 0), (0, 2)),
        goal_cells=((1, 1),),
        wave_specs=[{(0, 0): {"grunt": 3}}, {(0, 2): {"tank": 1}}],
    )


def test_load_level_populates_path_and_spawn_and_goal_cells():
    editor = Editor()
    editor.load_level(_make_saved_level())
    assert editor.path_cells == {(0, 0), (0, 1), (0, 2), (1, 1)}
    assert editor.spawn_cells == {(0, 0), (0, 2)}
    assert editor.goal_cells == {(1, 1)}


def test_load_level_populates_waves_and_resets_the_active_wave():
    editor = Editor()
    editor.add_wave()
    editor.set_active_wave(1)

    editor.load_level(_make_saved_level())

    assert editor.wave_specs == [{(0, 0): {"grunt": 3}}, {(0, 2): {"tank": 1}}]
    assert editor.active_wave_index == 0


def test_load_level_leaves_the_editor_playable_and_switches_to_the_paint_tool():
    editor = Editor()
    editor.set_tool(EditorTool.GOAL)

    editor.load_level(_make_saved_level())

    assert editor.path_is_valid()
    assert editor.can_play()
    assert editor.active_tool == EditorTool.PAINT


def test_load_level_replaces_whatever_was_previously_painted():
    editor = Editor()
    editor.paint_at(*cell_center_px((5, 5)))
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((5, 5)))

    editor.load_level(_make_saved_level())

    assert (5, 5) not in editor.path_cells
    assert (5, 5) not in editor.spawn_cells


def test_load_level_does_not_mutate_the_source_level_on_later_edits():
    level = _make_saved_level()
    editor = Editor()
    editor.load_level(level)

    editor.set_active_spawn((0, 0))
    editor.adjust_unit_count("grunt", +5)

    assert level.wave_specs == [{(0, 0): {"grunt": 3}}, {(0, 2): {"tank": 1}}]  # unchanged


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


# --- Active spawn selection ---

def test_painting_the_first_spawn_auto_selects_it():
    editor = Editor()
    assert editor.active_spawn_cell is None
    _add_spawn(editor, (2, 3))
    assert editor.active_spawn_cell == (2, 3)


def test_set_active_spawn_switches_to_a_different_existing_spawn():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((5, 5)))  # second spawn, doesn't move selection
    assert editor.active_spawn_cell == (0, 0)  # first spawn painted, unchanged so far

    editor.set_active_spawn((5, 5))
    assert editor.active_spawn_cell == (5, 5)


def test_set_active_spawn_ignores_a_cell_that_is_not_a_spawn():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.set_active_spawn((9, 9))
    assert editor.active_spawn_cell == (0, 0)


def test_erasing_the_active_spawn_reselects_a_remaining_spawn():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((5, 5)))
    editor.set_active_spawn((0, 0))

    editor.set_tool(EditorTool.ERASE)
    editor.paint_at(*cell_center_px((0, 0)))

    assert editor.active_spawn_cell == (5, 5)


def test_erasing_the_only_spawn_clears_the_active_spawn():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.set_tool(EditorTool.ERASE)
    editor.paint_at(*cell_center_px((0, 0)))
    assert editor.active_spawn_cell is None


def test_overwriting_the_active_spawn_with_the_goal_tool_reselects():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((0, 0)))  # replaces the spawn marker
    assert editor.active_spawn_cell is None


def test_erasing_a_spawn_drops_its_units_from_every_wave():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.adjust_unit_count("grunt", +3)
    editor.add_wave()
    editor.adjust_unit_count("tank", +1)
    assert editor.wave_specs == [{(0, 0): {"grunt": 3}}, {(0, 0): {"tank": 1}}]

    editor.set_tool(EditorTool.ERASE)
    editor.paint_at(*cell_center_px((0, 0)))

    assert editor.wave_specs == [{}, {}]


# --- Wave editing ---

def test_add_wave_appends_an_empty_wave_and_selects_it():
    editor = Editor()
    editor.add_wave()
    assert editor.wave_specs == [{}, {}]
    assert editor.active_wave_index == 1


def test_remove_wave_removes_the_active_wave_by_default():
    editor = Editor()
    _add_spawn(editor)
    editor.add_wave()
    editor.adjust_unit_count("grunt", +1)  # wave 2 (active) gets a grunt
    editor.remove_wave()
    assert len(editor.wave_specs) == 1
    assert editor.wave_specs[0] == {}  # wave 1 (untouched) remains


def test_remove_wave_refuses_to_drop_below_one_wave():
    editor = Editor()
    editor.remove_wave()
    assert len(editor.wave_specs) == 1


def test_remove_wave_with_an_explicit_out_of_range_index_is_a_no_op():
    editor = Editor()
    editor.add_wave()
    editor.remove_wave(index=5)
    editor.remove_wave(index=-1)
    assert len(editor.wave_specs) == 2


def test_remove_wave_with_an_explicit_in_range_index_removes_that_wave_not_the_active_one():
    editor = Editor()
    _add_spawn(editor)
    editor.add_wave()  # wave 2, now active
    editor.adjust_unit_count("tank", +1)  # goes on wave 2
    editor.remove_wave(index=0)  # remove wave 1 specifically
    assert editor.wave_specs == [{(0, 0): {"tank": 1}}]


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
    _add_spawn(editor)
    editor.add_wave()
    editor.set_active_wave(0)
    editor.adjust_unit_count("grunt", +3)
    assert editor.wave_specs[0] == {(0, 0): {"grunt": 3}}
    assert editor.wave_specs[1] == {}


def test_set_active_wave_ignores_an_out_of_range_index():
    editor = Editor()
    editor.set_active_wave(5)
    assert editor.active_wave_index == 0
    editor.set_active_wave(-1)
    assert editor.active_wave_index == 0


def test_adjust_unit_count_increments_and_decrements():
    editor = Editor()
    _add_spawn(editor)
    editor.adjust_unit_count("grunt", +1)
    editor.adjust_unit_count("grunt", +1)
    assert editor.wave_specs[0] == {(0, 0): {"grunt": 2}}
    editor.adjust_unit_count("grunt", -1)
    assert editor.wave_specs[0] == {(0, 0): {"grunt": 1}}


def test_adjust_unit_count_drops_the_key_at_zero_rather_than_storing_zero():
    editor = Editor()
    _add_spawn(editor)
    editor.adjust_unit_count("grunt", +1)
    editor.adjust_unit_count("grunt", -1)
    assert editor.wave_specs[0] == {}  # the emptied-out spawn is dropped too


def test_adjust_unit_count_does_not_go_negative():
    editor = Editor()
    _add_spawn(editor)
    editor.adjust_unit_count("grunt", -5)
    assert editor.wave_specs[0] == {}


def test_adjust_unit_count_ignores_an_unknown_enemy_name():
    editor = Editor()
    _add_spawn(editor)
    editor.adjust_unit_count("not-a-real-enemy", +1)
    assert editor.wave_specs[0] == {}


def test_adjust_unit_count_is_a_no_op_with_no_active_spawn():
    editor = Editor()  # nothing painted -- no active spawn to target
    editor.adjust_unit_count("grunt", +1)
    assert editor.wave_specs == [{}]


def test_adjust_unit_count_targets_only_the_active_spawn():
    editor = Editor()
    _add_spawn(editor, (0, 0))
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((5, 5)))
    editor.set_active_spawn((0, 0))
    editor.adjust_unit_count("grunt", +2)

    editor.set_active_spawn((5, 5))
    editor.adjust_unit_count("tank", +1)

    assert editor.wave_specs[0] == {(0, 0): {"grunt": 2}, (5, 5): {"tank": 1}}


def test_an_empty_wave_is_reported_by_number_in_wave_problems():
    editor = Editor()
    _add_spawn(editor)
    editor.add_wave()
    editor.set_active_wave(0)
    editor.adjust_unit_count("grunt", +1)
    # Wave 1 has a unit, wave 2 (added, never touched) doesn't.
    assert any("wave 2" in problem for problem in editor.wave_problems)
    assert not any("wave 1" in problem for problem in editor.wave_problems)


def test_a_wave_with_units_on_one_spawn_but_not_another_is_still_playable():
    # A spawn sitting out a given wave entirely is a valid design choice,
    # not something that should be flagged -- only a wave with *nothing*
    # from *any* spawn is a problem.
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (0, 1), (0, 2), (1, 1)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.paint_at(*cell_center_px((0, 2)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((1, 1)))
    editor.set_active_spawn((0, 0))
    editor.adjust_unit_count("grunt", +1)

    assert editor.path_is_valid()
    assert editor.can_play()
    assert editor.wave_problems == []


# --- to_level() ---

def test_to_level_builds_a_playable_level_from_a_valid_buffer():
    editor = Editor()
    _paint_valid_corridor(editor)

    level = editor.to_level(name="My Level")
    assert level.name == "My Level"
    assert level.path_cells == frozenset({(0, 0), (1, 0), (2, 0)})
    assert level.spawn_cells == ((0, 0),)
    assert level.goal_cells == ((2, 0),)
    assert level.wave_specs == [{(0, 0): {"grunt": 1}}]


def test_to_level_carries_over_every_wave_including_multi_species_ones():
    editor = Editor()
    _paint_valid_corridor(editor)
    editor.adjust_unit_count("scout", +2)
    editor.add_wave()
    editor.adjust_unit_count("tank", +1)

    level = editor.to_level()
    assert level.wave_specs == [{(0, 0): {"grunt": 1, "scout": 2}}, {(0, 0): {"tank": 1}}]


def test_to_level_carries_over_independent_per_spawn_compositions():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (0, 1), (0, 2), (1, 1)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.paint_at(*cell_center_px((0, 2)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((1, 1)))
    editor.set_active_spawn((0, 0))
    editor.adjust_unit_count("grunt", +3)
    editor.set_active_spawn((0, 2))
    editor.adjust_unit_count("tank", +2)

    level = editor.to_level()
    assert level.wave_specs == [{(0, 0): {"grunt": 3}, (0, 2): {"tank": 2}}]


def test_to_level_returns_independent_copies_not_live_references():
    editor = Editor()
    _paint_valid_corridor(editor)
    level = editor.to_level()

    editor.adjust_unit_count("grunt", +10)

    assert level.wave_specs == [{(0, 0): {"grunt": 1}}]  # unaffected by the later edit


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


# --- Undo/redo ---

def test_undo_on_a_fresh_editor_is_a_no_op():
    editor = Editor()
    assert editor.undo() is False
    assert editor.path_cells == set()


def test_redo_with_nothing_undone_is_a_no_op():
    editor = Editor()
    editor.paint_at(*cell_center_px((0, 0)))
    assert editor.redo() is False


def test_undo_reverts_a_single_painted_cell():
    editor = Editor()
    editor.paint_at(*cell_center_px((3, 4)))

    assert editor.undo() is True

    assert (3, 4) not in editor.path_cells


def test_redo_reapplies_an_undone_edit():
    editor = Editor()
    editor.paint_at(*cell_center_px((3, 4)))
    editor.undo()

    assert editor.redo() is True

    assert (3, 4) in editor.path_cells


def test_a_whole_drag_stroke_undoes_as_one_step_not_one_per_cell():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0), (3, 0)])  # one continuous drag

    editor.undo()

    assert editor.path_cells == set()  # the whole stroke gone in a single undo
    assert editor.undo() is False  # nothing more to undo -- it was one step


def test_ending_a_stroke_starts_a_fresh_undo_step_for_the_next_one():
    editor = Editor()
    editor.set_tool(EditorTool.PAINT)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.end_stroke()  # simulates a mouse-up between strokes
    editor.paint_at(*cell_center_px((1, 0)))

    editor.undo()  # undoes only the second stroke

    assert (0, 0) in editor.path_cells
    assert (1, 0) not in editor.path_cells


def test_new_edit_after_an_undo_clears_the_redo_stack():
    editor = Editor()
    editor.paint_at(*cell_center_px((0, 0)))
    editor.end_stroke()
    editor.undo()

    editor.paint_at(*cell_center_px((5, 5)))  # a genuinely new edit

    assert editor.redo() is False


def test_undo_limit_caps_how_far_back_history_goes():
    editor = Editor()
    # Wrap within the grid's real bounds (default 15x9 = 135 cells) --
    # painting straight off the edge past col 15 would silently no-op
    # (see Editor.in_bounds()) and never push an undo step at all.
    for i in range(Editor.UNDO_LIMIT + 10):
        col, row = i % editor.cols, i // editor.cols
        editor.paint_at(*cell_center_px((col, row)))
        editor.end_stroke()

    undo_count = 0
    while editor.undo():
        undo_count += 1

    assert undo_count == Editor.UNDO_LIMIT


def test_undo_restores_wave_data_too():
    editor = Editor()
    _paint_valid_corridor(editor)  # includes one grunt in wave 1
    editor.adjust_unit_count("grunt", +5)
    assert editor.wave_specs[0][(0, 0)]["grunt"] == 6

    editor.undo()

    assert editor.wave_specs[0][(0, 0)]["grunt"] == 1


def test_undo_after_clear_restores_everything():
    editor = Editor()
    _paint_valid_corridor(editor)
    editor.clear()
    assert editor.path_cells == set()

    editor.undo()

    assert editor.can_play()


def test_undo_after_load_level_restores_the_previous_in_progress_buffer():
    editor = Editor()
    _paint_corridor(editor, [(5, 5), (5, 6)])  # some in-progress, unsaved work
    other_level = Level(
        id="other", name="Other", path_cells=frozenset({(0, 0), (1, 0)}),
        spawn_cells=((0, 0),), goal_cells=((1, 0),),
        wave_specs=[{(0, 0): {"grunt": 1}}],
    )

    editor.load_level(other_level)
    assert editor.path_cells == {(0, 0), (1, 0)}

    editor.undo()

    assert editor.path_cells == {(5, 5), (5, 6)}


def test_undo_after_add_wave_removes_it():
    editor = Editor()
    assert len(editor.wave_specs) == 1
    editor.add_wave()
    assert len(editor.wave_specs) == 2

    editor.undo()

    assert len(editor.wave_specs) == 1


def test_undo_after_remove_wave_restores_it():
    editor = Editor()
    editor.add_wave()
    editor.remove_wave(0)
    assert len(editor.wave_specs) == 1

    editor.undo()

    assert len(editor.wave_specs) == 2


def test_remove_wave_no_op_does_not_push_an_undo_step():
    editor = Editor()
    editor.paint_at(*cell_center_px((0, 0)))  # one real edit on the stack
    editor.end_stroke()
    editor.remove_wave()  # only one wave exists -- a no-op, must not push anything

    editor.undo()

    assert (0, 0) not in editor.path_cells  # undid the paint, not a phantom no-op step
    assert editor.undo() is False


# --- Line/Rectangle tools ---

def test_line_tool_paints_a_straight_run_between_two_points():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    editor.begin_shape((0, 0))
    editor.update_shape_preview((3, 0))
    editor.commit_shape((3, 0))

    assert editor.path_cells == {(0, 0), (1, 0), (2, 0), (3, 0)}


def test_line_tool_snaps_a_diagonal_drag_to_the_dominant_axis():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    editor.begin_shape((0, 0))
    editor.update_shape_preview((5, 2))  # diagonal -- horizontal movement dominates

    editor.commit_shape((5, 2))  # must not raise (path_cells_from_corners rejects diagonals)

    assert (5, 0) in editor.path_cells  # snapped to the start row, not the end row
    assert (5, 2) not in editor.path_cells


def test_pending_shape_cells_does_not_mutate_path_cells_before_commit():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    editor.begin_shape((0, 0))
    editor.update_shape_preview((3, 0))

    preview = editor.pending_shape_cells()

    assert preview == {(0, 0), (1, 0), (2, 0), (3, 0)}
    assert editor.path_cells == set()  # nothing committed yet


def test_pending_shape_cells_is_empty_with_no_drag_in_progress():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    assert editor.pending_shape_cells() == frozenset()


def test_rect_tool_paints_a_hollow_perimeter():
    editor = Editor()
    editor.set_tool(EditorTool.RECT)
    editor.begin_shape((0, 0))
    editor.commit_shape((2, 2))

    assert editor.path_cells == {
        (0, 0), (1, 0), (2, 0),
        (0, 1), (2, 1),
        (0, 2), (1, 2), (2, 2),
    }
    assert (1, 1) not in editor.path_cells  # hollow, not filled


def test_rect_tool_initially_reports_a_loop():
    editor = Editor()
    editor.set_tool(EditorTool.RECT)
    editor.begin_shape((0, 0))
    editor.commit_shape((2, 2))
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 2)))

    assert not editor.path_is_valid()
    assert any("loop" in problem for problem in editor.path_problems)


def test_erasing_one_edge_of_a_rect_opens_it_into_a_valid_corridor():
    editor = Editor()
    editor.set_tool(EditorTool.RECT)
    editor.begin_shape((0, 0))
    editor.commit_shape((2, 2))
    editor.set_tool(EditorTool.ERASE)
    editor.paint_at(*cell_center_px((1, 0)))  # break the loop
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.set_tool(EditorTool.GOAL)
    editor.paint_at(*cell_center_px((2, 0)))

    assert editor.path_is_valid()


def test_begin_shape_ignores_an_out_of_bounds_cell():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    editor.begin_shape((-5, -5))
    assert editor.pending_shape_cells() == frozenset()


def test_a_click_with_no_drag_paints_a_single_cell_with_the_line_tool():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    editor.begin_shape((4, 4))
    editor.commit_shape((4, 4))
    assert editor.path_cells == {(4, 4)}


def test_commit_shape_with_no_drag_in_progress_is_a_no_op():
    editor = Editor()
    editor.set_tool(EditorTool.LINE)
    editor.commit_shape((4, 4))  # no begin_shape() call first
    assert editor.path_cells == set()


def test_a_whole_rect_drag_undoes_as_one_step():
    editor = Editor()
    editor.set_tool(EditorTool.RECT)
    editor.begin_shape((0, 0))
    editor.commit_shape((3, 3))
    assert editor.path_cells != set()

    editor.undo()

    assert editor.path_cells == set()


# --- Select tool + copy/paste ---

def test_select_tool_does_not_mutate_path_cells():
    editor = Editor()
    _paint_valid_corridor(editor)
    before = set(editor.path_cells)
    editor.set_tool(EditorTool.SELECT)
    editor.begin_shape((0, 0))
    editor.commit_shape((2, 0))

    assert editor.path_cells == before


def test_select_tool_sets_selection_bounds():
    editor = Editor()
    editor.set_tool(EditorTool.SELECT)
    editor.begin_shape((1, 3))
    editor.commit_shape((4, 5))

    assert editor.selection_bounds == (1, 3, 4, 5)


def test_select_bounds_are_normalized_regardless_of_drag_direction():
    editor = Editor()
    editor.set_tool(EditorTool.SELECT)
    editor.begin_shape((4, 5))  # dragging from bottom-right to top-left
    editor.commit_shape((1, 3))

    assert editor.selection_bounds == (1, 3, 4, 5)


def test_copy_selection_captures_relative_offsets():
    editor = Editor()
    _paint_corridor(editor, [(2, 2), (3, 2), (4, 2)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((2, 2)))
    editor.select_region((2, 2), (4, 2))

    editor.copy_selection()

    assert editor.clipboard["path"] == {(0, 0), (1, 0), (2, 0)}
    assert editor.clipboard["spawn"] == {(0, 0)}
    assert editor.clipboard["goal"] == frozenset()


def test_copy_selection_with_nothing_selected_is_a_no_op():
    editor = Editor()
    editor.copy_selection()
    assert editor.clipboard is None


def test_copy_selection_excludes_cells_outside_the_bounds():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0), (2, 0), (3, 0)])
    editor.select_region((0, 0), (1, 0))  # only the first 2 cells

    editor.copy_selection()

    assert editor.clipboard["path"] == {(0, 0), (1, 0)}


def test_paste_clipboard_stamps_at_a_new_anchor_additively():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0)])
    editor.select_region((0, 0), (1, 0))
    editor.copy_selection()

    editor.paste_clipboard((10, 10))

    assert (10, 10) in editor.path_cells
    assert (11, 10) in editor.path_cells
    assert (0, 0) in editor.path_cells  # original untouched -- additive, not a move


def test_paste_clipboard_includes_a_copied_spawn_marker():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0)])
    editor.set_tool(EditorTool.SPAWN)
    editor.paint_at(*cell_center_px((0, 0)))
    editor.select_region((0, 0), (1, 0))
    editor.copy_selection()

    editor.paste_clipboard((10, 10))

    assert (10, 10) in editor.spawn_cells


def test_pasted_spawn_has_no_wave_data_attached():
    editor = Editor()
    _paint_valid_corridor(editor)  # spawn at (0, 0) already has a grunt in wave 1
    editor.select_region((0, 0), (0, 0))
    editor.copy_selection()

    editor.paste_clipboard((10, 10))

    assert editor.wave_specs[0].get((10, 10)) is None


def test_paste_with_empty_clipboard_is_a_no_op():
    editor = Editor()
    before = set(editor.path_cells)
    editor.paste_clipboard((5, 5))
    assert editor.path_cells == before


def test_paste_is_undoable_as_one_step():
    editor = Editor()
    _paint_corridor(editor, [(0, 0), (1, 0)])
    editor.select_region((0, 0), (1, 0))
    editor.copy_selection()
    editor.paste_clipboard((10, 10))
    assert (10, 10) in editor.path_cells

    editor.undo()

    assert (10, 10) not in editor.path_cells
