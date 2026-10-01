# Map editor and custom levels

## Map editor and custom levels

`core/editor.py`'s `Editor` (driven by `GameState.EDITOR` in `core/game.py`, entered via `E` from the menu or
`main.py --editor`) is a freeform tile-paint brush: drag to paint/erase `path_cells`, separate
Spawn/Goal tools mark `spawn_cells`/`goal_cells`. Junctions are **auto-detected** from painted
geometry (`pathing.junctions_of` -- any cell with 3+ path-neighbors) rather than the player ever
declaring "this is a branch." `Editor.validate()` reruns `pathing.validate_topology` after every
edit, populating `path_problems` -- the only thing that gates moving on to wave editing (see below);
`wave_problems`/`validation_problems`/`can_play()` fold in wave validity too, and are what gate
Playtest/Save. Playtesting hands `Editor.to_level()`'s `Level` straight to `Game.load_custom_level()`
(the non-registry counterpart to `load_level(level_id)`) without saving first; `current_level_id`
becomes `None` for a custom level, which is what `has_next_level()`/`reset()`/
`advance_or_replay_level()` -- and the pause menu's "Return to Map Editor" option (`E`, only offered
when `current_level_id is None`; see `ui.draw_pause_menu`'s `is_custom_level` and
`Game._handle_keydown`'s `GameState.PAUSED` branch) -- check to know there's no `LEVELS` entry to
look back up. That option just switches `state` back to `GameState.EDITOR` without touching
`self.editor` at all, so whatever was playtested is still sitting there exactly as painted.

Painting itself has three additional quality-of-life layers, all scoped to the path editor (the
wave editor has no equivalent undo history of its own). **Undo/redo** (`Editor._undo_stack`/
`_redo_stack`, capped at `UNDO_LIMIT`) is whole-stroke, not per-cell -- `begin_stroke()`/
`end_stroke()` bracket an entire drag so painting a long corridor undoes as one step, not one cell
at a time. **Shape tools** (`EditorTool.LINE`/`RECT`/`SELECT`, `SHAPE_TOOLS`) preview a straight
line/rectangle/selection while dragging and only commit it to `path_cells` on mouse-up, reusing
`pathing.path_cells_from_corners()` the same way the freeform brush's own straight runs already do;
a freshly-stamped `RECT` is *always* a closed loop (exactly the shape `validate_topology` forbids),
which the sidebar calls out explicitly as a one-cell-erase fix rather than leaving the player to
puzzle out why a rectangle fails validation. **Copy/paste** (`select_region()`/`copy_selection()`/
`paste_clipboard()`) copies a rectangular selection's path/spawn/goal cells and re-anchors them
relative to wherever the paste lands; a pasted spawn starts with zero wave composition entries in
every wave -- wave data never carries over on copy, since the whole point of `wave_specs` staying
keyed by concrete spawn cell is that a copy is a genuinely new spawn point, not an alias for the one
it was copied from. A paste is clipped to the grid (an off-grid anchor is refused outright, leaving the
paste armed; any pasted cell that would land off-grid is dropped) -- nothing else in the editor can
reach an off-grid cell to erase it, since `paint_at()` ignores out-of-bounds pixels -- and pasted
spawns/goals follow the Spawn/Goal tools' own exclusivity rule rather than leaving a cell that's both.

Once the path is valid, `GameState.WAVE_EDITOR` (reached via the path editor's "Edit Waves" button)
edits `Editor.wave_specs` directly -- the exact same `[{spawn_cell: {enemy_type_name: count}}, ...]`
shape `Level.wave_specs` expects, not a separate representation converted later. Waves are a
**level-wide timeline** (add/remove-wave tabs affect every spawn's wave count at once, same
`wave_index`/countdown for the whole level -- see `WaveManager`), but each wave's **composition is
per-spawn**: clicking a spawn's marker in the read-only path preview (`Game._handle_wave_editor_click`
-> `Editor.set_active_spawn`) switches which spawn's own `{enemy_name: count}` dict the +/- buttons
target, so a multi-spawn level can send a completely different mix -- or nothing at all -- out of
each spawn in the same wave. `Editor.active_spawn_cell` is kept valid the same way
`active_wave_index` is: `validate()` re-clamps it (to `min(spawn_cells)`, or `None` if there are no
spawns left) any time painting/erasing changes which spawns exist, and erasing a spawn
(`Editor._forget_spawn`) drops its entries from every wave so removed spawns never leave orphaned
wave data behind. Every wave-editing method (`add_wave`/`remove_wave`/`set_active_wave`/
`adjust_unit_count`) calls `validate()` afterward, same as path edits do. `wave_specs` stays sparse
at both levels of nesting -- no explicit zero counts (`adjust_unit_count` pops the key instead) and
no empty per-spawn dicts (an emptied-out spawn is dropped from its wave entirely) -- and
`Level.__post_init__` independently rejects any wave whose counts sum to zero across every spawn,
so that invariant holds at the `Level` level too, not just via the editor's own UI. Which spawn a
given enemy starts from is decided once, when `_begin_wave()` builds one queue per spawn from that
spawn's own composition -- no more randomness involved in *that* choice (branching further along the
route, past the spawn, is still `pathing.sample_route`'s weighted-random job, unchanged). Every
spawn's own queue still spawns its species together, one type fully before the next -- interleaving
species order *within* one spawn's queue is a possible future refinement the data shape doesn't need
to anticipate. Across *different* spawns, though, `WaveManager` keeps every queue in lockstep: each
`spawn_interval` tick, `_spawn_next_round()` pops one enemy from *every* spawn queue that still has
one, all spawning together on the same tick -- the 1st enemy from every spawn goes out at once, then
the 2nd from every spawn that still has one, and so on, rather than one spawn's whole queue draining
before the next spawn's even starts. A spawn with fewer enemies queued for the wave just stops
contributing to later rounds once its own queue empties; it doesn't hold the others back or get
padded with empty turns to stay in sync.

`persistence/persistence.py` is the only file I/O of game data anywhere in the codebase: `save_level`/
`load_level_file`/`list_custom_levels` (de)serialize a `Level` to JSON under `custom_levels/`
(gitignored -- local player data, not shipped content), slugging the level's name into a stable
filename/id with a numeric suffix on collision. `list_custom_levels` skips a corrupt or
hand-edited-invalid file rather than crashing the whole level-select screen, same spirit as
`AssetManager` falling back to a placeholder instead of crashing on a missing sprite. A saved level
persists across game sessions with no extra work -- `Game._enter_level_select()` calls
`list_custom_levels()` fresh every time it's entered, reading straight off disk, so a level saved in
an earlier run shows up exactly like one saved this session. Since the saved file is just
self-contained JSON with no player-specific data, it doubles as this game's map-sharing mechanism:
handing someone the file and having them drop it into their own `custom_levels/` is enough --
`Game.last_saved_path` (shown in the wave editor's sidebar after Save, see `presentation/ui.py`) exists purely to
tell the player where to find that file on disk to go do that.

`ui.build_level_thumbnail(level, width, height)` renders a level's `path_cells`/`spawn_cells`/
`goal_cells` as a small static image -- a `(width, height)` surface at exactly `GRID_COLS:GRID_ROWS`
aspect ratio so each cell maps to a perfect square, colored ground/path fills plus spawn/goal dots,
no `AssetManager` sprites involved (same placeholder-shape spirit as `AssetManager`'s own fallback,
appropriate at this scale regardless of whether an art pack is installed). `Game._enter_level_select()`
builds one thumbnail per entry (`level_select_thumbnails`, keyed the same as `level_select_entries`/
`level_select_rects`) so the level-select screen reads as an actual visual map browser, not just a
list of names.

The level browser (`GameState.LEVEL_SELECT`) serves two different purposes from the same screen,
tracked by `Game.level_select_purpose` ("play", the default, or "edit") and threaded through to
`ui.draw_level_select_screen` for its title/back-hint/tag text: entered via the menu's `L`, it lists
built-ins and custom levels together and picking one starts playing it as **Practice** -- always
`sandbox=True`, never gated by anything, earning nothing (see "Difficulty modes, Sandbox/Practice
mode, and player settings" below); entered via the editor's "Load Map..." action (`Game._handle_editor_action`'s `"load"` branch,
`_enter_level_select(purpose="edit")`), it lists **only** custom levels -- a built-in one has no
corresponding file to reopen -- and picking one calls `Editor.load_level(level)` instead, then
returns to `GameState.EDITOR` rather than `PLAYING`. `Editor.load_level()` is a full replace of every
buffer (path/spawn/goal cells, wave_specs, active wave/spawn/tool), copied at every level of nesting
so later edits never mutate the `Level` it was loaded from -- there's no merge or unsaved-changes
warning, same as Playtest/Save never asking about unsaved changes anywhere else in this editor.
Escape from `LEVEL_SELECT` returns to wherever it was entered from (`MENU` for "play", `EDITOR` for
"edit"), driven by the same `level_select_purpose`.

More rows than fit between `ui.LEVEL_SELECT_TOP` and `ui.LEVEL_SELECT_BOTTOM` scroll with the mouse
wheel rather than running off-screen unreachably: `Game.level_select_scroll_offset` (reset to 0 by
`_enter_level_select`, updated and clamped to `ui.level_select_max_scroll(len(entries))` by
`_scroll_level_select` on every `pygame.MOUSEWHEEL` event) feeds into
`ui.build_level_select_rects(entries, scroll_offset)`, which is what actually shifts row positions --
`Game._rebuild_level_select_rects()` is the one place that combines the two and is called both on
entry and after every scroll, so `level_select_rects` (read by both the click handler and `render()`)
is never stale. `Game._handle_level_select_click` fences `pos` to that same viewport *before* doing
any hit-testing -- a row scrolled off the top or bottom still has a real (if currently useless) `Rect`
whose geometry can extend into the title/hint areas, so without that fence a click there could match
a row that isn't actually visible. `ui.draw_level_select_screen` mirrors this on the drawing side with
an actual `surface.set_clip()` around the row loop, plus a "more above"/"more below" hint whenever
`level_select_max_scroll(...)` is nonzero.
