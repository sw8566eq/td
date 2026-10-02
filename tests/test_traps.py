"""Path traps -- towers with PLACEMENT "path" (Spike Trap, Tar Pit): built on
a whole path tile instead of beside the path, snapped to that tile, and
fired through the ordinary projectile pipeline."""

import pygame
import pytest
from conftest import start_first_floor

from entities.enemy import FlyingEnemy, GruntEnemy
from entities.tower import TOWER_TYPES, SpikeTrapTower, TarPitTower

TRAPS = [name for name, cls in TOWER_TYPES.items() if cls.PLACEMENT == "path"]


def _path_tile(game):
    return min(game.grid.path_cells)


def _ground_tile(game):
    for row in range(game.grid.rows):
        for col in range(game.grid.cols):
            if not game.grid.is_path(col, row) and not game.grid.is_blocked(col, row):
                return col, row
    raise AssertionError("no ground tile")


def _tile_center(game, tile):
    return game.grid.tile_to_pixel_center(*tile)


def _select(game, name):
    if name not in game.active_run.unlocked_towers:
        game.active_run.unlocked_towers.append(name)
        game._rebuild_button_rects()
    game.selected_tower_name = name
    game.economy.gold = 1000


def test_both_traps_are_registered_path_towers():
    assert set(TRAPS) == {"spike_trap", "tar_pit"}
    assert all(not TOWER_TYPES[name].can_target_flying for name in TRAPS)


@pytest.mark.parametrize("name", TRAPS)
def test_a_trap_builds_on_the_path_snapped_to_its_tile(game, name):
    start_first_floor(game, seed=1)
    _select(game, name)
    tile = _path_tile(game)
    center = _tile_center(game, tile)
    off_center = (center.x + 20, center.y - 20)  # anywhere on the tile snaps to it
    anchor = game.placement_anchor_at(*off_center, TOWER_TYPES[name])
    spt = game.grid.subtiles_per_tile
    assert anchor == (tile[0] * spt, tile[1] * spt)
    assert game.try_place_tower(*anchor)
    trap = game.towers[-1]
    assert trap.pos == center and trap.footprint_subtiles == spt
    assert not game.try_place_tower(*anchor)  # occupied now


@pytest.mark.parametrize("name", TRAPS)
def test_a_trap_cannot_be_built_off_the_path_and_a_tower_cannot_be_built_on_it(game, name):
    start_first_floor(game, seed=1)
    _select(game, name)
    ground = _tile_center(game, _ground_tile(game))
    assert not game.try_place_tower(*game.placement_anchor_at(*ground, TOWER_TYPES[name]))
    _select(game, "basic")
    path = _tile_center(game, _path_tile(game))
    assert not game.try_place_tower(*game.placement_anchor_at(*path, TOWER_TYPES["basic"]))


def test_traps_ignore_footprint_shrinking_relics(game, monkeypatch):
    start_first_floor(game, seed=1)
    monkeypatch.setattr(game, "_current_footprint_subtiles", lambda: 1)
    assert game._footprint_for(SpikeTrapTower) == game.grid.subtiles_per_tile
    assert game._footprint_for(TOWER_TYPES["basic"]) == 1


def test_spike_trap_splashes_ground_enemies_and_tar_pit_slows_them():
    route = [pygame.Vector2(0, 0), pygame.Vector2(500, 0)]
    grunt = GruntEnemy(route, wave_number=1)
    spike = SpikeTrapTower(0, 0, (0, 0))
    shot = spike.create_projectile(grunt)
    assert shot.splash_radius == spike.splash_radius
    tar = TarPitTower(0, 0, (0, 0))
    assert tar.create_projectile(grunt).slow_effect == (tar.slow_factor, tar.slow_duration)
    flyer = FlyingEnemy(route, wave_number=1)
    assert spike.acquire_target([flyer]) is None


def test_trap_placement_preview_renders(game):
    from conftest import clear_mouse_mock, mock_mouse_pos

    start_first_floor(game, seed=1)
    _select(game, "tar_pit")
    try:
        mock_mouse_pos(tuple(_tile_center(game, _path_tile(game))))
        game.render()
    finally:
        clear_mouse_mock()


def test_a_saved_trap_resumes_on_its_tile(game):
    from persistence import save_state

    start_first_floor(game, seed=1)
    _select(game, "spike_trap")
    tile = _path_tile(game)
    assert game.try_place_tower(*game.placement_anchor_at(*_tile_center(game, tile), SpikeTrapTower))
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    trap = game.towers[0]
    assert isinstance(trap, SpikeTrapTower) and trap.pos == _tile_center(game, tile)
