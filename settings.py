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

# --- Window ---
HUD_HEIGHT = 96
SCREEN_WIDTH = GRID_COLS * TILE_SIZE
SCREEN_HEIGHT = GRID_ROWS * TILE_SIZE + HUD_HEIGHT
FPS = 60
WINDOW_TITLE = "Tower Defense"

# --- Waves ---
TOTAL_WAVES = 10
SPAWN_INTERVAL = 0.8  # seconds between individual enemy spawns within a wave
BETWEEN_WAVE_DELAY = 5.0  # seconds of downtime before the next wave starts

# --- Colors (used by UI and placeholder-shape fallbacks) ---
COLOR_BG = (24, 28, 22)
COLOR_HUD_BG = (32, 32, 40)
COLOR_TEXT = (240, 240, 240)
COLOR_TEXT_DIM = (170, 170, 180)
COLOR_GOLD = (255, 215, 0)
COLOR_LIVES = (220, 60, 60)
COLOR_BUTTON = (60, 60, 80)
COLOR_BUTTON_HOVER = (85, 85, 115)
COLOR_BUTTON_DISABLED = (45, 45, 50)
COLOR_BUTTON_SELECTED = (110, 150, 90)
COLOR_RANGE_PREVIEW = (255, 255, 255)
