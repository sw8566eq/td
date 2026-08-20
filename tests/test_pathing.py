import random

import pytest

import pathing
from pathing import PathTopology, RoutingError, junctions_of, sample_route, validate_topology


# --- path_cells_from_corners ---

def test_path_cells_from_corners_include_every_corner():
    corners = [(0, 4), (4, 4), (4, 1)]
    cells = pathing.path_cells_from_corners(corners)
    for corner in corners:
        assert corner in cells


def test_path_cells_from_corners_include_the_full_segment_between_corners():
    cells = pathing.path_cells_from_corners([(0, 4), (4, 4), (4, 1)])
    for col in range(0, 5):
        assert (col, 4) in cells
    for row in range(1, 5):
        assert (4, row) in cells


def test_diagonal_corners_are_rejected():
    with pytest.raises(ValueError):
        pathing.path_cells_from_corners([(0, 0), (1, 1)])


# --- PathTopology: neighbor/junction detection ---

def test_topology_neighbors_are_restricted_to_path_cells():
    # A plus-shaped path centered on (1, 1), with an extra unconnected
    # cell (5, 5) that should never show up as anyone's neighbor.
    path_cells = {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (5, 5)}
    topo = PathTopology(path_cells, spawn_cells=[(1, 0)], goal_cells=[(1, 2)])
    assert set(topo.neighbors[(1, 1)]) == {(1, 0), (0, 1), (2, 1), (1, 2)}
    assert topo.neighbors[(5, 5)] == []


def test_junctions_are_auto_detected_from_degree_three_or_more():
    # Same plus shape: the center cell has 4 path-neighbors, everything
    # else has 1.
    path_cells = {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)}
    topo = PathTopology(path_cells, spawn_cells=[(1, 0)], goal_cells=[(1, 2)])
    assert topo.junctions == frozenset({(1, 1)})


def test_a_simple_corridor_has_no_junctions():
    path_cells = {(0, 0), (1, 0), (2, 0), (3, 0)}
    topo = PathTopology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(3, 0)])
    assert topo.junctions == frozenset()


def test_junctions_of_needs_no_spawn_or_goal_and_works_on_a_mid_edit_path():
    # A plus shape with a dangling, not-yet-connected stub -- exactly the
    # kind of incomplete/invalid-so-far state the editor has mid-paint,
    # before any spawn or goal has been placed at all.
    path_cells = {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2), (10, 10)}
    assert junctions_of(path_cells) == frozenset({(1, 1)})


# --- validate_topology ---

def _corridor(length=4, row=0):
    return frozenset((col, row) for col in range(length))


def test_a_simple_corridor_is_valid():
    path_cells = _corridor()
    assert validate_topology(path_cells, [(0, 0)], [(3, 0)], cols=15, rows=9) == []


def test_a_branch_splitting_toward_two_goals_is_valid():
    # (0,0)-(1,0)-(2,0) branches at (2,0) into (2,1) and (3,0), each a goal.
    path_cells = {(0, 0), (1, 0), (2, 0), (2, 1), (3, 0)}
    problems = validate_topology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(2, 1), (3, 0)], cols=15, rows=9)
    assert problems == []


def test_two_spawns_merging_toward_one_goal_is_valid():
    # (0,0) and (0,2) both feed into (1,1), which continues to goal (2,1).
    path_cells = {(0, 0), (0, 1), (0, 2), (1, 1), (2, 1)}
    problems = validate_topology(path_cells, spawn_cells=[(0, 0), (0, 2)], goal_cells=[(2, 1)], cols=15, rows=9)
    assert problems == []


def test_a_closed_loop_is_rejected():
    # A 2x2 square loop (1,0)-(2,0)-(2,1)-(1,1)-(1,0), with a spawn cell
    # (0,0) hanging off it and the goal on the loop itself.
    path_cells = {(0, 0), (1, 0), (2, 0), (2, 1), (1, 1)}
    problems = validate_topology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(2, 1)], cols=15, rows=9)
    assert problems
    assert any("loop" in p for p in problems)


def test_a_branch_that_reconnects_downstream_is_a_loop_and_is_rejected():
    # Spawn (0,0) splits into a top lane (0,0)-(1,0)-(2,0) and a bottom
    # lane (0,0)-(0,1)-(1,1)-(2,1) that rejoins the top lane at (2,0)-(2,1)
    # before continuing to the goal -- a diamond, which is a cycle in the
    # undirected sense even though each half looks like an innocuous
    # branch on its own.
    path_cells = {(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (3, 0)}
    problems = validate_topology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(3, 0)], cols=15, rows=9)
    assert any("loop" in p for p in problems)


def test_a_disconnected_stub_is_rejected():
    path_cells = _corridor() | {(10, 5)}  # an island nowhere near the spawn
    problems = validate_topology(path_cells, [(0, 0)], [(3, 0)], cols=15, rows=9)
    assert any("connected to any spawn" in p for p in problems)


def test_a_dead_end_branch_that_never_reaches_a_goal_is_rejected():
    # Branch at (2,0): one arm reaches the goal at (3,0), the other arm
    # (2,1) dangles with nothing at the end of it.
    path_cells = {(0, 0), (1, 0), (2, 0), (3, 0), (2, 1)}
    problems = validate_topology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(3, 0)], cols=15, rows=9)
    assert any("dead end" in p for p in problems)


def test_out_of_bounds_cells_are_rejected():
    path_cells = {(0, 0), (1, 0), (-1, 0)}
    problems = validate_topology(path_cells, spawn_cells=[(-1, 0)], goal_cells=[(1, 0)], cols=15, rows=9)
    assert any("out of bounds" in p for p in problems)


def test_missing_spawn_is_rejected():
    path_cells = _corridor()
    assert any("spawn" in p for p in validate_topology(path_cells, [], [(3, 0)], cols=15, rows=9))


def test_missing_goal_is_rejected():
    path_cells = _corridor()
    assert any("goal" in p for p in validate_topology(path_cells, [(0, 0)], [], cols=15, rows=9))


def test_spawn_and_goal_on_the_same_cell_is_rejected():
    path_cells = _corridor()
    problems = validate_topology(path_cells, [(0, 0)], [(0, 0)], cols=15, rows=9)
    assert any("both spawn and goal" in p for p in problems)


def test_spawn_not_on_the_path_is_rejected():
    path_cells = _corridor()
    problems = validate_topology(path_cells, [(99, 99)], [(3, 0)], cols=15, rows=9)
    assert any("must be on the path" in p for p in problems)


def test_goal_not_on_the_path_is_rejected():
    path_cells = _corridor()
    problems = validate_topology(path_cells, [(0, 0)], [(99, 99)], cols=15, rows=9)
    assert any("must be on the path" in p for p in problems)


# --- sample_route ---

def test_sample_route_along_a_corridor_walks_every_cell_in_order():
    path_cells = _corridor()
    topo = PathTopology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(3, 0)])
    route = sample_route(topo, (0, 0), branch_weights={}, rng=random.Random(0))
    assert route == [(0, 0), (1, 0), (2, 0), (3, 0)]


def test_sample_route_stops_at_the_first_goal_reached():
    # Goal is placed mid-corridor -- the route must not walk past it.
    path_cells = _corridor()
    topo = PathTopology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(2, 0)])
    route = sample_route(topo, (0, 0), branch_weights={}, rng=random.Random(0))
    assert route == [(0, 0), (1, 0), (2, 0)]


def test_sample_route_never_steps_back_the_way_it_came():
    # At the junction (1,1), the only valid forward moves are away from
    # (1,0) (where we just came from) -- confirm we never see (1,0) twice.
    path_cells = {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)}
    topo = PathTopology(path_cells, spawn_cells=[(1, 0)], goal_cells=[(1, 2)])
    route = sample_route(topo, (1, 0), branch_weights={}, rng=random.Random(0))
    assert route.count((1, 0)) == 1
    assert route[-1] == (1, 2)


def test_sample_route_respects_branch_weights_deterministically():
    # A branch at (1,0) toward two goals; a weight of 0 on one edge should
    # never be chosen regardless of RNG seed.
    path_cells = {(0, 0), (1, 0), (2, 0), (1, 1)}
    topo = PathTopology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(2, 0), (1, 1)])
    weights = {((1, 0), (1, 1)): 0.0, ((1, 0), (2, 0)): 1.0}
    for seed in range(20):
        route = sample_route(topo, (0, 0), branch_weights=weights, rng=random.Random(seed))
        assert route[-1] == (2, 0)


def test_sample_route_never_wanders_into_a_different_spawns_dead_branch():
    # Two spawns, (0, 0) and (0, 2), merge at junction (0, 1) before a
    # single shared run to goal (1, 1). A route starting at either spawn
    # must go straight to the goal -- it must never step from the
    # junction toward the *other* spawn, which is a dead end for it.
    path_cells = {(0, 0), (0, 1), (0, 2), (1, 1)}
    topo = PathTopology(path_cells, spawn_cells=[(0, 0), (0, 2)], goal_cells=[(1, 1)])
    for spawn in [(0, 0), (0, 2)]:
        other_spawn = (0, 2) if spawn == (0, 0) else (0, 0)
        for seed in range(20):
            route = sample_route(topo, spawn, branch_weights={}, rng=random.Random(seed))
            assert route[-1] == (1, 1)
            assert other_spawn not in route


def test_sample_route_raises_if_it_exceeds_its_step_budget():
    # A rigged topology: real neighbors for a 5-cell corridor (so
    # candidates are always found -- this is *not* the dead-end case),
    # but path_cells artificially shrunk after construction so the step
    # budget (len(topology.path_cells) + 1) runs out before the walk
    # actually reaches the goal at the far end. Exercises the final
    # fallback raise, distinct from the mid-walk "no forward move" one.
    path_cells = _corridor(length=5)
    topo = PathTopology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(4, 0)])
    topo.path_cells = frozenset({(0, 0)})
    with pytest.raises(RoutingError):
        sample_route(topo, (0, 0), branch_weights={}, rng=random.Random(0))


def test_sample_route_raises_instead_of_looping_forever_on_a_dead_end():
    # An unvalidated topology with a genuine dead end (no goal reachable)
    # must fail loudly rather than hang.
    path_cells = {(0, 0), (1, 0), (2, 0)}
    topo = PathTopology(path_cells, spawn_cells=[(0, 0)], goal_cells=[(99, 99)])
    with pytest.raises(RoutingError):
        sample_route(topo, (0, 0), branch_weights={}, rng=random.Random(0))
