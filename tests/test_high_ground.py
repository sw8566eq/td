"""High ground: Level.high_ground_cells, the Grid footprint rule, the +range
tower bonus (and the Watchtowers relic), drawing, the map editor brush, and
persistence. See docs/agents/grid-paths.md "High ground"."""

import json

import pygame
import pytest
from conftest import clear_mouse_mock, mock_mouse_pos, start_first_floor

from core.editor import Editor, EditorTool
from core.game import GameState
from persistence import persistence, save_state
from presentation import ui
from presentation.assets import AssetManager
from support import settings
from world.grid import Grid
from world.levels import LEVELS, Level

N = settings.SUBTILES_PER_TILE
HIGH = frozenset({(5, 2), (6, 2)})


def make_level(high_ground_cells=HIGH, **kwargs):
    path = frozenset((col, 0) for col in range(settings.GRID_COLS))
    return Level(
        id="hg", name="High Ground Test", path_cells=path,
        spawn_cells=((0, 0),), goal_cells=((settings.GRID_COLS - 1, 0),),
        wave_specs=[{(0, 0): {"grunt": 2}}], high_ground_cells=high_ground_cells, **kwargs,
    )


def make_grid(high_ground_cells=HIGH):
    level = make_level(high_ground_cells)
    return Grid(settings.GRID_COLS, settings.GRID_ROWS, settings.TILE_SIZE, level.path_cells,
                level.spawn_cells, level.goal_cells, high_ground_cells=level.high_ground_cells)


def load(game, level=None):
    game.load_custom_level(level or make_level())
    game.state = GameState.PLAYING
    game.economy.gold = 10_000
    return game


def place(game, name, cell, offset=(0, 0)):
    game.selected_tower_name = name
    anchor = (cell[0] * N + offset[0], cell[1] * N + offset[1])
    assert game.try_place_tower(*anchor)
    return game.towers[-1]


# --- Level ---


def test_level_high_ground_defaults_to_empty():
    level = make_level(frozenset())
    assert level.high_ground_cells == frozenset()
    assert LEVELS[1].high_ground_cells == frozenset()


def test_level_coerces_high_ground_to_a_frozenset():
    assert make_level({(5, 2)}).high_ground_cells == frozenset({(5, 2)})


@pytest.mark.parametrize("cell", [(3, 0), (-1, 2), (settings.GRID_COLS, 2), (1, 99), (1.0, 2), (True, 2),
                                  (1, 2, 3), "ab"])
def test_level_rejects_bad_or_on_path_high_ground(cell):
    with pytest.raises(ValueError):
        make_level(frozenset({cell}))


def test_several_built_in_levels_have_high_ground_beside_the_path():
    with_high_ground = [level for level in LEVELS.values() if level.high_ground_cells]
    assert 8 <= len(with_high_ground) < len(LEVELS)
    for level in with_high_ground:
        assert 2 <= len(level.high_ground_cells) <= 6
        for col, row in level.high_ground_cells:
            assert (col, row) not in level.path_cells
            assert (col, row) not in level.blocked_cells
            near = {(col + dc, row + dr) for dc in range(-2, 3) for dr in range(-2, 3)}
            assert near & level.path_cells, f"level {level.id} high ground {(col, row)} is far from the path"


# --- Grid ---


def test_high_ground_fraction_counts_footprint_subtiles():
    grid = make_grid(frozenset({(5, 2)}))
    assert grid.is_high_ground(5, 2) and not grid.is_high_ground(6, 2)
    assert grid.high_ground_fraction(5 * N, 2 * N) == 1.0
    assert grid.high_ground_fraction(5 * N + N // 2, 2 * N) == 0.5  # straddles (5,2)/(6,2)
    assert grid.high_ground_fraction(5 * N + N // 2, 2 * N + N // 2) == 0.25
    assert grid.high_ground_fraction(8 * N, 4 * N) == 0.0
    assert grid.high_ground_fraction(5 * N, 2 * N, footprint_subtiles=0) == 0.0


def test_is_on_high_ground_needs_half_the_footprint():
    grid = make_grid(frozenset({(5, 2)}))
    assert grid.is_on_high_ground(5 * N, 2 * N)
    assert grid.is_on_high_ground(5 * N + N // 2, 2 * N)
    assert not grid.is_on_high_ground(5 * N + N // 2, 2 * N + N // 2)
    assert not make_grid(frozenset()).is_on_high_ground(5 * N, 2 * N)


def test_high_ground_draws_raised_with_a_lit_edge_and_a_shadow(tmp_path):
    assets = AssetManager(asset_root=str(tmp_path))
    raised, flat = make_grid(), make_grid(frozenset())
    size = (settings.GRID_COLS * settings.TILE_SIZE, settings.GRID_ROWS * settings.TILE_SIZE)
    surfaces = [pygame.Surface(size), pygame.Surface(size)]
    raised.draw(surfaces[0], assets)
    flat.draw(surfaces[1], assets)
    t = settings.TILE_SIZE
    x0, y0 = 5 * t, 2 * t
    assert surfaces[0].get_at((x0, y0 + t // 2))[:3] == settings.COLOR_HIGH_GROUND_EDGE  # left edge
    assert surfaces[0].get_at((x0 + t + t - 1, y0 + t // 2))[:3] == settings.COLOR_HIGH_GROUND_SHADOW  # right edge
    # (5,2) and (6,2) form one plateau: no shadow between them.
    assert surfaces[0].get_at((x0 + t - 1, y0 + t // 2))[:3] != settings.COLOR_HIGH_GROUND_SHADOW
    center = (x0 + t // 2 + 3, y0 + t // 2 + 3)
    assert surfaces[0].get_at(center) != surfaces[1].get_at(center)  # the wash lightens it


def test_thumbnail_shows_high_ground():
    level = make_level()
    thumb = ui.build_level_thumbnail(level, settings.GRID_COLS * 10, settings.GRID_ROWS * 10)
    assert thumb.get_at((55, 25))[:3] == settings.COLOR_THUMBNAIL_HIGH_GROUND
    assert thumb.get_at((95, 55))[:3] == settings.COLOR_THUMBNAIL_GROUND


# --- Tower bonus ---


def test_a_tower_on_high_ground_gets_the_range_bonus(game):
    load(game)
    high = place(game, "basic", (5, 2))
    low = place(game, "basic", (9, 4))
    assert high.on_high_ground and high.high_ground_range_bonus == settings.HIGH_GROUND_RANGE_BONUS
    assert high.effective_range() == pytest.approx(high.range * (1 + settings.HIGH_GROUND_RANGE_BONUS))
    assert not low.on_high_ground and low.effective_range() == pytest.approx(low.range)
    assert high.high_ground_damage_bonus == 0.0  # no run, no Watchtowers


def test_the_bonus_follows_the_half_footprint_rule(game):
    load(game, make_level(frozenset({(5, 2)})))
    half = place(game, "basic", (5, 2), offset=(N // 2, 0))
    quarter = place(game, "basic", (5, 3), offset=(N // 2, N // 2))
    assert half.on_high_ground
    assert not quarter.on_high_ground


def test_the_bonus_stacks_additively_with_a_range_relic(game):
    load(game)
    tower = place(game, "basic", (5, 2))
    tower.relic_range_bonus_multiplier = 1.15
    assert tower.effective_range() == pytest.approx(tower.range * (1 + 0.15 + settings.HIGH_GROUND_RANGE_BONUS))


def test_a_support_tower_on_high_ground_broadcasts_further(game):
    load(game)
    support = place(game, "support", (5, 2))
    assert support.relic_adjusted_range() == pytest.approx(support.range * (1 + settings.HIGH_GROUND_RANGE_BONUS))


def test_a_path_trap_never_gets_the_bonus(game, monkeypatch):
    load(game)
    monkeypatch.setattr(game.grid, "is_on_high_ground", lambda *args, **kwargs: True)
    trap = place(game, "spike_trap", (3, 0))
    assert not trap.on_high_ground and trap.high_ground_range_bonus == 0.0
    assert place(game, "basic", (9, 4)).on_high_ground  # the stub itself does fire for ground towers


def test_placement_preview_probe_shows_the_boosted_range(game):
    load(game)
    from entities.tower import BasicTower

    probe = game.preview_tower(BasicTower, 5 * N, 2 * N)
    assert probe.effective_range() == pytest.approx(BasicTower.range * (1 + settings.HIGH_GROUND_RANGE_BONUS))
    assert game.preview_tower(BasicTower, 9 * N, 4 * N).effective_range() == pytest.approx(BasicTower.range)
    game.selected_tower_name = "basic"
    try:
        mock_mouse_pos((5 * settings.TILE_SIZE + 32, 2 * settings.TILE_SIZE + 32))
        game.render()
    finally:
        clear_mouse_mock()


def test_stats_panel_names_high_ground_and_tags_the_range(game):
    load(game)
    high = place(game, "basic", (5, 2))
    assert ui.resonance_line(high) == f"High ground (+{round(settings.HIGH_GROUND_RANGE_BONUS * 100)}% range)"
    assert ui.bonus_tag(high.range, high.effective_range()) == "+20%"
    high.resonance_keys = ["superconductor"] if "superconductor" in ui.RESONANCES else list(ui.RESONANCES)[:1]
    assert ui.resonance_line(high).startswith("High ground; ")
    low = place(game, "basic", (9, 4))
    assert ui.resonance_line(low) is None
    game.selected_tower = high
    game.render()


def test_moving_a_tower_on_or_off_high_ground_updates_the_bonus(game, monkeypatch):
    load(game)
    tower = place(game, "basic", (9, 4))
    monkeypatch.setattr(game, "can_move_towers", lambda: True)
    assert game.move_preview_range(tower, 5 * N, 2 * N) == pytest.approx(
        tower.range * (1 + settings.HIGH_GROUND_RANGE_BONUS))
    assert game.try_move_tower(tower, 5 * N, 2 * N)
    assert tower.on_high_ground
    assert game.move_preview_range(tower, 9 * N, 5 * N) == pytest.approx(tower.range)
    assert game.try_move_tower(tower, 9 * N, 5 * N)
    assert not tower.on_high_ground and tower.effective_range() == pytest.approx(tower.range)


def test_watchtowers_adds_damage_only_on_high_ground(game):
    run = start_first_floor(game, seed=1)
    run.relics.append("watchtowers")
    game._load_level_object(make_level(), active_run=run)
    game.state = GameState.PLAYING
    game.economy.gold = 10_000
    name = run.unlocked_towers[0]
    high = place(game, name, (5, 2))
    low = place(game, name, (9, 4))
    assert high.high_ground_damage_bonus == pytest.approx(0.15)
    assert low.high_ground_damage_bonus == 0.0
    assert high.effective_damage() > low.effective_damage()


# --- Editor ---


def test_editor_high_ground_brush_paints_then_erases_by_first_cell():
    editor = Editor()
    editor.set_tool(EditorTool.HIGH_GROUND)
    editor._apply_tool((3, 3))
    editor._apply_tool((4, 3))
    editor.end_stroke()
    assert editor.high_ground_cells == {(3, 3), (4, 3)}
    editor._apply_tool((3, 3))  # starts on high ground: this stroke lowers
    editor._apply_tool((5, 3))  # already low -- stays low
    editor.end_stroke()
    assert editor.high_ground_cells == {(4, 3)}


def test_editor_high_ground_skips_the_path_and_is_flattened_by_it():
    editor = Editor()
    editor._apply_tool((2, 2))  # Paint path
    editor.end_stroke()
    editor.set_tool(EditorTool.HIGH_GROUND)
    editor._apply_tool((2, 2))
    editor._apply_tool((3, 2))
    editor.end_stroke()
    assert editor.high_ground_cells == {(3, 2)}
    editor.set_tool(EditorTool.PAINT)
    editor._apply_tool((3, 2))
    editor.end_stroke()
    assert editor.high_ground_cells == set()


def test_editor_erase_clears_high_ground_and_undo_redo_restore_it():
    editor = Editor()
    editor.set_tool(EditorTool.HIGH_GROUND)
    editor._apply_tool((6, 6))
    editor.end_stroke()
    editor.set_tool(EditorTool.ERASE)
    editor._apply_tool((6, 6))
    editor.end_stroke()
    assert editor.high_ground_cells == set()
    assert editor.undo()
    assert editor.high_ground_cells == {(6, 6)}
    assert editor.undo()
    assert editor.high_ground_cells == set()
    assert editor.redo()
    assert editor.high_ground_cells == {(6, 6)}


def test_editor_copy_paste_carries_high_ground_and_path_wins():
    editor = Editor()
    editor.set_tool(EditorTool.HIGH_GROUND)
    editor._apply_tool((1, 1))
    editor.end_stroke()
    editor.select_region((0, 0), (1, 1))
    editor.copy_selection()
    assert editor.clipboard["high_ground"] == frozenset({(1, 1)})
    assert editor.paste_clipboard((5, 5))
    assert (6, 6) in editor.high_ground_cells
    editor.path_cells.add((11, 11 - 3))  # a path cell where the next paste's high ground lands
    assert editor.paste_clipboard((10, 7))
    assert (11, 8) not in editor.high_ground_cells


def test_editor_level_round_trip_and_clear_keep_high_ground_consistent():
    level = make_level()
    editor = Editor()
    editor.load_level(level)
    assert editor.high_ground_cells == set(HIGH)
    editor.wave_specs = [{(0, 0): {"grunt": 1}}]
    editor.validate()
    assert editor.to_level().high_ground_cells == HIGH
    editor.clear()
    assert editor.high_ground_cells == set()


def test_editor_screen_and_toolbar_draw_high_ground(game):
    game.state = GameState.EDITOR
    game.editor.load_level(make_level())
    assert "high_ground" in game.editor_tool_rects
    assert ui.EDITOR_TOOL_ORDER[-1] == EditorTool.HIGH_GROUND
    from core.editor import TOOL_ORDER

    assert TOOL_ORDER == ui.EDITOR_TOOL_ORDER
    game.input_handler._handle_editor_click(game.editor_tool_rects["high_ground"].center)
    assert game.editor.active_tool == EditorTool.HIGH_GROUND
    game.render()
    x, y = 5 * settings.TILE_SIZE, 2 * settings.TILE_SIZE + 20
    assert game.screen.get_at((x, y))[:3] == settings.COLOR_HIGH_GROUND_EDGE


# --- Persistence ---


def test_level_json_round_trips_high_ground():
    data = json.loads(json.dumps(persistence.level_to_dict(make_level())))
    assert data["high_ground_cells"] == [[5, 2], [6, 2]]
    assert persistence.level_from_dict(data).high_ground_cells == HIGH


def test_level_json_without_high_ground_still_loads():
    data = persistence.level_to_dict(make_level())
    del data["high_ground_cells"]
    assert persistence.level_from_dict(data).high_ground_cells == frozenset()


def test_custom_level_with_bad_high_ground_is_skipped(tmp_path):
    for name, cells in (("good", [[5, 2]]), ("on_path", [[3, 0]]), ("garbage", [7])):
        data = persistence.level_to_dict(make_level())
        data["name"] = name
        data["high_ground_cells"] = cells
        (tmp_path / f"{name}.json").write_text(json.dumps(data))
    assert [level.name for level in persistence.list_custom_levels(tmp_path)] == ["good"]


def test_a_resumed_fight_keeps_high_ground_and_the_tower_bonus(game):
    load(game)
    place(game, "basic", (5, 2))
    assert game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.level.high_ground_cells == HIGH
    assert game.grid.high_ground_cells == HIGH
    assert game.towers[0].on_high_ground


def test_an_older_save_without_high_ground_still_resumes(game):
    load(game)
    place(game, "basic", (5, 2))
    assert game.save_run()
    data = json.loads(game.save_path.read_text())
    del data["level"]["high_ground_cells"]
    game.save_path.write_text(json.dumps(data))
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.level.high_ground_cells == frozenset()
    assert not game.towers[0].on_high_ground
