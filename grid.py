"""Tile grid: buildable-cell tracking and pixel/tile coordinate conversion.

Grid holds no hardcoded path -- it's constructed from whatever Level is
currently active (see levels.py and Game.load_level), so a new level with a
different path/blocked cells needs no changes here. path_cells/spawn_cells/
goal_cells are taken as given, already validated by Level.__post_init__
(see pathing.validate_topology) -- Grid doesn't re-derive or re-check them,
just stores and queries them.

Two coordinate systems coexist:
  - Coarse tile coords (col, row; unit = tile_size) -- the path, blocked
    cells, and rendering all work at this granularity, unchanged from
    before subtile placement existed.
  - Subtile coords (sub_col, sub_row; unit = subtile_size) -- a finer grid
    used only for tower placement. A tower's footprint is normally a
    subtiles_per_tile x subtiles_per_tile block of subtiles (the same
    pixel area as one coarse tile), anchored at its top-left subtile
    (anchor_col, anchor_row) -- smaller for a relic-shrunk footprint (see
    Game._current_footprint_subtiles; every footprint-touching method
    below takes an optional footprint_subtiles, defaulting to a full
    tile). Anchors don't need to align to coarse tile boundaries, which is
    what gives placement its finer granularity.
"""

import pygame


class Grid:
    def __init__(self, cols, rows, tile_size, path_cells, spawn_cells, goal_cells,
                 blocked_cells=None, subtiles_per_tile=8, subtile_gap=1, subtile_gap_alpha=60):
        # (defaults match settings.SUBTILE_GAP / SUBTILE_GAP_ALPHA)
        if tile_size % subtiles_per_tile != 0:
            raise ValueError(
                f"tile_size ({tile_size}) must be evenly divisible by "
                f"subtiles_per_tile ({subtiles_per_tile}) for exact "
                f"pixel<->subtile conversion"
            )
        subtile_size = tile_size // subtiles_per_tile
        if not (0 <= subtile_gap < subtile_size):
            raise ValueError(
                f"subtile_gap ({subtile_gap}) must be less than subtile_size "
                f"({subtile_size}) so each drawn small tile has positive size"
            )
        if not (0 <= subtile_gap_alpha <= 255):
            raise ValueError(f"subtile_gap_alpha ({subtile_gap_alpha}) must be 0-255")

        self.cols = cols
        self.rows = rows
        self.tile_size = tile_size

        self.path_cells = frozenset(path_cells)
        self.spawn_cells = tuple(spawn_cells)
        self.goal_cells = tuple(goal_cells)
        self.blocked_cells = set(blocked_cells or ())

        self.subtiles_per_tile = subtiles_per_tile
        self.subtile_size = subtile_size
        self.subtile_gap = subtile_gap
        self.subtile_gap_alpha = subtile_gap_alpha
        self.sub_cols = cols * subtiles_per_tile
        self.sub_rows = rows * subtiles_per_tile
        # Every subtile currently covered by some tower's footprint --
        # this is what buildability overlap-checks against, so two
        # footprints collide whenever they overlap at all, regardless of
        # whether their anchors happen to be tile-aligned.
        self.occupied_subtiles = set()
        self.towers_by_anchor = {}
        # What footprint size occupy() actually reserved at each anchor --
        # populated by occupy(), consulted by remove() -- so a Compact
        # Framework-style relic's smaller footprint (see
        # Game._current_footprint_subtiles) frees exactly what it
        # reserved without remove() needing the size passed back in, or
        # needing to introspect the tower object itself (several tests
        # occupy anchors with a bare placeholder, not a real Tower).
        self._footprint_size_by_anchor = {}
        # Lazily built and cached by draw() -- see _build_background.
        self._background = None

    # --- Coarse tile queries (path/blocked/bounds, rendering) ---

    def in_bounds(self, col, row):
        return 0 <= col < self.cols and 0 <= row < self.rows

    def is_path(self, col, row):
        return (col, row) in self.path_cells

    def is_blocked(self, col, row):
        return (col, row) in self.blocked_cells

    def tile_to_pixel_center(self, col, row):
        return pygame.Vector2(
            col * self.tile_size + self.tile_size / 2,
            row * self.tile_size + self.tile_size / 2,
        )

    def pixel_to_tile(self, x, y):
        return int(x // self.tile_size), int(y // self.tile_size)

    # --- Subtile placement (footprint buildability/occupancy) ---

    def pixel_to_subtile(self, x, y):
        return int(x // self.subtile_size), int(y // self.subtile_size)

    def resolve_footprint_size(self, footprint_subtiles=None):
        """A tower's footprint size in subtiles -- `footprint_subtiles`
        itself if given, else a full tile's worth (subtiles_per_tile). The
        one place every footprint-aware method below (and
        ui.draw_footprint_preview, which has no other way to reach this
        default) resolves it, so the default can never drift between
        them."""
        return self.subtiles_per_tile if footprint_subtiles is None else footprint_subtiles

    def placement_anchor(self, x, y, footprint_subtiles=None):
        """Top-left subtile of the tower-sized footprint centered on pixel
        (x, y) -- `footprint_subtiles` defaults to a full tile
        (subtiles_per_tile), or a smaller value for a relic-shrunk
        footprint (see Game._current_footprint_subtiles). Not clamped to
        the grid -- a hover/click near the edge (or entirely outside the
        grid, e.g. over the stats panel) can produce an anchor whose
        footprint is partly or fully out of bounds; that's left for
        is_buildable() to reject rather than silently clamped into a
        valid spot the player didn't actually point at."""
        sub_col, sub_row = self.pixel_to_subtile(x, y)
        size = self.resolve_footprint_size(footprint_subtiles)
        half = size // 2
        return sub_col - half, sub_row - half

    def anchor_to_pixel_center(self, anchor_col, anchor_row, footprint_subtiles=None):
        size = self.resolve_footprint_size(footprint_subtiles)
        footprint_pixels = size * self.subtile_size
        return pygame.Vector2(
            anchor_col * self.subtile_size + footprint_pixels / 2,
            anchor_row * self.subtile_size + footprint_pixels / 2,
        )

    def _footprint_subtiles(self, anchor_col, anchor_row, size):
        """Subtiles covered by a `size` x `size` footprint anchored at
        (anchor_col, anchor_row). `size` is taken as already resolved
        (see resolve_footprint_size) -- every caller below resolves it
        itself first, so this never re-defaults and never runs at all for
        a non-positive size, rather than silently yielding nothing and
        leaving a caller like is_buildable() to mistake "nothing to
        check" for "everything checked out"."""
        for dr in range(size):
            for dc in range(size):
                yield anchor_col + dc, anchor_row + dr

    def is_buildable(self, anchor_col, anchor_row, footprint_subtiles=None):
        """True if the footprint_subtiles x footprint_subtiles footprint
        (a full tile, subtiles_per_tile, unless a smaller size is passed --
        see Game._current_footprint_subtiles) anchored at (anchor_col,
        anchor_row) is entirely in bounds, off the path, unblocked, and
        doesn't overlap any placed tower's footprint. A non-positive size
        is never buildable -- _footprint_subtiles() would otherwise yield
        no cells at all to check, and an empty check vacuously returns
        True for any anchor, path/blocked/occupied cells included."""
        size = self.resolve_footprint_size(footprint_subtiles)
        if size <= 0:
            return False
        for sub_col, sub_row in self._footprint_subtiles(anchor_col, anchor_row, size):
            if not (0 <= sub_col < self.sub_cols and 0 <= sub_row < self.sub_rows):
                return False
            # Always the map's own fixed tile/subtile ratio here, regardless
            # of footprint_subtiles -- is_path/is_blocked are properties of
            # the coarse map grid, unrelated to any one tower's own
            # (possibly relic-shrunk) footprint size.
            coarse = (sub_col // self.subtiles_per_tile, sub_row // self.subtiles_per_tile)
            if self.is_path(*coarse) or self.is_blocked(*coarse):
                return False
            if (sub_col, sub_row) in self.occupied_subtiles:
                return False
        return True

    def occupy(self, anchor_col, anchor_row, tower, footprint_subtiles=None):
        size = self.resolve_footprint_size(footprint_subtiles)
        for cell in self._footprint_subtiles(anchor_col, anchor_row, size):
            self.occupied_subtiles.add(cell)
        self.towers_by_anchor[(anchor_col, anchor_row)] = tower
        self._footprint_size_by_anchor[(anchor_col, anchor_row)] = size

    def remove(self, anchor_col, anchor_row):
        """Free the footprint anchored at (anchor_col, anchor_row) -- the
        inverse of occupy(), used when a tower is sold. No-op if nothing
        is anchored there. Frees exactly the footprint size occupy() was
        given (see _footprint_size_by_anchor) -- the caller never needs to
        pass it again."""
        if (anchor_col, anchor_row) not in self.towers_by_anchor:
            return
        size = self._footprint_size_by_anchor.pop((anchor_col, anchor_row), self.subtiles_per_tile)
        for cell in self._footprint_subtiles(anchor_col, anchor_row, size):
            self.occupied_subtiles.discard(cell)
        del self.towers_by_anchor[(anchor_col, anchor_row)]

    def is_occupied(self, anchor_col, anchor_row):
        return (anchor_col, anchor_row) in self.towers_by_anchor

    def get_tower(self, anchor_col, anchor_row):
        return self.towers_by_anchor.get((anchor_col, anchor_row))

    def _tile_name(self, col, row):
        if self.is_path(col, row):
            return "tile_path"
        if self.is_blocked(col, row):
            return "tile_blocked"
        return "tile_grass"

    def _build_background(self, assets):
        """Render the whole grid once into an offscreen surface and cache
        it -- built once and blitted as a single surface thereafter,
        since redrawing thousands of small tiles every frame would be far
        more blits than the game needs. The path is one unbroken
        full-size sprite (see _blit_solid_tile); every other tile is a
        mosaic of individually rendered small tiles (see
        _blit_subtile_mosaic)."""
        background = pygame.Surface(
            (self.cols * self.tile_size, self.rows * self.tile_size), pygame.SRCALPHA,
        )
        # A soft translucent tile-sized tint, laid down under a mosaic
        # before its small tiles are blitted on top, so the gap between
        # them reveals a gentle tint rather than a hard cut straight
        # through to the background color.
        gap_tint = pygame.Surface((self.tile_size, self.tile_size), pygame.SRCALPHA)
        gap_tint.fill((0, 0, 0, self.subtile_gap_alpha))

        for row in range(self.rows):
            for col in range(self.cols):
                pos = (col * self.tile_size, row * self.tile_size)
                name = self._tile_name(col, row)
                if self.is_path(col, row):
                    self._blit_solid_tile(background, assets, name, pos)
                else:
                    self._blit_subtile_mosaic(background, assets, name, pos, gap_tint)

        return background

    def _blit_solid_tile(self, background, assets, name, pos):
        sprite = assets.get(name, (self.tile_size, self.tile_size))
        background.blit(sprite, pos)

    def _blit_subtile_mosaic(self, background, assets, name, pos, gap_tint):
        """One buildable tile's subtiles_per_tile x subtiles_per_tile
        mosaic of individually rendered small tiles -- not one big sprite
        with lines drawn over it -- with a small gap between them."""
        x0, y0 = pos
        background.blit(gap_tint, pos)

        drawn_size = self.subtile_size - self.subtile_gap
        sprite = assets.get(name, (drawn_size, drawn_size))
        for dr in range(self.subtiles_per_tile):
            for dc in range(self.subtiles_per_tile):
                x = x0 + dc * self.subtile_size
                y = y0 + dr * self.subtile_size
                background.blit(sprite, (x, y))

    def draw(self, surface, assets):
        if self._background is None:
            self._background = self._build_background(assets)
        surface.blit(self._background, (0, 0))
