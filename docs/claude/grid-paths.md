# Grid and paths

## Grid has two coordinate systems

`Grid` (`world/grid.py`) tracks the map at two granularities at once:
- **Coarse tile coords** (`col, row`; unit = `TILE_SIZE`, 64px) -- path, blocked cells, and the
  rendered mosaic. Comes straight from a `Level`'s `path_cells`/`spawn_cells`/`goal_cells`/
  `blocked_cells` (see "Paths are a graph, not a route" below).
- **Subtile coords** (`anchor_col, anchor_row`; unit = `SUBTILE_SIZE`, `TILE_SIZE /
  SUBTILES_PER_TILE`) -- tower placement. A tower's footprint is normally one tile's worth of area
  (`SUBTILES_PER_TILE x SUBTILES_PER_TILE` subtiles, currently 8x8) but can be *anchored* at any
  subtile, not just a tile boundary, which is what gives placement finer-than-a-tile precision.
  `SUBTILES_PER_TILE` must evenly divide `TILE_SIZE` (enforced in `Grid.__init__`) so every
  pixel<->subtile conversion is exact integer math.

`is_buildable`/`occupy`/`placement_anchor`/`anchor_to_pixel_center`/`_footprint_subtiles` all take an
optional `footprint_subtiles` (default `None`, meaning a full tile) -- the one hook a Compact
Framework-style relic uses to shrink every tower's footprint for a floor (see
`Game._current_footprint_subtiles`, clamped to `settings.MIN_TOWER_FOOTPRINT_SUBTILES` so a relic
can never collapse it to nothing). `remove(anchor_col, anchor_row)` keeps its original 2-argument
signature regardless -- `occupy()` records what size it actually reserved in
`Grid._footprint_size_by_anchor`, so `remove()` can free exactly that without the caller (or the
tower object itself, which several tests stand in for with a bare placeholder) needing to repeat it.
`Tower` mirrors this as its own `footprint_subtiles` instance attribute (set once at construction by
`Game._construct_tower`, read by `tile_rect()`/`upgrade_badge_center()`/`draw()` in place of the
`settings.TILE_SIZE`/`SUBTILE_SIZE` those methods used to hardcode directly) so a shrunk footprint's
sprite, hit-box, and click target all shrink together rather than the grid and the tower silently
disagreeing about how much space one occupies.

`is_buildable`/`occupy`/`remove`/`is_occupied`/`get_tower` all operate in subtile coords; two
footprints collide if they overlap *at all* (checked against a flat `occupied_subtiles` set), not
just when their anchors match, so finer placement doesn't need anchors to line up on any grid.
`placement_anchor(x, y)` (pixel -> anchor, centered on the cursor) is deliberately **not** clamped
to stay in bounds -- an out-of-grid or edge-hugging anchor is left for `is_buildable` to reject,
rather than silently snapped somewhere the player didn't point at.

## Paths are a graph, not a route

A `Level`'s path (`path_cells`/`spawn_cells`/`goal_cells`) is a set of tiles, not one ordered
waypoint list -- it can branch (one lane fanning out into several) and merge (several spawns
converging on shared lanes toward a goal), same as anything the map editor's freeform brush can
paint. The one restriction (`pathing.validate_topology`) is that it must be a **forest**: a lane
can never split and later reconnect to itself downstream, since that specific "diamond" shape is a
closed loop in the underlying undirected adjacency graph, indistinguishable from a full roundabout.
Forbidding it is what makes `pathing.sample_route` a simple, always-terminating walk -- a tree has
exactly one simple path between any two cells, so a route never needs to backtrack or guess which
branch leads to a dead end. `pathing.PathTopology.leads_to_goal` is what keeps that walk from
wandering into a *different* spawn's own dead-end branch at a merge point -- an early version of
this validated per-cell reachability with an undirected BFS from the goal, which is trivially true
for every cell in a connected tree (you can always walk backward to it) and so never actually
caught anything; the fix was requiring every leaf of the tree to be a spawn or a goal. That leaf
rule alone still admits a component whose only leaves are *spawns* (a lone spawn tile, or a lane
with a spawn at each end) -- no goal anywhere to walk to, so `sample_route` would raise
`RoutingError` on the first spawn -- which is why `validate_topology` also BFSes out from the goals
and rejects any spawn that search never reaches.

`Enemy` itself needs **zero branching logic**: `WaveManager` samples one concrete flat pixel
waypoint list per spawned enemy (`pathing.sample_route`, weighted-random at branch points, default
uniform) and hands it to the same `Enemy.__init__(waypoints_px, wave_number)` as always. All of the
graph complexity lives in `world/pathing.py` and at spawn time, not in movement.

`world/levels.py`'s hand-written levels stay a terse ordered corner list (`pathing.path_cells_from_corners`
walks each axis-aligned segment into the cell set) purely as an authoring convenience; a `Level`
built by the map editor's tile-paint brush builds `path_cells`/`spawn_cells`/`goal_cells` directly,
with no corner list involved. Both end up as the exact same shape -- one representation, not two
parallel formats.
