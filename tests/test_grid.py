from grid import Grid

WAYPOINTS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]
N = 8  # default subtiles_per_tile


def make_grid(**kwargs):
    return Grid(cols=15, rows=9, tile_size=64, waypoints_tiles=WAYPOINTS, **kwargs)


def test_path_cells_include_every_waypoint():
    grid = make_grid()
    for cell in WAYPOINTS:
        assert grid.is_path(*cell)


def test_path_cells_include_the_full_segment_between_waypoints():
    grid = make_grid()
    # Segment (0,4) -> (4,4) should cover every column in between at row 4.
    for col in range(0, 5):
        assert grid.is_path(col, 4)
    # Segment (4,4) -> (4,1) should cover every row in between at col 4.
    for row in range(1, 5):
        assert grid.is_path(4, row)


def test_non_path_cell_is_buildable():
    grid = make_grid()
    assert not grid.is_path(0, 0)
    assert grid.is_buildable(0, 0)


def test_path_cell_is_not_buildable():
    grid = make_grid()
    # Coarse tile (0, 4) is on the path -- its footprint anchor is (0*N, 4*N).
    assert not grid.is_buildable(0, 4 * N)


def test_out_of_bounds_cell_is_not_buildable():
    grid = make_grid()
    assert not grid.is_buildable(-1, 0)
    assert not grid.is_buildable(0, -1)
    assert not grid.is_buildable(grid.sub_cols, 0)
    assert not grid.is_buildable(0, grid.sub_rows)


def test_blocked_cell_is_not_buildable():
    grid = make_grid(blocked_cells=frozenset({(2, 2)}))
    assert grid.is_blocked(2, 2)
    assert not grid.is_buildable(2 * N, 2 * N)


def test_occupied_cell_is_not_buildable():
    grid = make_grid()
    assert grid.is_buildable(0, 0)
    grid.occupy(0, 0, tower="fake-tower")
    assert grid.is_occupied(0, 0)
    assert not grid.is_buildable(0, 0)


def test_get_tower_returns_the_occupying_tower_or_none():
    grid = make_grid()
    assert grid.get_tower(0, 0) is None
    grid.occupy(0, 0, tower="fake-tower")
    assert grid.get_tower(0, 0) == "fake-tower"


def test_pixel_to_tile_and_back_round_trip():
    grid = make_grid()
    for col, row in [(0, 0), (3, 5), (14, 8)]:
        center = grid.tile_to_pixel_center(col, row)
        assert grid.pixel_to_tile(center.x, center.y) == (col, row)


def test_diagonal_waypoints_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        Grid(cols=15, rows=9, tile_size=64, waypoints_tiles=[(0, 0), (1, 1)])


def test_tile_size_not_divisible_by_subtiles_per_tile_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        Grid(cols=15, rows=9, tile_size=64, waypoints_tiles=WAYPOINTS, subtiles_per_tile=5)


# --- Subtile placement ---

def test_placement_anchor_centers_on_a_tiles_pixel_center():
    grid = make_grid()
    for col, row in [(0, 0), (3, 5), (14, 8)]:
        center = grid.tile_to_pixel_center(col, row)
        assert grid.placement_anchor(center.x, center.y) == (col * N, row * N)


def test_placement_anchor_is_not_clamped_near_the_edge():
    grid = make_grid()
    # Hovering right at the top-left corner pixel centers a footprint that
    # would hang off the top/left edge -- the anchor reflects that (goes
    # negative) rather than being pulled back on-grid.
    anchor_col, anchor_row = grid.placement_anchor(0, 0)
    assert anchor_col < 0
    assert anchor_row < 0
    assert not grid.is_buildable(anchor_col, anchor_row)


def test_is_buildable_rejects_a_footprint_straddling_the_path():
    grid = make_grid()
    # Tile (5, 4) is grass, but its left neighbor tile (4, 4) is on the
    # path. An anchor offset a few subtiles left of tile (5, 4)'s own
    # anchor pulls part of the footprint onto the path tile.
    home_anchor_col, home_anchor_row = 5 * N, 4 * N
    assert grid.is_buildable(home_anchor_col, home_anchor_row)
    straddling_anchor_col = home_anchor_col - N // 2
    assert not grid.is_buildable(straddling_anchor_col, home_anchor_row)


def test_overlapping_footprints_collide_even_when_anchors_differ():
    grid = make_grid()
    grid.occupy(0, 0, tower="fake-tower")
    # Offset by fewer than N subtiles in both axes -> footprints overlap.
    assert not grid.is_buildable(N - 1, N - 1)


def test_non_overlapping_footprints_do_not_collide():
    grid = make_grid()
    grid.occupy(0, 0, tower="fake-tower")
    # Offset by exactly N subtiles in x -> footprints are adjacent, not
    # overlapping.
    assert grid.is_buildable(N, 0)
