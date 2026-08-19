"""Tile grid: buildable-cell tracking and pixel/tile coordinate conversion.

Grid holds no hardcoded path -- it's constructed from whatever Level is
currently active (see levels.py and Game.load_level), so a new level with a
different path/blocked cells needs no changes here.

Two coordinate systems coexist:
  - Coarse tile coords (col, row; unit = tile_size) -- the path, blocked
    cells, and rendering all work at this granularity, unchanged from
    before subtile placement existed.
  - Subtile coords (sub_col, sub_row; unit = subtile_size) -- a finer grid
    used only for tower placement. A tower's footprint is a
    subtiles_per_tile x subtiles_per_tile block of subtiles (the same
    pixel area as one coarse tile), anchored at its top-left subtile
    (anchor_col, anchor_row). Anchors don't need to align to coarse tile
    boundaries, which is what gives placement its finer granularity.
"""

import pygame


class Grid:
    def __init__(self, cols, rows, tile_size, waypoints_tiles, blocked_cells=None,
                 subtiles_per_tile=8, subtile_gap=1, subtile_gap_alpha=60):
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
        self.waypoints_tiles = waypoints_tiles

        self.path_cells = self._compute_path_cells(waypoints_tiles)
        self.blocked_cells = set(blocked_cells or ())
        self.waypoints_px = [self.tile_to_pixel_center(c, r) for c, r in waypoints_tiles]

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
        # Lazily built and cached by draw() -- see _build_background.
        self._background = None

    @staticmethod
    def _compute_path_cells(waypoints_tiles):
        """Walk each axis-aligned segment between consecutive waypoints and
        collect every tile it passes through."""
        cells = set()
        for (c1, r1), (c2, r2) in zip(waypoints_tiles, waypoints_tiles[1:]):
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
                    f"Waypoints must form axis-aligned segments: "
                    f"{(c1, r1)} -> {(c2, r2)} is diagonal"
                )
        return cells

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

    def placement_anchor(self, x, y):
        """Top-left subtile of the tower-sized footprint centered on pixel
        (x, y). Not clamped to the grid -- a hover/click near the edge (or
        entirely outside the grid, e.g. over the stats panel) can produce
        an anchor whose footprint is partly or fully out of bounds; that's
        left for is_buildable() to reject rather than silently clamped
        into a valid spot the player didn't actually point at."""
        sub_col, sub_row = self.pixel_to_subtile(x, y)
        half = self.subtiles_per_tile // 2
        return sub_col - half, sub_row - half

    def anchor_to_pixel_center(self, anchor_col, anchor_row):
        return pygame.Vector2(
            anchor_col * self.subtile_size + self.tile_size / 2,
            anchor_row * self.subtile_size + self.tile_size / 2,
        )

    def _footprint_subtiles(self, anchor_col, anchor_row):
        for dr in range(self.subtiles_per_tile):
            for dc in range(self.subtiles_per_tile):
                yield anchor_col + dc, anchor_row + dr

    def is_buildable(self, anchor_col, anchor_row):
        """True if the subtiles_per_tile x subtiles_per_tile footprint
        anchored at (anchor_col, anchor_row) is entirely in bounds, off
        the path, unblocked, and doesn't overlap any placed tower's
        footprint."""
        for sub_col, sub_row in self._footprint_subtiles(anchor_col, anchor_row):
            if not (0 <= sub_col < self.sub_cols and 0 <= sub_row < self.sub_rows):
                return False
            coarse = (sub_col // self.subtiles_per_tile, sub_row // self.subtiles_per_tile)
            if self.is_path(*coarse) or self.is_blocked(*coarse):
                return False
            if (sub_col, sub_row) in self.occupied_subtiles:
                return False
        return True

    def occupy(self, anchor_col, anchor_row, tower):
        for cell in self._footprint_subtiles(anchor_col, anchor_row):
            self.occupied_subtiles.add(cell)
        self.towers_by_anchor[(anchor_col, anchor_row)] = tower

    def remove(self, anchor_col, anchor_row):
        """Free the footprint anchored at (anchor_col, anchor_row) -- the
        inverse of occupy(), used when a tower is sold. No-op if nothing
        is anchored there."""
        if (anchor_col, anchor_row) not in self.towers_by_anchor:
            return
        for cell in self._footprint_subtiles(anchor_col, anchor_row):
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
        it. Off the path, each tile is drawn as its own
        subtiles_per_tile x subtiles_per_tile mosaic of individually
        rendered small tiles -- not one big sprite with lines drawn over
        it -- with a small gap between them. A soft translucent base
        (subtile_gap_alpha) is laid down under that mosaic first, so the
        gap reveals a gentle tint rather than a hard cut straight through
        to the background color. The path is left as one unbroken
        full-size sprite -- no seams at all. Built once and blitted as a
        single surface thereafter -- redrawing thousands of small tiles
        every frame would be far more blits than the game needs."""
        background = pygame.Surface(
            (self.cols * self.tile_size, self.rows * self.tile_size), pygame.SRCALPHA,
        )
        full_size = (self.tile_size, self.tile_size)
        drawn_size = self.subtile_size - self.subtile_gap
        small_size = (drawn_size, drawn_size)

        base = pygame.Surface(full_size, pygame.SRCALPHA)
        base.fill((0, 0, 0, self.subtile_gap_alpha))

        for row in range(self.rows):
            for col in range(self.cols):
                x0, y0 = col * self.tile_size, row * self.tile_size
                name = self._tile_name(col, row)

                if self.is_path(col, row):
                    background.blit(assets.get(name, full_size), (x0, y0))
                    continue

                background.blit(base, (x0, y0))
                sprite = assets.get(name, small_size)
                for dr in range(self.subtiles_per_tile):
                    for dc in range(self.subtiles_per_tile):
                        x = x0 + dc * self.subtile_size
                        y = y0 + dr * self.subtile_size
                        background.blit(sprite, (x, y))

        return background

    def draw(self, surface, assets):
        if self._background is None:
            self._background = self._build_background(assets)
        surface.blit(self._background, (0, 0))
