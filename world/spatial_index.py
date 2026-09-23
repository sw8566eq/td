"""Broad-phase spatial index over one frame's live enemies.

`Tower.acquire_target()` scans every enemy to find the ones in range -- fine
at this game's original scale, but endless mode's design is *unbounded*
enemy growth by intent (see `waves.py`'s `_default_endless_wave`), so
`Game.update()`'s O(towers x enemies) tower-targeting pass is exactly the
place that growth eventually gets felt. `EnemySpatialIndex` narrows that
scan to enemies near enough to plausibly be in range, without changing what
any tower actually targets -- see `EnemySpatialIndex.near()`'s own
docstring for why the result set is still only a *candidate* pool, not a
final answer.

A uniform grid, not a quadtree/k-d tree: the play area is small and
fixed-size (`settings.PLAY_WIDTH` x `settings.SCREEN_HEIGHT`) regardless of
how many enemies are on it, so a flat dict of `(cell_x, cell_y) -> [enemy,
...]` buckets is simpler than a tree and, at this scale, just as fast --
nothing here needs a tree's adaptive depth.

Rebuilt from scratch every frame (`Game.update()`, once, right before the
tower loop) rather than maintained incrementally as enemies move -- enemy
positions change every frame regardless, so an incremental structure would
need to re-bucket most enemies every frame anyway for no less work than a
full rebuild, which is a single O(enemies) pass.
"""

from collections import defaultdict

# ~2 tiles (settings.TILE_SIZE is 64) -- close to a typical tower's own
# range (90-220px across TOWER_TYPES), so a query's cell neighborhood is
# usually a small handful of cells, not the whole board and not one cell
# per enemy either.
CELL_SIZE = 128


class EnemySpatialIndex:
    """Buckets a frame's enemies by grid cell for `near(pos, radius)`.

    Built once per frame from the live `Game.enemies` list -- an enemy
    that's already dead or has already reached the goal is excluded up
    front, mirroring the same exclusion `Tower.acquire_target()`'s own
    candidate filter already applies, so a tower can never be handed a
    stale target through this path that it couldn't have found scanning
    the raw list either. Buckets hold the enemy objects themselves, not
    copies, so an enemy another tower kills earlier in this same frame
    (`Game.update()`'s tower loop runs before dead enemies are pruned) is
    still reflected immediately -- `is_dead` is read fresh off the shared
    object, not snapshotted at index-build time.
    """

    def __init__(self, enemies, cell_size=CELL_SIZE):
        self.cell_size = cell_size
        self._buckets = defaultdict(list)
        for enemy in enemies:
            if enemy.is_dead or enemy.reached_goal:
                continue
            self._buckets[self._cell(enemy.pos)].append(enemy)

    def _cell(self, pos):
        return (int(pos.x // self.cell_size), int(pos.y // self.cell_size))

    def _cell_span(self, coord, radius):
        return int((coord - radius) // self.cell_size), int((coord + radius) // self.cell_size)

    def near(self, pos, radius):
        """Every indexed enemy in a cell within `radius` of `pos`.

        Over-inclusive by design -- a circular query against this index's
        square cells can return an enemy slightly further than `radius`
        away -- exactly the same slack a caller already tolerates when it
        scans the raw enemy list and filters with its own exact
        `distance_to()` check afterward (see `Tower.acquire_target()`), so
        no caller needs to change to accommodate it.
        """
        min_cx, max_cx = self._cell_span(pos.x, radius)
        min_cy, max_cy = self._cell_span(pos.y, radius)
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = self._buckets.get((cx, cy))
                if bucket:
                    yield from bucket
