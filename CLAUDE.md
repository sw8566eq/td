# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py                     # run the game
python main.py --unlimited-gold    # debug flag -- every purchase always succeeds, gold never spent
python main.py --editor            # launch straight into the map editor (also reachable via E from the menu)

pytest                             # full suite
pytest tests/test_grid.py          # one file
pytest tests/test_grid.py::test_non_path_cell_is_buildable   # one test
pytest -v                          # what CI runs (.github/workflows/tests.yml)
```

No linter/formatter is configured. `pyproject.toml` only sets pytest's `pythonpath`.

`Game()` and some `AssetManager` tests open a real pygame window; `tests/test_game.py` and
`tests/test_assets.py` force the SDL dummy video driver themselves
(`os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` before pygame is imported), so `pytest` runs
headless with no extra setup anywhere, including CI.

## Architecture

`Game` (`game.py`) is the state machine and frame loop: it owns `Grid`, `Economy`, `WaveManager`,
and the live `enemies`/`towers`/`projectiles` lists, and drives `handle_events()` ->
`update(dt)` -> `render()` each frame. `load_level()` rebuilds all of that from a `Level` in one
call, so `reset()` / `advance_or_replay_level()` (win -> next level, or replay the last one) are
just "call `load_level` again."

### Content is registries, not conditionals

Towers (`TOWER_TYPES` in `tower.py`), enemies (`ENEMY_TYPES` in `enemy.py`), and levels (`LEVELS`
in `levels.py`) are all `{name: class_or_instance}` dicts. `Grid`, `WaveManager`, `ui.py`'s build
menu, and `Game`'s placement logic all iterate or index these registries generically -- adding a
new tower/enemy/level is subclassing (or a new `Level(...)`) plus one registry line, never a
change to the systems that consume it. `Tower.EXTRA_STATS` (label, attribute, format-fn tuples)
is how a subclass's special mechanic (splash radius, slow %, chain range, ...) shows up in the
stats panel automatically. `Projectile` (`projectile.py`) is a single data-parametrized class, not
one subclass per tower -- splash/slow/knockback/chain are just constructor args a tower's
`create_projectile()` passes in, and the hit-resolution algorithm doesn't care which combination
it got.

### Grid has two coordinate systems

`Grid` (`grid.py`) tracks the map at two granularities at once:
- **Coarse tile coords** (`col, row`; unit = `TILE_SIZE`, 64px) -- path, blocked cells, and the
  rendered mosaic. Comes straight from a `Level`'s `path_cells`/`spawn_cells`/`goal_cells`/
  `blocked_cells` (see "Paths are a graph, not a route" below).
- **Subtile coords** (`anchor_col, anchor_row`; unit = `SUBTILE_SIZE`, `TILE_SIZE /
  SUBTILES_PER_TILE`) -- tower placement. A tower's footprint is always one tile's worth of area
  (`SUBTILES_PER_TILE x SUBTILES_PER_TILE` subtiles, currently 8x8) but can be *anchored* at any
  subtile, not just a tile boundary, which is what gives placement finer-than-a-tile precision.
  `SUBTILES_PER_TILE` must evenly divide `TILE_SIZE` (enforced in `Grid.__init__`) so every
  pixel<->subtile conversion is exact integer math.

`is_buildable`/`occupy`/`remove`/`is_occupied`/`get_tower` all operate in subtile coords; two
footprints collide if they overlap *at all* (checked against a flat `occupied_subtiles` set), not
just when their anchors match, so finer placement doesn't need anchors to line up on any grid.
`placement_anchor(x, y)` (pixel -> anchor, centered on the cursor) is deliberately **not** clamped
to stay in bounds -- an out-of-grid or edge-hugging anchor is left for `is_buildable` to reject,
rather than silently snapped somewhere the player didn't point at.

### Paths are a graph, not a route

A `Level`'s path (`path_cells`/`spawn_cells`/`goal_cells`) is a set of tiles, not one ordered
waypoint list -- it can branch (one lane fanning out into several) and merge (several spawns
converging on shared lanes toward a goal), same as anything the map editor's freeform brush can
paint. The one restriction (`pathing.validate_topology`) is that it must be a **forest**: a lane
can never split and later reconnect to itself downstream, since that specific "diamond" shape is a
closed loop in the underlying undirected adjacency graph, indistinguishable from a full roundabout.
Forbidding it is what makes `pathing.sample_route` a simple, always-terminating walk -- a tree has
exactly one simple path between any two cells, so a route never needs to backtrack or guess which
branch leads to a dead end. `pathing.PathTopology.leads_to_goal` is what keeps that walk from
wandering into a *different* spawn's own dead-end branch at a merge point -- an early version of
this validated per-cell reachability with an undirected BFS from the goal, which is trivially true
for every cell in a connected tree (you can always walk backward to it) and so never actually
caught anything; the fix was requiring every leaf of the tree to be a spawn or a goal.

`Enemy` itself needs **zero branching logic**: `WaveManager` samples one concrete flat pixel
waypoint list per spawned enemy (`pathing.sample_route`, weighted-random at branch points, default
uniform) and hands it to the same `Enemy.__init__(waypoints_px, wave_number)` as always. All of the
graph complexity lives in `pathing.py` and at spawn time, not in movement.

`levels.py`'s hand-written levels stay a terse ordered corner list (`pathing.path_cells_from_corners`
walks each axis-aligned segment into the cell set) purely as an authoring convenience; a `Level`
built by the map editor's tile-paint brush builds `path_cells`/`spawn_cells`/`goal_cells` directly,
with no corner list involved. Both end up as the exact same shape -- one representation, not two
parallel formats.

### Map editor and custom levels

`editor.py`'s `Editor` (driven by `GameState.EDITOR` in `game.py`, entered via `E` from the menu or
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

`persistence.py` is the only file I/O of game data anywhere in the codebase: `save_level`/
`load_level_file`/`list_custom_levels` (de)serialize a `Level` to JSON under `custom_levels/`
(gitignored -- local player data, not shipped content), slugging the level's name into a stable
filename/id with a numeric suffix on collision. `list_custom_levels` skips a corrupt or
hand-edited-invalid file rather than crashing the whole level-select screen, same spirit as
`AssetManager` falling back to a placeholder instead of crashing on a missing sprite.

### Tower progression is two separate axes

1. **Leveling** (1 -> `MAX_LEVEL`, currently 3): generic on the `Tower` base class.
   `LEVEL_SCALED_STATS` names which attributes scale; `LEVEL_STAT_MULTIPLIERS` is the shared
   level->multiplier curve; `LEVEL_STAT_MULTIPLIER_OVERRIDES` lets one stat use its own curve
   instead (e.g. `BasicTower`'s damage). `upgrade()` always rescales from the level-1 base
   snapshot (`_base_stats`), never compounds on an already-scaled number.
2. **Specialization**: a one-time branching choice available only at `MAX_LEVEL`
   (`Tower.can_specialize`), picking one of two named options in `Tower.SPECIALIZATIONS` (each a
   `stat_multipliers` dict applied on top of current stats). Independent of `level` -- a maxed,
   unspecialized tower and a maxed, specialized tower are both `level == MAX_LEVEL`. Every tower
   currently shares the same two generic placeholder specializations from the base class; a
   subclass can override `SPECIALIZATIONS` to offer its own.

`Tower.total_invested` (base `cost` + every upgrade/specialization cost actually paid) is what
`sell_value()` refunds a fraction of (`settings.SELL_REFUND_FRACTION`) -- selling isn't just base
`cost` * fraction.

### Stats panel subject resolution, and a click-routing gotcha

`Game._stats_panel_subject()` resolves what the sidebar shows, in priority order: the tower
currently under the mouse > a tower pinned open by clicking it (`self.selected_tower`, persists
after the mouse moves away) > the tower type currently selected to build > nothing. `render()` and
`_handle_click()` both call it, so the panel and its action buttons (Upgrade / two Specialize
choices / Sell, built by `ui.build_*_button_rect()`) always agree on which tower they act on.

Upgrade and the first Specialize button **intentionally share the same `Rect`** (`ui.py`,
`ACTION_AREA_TOP`) -- a tower is never both upgradeable and specializable at once, so they occupy
the same panel slot. `Game._handle_click` resolves a click there by the subject's *actual state*
(maxed or not), not by which `if` happens to run first -- get that backwards and a maxed tower's
click silently falls into `try_upgrade_tower` (a no-op once maxed) instead of specializing, which
is exactly the bug the regression tests around `ACTION_AREA_TOP`/`build_specialize_button_rects`
in `test_ui.py`/`test_game.py` exist to catch.

### Waves

`WaveManager` (`waves.py`) is a small state machine: `AWAITING_START` -> `BETWEEN_WAVES` ->
`SPAWNING` -> (loop) -> `DONE`. Wave 1 starts in `AWAITING_START` and never advances on its own --
`skip_delay()` (the HUD's Start/Skip button, or `Space`) is what moves it to `BETWEEN_WAVES` with
the timer zeroed, same as skipping any later between-wave countdown. Every wave after the first
auto-counts down `between_wave_delay` as normal.

### Assets

Every sprite is referenced elsewhere by a logical name (`"tower_basic"`, `"enemy_grunt"`, ...),
never a file path. `AssetManager` (`assets.py`) looks the name up in `SPRITE_MANIFEST` for a
relative path + fallback color/shape; if the file exists under `asset_root` (default `assets/`) it
loads and scales that, otherwise it synthesizes a placeholder (rounded rect / circle with an
outline at normal sizes, a plain flat fill below ~12px so tiny sprites like the map's subtile
mosaic don't collapse into a dot). Dropping in real art is a files-only change -- no code changes
unless filenames differ from the manifest.

### Economy debug flag

`Economy.unlimited_gold` (set via `Game(unlimited_gold=...)`, which `main.py --unlimited-gold`
threads through) makes `can_afford()` always `True` and `spend()` a no-op that leaves `gold`
untouched -- every purchase path (place/upgrade/specialize a tower) needed no changes to support
it. `ui.py`'s HUD shows `"Gold: unlimited"` while it's set.
