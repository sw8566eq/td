"""Global constants.

Screen sizing is derived from tile/grid counts so that swapping in a
differently-sized art pack (e.g. 128px tiles instead of 64px) is a one-line
change here rather than a hunt through the codebase.

The grid size (GRID_COLS/GRID_ROWS) is intentionally shared by every level in
the LEVELS registry (see levels.py) rather than being per-level -- levels
differ by path/waves/blocked cells, not by canvas size. Variable-sized maps
would need camera/scroll support, which is out of scope for now.
"""

# --- Map / grid ---
TILE_SIZE = 64
GRID_COLS = 15
GRID_ROWS = 9

# Tower placement works at finer-than-tile granularity: each tile is cut
# into an 8x8 grid of small tiles, and a tower's required footprint is
# exactly one tile's worth of area (8x8 subtiles) but can be anchored at
# any subtile, not just a tile boundary -- see Grid.placement_anchor. 8
# divides TILE_SIZE evenly, so every pixel<->subtile conversion is exact
# integer math with no rounding edge cases.
SUBTILES_PER_TILE = 8
SUBTILE_SIZE = TILE_SIZE // SUBTILES_PER_TILE
# How each buildable tile's subtile mosaic is drawn (see Grid.draw): each
# small tile is inset by SUBTILE_GAP pixels, and SUBTILE_GAP_ALPHA (0-255)
# controls how visible the soft tint showing through that gap is -- kept
# low so the seam reads as gentle rather than a hard, high-contrast cut.
# Never shown on the path (see Grid), which stays one unbroken tile.
SUBTILE_GAP = 1
SUBTILE_GAP_ALPHA = 60

# --- Window ---
HUD_HEIGHT = 96
# PLAY_WIDTH is the grid + the HUD bar beneath it; PANEL_WIDTH is the tower
# stats sidebar to its right. The window is simply grown to fit both --
# nothing about the grid/HUD's own size or position changes.
PLAY_WIDTH = GRID_COLS * TILE_SIZE
PANEL_WIDTH = 240
SCREEN_WIDTH = PLAY_WIDTH + PANEL_WIDTH
SCREEN_HEIGHT = GRID_ROWS * TILE_SIZE + HUD_HEIGHT
FPS = 60
WINDOW_TITLE = "Tower Defense"

# --- Waves ---
SPAWN_INTERVAL = 0.8  # seconds between individual enemy spawns within a wave
BETWEEN_WAVE_DELAY = 5.0  # seconds of downtime before the next wave starts

# --- Economy ---
# Fraction of a tower's total investment (its base cost plus any upgrades
# paid for) refunded when it's sold -- less than 1.0 so build/sell isn't a
# free way to reposition a tower.
SELL_REFUND_FRACTION = 0.7

# --- Colors (used by UI and placeholder-shape fallbacks) ---
COLOR_BG = (24, 28, 22)
COLOR_HUD_BG = (32, 32, 40)
COLOR_TEXT = (240, 240, 240)
COLOR_TEXT_DIM = (170, 170, 180)
COLOR_GOLD = (255, 215, 0)
COLOR_LIVES = (220, 60, 60)
COLOR_BUTTON = (60, 60, 80)
COLOR_BUTTON_DISABLED = (45, 45, 50)
COLOR_BUTTON_SELECTED = (110, 150, 90)
COLOR_RANGE_PREVIEW = (255, 255, 255)
COLOR_FOOTPRINT_VALID = (255, 255, 255)
COLOR_FOOTPRINT_INVALID = (220, 60, 60)

# --- Map editor markers ---
COLOR_EDITOR_SPAWN = (90, 200, 120)
COLOR_EDITOR_GOAL = (220, 160, 60)
COLOR_EDITOR_JUNCTION = (120, 160, 220)

# --- Level-select map thumbnails ---
COLOR_THUMBNAIL_GROUND = (44, 54, 40)
COLOR_THUMBNAIL_PATH = (150, 130, 90)
