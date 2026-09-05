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
pytest tests/test_run.py           # one file
pytest tests/test_grid.py::test_non_path_cell_is_buildable   # one test
pytest -v                          # what CI runs (.github/workflows/tests.yml)

pyinstaller --onedir --name td --add-data "assets:assets" main.py   # build a Linux release binary locally -- see "Release binary" below
```

No linter/formatter is configured. `pyproject.toml` only sets pytest's `pythonpath`.

`Game()` and some `AssetManager` tests open a real pygame window, so the SDL dummy video driver is
forced before pygame is ever imported (`os.environ.setdefault("SDL_VIDEODRIVER", "dummy")`) --
once in `tests/conftest.py` for every `Game`-level module, and again in `tests/test_assets.py`,
which stands alone. `pytest` runs headless with no extra setup anywhere, including CI.

The `Game`-level tests are split three ways by concern, all drawing fixtures (`game`/
`playing_game`) and helpers (`find_buildable_anchor`, `cell_center_px`, `make_custom_level`, the
`mock_mouse_pos`/`mock_key_mods` pairs) from `tests/conftest.py`: `tests/test_game.py` (state
machine, input handling, the update loop, rendering), `tests/test_run.py` (the roguelike run
lifecycle end to end), and `tests/test_game_editor.py` (the map editor, wave editor, and level
browser screens as `Game` drives them). `Editor` itself is still tested directly in
`tests/test_editor.py`.

## Architecture

`Game` (`game.py`) is the state machine and frame loop: it owns `Grid`, `Economy`, `WaveManager`,
and the live `enemies`/`towers`/`projectiles` lists, and drives `handle_events()` ->
`update(dt)` -> `render()` each frame. `_load_level_object()` rebuilds all of that from a `Level`
in one call -- it's the single choke point every way of starting a level funnels through
(`load_level()` for a `LEVELS` id, `load_custom_level()` for an editor-authored one,
`_load_floor()` for a run's floor, `resume_saved_run()` for a save) -- so `reset()` /
`advance_or_replay_level()` are just "call it again."

**The game is a roguelike deckbuilder, and the run loop is its primary loop.** A single level
played on its own still works exactly as it always did, but that's now Practice, a side path; the
main path is a run. Read the next section before anything else here.

### The roguelike run loop is the primary loop

A **run** is a seeded, ordered sequence of floors, each floor one full `_load_level_object()` pass
on one `Level` -- the same complete `Grid`/`Economy`/`WaveManager`/towers/enemies reset a level load
always did. What's new is `RunState` (`run_state.py`), the small bundle that survives *across* those
resets: seed, `floor_sequence`, `floor_index`, `difficulty`, lives, gold, `unlocked_towers`, and
`relics`. Placed towers and the grid stay floor-scoped, deliberately -- a deckbuilder doesn't carry
board state between combats, only your deck and your HP. `Game.active_run` holds it, and is reset to
`None` inside `_load_level_object()` itself (not at each call site), so any loader that doesn't know
about runs -- `resume_saved_run()` for a classic save, say -- structurally can't leak a stale
`RunState` into a non-run level.

The pieces, each a small module in this codebase's registry-or-bare-function style:

- `run_floors.py` -- `sample_floor_sequence(rng, count=6)`: ids sampled from `LEVELS` *without*
  reordering. Deliberately not a shuffle: `LEVELS`' ids already read as an authored difficulty ramp,
  so ascending order is what makes a run escalate rather than occasionally front-loading a hard map.
- `card_pool.py` -- a "card" is, for v1, exactly a `TOWER_TYPES` key. `STARTER_TOWERS` is what every
  run begins with; `draft_offer(rng, run, ...)` samples `count` names from the account-wide unlocked
  pool minus what the run already holds, returning *fewer* than `count` once exhausted rather than
  raising. `_default_unlocked_pool` reorders into `TOWER_TYPES`' own registry order before sampling
  -- `rng.sample`'s result depends on its input's order, so feeding it a raw `set` would silently
  break "the same seed offers the same cards" across two process launches.
- `relics.py` -- `RELICS`, a registry of run-wide passive modifiers, plus `relic_offer()` (mirroring
  `draft_offer`) and `compose_relic_modifiers()` (which composes only the two fields that genuinely
  recur every floor a relic is held, `gold_per_floor_bonus`/`enemy_gold_multiplier` -- a relic's
  other two fields, `starting_gold_multiplier`/`starting_lives_bonus`, are a one-time bonus applied
  directly at draft-pick time instead, see `Game._apply_one_time_relic_bonus`; `RelicModifiers`
  itself has no fields for them at all). Not unlock-gated, unlike tower cards.
- `run_escalation.py` -- `escalation_for_floor(floor_index)`, a bare formula rather than a registry
  precisely because `floor_index` is unbounded once the final floor's endless tail runs.
- `meta_progression.py` / `run_history.py` -- cross-run persistence; see the on-disk-state section.

`Game.start_new_run(seed=None, is_daily=False)` builds the `RunState` and calls `_load_floor(0)`.
`_load_floor` composes *three* independent extra factors into the one `_load_level_object()` call --
the run's snapshotted `difficulty`, `escalation_for_floor(floor_index)`, and
`compose_relic_modifiers(run.relics)` -- each an extra multiplier on top of what's already there,
never a replacement, per `difficulty.py`'s own rule. Floor 0 is the one asymmetric case: `RunState`
starts with `lives=gold=0` as a placeholder and *captures* floor 0's freshly-loaded `Economy`,
while floor 1 onward *restores* into it instead.

Clearing a floor goes `update()`'s win-check -> `_advance_run_floor()` -> `GameState.FLOOR_CLEARED`
-> (any key) `_enter_draft()` -> `GameState.DRAFT` -> (click) `_handle_draft_click()` ->
`_load_floor(next)`. Two details worth knowing:

- `_enter_draft` picks the draft's *kind* by floor (`_is_relic_floor`: every
  `relics.RELIC_FLOOR_INTERVAL`-th, so a 6-floor run's 5 draft screens -- one per floor cleared, the
  6th never clears once it's loaded `endless=True` -- alternate 3 tower / 2 relic, never both at
  once). A relic floor with nothing left to offer (every relic already held -- unreachable at the
  current `RELICS`/`RELIC_FLOOR_INTERVAL` tuning, since a run can never hold more relics than it has
  relic-draft floors for) falls back to a tower draft on the same rng/floor instead; only skips the
  screen entirely -- straight to the next floor -- if that also comes up empty.
- The next floor isn't loaded until a card is actually picked, which is what leaves
  `self.towers`/`self.economy` intact for `FLOOR_CLEARED` to render real results from.

A run ends **only** by permadeath. The last floor always loads `endless=True`, so
`all_waves_complete` structurally can never fire for it, and `update()`'s win-check routes a run to
`_advance_run_floor()` rather than `VICTORY` regardless -- there is no "you won the run" event by
construction, not by a missing branch. `_record_run_permadeath()` writes the outcome to
`run_history.py` and bumps the meta-progression counters.

Both RNG streams a floor needs (its own enemy routing, and its draft offer) are re-derived from
`(run.seed, floor_index)` on demand via `Game._run_rng(run, stream, floor_index)` rather than
carried as one continuously-consumed `random.Random`. That's what lets `save_state.py` serialize a
run without serializing any RNG state at all -- a resumed run just re-derives the identical objects
(`resume_saved_run()` is why `run` is a parameter here rather than read off `self.active_run`: it
needs this derivation *before* `_load_level_object()` sets `self.active_run`). The seed itself is a
string (`f"{run.seed}:{stream}:{floor_index}"`), not `run.seed * stream + floor_index` -- that
integer scheme degenerated to plain `floor_index` for every stream whenever `run.seed == 0`,
colliding the two streams; a string has no such degenerate case.

A **Daily Run** is not a separate mode: `_start_daily_challenge()` is
`start_new_run(seed=todays_seed(), is_daily=True)`. `is_daily` changes exactly one thing -- the run
snapshots `"normal"` instead of the player's sticky difficulty preference, so scores are comparable.
`run_history.py` already tracks `{seed: best_floors_cleared}` for any seed, so a date-derived seed
needs no special handling anywhere.

### Content is registries, not conditionals

Towers (`TOWER_TYPES` in `tower.py`), enemies (`ENEMY_TYPES` in `enemy.py`), and levels (`LEVELS`
in `levels.py`) are all `{name: class_or_instance}` dicts. `Grid`, `WaveManager`, `ui.py`'s build
menu, and `Game`'s placement logic all iterate or index these registries generically -- adding a
new tower/enemy/level is subclassing (or a new `Level(...)`) plus one registry line, never a
change to the systems that consume it. The run loop added one wrinkle to exactly one of those
consumers: the build menu is built from `Game._active_tower_names()` (a run's own
`unlocked_towers` while one is active, `ui.TOWER_ORDER` otherwise) rather than `TOWER_TYPES`
directly, rebuilt on demand by `_rebuild_button_rects()` inside `_load_level_object()` -- the same
"rebuilt on demand, never cached once" precedent `level_select_rects` already set. `try_place_tower`
re-checks membership itself as defense in depth, since `selected_tower_name` could in principle
outlive the menu that set it. `Tower.EXTRA_STATS` (label, attribute, format-fn tuples)
is how a subclass's special mechanic (splash radius, slow %, chain range, ...) shows up in the
stats panel automatically. `Projectile` (`projectile.py`) is a single data-parametrized class, not
one subclass per tower -- splash/slow/knockback/chain are just constructor args a tower's
`create_projectile()` passes in, and the hit-resolution algorithm doesn't care which combination
it got.

### Boss enemy mechanics

`BossEnemy` (`enemy.py`) layers two self-contained, one-time mechanics on top of the generic
`Enemy` base, following the same "override `take_damage()`/`update()`, guard `is_dead`/
`reached_goal` first" shape `ShieldedEnemy`'s regenerating shield already established: **enrage**
(a permanent speed multiplier once HP drops to/below `ENRAGE_HP_FRACTION` of `max_hp`, capped at
`max_speed` like any other speed change) and a one-time **armor phase** (a flat damage reduction
for `ARMOR_DURATION` seconds once HP drops to/below the lower `ARMOR_HP_FRACTION`, absorbed the
same way `ShieldedEnemy`'s shield eats damage before HP does). Both thresholds are checked against
`self.max_hp` *at the moment of the check*, never a value cached in `__init__` -- `WaveManager.
_spawn_enemy` multiplies `max_hp`/`hp` by the active difficulty's `enemy_hp_multiplier` *after*
construction (the same reason it already has a `hasattr(enemy, "max_shield")` patch-up for
`ShieldedEnemy`), so a threshold baked in early would silently fire at the wrong HP on Easy/Hard.

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
it was copied from.

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
`AssetManager` falling back to a placeholder instead of crashing on a missing sprite. A saved level
persists across game sessions with no extra work -- `Game._enter_level_select()` calls
`list_custom_levels()` fresh every time it's entered, reading straight off disk, so a level saved in
an earlier run shows up exactly like one saved this session. Since the saved file is just
self-contained JSON with no player-specific data, it doubles as this game's map-sharing mechanism:
handing someone the file and having them drop it into their own `custom_levels/` is enough --
`Game.last_saved_path` (shown in the wave editor's sidebar after Save, see `ui.py`) exists purely to
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

### Tower progression is two separate axes

1. **Leveling** (1 -> `MAX_LEVEL`, currently 3): generic on the `Tower` base class.
   `LEVEL_SCALED_STATS` names which attributes scale; `LEVEL_STAT_MULTIPLIERS` is the shared
   level->multiplier curve; `LEVEL_STAT_MULTIPLIER_OVERRIDES` lets one stat use its own curve
   instead (e.g. `BasicTower`'s damage). `upgrade()` always rescales from the level-1 base
   snapshot (`_base_stats`), never compounds on an already-scaled number.
2. **Specialization**: a one-time branching choice available only at `MAX_LEVEL`
   (`Tower.can_specialize`), picking one of two named options in `Tower.SPECIALIZATIONS` (each a
   `stat_multipliers` dict applied on top of current stats). Independent of `level` -- a maxed,
   unspecialized tower and a maxed, specialized tower are both `level == MAX_LEVEL`. `Tower`'s own
   `SPECIALIZATIONS` (`"power"`/`"precision"`, generic damage/range-and-rate buffs) is a fallback
   for a tower with no distinctive mechanic to name a specialization after -- every concrete
   `TOWER_TYPES` entry overrides it with its own tower-specific pair playing off that tower's own
   `EXTRA_STATS` mechanic instead (e.g. `CannonTower`'s bigger-splash-radius vs. bigger-damage,
   `FrostTower`'s colder-slow vs. longer-slow-duration -- note `slow_factor` is the one stat in the
   whole registry where *smaller* is the buff direction, the opposite of everything else here), down
   to `BasicTower`/`SniperTower`, which have no unique mechanic to key off and so just get their own
   names/tuning on the same damage/range/fire_rate stats. `BasicTower` deliberately keeps the base
   class's literal `"power"`/`"precision"` *keys* (only its values/flavor text differ) since several
   tests exercise the generic `specialize()` mechanism via a default-constructed `BasicTower` and
   hardcode those two key strings.

### Support towers and the two-pass update loop

`SupportTower` (`tower.py`) is the one `TOWER_TYPES` entry that never attacks at all
(`damage = fire_rate = 0`, `IS_SUPPORT = True`) -- instead, every frame, it buffs every *other*
tower within its `range` (`buff_damage_multiplier`/`buff_range_multiplier`, its own
`LEVEL_SCALED_STATS` in place of the now-meaningless `damage`). This needed one real change to
`Game.update()`: towers are updated in **two passes** -- every tower's `reset_aura()` runs before
any tower's own `update()` does -- so a `SupportTower` later in `self.towers` still gets to
(re-)buff a tower earlier in the list within the same frame, regardless of iteration order.
`Tower.receive_aura()` takes the `max()` of every buff offered that frame rather than stacking them,
so several overlapping support towers don't compound into an ever-growing buff, and a tower that
walks out of every support tower's range this frame reverts to `1.0x` (via `reset_aura()`) rather
than keeping a stale buff. Every attack path reads `effective_damage()`/`in_range()` (which fold the
current aura multiplier in) instead of `self.damage`/`self.range` directly, so a buffed tower's own
stats shown in the sidebar and its actual shots always agree. `ui.py`'s stats panel and
`Game._handle_panel_action_click` both check `IS_SUPPORT` to skip the targeting-mode row and the
plain Damage/Range/Fire-rate stat block, which would otherwise show a meaningless
`"Damage: 0.0"`/a clickable targeting mode a support tower never reads.

### Post-level results

Every `Tower` tracks its own lifetime `shots_fired`/`shots_hit`/`damage_dealt`/`kills` purely for
display -- no gameplay logic ever reads them. `Projectile._apply_hit_effects()` is the one place
that attributes a hit back to `self.source` (the firing tower), counting `shots_hit`/`damage_dealt`/
`kills` once per *projectile* even for a splash/chain shot that actually touches several enemies at
once (matching how `shots_fired` itself is counted once per fire in `Tower.update()`, not once per
enemy it eventually hits). `Game.try_sell_tower()` moves a sold tower into `self.sold_towers` rather
than discarding it, so a tower's stats still show up in the results table even after being sold
mid-level -- `Game._tower_results()` reports on `self.towers + self.sold_towers` together.
`ui.compute_tower_results()`/`draw_results_table()` render that as a compact, damage-sorted table
capped at `RESULTS_MAX_ROWS` rows (with a "+N more" line for the overflow) underneath the Victory,
Game Over, and Floor Cleared overlays alike (a run's floor clear is the common case now -- see
`_advance_run_floor`'s docstring for why the just-cleared floor's towers are still live at that
point) -- `accuracy` is `None` (not `0`) for a tower that never got a shot
off, which is *every* `SupportTower`, so the table shows `"--"` rather than a misleading `0%`.

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

**Endless (Survival) mode** is the same state machine with one exit removed: constructed with
`endless=True`, `WaveManager._advance_after_clear()` never transitions to `DONE` once the last
authored wave clears -- instead it calls `endless_wave_generator(level, next_wave_number)` (default
`_default_endless_wave`: take the *immediately preceding* wave's own per-spawn composition and bump
every count by `max(1, count // 4)`) and appends the result onto `level.wave_specs`, so growth
compounds off whatever the last wave actually was rather than the level's original final wave --
unbounded escalation, not a curve that flattens out. `all_waves_complete` staying permanently
`False` is what keeps `Game.update()`'s win-check from ever firing for a genuine endless run (it
only ever reaches `GAME_OVER`). Because `WaveManager.level` and `Game.level` are the *same object*,
appending a generated wave would otherwise permanently leak it into the shared `LEVELS` registry
singleton for a built-in level -- `Game._load_level_object` sidesteps this with
`dataclasses.replace(level, wave_specs=list(level.wave_specs))` whenever `endless=True`, so every
endless run gets its own private wave list to grow. `Game.level_select_endless_armed` (toggled by
`V` while browsing to play, reset every time the browser reopens) is what threads `endless=True`
into whichever level gets picked next; it's independent of, and combinable with, Sandbox mode (see
below).

### Difficulty modes, Sandbox/Practice mode, and player settings

`difficulty.py`'s `DIFFICULTY_MODES` registry (easy/normal/hard, same `{key: ...}` shape as every
other registry in this codebase) is a bundle of multipliers -- `enemy_hp_multiplier`/
`enemy_speed_multiplier`/`enemy_gold_multiplier`/`starting_gold_multiplier`/
`starting_lives_multiplier` -- composed as an *extra* factor on top of `Enemy`'s own existing
per-wave scaling math, never replacing it. `"normal"` is every multiplier at `1.0`, so picking it is
byte-for-byte the pre-difficulty behavior -- neither `Enemy` nor `Economy` needed any changes to
support this; `WaveManager._spawn_enemy` (enemy stats, applied post-construction) and
`Game._load_level_object` (starting gold/lives) are the only two application points. The active
difficulty is a **sticky, cross-session player preference** (`self.difficulty`, persisted via
`player_settings.py`), read at `_load_level_object` time -- changing it mid-level has no effect
until the next level load, the same "applies on next load" precedent `unlimited_gold` already set.

**Sandbox/Creative mode** is a player-reachable, per-level alternative to the CLI-only
`--unlimited-gold` debug flag, threaded through `load_level`/`load_custom_level`/
`_load_level_object` exactly parallel to `endless` above (a sticky `self.sandbox`). It used to be
its own independent level-select toggle (`B`, alongside `V`'s endless toggle); the run loop's
Practice mode (below) absorbed that entirely -- picking any level to play always loads
`sandbox=True` now, unconditionally, so there is no `B` key or `level_select_sandbox_armed` flag
left to arm it separately. It sets both `Economy.unlimited_gold` and a new `Economy.invulnerable`
(`lose_life()` becomes a no-op, `is_out_of_lives` stays `False` regardless of `self.lives`,
mirroring `unlimited_gold`'s "never actually deducted" precedent rather than a decrement-then-clamp
`ui.py` would then have to also mask). A sandbox win intentionally does *not* record progress or
bump any achievement/meta-progression counter -- trivializing victory shouldn't trivialize real
progress -- the same reasoning that already keeps a genuine endless run's `all_waves_complete` from
ever firing at all. `Game._record_level_cleared()`'s own `if self.sandbox: return` is the one gate
for the `progress.py` half; `_record_achievement`/`_record_meta_progress` share a second one inside
`_record_progress_counter()`, the helper both delegate to, rather than either repeating it at its
own call sites. `_record_run_permadeath()` carries a third, separate `if self.sandbox: return` of
its own -- its `run_history.record_run_result()` call has no sandbox awareness to delegate to, so
this one guard can't be folded into the shared helper the other two use.

**Practice mode** is what absorbed "play a level standalone": `LEVEL_SELECT`'s play purpose always
loads `sandbox=True`. That's a deliberate design position, not an implementation detail -- real
progress comes only from playing a run, so a standalone level is explicitly a place to experiment
and earns nothing. It's also what retired `progress.is_unlocked()`: with no progress to gate on and
no gate to apply it to, sequential campaign unlocking was removed outright rather than left
half-wired (see the `progress.py` bullet below for what survived).

The `GameState.SETTINGS` screen (`S` from the menu) is where `fullscreen` and `difficulty` actually
get changed (`ui.draw_settings_screen`/`get_clicked_settings_option`); both persist immediately on
change via `player_settings.save_settings()` rather than only on quit, the same "write through
immediately" choice `progress.mark_level_cleared()` and the achievement/meta-progression/save-state
modules below all make too.

### Small on-disk JSON state files: progress, achievements, meta-progression, run history, and a saved run

Six modules now follow the exact same shape for local player data: one JSON file, a defensive
`load_*()` that falls back to an empty/default state on a missing or corrupt file rather than
crashing (same spirit as `AssetManager` falling back to a placeholder sprite), and a path that's
always injectable (`Game.__init__`'s `progress_path`/`settings_path`/`achievements_path`/
`save_path`/`meta_progression_path`/`run_history_path` params) so tests never touch the real
repo-root files. All six are gitignored -- local player data, not shipped content, same as
`custom_levels/`. That shared shape isn't just convention --
`json_io.load_json_with_fallback(path, transform, default)` is the one function every one of those
`load_*()`s is ultimately built on (`achievements.load_achievements()`/`meta_progression.
load_meta_progression()` go through `threshold_unlocks.load_counters_state()`'s own thin wrapper
around it, since those two share their load/save/bump mechanics -- see the `meta_progression.py`
bullet below for that split -- rather than calling it directly themselves): it does the file-exists
check and `try`/`except` itself, and takes
`transform` (parsed JSON -> whatever shape the caller wants, also where a caller raises on
well-formed-but-semantically-invalid data, e.g. `save_state.load_run()`'s tower-type checks) and
`default` (a zero-arg callable, not a plain value, so a mutable fallback like `dict`/`list` is never
accidentally shared across calls) as the two places each module still supplies its own behavior.
`json_io.module_relative_path(module_file, *parts)` factors out the other shape all eight
on-disk-state modules share (the six above, plus `persistence.py`'s `LEVELS_DIR` and `assets.py`'s
`DEFAULT_ASSET_ROOT`): a path anchored to the calling module's own `__file__`, not the process's
current working directory -- see "Release binary" below for why that distinction matters for a
packaged build. Before this was factored out, each independently wrote the same
`os.path.join(os.path.dirname(os.path.abspath(__file__)), ...)` expression.

- `progress.py` tracks `{level_id: best_lives_remaining}`. It is now a *record*, not a gate: it
  used to also own sequential unlocking (`is_unlocked()`), which the run loop retired outright --
  a run picks its own floors, `meta_progression.py` gates what the draft can offer, and Practice
  plays anything immediately, so there was nothing left for it to gate. `Game._record_level_cleared()`
  is the single writer, called from both `_advance_run_floor()` (a floor clear -- the common case
  now) and `update()`'s `VICTORY` branch (Practice/editor playtest). Keeping those two paths on one
  helper is load-bearing rather than tidiness: the bookkeeping used to live inline in the `VICTORY`
  branch alone, which a run never reaches, so `progress.py` and the `distinct_levels_cleared`
  achievement derived from it had quietly become unreachable in normal play. A custom
  (editor-authored) level still bumps the naive `levels_cleared` tally but is never recorded here --
  it has no registry id to key on.
- `achievements.py` is a registry (`ACHIEVEMENTS`, same shape as every other registry) of
  unlockable achievements, each keyed off a threshold on one of a handful of cumulative lifetime
  counters (kills, towers built/maxed/specialized, levels cleared, waves survived). `bump()` mirrors
  `progress.mark_level_cleared()`'s exact load-mutate-save-return shape, so it's always safe to call
  from wherever the relevant event actually happens with no in-memory counters of its own to go
  stale. Every counter is bumped from `Game` itself (`try_place_tower`/`try_upgrade_tower`/
  `try_specialize_tower` on success, and a few points in `update()`) -- **never** from inside
  `Tower`/`Enemy`/`Economy`, since `resume_saved_run()` (below) reconstructs a resumed tower via
  `Tower.upgrade()`/`specialize()` directly, and a counter living inside those methods would
  silently double-count on every resume. The sandbox guard lives once inside the shared
  `_record_progress_counter()` helper `_record_achievement`/`_record_meta_progress` both delegate
  to, rather than at each of *their* own call sites, mirroring `_record_level_cleared`'s own single
  guard.
- `meta_progression.py` is the run loop's cross-run unlock registry (`META_UNLOCKS`: one
  `TOWER_TYPES` name each, gated on a threshold on `total_floors_cleared`/`runs_played`/
  `runs_reached_endless`), sharing its load/save/bump-counter mechanics with `achievements.py` via
  `threshold_unlocks.py`'s own `load_counters_state`/`save_counters_state`/`bump_counter`/
  `set_counter` (each module's own `load_*`/`save_*`/`bump()` just delegates its body to these,
  supplying its own registry/path/schema version) while keeping a genuinely separate file, registry,
  and JSON state.
  The split is intentional: achievements are cosmetic/trophy-flavored, meta-progression unlocks are
  gameplay-flavored -- they change what `card_pool.draft_offer()` can offer a future run.
  `Game._record_meta_progress()` mirrors `_record_achievement()` exactly, sandbox guard included.
  `unlock_knockback`'s goal of `1` is load-bearing: `_advance_run_floor` bumps
  `total_floors_cleared` *before* the player reaches the draft screen, so a brand-new player's very
  first draft has a real card to offer instead of finding `STARTER_TOWERS` exhausted and silently
  skipping.
- `run_history.py` records `{seed: best_floors_cleared}`, written once per run by
  `_record_run_permadeath()`. Per-seed max rather than last-write, which is what makes a replayed
  seed (a Daily Run's date-derived one) keep its best result -- and why a Daily Run needs no special
  handling here at all, it's just another seed.
- `save_state.py` saves a single in-progress session -- but **only** between waves. ("Session," not
  "run": `save_run()`/`can_save_run()`/`resume_saved_run()`/`_resumed_from_save` predate the
  overhaul and name *whatever's being played*, classic level or roguelike run alike -- unrelated to
  `RunState`/`Game.active_run`/`start_new_run()`, which are always the roguelike run specifically.
  A rename would touch ~60 production call sites plus every test, so it's left alone; the prose
  here says "session" for the save-file sense precisely to keep the two apart on the page even
  though the code itself doesn't.)
  (`Game.can_save_run()`: `WaveManager.state` in `AWAITING_START`/`BETWEEN_WAVES`), so there's no
  live enemy/projectile/effect state to serialize at all; a resumed run always starts from a clean
  wave boundary. It reuses `persistence.level_to_dict`/`level_from_dict` for the level blob (an
  endless run's already-appended escalation waves live directly on `game.level.wave_specs` by save
  time, so they're captured for free) and snapshots the run's *own* difficulty rather than
  `self.difficulty` -- the live, sticky player preference could have changed between saving and
  resuming, and applying new multipliers mid-run to waves already fought under the old ones would be
  inconsistent. `Game.resume_saved_run()` reconstructs via `_load_level_object()` directly (never
  `load_level()`'s `LEVELS[id]` re-lookup, even for a built-in id -- that would silently discard the
  endless escalation above) and rebuilds each tower via `TOWER_TYPES[name](...)` plus replaying
  `upgrade()`/`specialize()` the right number of times, bypassing `Game.try_upgrade_tower`/
  `try_specialize_tower` entirely so resuming never re-charges gold. `WaveManager.restore()` is the
  one method that actually mutates `wave_index`/`state`/`between_wave_timer` from outside, kept as a
  single guarded entry point (rejecting anything but the two resumable states) rather than `Game`
  poking those fields directly. `Game._resumed_from_save` -- true only between a `resume_saved_run()`
  call and that run's own eventual `GAME_OVER`/`VICTORY` -- is what gates deleting the save file on
  conclusion, so a fresh, unrelated session's own victory can never delete a different, still-valid
  save left over from some other abandoned run. An explicit `_load_level_object()` parameter
  (default `False`), mirroring `active_run` just below it: `resume_saved_run()` passes `True`
  directly; `_load_floor()` passes `self._resumed_from_save` straight through unchanged on every one
  of a run's own floor transitions (resumed or not, it's still the same session continuing); only
  `start_new_run()` -- the one place a genuinely *new* session begins -- explicitly resets it first.
  An optional `"run"` key carries the `RunState` (validated on load against `LEVELS`/`TOWER_TYPES`/
  `RELICS`); `None` means a save with no active run -- Practice, an editor playtest, or a file
  written before the key existed -- and is passed straight through to `_load_level_object()`'s
  `active_run` parameter either way, so its one `_rebuild_button_rects()` call already produces the
  right menu (the run's drafted pool, or every tower) with nothing left to fix up afterward. No RNG
  state is serialized: a run's streams are re-derived from `(seed, floor_index)` on demand (see the
  run loop section above).

### Visual effects: the drain-a-per-frame-event-list idiom

`effects.py` holds small, short-lived, data-parametrized visual effects -- `FloatingText` (a
rising, fading damage-number popup) and `ExpandingRing` (a growing, fading ring, reused for both a
splash-blast flash and an enemy death poof via different constructor args, the same "one class,
several constructor-arg shapes" spirit as `Projectile` itself). Both are spawned via the same
idiom: the thing that actually causes the effect (`Enemy.damage_events`, a list of raw damage
amounts appended in `take_damage()` and cleared every frame; `Projectile.impact_events`, one
`(impact_pos, splash_radius_or_None)` tuple appended once per resolved hit in `_resolve_hit()`,
counted once per *projectile* the same way `shots_hit` already is) has zero knowledge of
`effects.py` at all -- `Game.update()` is the one place that drains each per-frame list into an
owned, aged-and-pruned effect list (`self.damage_numbers`/`self.impact_effects`) every frame, in
each case *before* whatever produced the event (a dead enemy, a dead projectile) is actually
removed, so a killing blow's own popup/flash still spawns at the position it landed rather than
being silently dropped. Adding a new transient visual effect anywhere in this codebase means
following this same three-step shape: a class in `effects.py`, a per-frame event list on whatever
produces the event, and one drain site in `Game.update()` -- never a new effect spawned directly
from inside `Enemy`/`Projectile`/`Tower`, which would couple simulation logic to rendering.

### Assets

Every sprite is referenced elsewhere by a logical name (`"tower_basic"`, `"enemy_grunt"`, ...),
never a file path. `AssetManager` (`assets.py`) looks the name up in `SPRITE_MANIFEST` for a
relative path + fallback color/shape; if the file exists under `asset_root` (default
`DEFAULT_ASSET_ROOT`, an `assets/` folder resolved relative to `assets.py`'s own location, not the
process's current working directory -- see "Release binary" below for why that distinction matters
for a packaged build) it loads and scales that, otherwise it synthesizes a placeholder (rounded
rect / circle with an outline at normal sizes, a plain flat fill below ~12px so tiny sprites like
the map's subtile mosaic don't collapse into a dot). Dropping in real art is a files-only change --
no code changes unless filenames differ from the manifest.

### Economy debug flag

`Economy.unlimited_gold` (set via `Game(unlimited_gold=...)`, which `main.py --unlimited-gold`
threads through) makes `can_afford()` always `True` and `spend()` a no-op that leaves `gold`
untouched -- every purchase path (place/upgrade/specialize a tower) needed no changes to support
it. `ui.py`'s HUD shows `"Gold: unlimited"` while it's set. Sandbox mode (see "Difficulty modes,
Sandbox mode, and player settings" above) reuses this exact flag for its own unlimited-gold behavior
(`unlimited_gold=self.unlimited_gold or sandbox`) rather than introducing a second, parallel
concept -- `Economy.invulnerable` is the one genuinely new flag Sandbox needed.

### Release binary

`.github/workflows/release.yml` builds a standalone Linux binary with PyInstaller and publishes it
to a GitHub Release whenever a `v*` tag is pushed -- `requirements.txt` includes `pyinstaller`
alongside `pygame`/`pytest` for exactly this, so `pip install -r requirements.txt` is still the one
setup command that covers running, testing, *and* packaging the game. Linux only, deliberately --
this project has never had a Windows/macOS build, and nothing about the packaging step below has
been verified on either.

It's `--onedir`, never `--onefile`, and that's load-bearing rather than a style preference:
`--onefile` re-extracts every bundled file into a *fresh* temp directory on every single launch and
deletes it again on exit. `progress.py`/`achievements.py`/`player_settings.py`/`save_state.py` (see
"Small on-disk JSON state files" above) all resolve their JSON file's path relative to their own
module's `__file__` -- under `--onefile` that's a different, vanishing directory every run, so none
of progress/achievements/settings/a saved run would actually survive being closed and reopened,
even though every one of those features works perfectly when run from source. `--onedir` keeps that
directory stable (it's just the unpacked folder sitting next to the executable), so persistence
works exactly like an ordinary `python main.py` run. This was verified empirically, not assumed --
building a throwaway diagnostic executable and comparing `__file__` across two separate launches is
what caught it, since it isn't the kind of bug a single smoke-test launch would ever surface.

`assets.py`'s `DEFAULT_ASSET_ROOT` exists for the same category of reason: it used to be a bare
`asset_root="assets"` default, resolved against the process's current working directory -- fine for
`python main.py` run from the repo root (the only way this project was ever launched before a
packaged build existed), but a packaged binary double-clicked from a file manager or run via a PATH
symlink has no such guarantee about its own cwd. `DEFAULT_ASSET_ROOT` is computed once, relative to
`assets.py`'s own `__file__`, the same fix in the same spirit as the JSON state files above -- and
under PyInstaller's `--onedir`, that resolves to the bundled `assets/` folder sitting right next to
the module itself regardless of launch directory, which is also why the release build step passes
`--add-data "assets:assets"` to put it there in the first place.

The workflow runs the full test suite before building (`pytest -q`) as a last line of defense, then
tars up `dist/td` (a directory, not a single file -- `--onedir`'s whole point) and attaches it to
the release via `gh release create`, using the pushed tag itself as both the release name and the
archive's version suffix.
