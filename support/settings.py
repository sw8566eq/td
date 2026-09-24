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
# normally one tile's worth of area (8x8 subtiles, smaller for a
# relic-shrunk footprint -- see Game._current_footprint_subtiles) but can
# be anchored at any subtile, not just a tile boundary -- see
# Grid.placement_anchor. 8 divides TILE_SIZE evenly, so every
# pixel<->subtile conversion is exact integer math with no rounding edge
# cases.
SUBTILES_PER_TILE = 8
SUBTILE_SIZE = TILE_SIZE // SUBTILES_PER_TILE
# A floor under how far a Compact Framework-style relic (or several
# summed together) can shrink a tower's footprint -- half a tile, so
# placement never collapses to a degenerate zero/negative-size footprint.
MIN_TOWER_FOOTPRINT_SUBTILES = 4
# How each buildable tile's subtile mosaic is drawn (see Grid.draw): each
# small tile is inset by SUBTILE_GAP pixels, and SUBTILE_GAP_ALPHA (0-255)
# controls how visible the soft tint showing through that gap is -- kept
# low so the seam reads as gentle rather than a hard, high-contrast cut.
# Never shown on the path (see Grid), which stays one unbroken tile.
SUBTILE_GAP = 1
SUBTILE_GAP_ALPHA = 60

# --- Window ---
# 96px for the toolbar/button row itself, plus a 32px strip above it (see
# ui.HUD_TOP_STRIP_HEIGHT) reserved for HUD content that's independent of
# how many tower buttons are registered -- the speed toggle and the
# upcoming-wave preview text both live there rather than competing for
# whatever horizontal gap happens to be left next to the tower buttons.
HUD_HEIGHT = 128
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

# --- Enemy health/shield bars and BossEnemy's own armor/enrage ring
# (enemy.py) -- named here rather than left as inline RGB tuples, matching
# every other color in this file, and specifically re-checked for
# colorblind safety since a health/shield bar conveys real gameplay
# information (how hurt is this enemy) through color, not just text.
# Verified with an actual deuteranopia/protanopia simulation (a Machado et
# al. 2009-style linear-RGB transform), not by eye: COLOR_ENEMY_HP_BAR_BG/
# FILL and COLOR_ENEMY_SHIELD_BAR_BG/FILL already have wide-enough
# luminance separation to stay clearly distinguishable under simulation
# (their color *pair* differs mostly in brightness, not hue, which is what
# both common forms of red-green colorblindness preserve) -- kept as-is.
# COLOR_ENEMY_ENRAGE_RING was the one pair that measurably wasn't: the
# original (220, 90, 40) sat only 121.8 apart from COLOR_GOLD (this
# constant's own armor-ring counterpart) under simulated deuteranopia,
# the closest pair found anywhere in this palette -- a low-priority tell
# even so (BossEnemy.draw's own comment calls it "a small cosmetic tell,"
# not the primary way to read armor/enrage state, which is genre-standard
# damage-taken feedback either way), but cheap to widen: this crimson
# reads just as "hot/aggressive" while sitting 184.0 apart under the same
# simulation.
COLOR_ENEMY_HP_BAR_BG = (60, 20, 20)
COLOR_ENEMY_HP_BAR_FILL = (60, 200, 60)
COLOR_ENEMY_SHIELD_BAR_BG = (30, 40, 70)
COLOR_ENEMY_SHIELD_BAR_FILL = (90, 160, 255)
COLOR_ENEMY_ENRAGE_RING = (180, 20, 60)

# --- Map editor markers ---
COLOR_EDITOR_SPAWN = (90, 200, 120)
COLOR_EDITOR_GOAL = (220, 160, 60)
COLOR_EDITOR_JUNCTION = (120, 160, 220)

# --- Level-select map thumbnails ---
COLOR_THUMBNAIL_GROUND = (44, 54, 40)
COLOR_THUMBNAIL_PATH = (150, 130, 90)

# --- Run map screen (see run_map.py/ui.draw_map_screen) -- one color per
# node type, plus a dimmed color for a node that isn't reachable yet.
COLOR_NODE_COMBAT = (170, 80, 80)
COLOR_NODE_ELITE = (180, 70, 140)
COLOR_NODE_SHOP = (80, 150, 205)
COLOR_NODE_EVENT = (205, 165, 60)
COLOR_NODE_REST = (90, 180, 110)
COLOR_NODE_TREASURE = (215, 185, 90)
# Darker/more ominous than COLOR_NODE_COMBAT -- the map's one boss node
# should read as distinct from an ordinary Combat node at a glance.
COLOR_NODE_BOSS = (90, 20, 30)
COLOR_NODE_LOCKED = (60, 60, 68)
COLOR_NODE_EDGE = (90, 90, 100)
