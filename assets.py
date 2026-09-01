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

from json_io import module_relative_path

# Anchored to this file's own location, not the process's current working
# directory -- a bare "assets" default would resolve against whatever
# directory the game happened to be launched from, which is only ever
# guaranteed to be the repo root when running `python main.py` from there.
# A packaged build (see .github/workflows/release.yml) launched from a
# different cwd -- double-clicked from a file manager, run via a PATH
# symlink, etc. -- needs this to still find its own bundled assets/
# folder, which PyInstaller's --onedir mode places right next to this very
# module (see AssetManager's own docstring below for what happens if it
# doesn't). See json_io.module_relative_path for why this same expression
# lives in one place rather than six near-identical hand-copies.
DEFAULT_ASSET_ROOT = module_relative_path(__file__, "assets")

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
    "tower_sniper": ("towers/sniper.png", (60, 60, 60), "rect"),
    "tower_poison": ("towers/poison.png", (100, 160, 60), "rect"),
    "tower_support": ("towers/support.png", (200, 180, 80), "rect"),
    "enemy_grunt": ("enemies/grunt.png", (200, 30, 30), "circle"),
    "enemy_scout": ("enemies/scout.png", (255, 205, 60), "circle"),
    "enemy_tank": ("enemies/tank.png", (90, 45, 45), "circle"),
    "enemy_boss": ("enemies/boss.png", (130, 30, 150), "circle"),
    "enemy_shielded": ("enemies/shielded.png", (80, 120, 200), "circle"),
    "enemy_flying": ("enemies/flying.png", (200, 220, 255), "circle"),
    "projectile_basic": ("projectiles/bullet.png", (255, 255, 0), "circle"),
    "projectile_cannon": ("projectiles/ball.png", (90, 90, 90), "circle"),
    "projectile_frost": ("projectiles/shard.png", (150, 220, 255), "circle"),
    "projectile_knockback": ("projectiles/knock.png", (255, 180, 80), "circle"),
    "projectile_lightning": ("projectiles/bolt.png", (255, 255, 170), "circle"),
    "projectile_sniper": ("projectiles/sniper_round.png", (220, 220, 220), "circle"),
    "projectile_poison": ("projectiles/poison_dart.png", (140, 200, 80), "circle"),
}


class AssetManager:
    """Loads sprites by logical name, caching results and falling back to a
    synthesized placeholder Surface when the real image file is absent.
    Falling back is silent either way -- a missing art pack and a missing
    asset_root directory entirely look identical to _load_or_placeholder,
    which only ever checks os.path.isfile."""

    def __init__(self, asset_root=DEFAULT_ASSET_ROOT):
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

        # Corner rounding and the outline stroke are tuned for normal
        # sprite sizes (tens of pixels); at very small sizes (e.g. the
        # mosaic of small map tiles Grid draws) there aren't enough
        # pixels left for either without the shape collapsing into a dot,
        # so fall back to a plain filled shape below that size instead.
        short_side = min(w, h)
        plain = short_side < 12
        outline_width = 2 if short_side >= 16 else 1

        if shape == "circle":
            radius = short_side // 2 - 1
            center = (w // 2, h // 2)
            pygame.draw.circle(surface, color, center, radius)
            if not plain:
                pygame.draw.circle(surface, outline, center, radius, width=outline_width)
        elif plain:  # "rect", plain: fill edge-to-edge -- a 1px inset here
            # would stack with any gap the caller already inset the
            # requested size by (e.g. Grid's subtile mosaic), doubling it
            surface.fill(color)
        else:  # "rect", normal size: inset with a rounded border
            rect = pygame.Rect(1, 1, w - 2, h - 2)
            corner_radius = min(4, short_side // 3)
            pygame.draw.rect(surface, color, rect, border_radius=corner_radius)
            pygame.draw.rect(surface, outline, rect, width=outline_width, border_radius=corner_radius)

        return surface
