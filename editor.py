"""Map editor: freeform tile-paint authoring of a Level's path and waves.

The player paints/erases path tiles directly (a drag-to-paint brush, like a
pixel editor) and places spawn/goal markers with separate tools -- there's
no click-corner-to-corner segment drawing and no manual "declare a branch"
step. Junctions (branch/merge points) are auto-detected from painted
geometry alone (see pathing.junctions_of): whenever a cell ends up with 3+
path-neighbors, it's automatically a junction.

Once the path is valid, the player moves on to designing wave_specs: add or
remove waves (level-wide -- every spawn shares the same wave count/timeline),
and click +/- per enemy type within whichever wave *and spawn* are currently
selected -- clicking a different spawn marker in the preview switches to
that spawn's own independent unit counts for the same wave, so a multi-spawn
level can send a completely different mix out of each spawn. Every wave
still spawns its species together, one type fully before the next (see
WaveManager) -- interleaving spawn order within a wave is a possible future
refinement, not something the wave editor's data shape needs to anticipate.

Editor holds no pygame surface/display state of its own and needs no live
Grid -- it just tracks raw cell sets and asks pathing.py to validate them,
the same shape a saved/loaded custom level round-trips through (see
persistence.py). Game owns creating/destroying the Editor instance and
routing input to it; see GameState.EDITOR/WAVE_EDITOR in game.py.
"""

import pathing
import settings
from enemy import ENEMY_TYPES
from levels import Level


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

        # wave_specs is the exact same shape Level.wave_specs expects --
        # [{spawn_cell: {enemy_type_name: count}}, ...], one dict per wave
        # -- edited directly rather than built up separately and converted
        # later. Starts with one empty wave so there's always a wave
        # selected and ready to add units to. A spawn only appears as a key
        # within a given wave once it's actually been given a unit there
        # (see adjust_unit_count) -- wave dicts stay sparse, same as an
        # individual spawn's enemy-count dict only ever holds positive
        # counts.
        self.wave_specs = [{}]
        self.active_wave_index = 0
        # Which spawn's counts adjust_unit_count() currently targets --
        # kept valid (or None, if there's no spawn yet) by validate(),
        # since a spawn can be painted, erased, or overwritten by the Goal
        # tool at any time. See set_active_spawn() / clicking a spawn
        # marker in the wave editor (Game._handle_wave_editor_click).
        self.active_spawn_cell = None

        # Recomputed by validate() after every edit -- see render() and
        # to_level()/can_play() for how these get used. path_problems
        # alone (not the combined list) is what gates moving on to wave
        # editing in the first place -- see path_is_valid().
        self.path_problems = []
        self.wave_problems = []
        self.validation_problems = []
        self.junctions = frozenset()
        self.validate()

    # --- Coordinate helpers (no live Grid needed during authoring) ---

    def pixel_to_tile(self, x, y):
        return int(x // self.tile_size), int(y // self.tile_size)

    def in_bounds(self, cell):
        col, row = cell
        return 0 <= col < self.cols and 0 <= row < self.rows

    # --- Path editing ---

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
            self._forget_spawn(cell)
        elif self.active_tool == EditorTool.SPAWN:
            self.path_cells.add(cell)  # a spawn must be on the path
            self.goal_cells.discard(cell)  # can't be both -- see validate_topology
            self.spawn_cells.add(cell)
        elif self.active_tool == EditorTool.GOAL:
            self.path_cells.add(cell)
            self.spawn_cells.discard(cell)
            self.goal_cells.add(cell)
            self._forget_spawn(cell)
        self.validate()

    def _forget_spawn(self, cell):
        """Drop `cell`'s per-wave unit counts wherever they appear --
        called whenever `cell` stops being a spawn (erased outright, or
        overwritten by the Goal tool), so a removed spawn's waves don't
        linger as orphaned data nothing can see or edit any more."""
        for wave in self.wave_specs:
            wave.pop(cell, None)

    def clear(self):
        """Reset everything -- path *and* waves -- back to a blank slate."""
        self.path_cells.clear()
        self.spawn_cells.clear()
        self.goal_cells.clear()
        self.wave_specs = [{}]
        self.active_wave_index = 0
        self.active_spawn_cell = None
        self.validate()

    def load_level(self, level):
        """Replace every buffer with `level`'s own path/waves, to reopen a
        previously saved custom level for further editing (see
        Game._handle_level_select_click's "edit" purpose). A full
        replace, not a merge -- there's no undo here, same as Playtest/
        Save never asking about unsaved changes anywhere else in this
        editor. Copies at every level of nesting, not live references,
        matching to_level()'s own rule that a Level and the Editor that
        produced (or, here, consumes) it never share mutable state."""
        self.path_cells = set(level.path_cells)
        self.spawn_cells = set(level.spawn_cells)
        self.goal_cells = set(level.goal_cells)
        self.wave_specs = [
            {spawn: dict(composition) for spawn, composition in wave.items()}
            for wave in level.wave_specs
        ]
        self.active_wave_index = 0
        self.active_tool = EditorTool.PAINT
        self.validate()

    # --- Wave editing ---

    def add_wave(self):
        self.wave_specs.append({})
        self.active_wave_index = len(self.wave_specs) - 1
        self.validate()

    def remove_wave(self, index=None):
        """Remove the wave at `index` (the active wave if omitted). A
        no-op if that would leave zero waves -- there's always at least
        one wave to edit, same as there's always an active_tool."""
        if len(self.wave_specs) <= 1:
            return
        index = self.active_wave_index if index is None else index
        if not (0 <= index < len(self.wave_specs)):
            return
        del self.wave_specs[index]
        self.active_wave_index = min(self.active_wave_index, len(self.wave_specs) - 1)
        self.validate()

    def set_active_wave(self, index):
        if 0 <= index < len(self.wave_specs):
            self.active_wave_index = index

    def set_active_spawn(self, cell):
        """Switch which spawn's counts adjust_unit_count() targets --
        e.g. in response to clicking that spawn's marker. Ignored if
        `cell` isn't currently a spawn."""
        if cell in self.spawn_cells:
            self.active_spawn_cell = cell

    def adjust_unit_count(self, enemy_name, delta):
        """+/- `delta` of `enemy_name`, in the currently active wave, for
        the currently active spawn. A no-op if there's no active spawn
        (nothing painted yet). A count reaching zero (or below) drops the
        key entirely rather than storing an explicit 0 -- and an emptied-
        out spawn is dropped from the wave too -- so wave_specs stays
        exactly as sparse as a hand-authored level's would be, at every
        level of nesting."""
        if enemy_name not in ENEMY_TYPES or self.active_spawn_cell is None:
            return
        wave = self.wave_specs[self.active_wave_index]
        composition = wave.setdefault(self.active_spawn_cell, {})
        new_count = composition.get(enemy_name, 0) + delta
        if new_count <= 0:
            composition.pop(enemy_name, None)
        else:
            composition[enemy_name] = new_count
        if not composition:
            wave.pop(self.active_spawn_cell, None)
        self.validate()

    # --- Validation ---

    def validate(self):
        """Recompute path_problems/wave_problems/junctions from the
        current buffers -- called after every edit so all three are
        always current for rendering. path_is_valid() (path_problems
        alone) gates "Edit Waves"; can_play() (both) gates Playtest/Save.

        Also keeps active_spawn_cell valid: painting/erasing spawns can
        invalidate whichever one was selected, same reasoning as
        active_wave_index getting clamped in remove_wave()."""
        self.path_problems = pathing.validate_topology(
            self.path_cells, self.spawn_cells, self.goal_cells, self.cols, self.rows,
        )
        self.wave_problems = self._compute_wave_problems()
        self.validation_problems = self.path_problems + self.wave_problems
        self.junctions = pathing.junctions_of(self.path_cells)

        if self.active_spawn_cell not in self.spawn_cells:
            self.active_spawn_cell = min(self.spawn_cells) if self.spawn_cells else None

        return self.validation_problems

    def _compute_wave_problems(self):
        empty = [
            i + 1 for i, wave in enumerate(self.wave_specs)
            if sum(count for composition in wave.values() for count in composition.values()) <= 0
        ]
        if not empty:
            return []
        return [f"wave {n} has no units (from any spawn) -- use +/- to add some" for n in empty]

    def path_is_valid(self):
        return not self.path_problems

    def can_play(self):
        return not self.validation_problems

    # --- Handing off to a playable Level ---

    def to_level(self, name="Custom Level", starting_gold=150, starting_lives=20, level_id="custom"):
        """Build a playable Level from the current buffers. Raises
        ValueError (via Level.__post_init__) if the path or waves aren't
        valid -- callers should check can_play() first and treat that as
        the authoritative "is this ready" signal; this is a defensive
        backstop, not the primary check."""
        return Level(
            id=level_id,
            name=name,
            path_cells=frozenset(self.path_cells),
            spawn_cells=tuple(sorted(self.spawn_cells)),
            goal_cells=tuple(sorted(self.goal_cells)),
            # A copy at every level of nesting, not a live reference --
            # edits made after to_level() must never leak into the
            # Level it already handed back.
            wave_specs=[
                {spawn: dict(composition) for spawn, composition in wave.items()}
                for wave in self.wave_specs
            ],
            starting_gold=starting_gold,
            starting_lives=starting_lives,
        )
