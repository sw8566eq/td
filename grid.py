"""Tile grid: buildable-cell tracking and pixel/tile coordinate conversion.

Grid holds no hardcoded path -- it's constructed from whatever Level is
currently active (see levels.py and Game.load_level), so a new level with a
different path/blocked cells needs no changes here.
"""

import pygame


class Grid:
    def __init__(self, cols, rows, tile_size, waypoints_tiles, blocked_cells=None):
        self.cols = cols
        self.rows = rows
        self.tile_size = tile_size
        self.waypoints_tiles = waypoints_tiles

        self.path_cells = self._compute_path_cells(waypoints_tiles)
        self.blocked_cells = set(blocked_cells or ())
        self.waypoints_px = [self.tile_to_pixel_center(c, r) for c, r in waypoints_tiles]
        self.towers_by_cell = {}

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

    def in_bounds(self, col, row):
        return 0 <= col < self.cols and 0 <= row < self.rows

    def is_path(self, col, row):
        return (col, row) in self.path_cells

    def is_blocked(self, col, row):
        return (col, row) in self.blocked_cells

    def is_occupied(self, col, row):
        return (col, row) in self.towers_by_cell

    def get_tower(self, col, row):
        return self.towers_by_cell.get((col, row))

    def is_buildable(self, col, row):
        return (
            self.in_bounds(col, row)
            and not self.is_path(col, row)
            and not self.is_blocked(col, row)
            and not self.is_occupied(col, row)
        )

    def occupy(self, col, row, tower):
        self.towers_by_cell[(col, row)] = tower

    def tile_to_pixel_center(self, col, row):
        return pygame.Vector2(
            col * self.tile_size + self.tile_size / 2,
            row * self.tile_size + self.tile_size / 2,
        )

    def pixel_to_tile(self, x, y):
        return int(x // self.tile_size), int(y // self.tile_size)

    def draw(self, surface, assets):
        size = (self.tile_size, self.tile_size)
        for row in range(self.rows):
            for col in range(self.cols):
                if self.is_path(col, row):
                    name = "tile_path"
                elif self.is_blocked(col, row):
                    name = "tile_blocked"
                else:
                    name = "tile_grass"
                surface.blit(assets.get(name, size), (col * self.tile_size, row * self.tile_size))
