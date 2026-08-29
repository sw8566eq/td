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
    # Preview-while-dragging, commit-on-release tools -- a different
    # interaction from PAINT/ERASE/SPAWN/GOAL's "mutate on every motion
    # event" -- see begin_shape()/update_shape_preview()/commit_shape().
    LINE = "line"
    RECT = "rect"
    SELECT = "select"


TOOL_ORDER = [
    EditorTool.PAINT, EditorTool.ERASE, EditorTool.SPAWN, EditorTool.GOAL,
    EditorTool.LINE, EditorTool.RECT, EditorTool.SELECT,
]
SHAPE_TOOLS = (EditorTool.LINE, EditorTool.RECT, EditorTool.SELECT)


def _deep_copy_wave_specs(wave_specs):
    """A copy of `wave_specs` at every level of nesting (the list, each
    wave's dict, and each spawn's composition dict) -- never a live
    reference. Shared by _snapshot() (undo/redo), load_level(), and
    to_level(), all of which need the exact same guarantee: mutating one
    copy (an Editor's own buffer, an undo snapshot, or a handed-off Level)
    must never leak into any of the others."""
    return [
        {spawn: dict(composition) for spawn, composition in wave.items()}
        for wave in wave_specs
    ]


class Editor:
    # Capped-depth undo history -- a full-state snapshot per stroke/action,
    # not a diff, since path_cells/spawn_cells/goal_cells/wave_specs are
    # all small (path_cells caps at GRID_COLS*GRID_ROWS tuples; wave_specs
    # is a short list of small dicts) -- see _snapshot()/_push_undo().
    UNDO_LIMIT = 50

    def __init__(self, cols=settings.GRID_COLS, rows=settings.GRID_ROWS, tile_size=settings.TILE_SIZE):
        self.cols = cols
        self.rows = rows
        self.tile_size = tile_size

        self.path_cells = set()
        self.spawn_cells = set()
        self.goal_cells = set()
        self.active_tool = EditorTool.PAINT

        # Undo/redo -- see _snapshot()/_push_undo()/begin_stroke()/
        # end_stroke()/undo()/redo(). _stroke_active makes a whole
        # drag-painted stroke (many _apply_tool() calls) collapse into a
        # single undo step, rather than one step per painted cell.
        self._undo_stack = []
        self._redo_stack = []
        self._stroke_active = False

        # In-progress Line/Rect/Select drag -- see begin_shape()/
        # update_shape_preview()/pending_shape_cells()/commit_shape().
        # None (both) means no shape drag is currently in progress.
        self._shape_start = None
        self._shape_end = None

        # Set by copy_selection() (from a committed Select drag -- see
        # select_region()), consumed by paste_clipboard(). Copy-paste
        # never touches wave_specs -- a pasted spawn starts with no units
        # assigned, exactly like freshly painting a new spawn does.
        self.selection_bounds = None
        self.clipboard = None
        # Armed by the path editor's "Paste" action (see
        # Game._handle_editor_action) -- the next click on the grid pastes
        # at that cell instead of applying the active tool.
        self.paste_pending = False

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
        # The first cell of a drag pushes one undo snapshot; every
        # subsequent call during the same held-button drag (see
        # begin_stroke()) is a no-op here, so a whole corridor-length
        # drag is exactly one undo step, not one per painted cell.
        self.begin_stroke()
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

    # --- Undo/redo ---
    #
    # A full-state snapshot stack, not diffs -- path/spawn/goal cells and
    # wave_specs are all small (see UNDO_LIMIT's comment), so the simplicity
    # of snapshotting beats the complexity of diffing. Every mutator above
    # and below pushes exactly one snapshot per player-visible action: a
    # whole drag-painted stroke collapses into one (see begin_stroke(),
    # called from _apply_tool()), while a discrete button click (add/
    # remove wave, adjust a unit count, Clear, Load) pushes one each time.

    def _snapshot(self):
        return {
            "path_cells": set(self.path_cells),
            "spawn_cells": set(self.spawn_cells),
            "goal_cells": set(self.goal_cells),
            "wave_specs": _deep_copy_wave_specs(self.wave_specs),
            "active_wave_index": self.active_wave_index,
            "active_spawn_cell": self.active_spawn_cell,
            "active_tool": self.active_tool,
        }

    def _restore(self, snapshot):
        self.path_cells = snapshot["path_cells"]
        self.spawn_cells = snapshot["spawn_cells"]
        self.goal_cells = snapshot["goal_cells"]
        self.wave_specs = snapshot["wave_specs"]
        self.active_wave_index = snapshot["active_wave_index"]
        self.active_spawn_cell = snapshot["active_spawn_cell"]
        self.active_tool = snapshot["active_tool"]
        self.validate()

    def _push_undo(self):
        """Called by every mutator, right before it actually mutates
        anything, so the pushed snapshot is always "what things looked
        like just before this edit." Any new edit invalidates whatever
        could previously have been redone -- the standard undo/redo rule."""
        self._undo_stack.append(self._snapshot())
        del self._undo_stack[:-self.UNDO_LIMIT]  # cap depth, oldest first
        self._redo_stack.clear()

    def begin_stroke(self):
        """Marks the start of a drag-paint stroke -- the first call during
        a held-button drag pushes one undo snapshot; every later call in
        the same drag (see _stroke_active) is a no-op, so the whole stroke
        undoes as a single step. end_stroke() (called on mouse-up) resets
        this for the next drag."""
        if not self._stroke_active:
            self._push_undo()
            self._stroke_active = True

    def end_stroke(self):
        self._stroke_active = False

    def undo(self):
        """Step back to the state just before the most recent pushed
        edit. False (a no-op) if there's nothing to undo."""
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())
        return True

    def redo(self):
        """Step forward to the state undo() most recently moved away
        from. False (a no-op) if there's nothing to redo, or if a new
        edit was made since the last undo (see _push_undo())."""
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
        return True

    # --- Line/Rectangle/Select tools ---
    #
    # A different interaction from PAINT/ERASE/SPAWN/GOAL's "mutate on
    # every motion event": these preview a shape while the mouse is held
    # (pending_shape_cells(), drawn as a ghost overlay -- see ui.py) and
    # only actually commit it on release (commit_shape()) -- see
    # Game._handle_editor_click/_handle_editor_motion/_handle_editor_
    # mouse_up for how input routes here vs. to paint_at().

    def begin_shape(self, cell):
        if not self.in_bounds(cell):
            return
        self._shape_start = cell
        self._shape_end = cell
        if self.active_tool in (EditorTool.LINE, EditorTool.RECT):
            # One undo step for the whole drag, same idea as
            # _apply_tool()'s begin_stroke() call -- Select doesn't mutate
            # path/spawn/goal data at all, so it needs no undo step.
            self.begin_stroke()

    def update_shape_preview(self, cell):
        if self._shape_start is not None and self.in_bounds(cell):
            self._shape_end = cell

    def _snapped_line_end(self):
        """The drag's end cell, snapped onto whichever axis moved further
        from the start -- guarantees an axis-aligned 2-corner list, which
        is all pathing.path_cells_from_corners() accepts (it raises on a
        diagonal corner pair)."""
        start_col, start_row = self._shape_start
        end_col, end_row = self._shape_end
        if abs(end_col - start_col) >= abs(end_row - start_row):
            return (end_col, start_row)
        return (start_col, end_row)

    def _rect_corners(self):
        """The drag's bounding box as a closed 5-corner loop -- axis-
        aligned by construction, so path_cells_from_corners() traces its
        hollow perimeter with no new geometry code needed."""
        (start_col, start_row), (end_col, end_row) = self._shape_start, self._shape_end
        return [
            (start_col, start_row), (end_col, start_row),
            (end_col, end_row), (start_col, end_row),
            (start_col, start_row),
        ]

    def _selection_preview_cells(self):
        """Every cell in the drag's bounding box (a filled rectangle, not
        just its perimeter) -- what a Select drag actually previews and
        eventually captures, unlike Line/Rect which paint just the
        outline."""
        (start_col, start_row), (end_col, end_row) = self._shape_start, self._shape_end
        min_col, max_col = sorted((start_col, end_col))
        min_row, max_row = sorted((start_row, end_row))
        return frozenset(
            (col, row) for col in range(min_col, max_col + 1) for row in range(min_row, max_row + 1)
        )

    def pending_shape_cells(self):
        """Ghost-preview cells for whichever shape drag is currently in
        progress -- no mutation. Empty once no drag is active."""
        if self._shape_start is None:
            return frozenset()
        if self.active_tool == EditorTool.LINE:
            return pathing.path_cells_from_corners([self._shape_start, self._snapped_line_end()])
        if self.active_tool == EditorTool.RECT:
            return pathing.path_cells_from_corners(self._rect_corners())
        if self.active_tool == EditorTool.SELECT:
            return self._selection_preview_cells()
        return frozenset()

    def commit_shape(self, cell):
        """Finalize whatever shape drag is in progress (a no-op if none
        is) -- Line/Rect stamp their pending cells into path_cells (one
        validate() call for the whole shape, not one per cell); Select
        instead captures its bounding box for a later copy_selection()."""
        if self._shape_start is None:
            return
        self.update_shape_preview(cell)
        if self.active_tool == EditorTool.SELECT:
            self.select_region(self._shape_start, self._shape_end)
        else:
            self.path_cells.update(self.pending_shape_cells())
            self.end_stroke()
            self.validate()
        self._shape_start = None
        self._shape_end = None

    # --- Copy/paste ---

    def select_region(self, corner_a, corner_b):
        col_a, row_a = corner_a
        col_b, row_b = corner_b
        self.selection_bounds = (min(col_a, col_b), min(row_a, row_b), max(col_a, col_b), max(row_a, row_b))

    def copy_selection(self):
        """Capture path/spawn/goal cells within selection_bounds as
        offsets relative to its own top-left corner -- a no-op if nothing
        is currently selected. Wave data is deliberately not part of the
        clipboard -- see paste_clipboard()."""
        if self.selection_bounds is None:
            return
        min_col, min_row, max_col, max_row = self.selection_bounds

        def within(cell):
            col, row = cell
            return min_col <= col <= max_col and min_row <= row <= max_row

        self.clipboard = {
            "path": frozenset((col - min_col, row - min_row) for col, row in self.path_cells if within((col, row))),
            "spawn": frozenset((col - min_col, row - min_row) for col, row in self.spawn_cells if within((col, row))),
            "goal": frozenset((col - min_col, row - min_row) for col, row in self.goal_cells if within((col, row))),
        }

    def paste_clipboard(self, anchor_cell):
        """Re-add the clipboard's cells, offset from `anchor_cell` -- a
        no-op if nothing's been copied yet. Additive (never erases
        anything already there), same spirit as every other paint tool.
        A pasted spawn starts with zero wave-composition entries in every
        wave, identical to freshly painting a brand-new spawn with the
        Spawn tool -- the player fills its waves in afterward as normal."""
        if self.clipboard is None:
            return
        self.begin_stroke()
        anchor_col, anchor_row = anchor_cell
        self.path_cells.update((anchor_col + dc, anchor_row + dr) for dc, dr in self.clipboard["path"])
        self.spawn_cells.update((anchor_col + dc, anchor_row + dr) for dc, dr in self.clipboard["spawn"])
        self.goal_cells.update((anchor_col + dc, anchor_row + dr) for dc, dr in self.clipboard["goal"])
        self.end_stroke()
        self.validate()

    def clear(self):
        """Reset everything -- path *and* waves -- back to a blank slate."""
        self._push_undo()
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
        Game._handle_level_select_click's "edit" purpose). A full replace,
        not a merge -- Playtest/Save still never ask about unsaved changes
        anywhere in this editor, but this *does* push one undo step first,
        so loading a map over unsaved work is itself undoable. Copies at
        every level of nesting, not live references, matching to_level()'s
        own rule that a Level and the Editor that produced (or, here,
        consumes) it never share mutable state."""
        self._push_undo()
        self.path_cells = set(level.path_cells)
        self.spawn_cells = set(level.spawn_cells)
        self.goal_cells = set(level.goal_cells)
        self.wave_specs = _deep_copy_wave_specs(level.wave_specs)
        self.active_wave_index = 0
        self.active_tool = EditorTool.PAINT
        self.validate()

    # --- Wave editing ---

    def add_wave(self):
        self._push_undo()
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
        self._push_undo()
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
        self._push_undo()
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
            wave_specs=_deep_copy_wave_specs(self.wave_specs),
            starting_gold=starting_gold,
            starting_lives=starting_lives,
        )
