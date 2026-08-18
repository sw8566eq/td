"""Asset loading with placeholder-shape fallback.

Every sprite the game needs is referred to elsewhere in the code by a
*logical name* (e.g. "tower_basic", "enemy_grunt") rather than a file path.
SPRITE_MANIFEST is the single place that maps a logical name to where its
real image file should live, plus a fallback color/shape to synthesize if
that file doesn't exist yet.

This means: today, with no art pack present, every sprite renders as a
simple colored placeholder. Later, dropping real PNGs into assets/towers/,
assets/enemies/, etc. at the paths listed below makes the real art appear
with *no code changes* -- unless the pack uses different filenames, in which
case only the path string in the manifest needs editing.

New towers/enemies register their own sprite_name pointing at a new manifest
entry -- adding art for new content is always a manifest line, never a
change to AssetManager itself.
"""

import os

import pygame

# logical_name -> (relative_path_under_assets/, fallback_color, fallback_shape)
# fallback_shape is one of "rect" or "circle".
SPRITE_MANIFEST = {
    "tile_grass": ("tiles/grass.png", (58, 102, 46), "rect"),
    "tile_path": ("tiles/path.png", (169, 132, 79), "rect"),
    "tile_blocked": ("tiles/blocked.png", (70, 70, 78), "rect"),
    "tower_basic": ("towers/basic.png", (70, 130, 180), "rect"),
    "tower_cannon": ("towers/cannon.png", (139, 69, 19), "rect"),
    "tower_frost": ("towers/frost.png", (120, 210, 255), "rect"),
    "tower_knockback": ("towers/knockback.png", (210, 140, 40), "rect"),
    "tower_lightning": ("towers/lightning.png", (250, 235, 90), "rect"),
    "enemy_grunt": ("enemies/grunt.png", (200, 30, 30), "circle"),
    "enemy_scout": ("enemies/scout.png", (255, 205, 60), "circle"),
    "enemy_tank": ("enemies/tank.png", (90, 45, 45), "circle"),
    "enemy_boss": ("enemies/boss.png", (130, 30, 150), "circle"),
    "projectile_basic": ("projectiles/bullet.png", (255, 255, 0), "circle"),
    "projectile_cannon": ("projectiles/ball.png", (90, 90, 90), "circle"),
    "projectile_frost": ("projectiles/shard.png", (150, 220, 255), "circle"),
    "projectile_knockback": ("projectiles/knock.png", (255, 180, 80), "circle"),
    "projectile_lightning": ("projectiles/bolt.png", (255, 255, 170), "circle"),
}


class AssetManager:
    """Loads sprites by logical name, caching results and falling back to a
    synthesized placeholder Surface when the real image file is absent."""

    def __init__(self, asset_root="assets"):
        self.asset_root = asset_root
        self._cache = {}

    def get(self, logical_name, size=None):
        """Return a pygame.Surface for logical_name, scaled to `size` (a
        (width, height) tuple) if given. Cached per (name, size)."""
        key = (logical_name, size)
        if key in self._cache:
            return self._cache[key]

        surface = self._load_or_placeholder(logical_name, size)
        self._cache[key] = surface
        return surface

    def _load_or_placeholder(self, logical_name, size):
        if logical_name not in SPRITE_MANIFEST:
            raise KeyError(
                f"Unknown sprite logical_name {logical_name!r} -- "
                f"add it to SPRITE_MANIFEST in assets.py"
            )
        rel_path, fallback_color, fallback_shape = SPRITE_MANIFEST[logical_name]
        full_path = os.path.join(self.asset_root, rel_path)

        if os.path.isfile(full_path):
            surface = pygame.image.load(full_path).convert_alpha()
            if size is not None:
                surface = pygame.transform.smoothscale(surface, size)
            return surface

        return self._make_placeholder(fallback_color, fallback_shape, size)

    @staticmethod
    def _make_placeholder(color, shape, size):
        w, h = size if size is not None else (48, 48)
        surface = pygame.Surface((w, h), pygame.SRCALPHA)
        outline = (min(color[0] + 60, 255), min(color[1] + 60, 255), min(color[2] + 60, 255))

        if shape == "circle":
            radius = min(w, h) // 2 - 1
            center = (w // 2, h // 2)
            pygame.draw.circle(surface, color, center, radius)
            pygame.draw.circle(surface, outline, center, radius, width=2)
        else:  # "rect"
            rect = pygame.Rect(1, 1, w - 2, h - 2)
            pygame.draw.rect(surface, color, rect, border_radius=4)
            pygame.draw.rect(surface, outline, rect, width=2, border_radius=4)

        return surface
