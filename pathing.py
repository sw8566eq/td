"""Path graph logic: turning a set of painted path tiles into a validated
topology, and sampling a concrete route for a spawned enemy to walk.

Pure data/graph logic -- no pygame dependency -- so it's usable from Level
construction (validation), WaveManager (route sampling), and the map editor
(live validation feedback while painting) without any pygame or Level
import cycle.

A painted path is required to be a *forest*: one lane can fan out into
several (a branch), and several spawns can converge onto a shared lane
toward the goal (a merge -- multiple leaves feeding one root, exactly what
a tree already allows), but a lane can never split and later reconnect to
itself downstream -- that specific "diamond" shape is a closed loop in the
underlying undirected adjacency graph, indistinguishable from a full
roundabout. Forbidding it is what makes sample_route() a simple,
always-terminating walk: a tree has exactly one simple path between any two
cells, so there's never a need to backtrack or guess which branch leads to
a dead end.
"""

import random


def neighbors4(cell):
    """The four orthogonally adjacent cells to (col, row)."""
    col, row = cell
    return [(col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)]


def path_cells_from_corners(corners):
    """Walk each axis-aligned segment between consecutive corners and
    collect every tile it passes through. An authoring convenience for
    hand-written levels (see levels.py) -- equivalent to Grid's old
    _compute_path_cells, relocated here so both levels.py and the editor
    can build a path_cells set out of straight runs without going through
    Grid at all."""
    cells = set()
    for (c1, r1), (c2, r2) in zip(corners, corners[1:]):
        if c1 == c2:
            step = 1 if r2 >= r1 else -1
            for r in range(r1, r2 + step, step):
                cells.add((c1, r))
        elif r1 == r2:
            step = 1 if c2 >= c1 else -1
            for c in range(c1, c2 + step, step):
                cells.add((c, r1))
        else:
            raise ValueError(
                f"Corners must form axis-aligned segments: "
                f"{(c1, r1)} -> {(c2, r2)} is diagonal"
            )
    return frozenset(cells)


class TopologyError(ValueError):
    """Raised by PathTopology construction when asked to build on an
    already-known-invalid path -- callers should run validate_topology()
    first and surface its problem list instead of relying on this."""


class RoutingError(RuntimeError):
    """Raised by sample_route() when it can't find a way forward. Should
    be unreachable for any topology that passed validate_topology() --
    seeing this means a validated level's path and its runtime topology
    have drifted out of sync somewhere."""


def junctions_of(path_cells):
    """Cells with 3+ path-neighbors -- a branch or merge point just *is*
    one of these in this model; nothing marks a junction explicitly,
    degree alone determines it. Well-defined for any set of cells,
    including a mid-edit painted set that isn't a valid topology yet, so
    the editor can show junction markers live without needing spawn/goal
    cells or running full validation first."""
    path_cells = frozenset(path_cells)
    return frozenset(
        cell for cell in path_cells
        if sum(1 for n in neighbors4(cell) if n in path_cells) >= 3
    )


class PathTopology:
    """4-adjacency graph over a set of path cells, plus the auto-detected
    junctions (see junctions_of)."""

    def __init__(self, path_cells, spawn_cells, goal_cells):
        self.path_cells = frozenset(path_cells)
        self.spawn_cells = tuple(spawn_cells)
        self.goal_cells = frozenset(goal_cells)
        self.neighbors = {
            cell: [n for n in neighbors4(cell) if n in self.path_cells]
            for cell in self.path_cells
        }
        self.junctions = junctions_of(self.path_cells)
        # For every directed edge (u, v): does continuing forward from v
        # (never stepping back to u) eventually reach a goal? A merge
        # point has one neighbor whose subtree is "just another spawn,
        # with no goal in it" -- that direction must never be a candidate
        # for sample_route to wander into, no matter which spawn a given
        # route actually started from. See _compute_leads_to_goal.
        self.leads_to_goal = _compute_leads_to_goal(self.path_cells, self.neighbors, self.goal_cells)


def _compute_leads_to_goal(path_cells, neighbors, goal_cells):
    """For every directed edge (u -> v) in the (possibly multi-component)
    forest, whether continuing forward from v -- i.e. exploring v's whole
    subtree without ever stepping back to u -- can reach a goal cell.

    One pass per connected component: an iterative DFS from an arbitrary
    root builds a parent tree and a discovery order where every cell
    appears before all of its descendants (an explicit-stack DFS can only
    discover a child while processing its already-popped parent); walking
    that order in reverse is therefore a valid post-order, letting each
    cell's goal count fold into its parent's before the parent is used."""
    leads_to_goal = {}
    visited = set()
    for start in path_cells:
        if start in visited:
            continue
        parent = {start: None}
        order = []
        stack = [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            order.append(node)
            for n in neighbors[node]:
                if n not in visited:
                    visited.add(n)
                    parent[n] = node
                    stack.append(n)

        subtree_goal_count = {node: (1 if node in goal_cells else 0) for node in order}
        for node in reversed(order):
            p = parent[node]
            if p is not None:
                subtree_goal_count[p] += subtree_goal_count[node]
                leads_to_goal[(p, node)] = subtree_goal_count[node] > 0

        total_goals = subtree_goal_count[start]
        for node in order:
            p = parent[node]
            if p is not None:
                # Going from `node` back toward `p` (and from there, into
                # whichever of p's other neighbors keep going forward) can
                # reach a goal exactly when this component has a goal
                # somewhere outside node's own subtree.
                leads_to_goal[(node, p)] = (total_goals - subtree_goal_count[node]) > 0

    return leads_to_goal


def _bfs(neighbors, starts):
    """Every cell reachable from `starts` by walking `neighbors` edges."""
    seen = set(starts)
    queue = list(starts)
    while queue:
        cell = queue.pop()
        for n in neighbors.get(cell, ()):
            if n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


def validate_topology(path_cells, spawn_cells, goal_cells, cols, rows):
    """Return a list of human-readable problems with this path -- an empty
    list means valid. Never raises, even on nonsense input (e.g. an empty
    path_cells) -- this is meant to be called directly against live editor
    state on every paint stroke, not just at Level-construction time."""
    path_cells = frozenset(path_cells)
    spawn_cells = frozenset(spawn_cells)
    goal_cells = frozenset(goal_cells)
    problems = []

    def in_bounds(cell):
        col, row = cell
        return 0 <= col < cols and 0 <= row < rows

    out_of_bounds = sorted(c for c in path_cells | spawn_cells | goal_cells if not in_bounds(c))
    if out_of_bounds:
        problems.append(f"{len(out_of_bounds)} cell(s) out of bounds: {out_of_bounds[:5]}")

    if not spawn_cells:
        problems.append("no spawn point placed")
    if not goal_cells:
        problems.append("no goal point placed")
    if not spawn_cells.issubset(path_cells):
        problems.append("every spawn point must be on the path")
    if not goal_cells.issubset(path_cells):
        problems.append("every goal point must be on the path")
    overlap = sorted(spawn_cells & goal_cells)
    if overlap:
        problems.append(f"a cell can't be both spawn and goal: {overlap}")

    # The graph traversal below assumes spawn/goal are honest path cells --
    # bail out before it if any of the basics above are already broken.
    if problems:
        return problems

    neighbors = {cell: [n for n in neighbors4(cell) if n in path_cells] for cell in path_cells}

    # Cycle check: DFS each connected component with explicit parent
    # tracking -- an edge to an already-visited cell that isn't the parent
    # we just came from closes a loop. (Standard undirected-graph cycle
    # detection; correct with an explicit stack because a node is only
    # ever pushed once in a genuine tree -- it's discovered via its single
    # true parent and nothing else reaches it before that parent does.)
    visited = set()
    has_cycle = False
    for start in path_cells:
        if start in visited:
            continue
        stack = [(start, None)]
        while stack:
            cell, parent = stack.pop()
            if cell in visited:
                has_cycle = True
                continue
            visited.add(cell)
            for n in neighbors[cell]:
                if n != parent:
                    stack.append((n, cell))
    if has_cycle:
        problems.append(
            "path contains a loop -- lanes may fan out or converge from "
            "multiple spawns, but a lane can't split and reconnect to itself"
        )
        return problems  # reachability below assumes a forest; skip once we know it isn't one

    reachable_from_spawn = _bfs(neighbors, spawn_cells)
    unreached = sorted(path_cells - reachable_from_spawn)
    if unreached:
        problems.append(f"{len(unreached)} painted cell(s) aren't connected to any spawn: {unreached[:5]}")

    # Every leaf (a cell with at most one path-neighbor) of the
    # spawn-connected tree must be a spawn or a goal. sample_route() walks
    # forward from a spawn without ever stepping back the way it came, so
    # any other leaf is a branch some enemy will eventually wander into
    # and get stuck at -- unlike an undirected "can this reach a goal at
    # all" check (trivially true for every cell in a connected tree, since
    # you can always walk backward to it), this is the check that actually
    # distinguishes a real dead end from a normal branch or merge.
    dead_ends = sorted(
        cell for cell in reachable_from_spawn
        if len(neighbors[cell]) <= 1 and cell not in spawn_cells and cell not in goal_cells
    )
    if dead_ends:
        problems.append(f"{len(dead_ends)} cell(s) are a dead end that never reaches a goal: {dead_ends[:5]}")

    return problems


def sample_route(topology, spawn_cell, branch_weights, rng=None):
    """Walk forward from spawn_cell to a goal, choosing weighted-randomly
    among genuine branch points (never stepping back the way we came), and
    return the concrete list of cells walked.

    Assumes `topology` already passed validate_topology(): a validated
    topology is a forest where every spawn can reach a goal, so this walk
    is guaranteed to terminate. If it doesn't, that's a RoutingError rather
    than an infinite loop -- a sign validation and topology drifted apart,
    not something for a caller to silently retry."""
    rng = rng or random
    route = [spawn_cell]
    previous = None
    current = spawn_cell
    for _ in range(len(topology.path_cells) + 1):
        if current in topology.goal_cells:
            return route
        # Never step back the way we came, and never step toward a
        # neighbor whose whole forward subtree is goal-free (e.g. another
        # spawn's own branch at a merge point) -- both are equally
        # "not a real forward move" for this walk.
        candidates = [
            n for n in topology.neighbors.get(current, ())
            if n != previous and topology.leads_to_goal.get((current, n), False)
        ]
        if not candidates:
            raise RoutingError(
                f"{current} has no forward move toward a goal -- "
                f"validate_topology() should have caught this"
            )
        if len(candidates) == 1:
            next_cell = candidates[0]
        else:
            weights = [branch_weights.get((current, c), 1.0) for c in candidates]
            next_cell = rng.choices(candidates, weights=weights, k=1)[0]
        route.append(next_cell)
        previous, current = current, next_cell
    raise RoutingError(f"route from {spawn_cell} exceeded the path's cell budget -- topology bug")
