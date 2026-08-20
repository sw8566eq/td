"""Map editor: freeform tile-paint authoring of a Level's path.

The player paints/erases path tiles directly (a drag-to-paint brush, like a
pixel editor) and places spawn/goal markers with separate tools -- there's
no click-corner-to-corner segment drawing and no manual "declare a branch"
step. Junctions (branch/merge points) are auto-detected from painted
geometry alone (see pathing.junctions_of): whenever a cell ends up with 3+
path-neighbors, it's automatically a junction.

Editor holds no pygame surface/display state of its own and needs no live
Grid -- it just tracks raw cell sets and asks pathing.py to validate them,
the same shape a saved/loaded custom level round-trips through (see
persistence.py). Game owns creating/destroying the Editor instance and
routing input to it; see GameState.EDITOR in game.py.
"""

import pathing
import settings
from levels import Level, generate_default_waves


class EditorTool:
    PAINT = "paint"
    ERASE = "erase"
    SPAWN = "spawn"
    GOAL = "goal"


TOOL_ORDER = [EditorTool.PAINT, EditorTool.ERASE, EditorTool.SPAWN, EditorTool.GOAL]


class Editor:
    def __init__(self, cols=settings.GRID_COLS, rows=settings.GRID_ROWS, tile_size=settings.TILE_SIZE):
        self.cols = cols
        self.rows = rows
        self.tile_size = tile_size

        self.path_cells = set()
        self.spawn_cells = set()
        self.goal_cells = set()
        self.active_tool = EditorTool.PAINT

        # Recomputed by validate() after every edit -- see render() and
        # to_level()/can_play() for how these get used.
        self.validation_problems = []
        self.junctions = frozenset()
        self.validate()

    # --- Coordinate helpers (no live Grid needed during authoring) ---

    def pixel_to_tile(self, x, y):
        return int(x // self.tile_size), int(y // self.tile_size)

    def in_bounds(self, cell):
        col, row = cell
        return 0 <= col < self.cols and 0 <= row < self.rows

    # --- Editing ---

    def set_tool(self, tool):
        if tool in TOOL_ORDER:
            self.active_tool = tool

    def paint_at(self, x, y):
        """Apply the active tool to whichever cell pixel (x, y) falls in.
        Out-of-bounds pixels (e.g. over the toolbar) are silently ignored
        -- callers don't need to fence the play area themselves."""
        cell = self.pixel_to_tile(x, y)
        if not self.in_bounds(cell):
            return
        self._apply_tool(cell)

    def _apply_tool(self, cell):
        if self.active_tool == EditorTool.PAINT:
            self.path_cells.add(cell)
        elif self.active_tool == EditorTool.ERASE:
            self.path_cells.discard(cell)
            self.spawn_cells.discard(cell)
            self.goal_cells.discard(cell)
        elif self.active_tool == EditorTool.SPAWN:
            self.path_cells.add(cell)  # a spawn must be on the path
            self.goal_cells.discard(cell)  # can't be both -- see validate_topology
            self.spawn_cells.add(cell)
        elif self.active_tool == EditorTool.GOAL:
            self.path_cells.add(cell)
            self.spawn_cells.discard(cell)
            self.goal_cells.add(cell)
        self.validate()

    def clear(self):
        self.path_cells.clear()
        self.spawn_cells.clear()
        self.goal_cells.clear()
        self.validate()

    # --- Validation ---

    def validate(self):
        """Recompute validation_problems/junctions from the current
        buffers -- called after every edit so both are always current for
        rendering; also what can_play()/to_level() rely on."""
        self.validation_problems = pathing.validate_topology(
            self.path_cells, self.spawn_cells, self.goal_cells, self.cols, self.rows,
        )
        self.junctions = pathing.junctions_of(self.path_cells)
        return self.validation_problems

    def can_play(self):
        return not self.validation_problems

    # --- Handing off to a playable Level ---

    def to_level(self, name="Custom Level", wave_specs=None, starting_gold=150,
                 starting_lives=20, level_id="custom"):
        """Build a playable Level from the current buffers. Raises
        ValueError (via Level.__post_init__) if the path isn't valid --
        callers should check can_play() first and treat that as the
        authoritative "is this ready" signal; this is a defensive
        backstop, not the primary check.

        wave_specs defaults to a simple ramping all-grunt schedule --
        designing custom wave compositions isn't part of this editor;
        players can still Save and hand-edit the level's JSON, or a future
        wave editor can pass its own wave_specs through this parameter."""
        return Level(
            id=level_id,
            name=name,
            path_cells=frozenset(self.path_cells),
            spawn_cells=tuple(sorted(self.spawn_cells)),
            goal_cells=tuple(sorted(self.goal_cells)),
            wave_specs=wave_specs if wave_specs is not None else generate_default_waves(total_waves=5),
            starting_gold=starting_gold,
            starting_lives=starting_lives,
        )
