# Core: folder layout and the decomposed `Game`

## Organized into folders

Every source module lives in one of eight top-level package folders, grouped by domain rather than
alphabetically or by when it was added -- a repo-wide housekeeping pass that moved 40 previously-flat
`.py` files (everything except `main.py`, which stays at the repo root as the entry point) into place
with no behavior change. Every folder sits exactly one level under the repo root, deliberately not
nested any deeper (no wrapping `src/`/`td/` package) -- this project isn't pip-installed, it's run
from checkout or PyInstaller-bundled, so a `src/` layout's usual benefit doesn't apply, and staying
flat matches how `assets/`/`tests/` already sat at the root before this pass.

- `core/` -- the `Game` state machine and its decomposed slices (`Renderer`, `InputHandler`,
  `ProgressTracker`, `SettingsManager`), plus the map editor `Game` drives.
- `entities/` -- live per-level actors (`Tower`, `Enemy`, `Projectile`) and their spawn timing
  (`waves.py`) / transient visual effects (`effects.py`).
- `world/` -- a level's own geometry (`grid.py`/`pathing.py`), the spatial index used for tower
  targeting, its authored economy config, and the level registry.
- `run/` -- the roguelike run's own meta-layer: the branching map, card/relic drafting, the Shop,
  Random Events, difficulty scaling, and Daily Run seeding.
- `progression/` -- cross-run persistent progress: achievements, account-wide meta-unlocks,
  level-clear records, and per-seed run history -- as opposed to `run/`'s single-run mechanics.
- `persistence/` -- generic on-disk JSON state infrastructure (`json_io.py`), save/resume, player
  settings, keybindings, and custom level files.
- `presentation/` -- drawing (`ui.py`) and sprite/sound asset loading (`assets.py`, `audio.py`).
- `support/` -- small cross-cutting utilities and global constants (`rng_sampling.py`, `settings.py`)
  used by nearly every other package.

Every intra-project import is fully qualified against this structure (`from entities.tower import
TOWER_TYPES`, `import progression.achievements as achievements`, ...), never a relative import --
kept uniform on purpose so any import site is greppable by its target's bare module name regardless
of which package is doing the importing. The one real technical wrinkle this move required:
`json_io.module_relative_path()` (see that module's own docstring) resolves every local JSON state
file/`assets/`/`custom_levels/` path relative to the *project root*, not the calling module's own
directory directly -- it walks up two levels (package dir, then that dir's parent) precisely because
every caller now lives at this same, single level of nesting. A module moved any deeper would need
that helper's own logic extended, not just its own call site fixed up.

`Game` (`core/game.py`) is the state machine and frame loop: it owns `Grid`, `Economy`, `WaveManager`,
and the live `enemies`/`towers`/`projectiles` lists, and drives `handle_events()` ->
`update(dt)` -> `render()` each frame. `_load_level_object()` rebuilds all of that from a `Level`
in one call -- it's the single choke point every way of starting a level funnels through
(`load_level()` for a `LEVELS` id, `load_custom_level()` for an editor-authored one,
`_load_combat_node()` for a run's floor, `resume_saved_run()` for a save) -- so `reset()` /
`advance_or_replay_level()` are just "call it again."

`Game.render()` itself is a one-line delegator to `renderer.Renderer.render()` (`core/renderer.py`) --
the first cut of decomposing `Game` out of a single ~2900-line file, picked as the first slice
because it was the most self-contained: it only ever reads `Game`'s state and delegates to `presentation/ui.py`'s
drawing functions, the one exception being `_last_panel_subject` (written here, read back by
`Game._handle_panel_action_click`, see "Stats panel subject resolution" below). `Renderer` holds a
`game` reference rather than a narrower set of parameters, since `render()` reads on the order of 40
distinct `Game` attributes/methods across its own per-state dispatch -- a narrower interface would
just be the same coupling spelled out longhand. The hit-testing/query helpers `render()` calls
(`_hovered_tower()`, `_stats_panel_subject()`, ...) stay on `Game` itself, not `Renderer`, since
`_handle_click`/`_handle_panel_action_click` read those same methods to resolve what a click acts on
-- moving them would split one shared source of truth into two copies that could drift. `core/renderer.py`
imports `GameState` lazily, inside `render()` itself, to avoid a circular import (`core/game.py` ->
`core/renderer.py` -> `core/game.py`) that a top-level import would hit before `GameState` is even defined.

Input handling -- `handle_events`, `_handle_keydown`, the `_handle_*_click` family, and the two
scroll handlers (`_scroll_level_select`/`_scroll_wave_unit_list`) -- is the second slice, moved into
`input_handler.InputHandler` (`core/input_handler.py`) the same way: `Game`'s own method of each name is a
one-line delegator to the identically-named method on `self.input_handler`. The boundary drawn there
is "translates a raw pygame event (a key, a click position, a wheel delta) into a decision" moves;
"given an already-resolved semantic value, does the actual state mutation" stays on `Game` --
concretely, `_handle_editor_action`/`_handle_wave_editor_action`/`_handle_editor_undo_redo_action`
(each takes an already-resolved action *string*, not raw input) and every `_enter_*_node`/
`_resolve_*`/`_rebuild_*_rects` business-logic method stay put, called from `InputHandler` via
`game.` exactly as they always were called via `self.`. Confirmed before the move: every one of the
21 relocated methods is only ever called by another one of the 21 (mostly from `handle_events`'s own
dispatch, or `_handle_click` calling `_handle_panel_action_click`) -- never from anywhere else in
`core/game.py` -- so every such call becomes `self.` on the `InputHandler` instance, never `game.`. One
sharp edge that fell out of this: three of `Game`'s own delegators (`_handle_editor_undo_redo_keydown`,
`_handle_panel_action_click`, `_handle_static_screen_back_click`) become unreachable except by a
*direct* call, since the callers that used to reach them are now `InputHandler` methods calling their
own siblings -- each needed one small dedicated regression test calling the `Game`-level method by
name to keep coverage honest (see `test_game.py`/`test_game_editor.py`'s own "called directly" tests).

The achievement/meta-progression/toast-recording group (`_record_level_cleared`/
`_record_progress_counter`/`_record_achievement`/`_queue_achievement_toasts`/`_record_meta_progress`/
`_queue_meta_unlock_toasts`/`_queue_toast`) is the third slice, moved into
`progress_tracker.ProgressTracker` (`core/progress_tracker.py`) the same way. This slice improves on
`InputHandler`'s own precedent rather than repeating its sharp edge: this group's real callers
(`try_place_tower`/`try_upgrade_tower`/`try_specialize_tower`, `update()`'s own kill/wave/level-clear
hooks, `_advance_run_floor`, `_record_run_permadeath`, `_handle_boss_defeated`) all stay on `Game`,
rather than every caller having moved too the way `InputHandler`'s 21 methods did -- so `Game` keeps a
one-line delegator only for the 5 methods with a real external caller or a direct test reference
(`_record_level_cleared`/`_record_achievement`/`_record_meta_progress`/`_queue_meta_unlock_toasts`/
`_queue_toast`), while `_record_progress_counter`/`_queue_achievement_toasts` (called only by methods
that moved here too) get no `Game`-level shim at all -- the same "private helper, no delegator" shape
`core/renderer.py`'s own `_render_placement_preview` already established. No coverage was orphaned by this
move, so unlike `InputHandler`'s slice, no new "called directly" regression tests were needed.

Toasts (`Game.achievement_toasts`) are the one per-frame effect list that is *not* PLAYING-scoped:
most unlocks are queued off the board (a Shop/Treasure/Event relic, a floor clear's meta-unlock, a
permadeath's `runs_played` unlock), so `Game.update()` ages them on real, unscaled `dt` *before* its
own `state != PLAYING` early return, `Renderer._draw_toasts()` draws them on every full-screen run
state (MAP/DRAFT/EVENT/REST/TREASURE) and on top of the board's overlays, and a floor load no longer
clears them -- a toast queued on the map just keeps fading into the next fight.

**The game is a roguelike deckbuilder, and the run loop is its primary loop.** A single level
played on its own still works exactly as it always did, but that's now Practice, a side path; the
main path is a run. Read the next section before anything else here.
