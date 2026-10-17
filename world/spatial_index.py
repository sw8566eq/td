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
        # Each indexed enemy's position in the `enemies` list it was built
        # from -- see near_in_order().
        self._order = {}
        buckets = self._buckets
        order = self._order
        for position, enemy in enumerate(enemies):
            if enemy.is_dead or enemy.reached_goal:
                continue
            pos = enemy.pos
            # The cell key, inlined -- this loop runs over every enemy, every frame.
            buckets[(int(pos.x // cell_size), int(pos.y // cell_size))].append(enemy)
            order[enemy] = position

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

        Returns a list, not a generator: a busy cell neighborhood holds
        a hundred-plus enemies, and per-item generator resumption was a
        measurable share of a Healer-heavy frame. Same visiting order.
        """
        min_cx, max_cx = self._cell_span(pos.x, radius)
        min_cy, max_cy = self._cell_span(pos.y, radius)
        get = self._buckets.get
        found = []
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = get((cx, cy))
                if bucket:
                    found.extend(bucket)
        return found

    def near_in_order(self, pos, radius):
        """near(), as a list in the original `enemies` list order.

        For a caller whose result depends on visiting order, not just on
        which enemies it visits: a splash hit rolls crits/relic procs per
        enemy in list order (one shared `random` stream), a chain hop breaks
        distance ties toward the earlier enemy, and a ground fire's damage
        credit is a float sum whose rounding depends on the order it was
        added in. Visiting the candidates in list order makes the indexed
        path give bit-identical results to a scan of the raw list.
        """
        return sorted(self.near(pos, radius), key=self._order.__getitem__)


# Extra query radius on top of the measured movement slack -- covers the
# rounding of math.hypot() against the real displacement; any positive
# margin works, since near() is over-inclusive anyway.
MOVEMENT_EPSILON = 1.0


class MovingEnemyIndex:
    """An EnemySpatialIndex for queries made while enemies are still moving.

    Game.update() moves enemies one at a time (`enemy.update()` in list
    order), and a HealerEnemy's heal reads the *current* position of every
    other enemy mid-loop -- some already moved this frame, some not yet. A
    snapshot index can still answer that exactly if every query is widened
    by how far any enemy has moved since the snapshot: Game.update() reports
    each enemy's displacement through note_moved() (only once the index is
    built -- before that there's no snapshot to drift from), and near()
    adds the largest one seen so far (`slack`) to the radius. An enemy now
    within `radius` was within `radius + slack` of its snapshot position,
    so the candidate pool is still a superset and every caller's own exact
    distance check keeps the result unchanged.

    Built lazily, on the first query, so a frame with nothing to ask (no
    Healer, no ground fire) never pays for the build or the movement
    tracking.
    """

    def __init__(self, enemies, cell_size=CELL_SIZE):
        self._enemies = enemies
        self._cell_size = cell_size
        self._index = None
        self.slack = 0.0

    @property
    def built(self):
        return self._index is not None

    def note_moved(self, distance):
        self.slack = max(self.slack, distance)

    def _snapshot(self):
        if self._index is None:
            self._index = EnemySpatialIndex(self._enemies, self._cell_size)
        return self._index

    def near(self, pos, radius):
        index = self._snapshot()
        widened = radius + self.slack + MOVEMENT_EPSILON
        return index.near(pos, widened)

    def near_in_order(self, pos, radius):
        index = self._snapshot()
        return index.near_in_order(pos, radius + self.slack + MOVEMENT_EPSILON)
