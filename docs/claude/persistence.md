# On-disk JSON state

## Small on-disk JSON state files: progress, achievements, meta-progression, run history, and a saved run

Seven modules now follow the exact same shape for local player data: one JSON file, a defensive
`load_*()` that falls back to an empty/default state on a missing or corrupt file rather than
crashing (same spirit as `AssetManager` falling back to a placeholder sprite), and a path that's
always injectable (`Game.__init__`'s `progress_path`/`settings_path`/`achievements_path`/
`save_path`/`meta_progression_path`/`run_history_path`/`keybindings_path` params) so tests never
touch the real repo-root files. All seven are gitignored -- local player data, not shipped content,
same as `custom_levels/`. That shared shape isn't just convention --
`json_io.load_json_with_fallback(path, transform, default)` is the one function every one of those
`load_*()`s is ultimately built on (`achievements.load_achievements()`/`meta_progression.
load_meta_progression()` go through `threshold_unlocks.load_counters_state()`'s own thin wrapper
around it, since those two share their load/save/bump mechanics -- see the `progression/meta_progression.py`
bullet below for that split -- rather than calling it directly themselves): it does the file-exists
check and `try`/`except` itself, and takes
`transform` (parsed JSON -> whatever shape the caller wants, also where a caller raises on
well-formed-but-semantically-invalid data, e.g. `save_state.load_run()`'s tower-type checks) and
`default` (a zero-arg callable, not a plain value, so a mutable fallback like `dict`/`list` is never
accidentally shared across calls) as the two places each module still supplies its own behavior.
`json_io.module_relative_path(module_file, *parts)` factors out the other shape all nine
on-disk-state modules share (the seven above, plus `persistence/persistence.py`'s `LEVELS_DIR` and `presentation/assets.py`'s
`DEFAULT_ASSET_ROOT`): a path anchored to the calling module's own `__file__`, not the process's
current working directory -- see "Release binary" below for why that distinction matters for a
packaged build. Before this was factored out, each independently wrote the same
`os.path.join(os.path.dirname(os.path.abspath(__file__)), ...)` expression.

- `progression/progress.py` tracks `{level_id: best_lives_remaining}`. It is now a *record*, not a gate: it
  used to also own sequential unlocking (`is_unlocked()`), which the run loop retired outright --
  a run picks its own floors, `progression/meta_progression.py` gates what the draft can offer, and Practice
  plays anything immediately, so there was nothing left for it to gate. `Game._record_level_cleared()`
  is the single writer, called from both `_advance_run_floor()` (a floor clear -- the common case
  now) and `update()`'s `VICTORY` branch (Practice/editor playtest). Keeping those two paths on one
  helper is load-bearing rather than tidiness: the bookkeeping used to live inline in the `VICTORY`
  branch alone, which a run never reaches, so `progression/progress.py` and the `distinct_levels_cleared`
  achievement derived from it had quietly become unreachable in normal play. A custom
  (editor-authored) level still bumps the naive `levels_cleared` tally but is never recorded here --
  it has no registry id to key on.
- `progression/achievements.py` is a registry (`ACHIEVEMENTS`, same shape as every other registry) of
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
- `progression/meta_progression.py` is the run loop's cross-run unlock registry (`META_UNLOCKS`: one
  `TOWER_TYPES` name each, gated on a threshold on `total_floors_cleared`/`runs_played`/
  `runs_reached_endless`), sharing its load/save/bump-counter mechanics with `progression/achievements.py` via
  `progression/threshold_unlocks.py`'s own `load_counters_state`/`save_counters_state`/`bump_counter`/
  `set_counter` (each module's own `load_*`/`save_*`/`bump()` just delegates its body to these,
  supplying its own registry/path/schema version) while keeping a genuinely separate file, registry,
  and JSON state.
  The split is intentional: achievements are cosmetic/trophy-flavored, meta-progression unlocks are
  gameplay-flavored -- they change what `card_pool.draft_offer()` can offer a future run.
  `Game._record_meta_progress()` mirrors `_record_achievement()` exactly, sandbox guard included.
  `unlock_knockback`'s goal of `1` is load-bearing: `_advance_run_floor` bumps
  `total_floors_cleared` *before* the player can reach any Shop node, so a brand-new player's very
  first shop visit has a real card to offer instead of finding `STARTER_TOWERS` exhausted and silently
  skipping -- strengthened, not weakened, by the branching map: row 0 is always Combat (see "The
  run's branching map" above), so a Shop node can never be reachable before at least one floor has
  cleared.
  The tower curve itself later grew from 7 to 9 entries when Overload Cannon and Siphon Tower
  shipped -- `unlock_overload_cannon` (`total_floors_cleared=8`) and `unlock_siphon`
  (`runs_played=4`), each one notch past that curve's own prior maximum in its own counter family
  (`unlock_lightning`'s `total_floors_cleared=5`, `unlock_beacon`'s `runs_played=3`) rather than
  restarting either counter's progression from scratch.
  Once `META_UNLOCKS`' 7-tower curve started feeling exhausted too quickly (every tower unlocks
  within `runs_played<=3`), two more small, additive registries extended it to the *newest* relics
  and levels specifically -- `RelicMetaUnlock`/`RELIC_META_UNLOCKS` (`relic_key`/`counter`/`goal`,
  same shape as `MetaUnlock`) and `LevelMetaUnlock`/`LEVEL_META_UNLOCKS` (`level_id` in place of
  `relic_key`) -- deliberately two more genuinely separate classes rather than teaching `MetaUnlock`
  a "kind" discriminator, since it's read directly (`unlock.tower_name`) in a few places and heavily
  covered by existing tests. Design mirrors the tower curve exactly: only the newest content is ever
  gated (the relic-category-gaps batch's `flak_rounds`/`breach_charges`/`containment_charges`; one of
  the four multi-lane levels, `Quad Muster`, id `14`) -- every relic/level that shipped before either
  registry existed stays permanently, unconditionally available, same "only the non-starter subset"
  precedent `META_UNLOCKS` already sets for towers. Thresholds sit well past `META_UNLOCKS`' own
  curve (`runs_played`/`total_floors_cleared` goals in the 10-25 range) so there's still something to
  chase long after every tower is unlocked; `unlock_containment_charges` is gated on `bosses_defeated`
  specifically as a deliberate cross-chunk payoff with the run's final boss (see that section above)
  -- "beat the boss once" rather than a grind threshold. A second wave of gating later extended
  `RELIC_META_UNLOCKS` to two of the cross-status combo-capstone batch's three relics
  (`frostbitten_mark`/`plague_mark`, thresholds `total_floors_cleared=50`/`runs_played=20`, both
  further out than the first wave's own 10-25 range) once that first curve itself started feeling
  exhausted -- `chill_rot`, the third relic in that same batch, stays deliberately ungated so the
  mechanic itself is still reachable early (see the `run/relics.py` bullet above). A third wave
  completed that same batch's gating with `seismic_slam` (Knockback's 2nd exclusive relic, the only
  relic from that batch still ungated after the second wave) at `total_floors_cleared=75` -- past
  even `frostbitten_mark`'s 50 -- and added a second `LEVEL_META_UNLOCKS` gate, `Double Confluence`
  (id `15`, the only other ordinary multi-lane level still ungated, a genuine step up from `Quad
  Muster`'s 4-spawns-into-1-goal via 2 independent goals instead) at `runs_played=25`, past
  `unlock_quad_muster`'s 15.
  `ALL_UNLOCKS` (`{**META_UNLOCKS, **RELIC_META_UNLOCKS, **LEVEL_META_UNLOCKS, **SHOP_META_UNLOCKS}`)
  is what `bump()` actually passes to `threshold_unlocks.bump_counter()` -- a single shared JSON
  file's flat `{"counters": .., "unlocked": {key, ...}}` state already spans all four content kinds
  (key namespaces never collide), so one bump of a shared counter name (`bosses_defeated`,
  `total_floors_cleared`, `runs_played`) can cross thresholds in more than one registry at once
  without the caller needing to know which kind a given counter happens to gate. `ShopMetaUnlock`
  (`SHOP_META_UNLOCKS`, one entry, `unlock_third_relic_slot`) is a fourth, genuinely separate class
  from `MetaUnlock`/`RelicMetaUnlock`/`LevelMetaUnlock` -- it gates an account-wide Shop *behavior*
  (`shop.build_offer()` offering a 3rd relic slot), not a specific tower/relic/level id, so it has no
  content id field to point at; `Game._queue_meta_unlock_toasts()`'s dispatch handles it as the
  trailing `else` (no display name to look up, so it queues a fixed toast string instead).
  `unlocked_relic_pool()`/`unlocked_level_pool()` mirror `unlocked_tower_pool()`'s shape, with one
  difference: `unlocked_level_pool()` returns the whole ready-to-use `LEVELS`-minus-locked-ids pool
  directly (passed straight into `run_map.generate_run_map`'s own `level_pool` param from
  `Game.start_new_run`) rather than just the small "what's been added" set the other two return,
  since only 2 of 15 levels are ever gated -- making every caller re-derive "everything else" would be
  the more awkward shape for the common case. `relics._default_relic_pool()` mirrors
  `card_pool._default_unlocked_pool()` exactly (every `RELICS` key not gated, plus whatever
  `unlocked_relic_pool()` says is unlocked, in `RELICS`' own stable registry order) and is threaded
  through `relic_offer()`'s own optional `unlocked_pool`/`meta_progression_path` params the same way
  `draft_offer()` already has them -- `shop.build_offer()`/`events.resolve_event_option()` both
  already received a `meta_progression_path` param for the tower half of their offer and just needed
  to start forwarding it to `relic_offer()` too; `Game._enter_treasure_node()`'s own direct
  `relic_offer()` call previously passed no path argument at all, now passes
  `self.meta_progression_path`. `Game._queue_meta_unlock_toasts()` dispatches on which of the three
  registries a newly-unlocked key belongs to (`"New tower/relic/level unlocked: ..."`, name read off
  `TOWER_TYPES`/`RELICS`/`LEVELS` respectively, since none of the three unlock classes carry a
  `display_name` of their own) rather than assuming every key `bump()` returns is a tower unlock.
- `progression/run_history.py` records `{seed: best_floors_cleared}`, written once per run by
  `_record_run_permadeath()`. Per-seed max rather than last-write, which is what makes a replayed
  seed (a Daily Run's date-derived one) keep its best result -- and why a Daily Run needs no special
  handling here at all, it's just another seed. The same file also keeps a `"runs"` list (additive,
  same schema version): one record per run (`details` = commander/ascension/act/daily/
  final_boss_defeated), newest first, capped at `MAX_RUN_RECORDS`; `save_run_history(best)` without
  `records` preserves the existing list. The Run History screen renders `ui.run_history_lines`, which
  falls back to the per-seed bests for a file written before records existed.
- `persistence/save_state.py` saves a single in-progress session -- but **only** between waves. ("Session," not
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
  directly; `_load_combat_node()` passes `self._resumed_from_save` straight through unchanged on
  every one of a run's own floor transitions (resumed or not, it's still the same session
  continuing); only `start_new_run()` -- the one place a genuinely *new* session begins -- explicitly
  resets it first.
  An optional `"run"` key carries the `RunState` (its map serialized node-by-node, validated on load
  against `LEVELS`/`TOWER_TYPES`/`RELICS`/`run_map.NODE_TYPES` -- including that `current_node_id`
  names a real node in its own map *and* that node is a Combat/Elite one, since a resumable save is
  always mid-`PLAYING`, per `can_save_run()`'s own gate, structurally never a Shop/Event/Rest/
  Treasure screen); `None` means a save with no active run -- Practice, an editor playtest, or a file
  written before the key existed -- and is passed straight through to `_load_level_object()`'s
  `active_run` parameter either way, so its one `_rebuild_button_rects()` call already produces the
  right menu (the run's drafted pool, or every tower) with nothing left to fix up afterward. No RNG
  state is serialized: a run's streams are re-derived from `(seed, key)` on demand (see the run loop
  section above). `SCHEMA_VERSION` bumped to `2` when the run's own floor_sequence/floor_index shape
  became map/current_node_id/visited_node_ids -- a save from before that (schema 1) has no meaningful
  way to become a map, so it's a **clean break**, not a migration: reaching for a `"map"` key that was
  never written raises `KeyError` (one of `json_io`'s own fallback-triggering exceptions), and
  `load_run()` falls all the way back to "nothing to resume," same as any other corrupt/incompatible
  save -- acceptable since `save_state.json` is local, gitignored player data, same reasoning this
  whole family of on-disk files already leans on.
- `persistence/keybindings.py` persists the player's rebound keys; see "Key remapping is curated, not
  repo-wide" above for the actual registry/matching/conflict logic -- it follows this same one-JSON-
  file, defensive-load, injectable-path shape, just with `(key, mods)` pairs as its values instead of
  a flat settings dict.

## Map checkpoints (autosave)

`save_state.save_map_checkpoint(run)` writes `{"kind": "map", "run": ...}` into the same single save
slot -- no floor state. `Game._autosave_run` calls it from `_enter_map` and `_enter_node` (before
dispatching, so the committed node is recorded), and sets `_resumed_from_save = True`: the active run
now owns the slot, so the existing floor-clear/permadeath deletion (`_delete_save_if_this_run_was_
resumed`) clears it like a resumed save, and the next map visit writes a fresh checkpoint. `load_run`
validates a map checkpoint with `_parse_and_validate_active_run(..., at_map=True)` (current node may be
None or any type). `_continue_saved_run` routes it to `_resume_map_checkpoint`: an unfinished current
node is re-entered fresh (a fight from wave 1; Shop/Event/Rest/Treasure re-derive identically, and the
pre-entry run state means nothing is granted twice), otherwise the map. A mid-floor `save_run()`
overwrites the checkpoint and still resumes the precise wave. Known gaps: quitting on the reward
screen or the opening blessing forfeits it.
