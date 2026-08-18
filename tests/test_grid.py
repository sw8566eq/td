from grid import Grid

WAYPOINTS = [(0, 4), (4, 4), (4, 1), (10, 1), (10, 7), (14, 7)]


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
    assert not grid.is_buildable(0, 4)


def test_out_of_bounds_cell_is_not_buildable():
    grid = make_grid()
    assert not grid.is_buildable(-1, 0)
    assert not grid.is_buildable(0, -1)
    assert not grid.is_buildable(15, 0)
    assert not grid.is_buildable(0, 9)


def test_blocked_cell_is_not_buildable():
    grid = make_grid(blocked_cells=frozenset({(2, 2)}))
    assert grid.is_blocked(2, 2)
    assert not grid.is_buildable(2, 2)


def test_occupied_cell_is_not_buildable():
    grid = make_grid()
    assert grid.is_buildable(0, 0)
    grid.occupy(0, 0, tower="fake-tower")
    assert grid.is_occupied(0, 0)
    assert not grid.is_buildable(0, 0)


def test_pixel_to_tile_and_back_round_trip():
    grid = make_grid()
    for col, row in [(0, 0), (3, 5), (14, 8)]:
        center = grid.tile_to_pixel_center(col, row)
        assert grid.pixel_to_tile(center.x, center.y) == (col, row)


def test_diagonal_waypoints_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        Grid(cols=15, rows=9, tile_size=64, waypoints_tiles=[(0, 0), (1, 1)])
