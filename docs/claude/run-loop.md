# The roguelike run loop

## The roguelike run loop is the primary loop

A **run** is a seeded, full branching map of nodes (see "The run's branching map" below), shown to
the player from the very start, each combat/elite node one full `_load_level_object()` pass on one
`Level` -- the same complete `Grid`/`Economy`/`WaveManager`/towers/enemies reset a level load always
did. What's new is `RunState` (`run/run_state.py`), the small bundle that survives *across* those resets:
seed, `map`, `current_node_id`, `visited_node_ids`, `difficulty`, lives, `shop_currency`,
`unlocked_towers`, and `relics`. Battle gold (`Economy.gold`) is deliberately *not* one of these --
see "Two currencies: battle gold and the Shop" below for the split this reflects. Placed towers and
the grid stay floor-scoped, deliberately -- a deckbuilder doesn't carry
board state between combats, only your deck and your HP. `Game.active_run` holds it, and is reset to
`None` inside `_load_level_object()` itself (not at each call site), so any loader that doesn't know
about runs -- `resume_saved_run()` for a classic save, say -- structurally can't leak a stale
`RunState` into a non-run level.

The pieces, each a small module in this codebase's registry-or-bare-function style:

- `run/run_map.py` -- `generate_run_map(rng)`: the whole branching map, generated once, up front (see
  "The run's branching map" below for the full shape). Combat/elite level ids are still sampled from
  `LEVELS`, but no longer read as a single flat ascending ramp the way the old, retired
  `run_floors.sample_floor_sequence` did -- see that section for what replaced it.
- `run/card_pool.py` -- a "card" is, for v1, exactly a `TOWER_TYPES` key. `STARTER_TOWERS` is what every
  run begins with; `draft_offer(rng, run, ...)` samples `count` names from the account-wide unlocked
  pool minus what the run already holds, returning *fewer* than `count` once exhausted rather than
  raising. `_default_unlocked_pool` reorders into `TOWER_TYPES`' own registry order before sampling
  -- `rng.sample`'s result depends on its input's order, so feeding it a raw `set` would silently
  break "the same seed offers the same cards" across two process launches.
- `run/relics.py` -- `RELICS` registry, `relic_offer()`, `compose_relic_modifiers()`; see [relics.md](relics.md).
- `run/run_escalation.py` -- `escalation_for_floor(floor_index)`, a bare formula rather than a registry
  precisely because `floor_index` (the current node's row) is unbounded once the boss node's endless
  tail runs. `apply_elite_multiplier()` layers an Elite node's own extra bump on top -- the difficulty
  half of the risk/reward trade an Elite node offers; see `shop.income_for_floor`'s own
  `ELITE_INCOME_MULTIPLIER` for the reward half.
- `run/events.py` -- `EVENTS`, a registry of Random Event nodes (a short prompt plus 2-3 options), plus
  `pick_event()` (deterministic per node) and `resolve_event_option()`. See "The run's branching map"
  below for the full node-type writeup.
- `progression/meta_progression.py` / `progression/run_history.py` -- cross-run persistence; see the on-disk-state section.

`Game.start_new_run(seed=None, is_daily=False)` builds the `RunState` (map generated once, up front,
via `run_map.generate_run_map`) and calls `_enter_map()` -- unlike the old flat sequence, a run no
longer auto-loads its first floor; the player's first act is picking one of the map's row-0 nodes
(always Combat, see below) themselves. `Game._enter_node(node_id)` sets `run.current_node_id` and
dispatches on that node's own type; for a Combat/Elite node that's `_load_combat_node(node)`, which
composes *three* independent extra factors into the one `_load_level_object()` call -- the run's
snapshotted `difficulty`, `escalation_for_floor(node.row)` (bumped further by
`apply_elite_multiplier` for an Elite node), and `compose_relic_modifiers(run.relics, node.row, ...)`
-- each an extra multiplier on top of what's already there, never a replacement, per `run/difficulty.py`'s
own rule. The run's very first resolved node is the one asymmetric case for lives: `RunState` starts
with `lives=0` as a placeholder and *captures* that node's freshly-loaded `Economy`'s lives (checked
via `not run.visited_node_ids`), while every node after that *restores* into it instead. Battle gold
has no such asymmetry -- see "Two currencies" below, it's rebuilt fresh from the same construction on
every floor, the first node included.

Clearing a Combat/Elite floor goes `update()`'s win-check -> `_advance_run_floor()` -> `GameState.
FLOOR_CLEARED` -> (any key) `_enter_map()` -> (a click on an available node) `_handle_map_click()` ->
`_enter_node()`. `_advance_run_floor` appends the cleared node's own id onto `run.visited_node_ids`
(what `RunState.floors_cleared` counts from -- see below) and converts leftover battle gold into shop
currency (`shop.income_for_floor`, with an Elite bonus -- see above). One detail worth knowing: the
next node isn't loaded until the player picks it from the map, which is what leaves `self.towers`/
`self.economy` intact for `FLOOR_CLEARED` to render real results from.

A run is `run_map.ACT_COUNT` (3) acts -- see "Acts" below. A run ends **only** by permadeath. The final
act's boss node (the sole node in its final row) always loads `endless=True`, so `all_waves_complete` structurally can never fire for it, and `update()`'s win-check
routes a run to `_advance_run_floor()` rather than `VICTORY` regardless -- there is no "you won the
run" event by construction, not by a missing branch. `_record_run_permadeath()` writes the outcome to
`progression/run_history.py` and bumps the meta-progression counters; `RunState.floors_cleared` (what both of
those read) counts only visited Combat/Elite nodes, not every node stopped at -- a Shop/Event/Rest/
Treasure detour doesn't inflate the score.

Every rng a node needs (its own enemy routing, its Shop offer, a Random Event's own pick and its
chosen option's item grant, a Treasure's own relic pick) is re-derived on demand via `Game._run_rng
(run, stream, key)` rather than carried as one continuously-consumed `random.Random`. That's what
lets `persistence/save_state.py` serialize a run without serializing any RNG state at all -- a resumed run just
re-derives the identical objects (`resume_saved_run()` is why `run` is a parameter here rather than
read off `self.active_run`: it needs this derivation *before* `_load_level_object()` sets `self.
active_run`). The seed itself is a string (`f"{run.seed}:{stream}:{key}"`), not
`run.seed * stream + key` -- that integer scheme degenerated to plain `key` for every stream whenever
`run.seed == 0`, colliding every stream; a string has no such degenerate case. `key` is a node's own
id (a string, unique within the run's map) for almost every stream -- critically, **never** a bare row
number: two sibling nodes in the same row would otherwise derive byte-identical rng, silently
defeating branching (both forks of a choice would route/offer/roll identically). A Shop's own offer
and a Random Event's own item grant fold in one further piece of identity on top of the node id (the
node id alone identifies *which visit*, not *which purchase* or *which option* -- see
`Game._enter_shop_node`/`_resolve_event_choice`).

A **Daily Run** is not a separate mode: `_start_daily_challenge()` is
`start_new_run(seed=todays_seed(), is_daily=True)`. `is_daily` changes exactly one thing -- the run
snapshots `"normal"` instead of the player's sticky difficulty preference, so scores are comparable.
`progression/run_history.py` already tracks `{seed: best_floors_cleared}` for any seed, so a date-derived seed
needs no special handling anywhere. The whole map is generated from that same date-derived seed, so
every player sees the identical branching map (and Shop/Event offers) on a given day too.

## Ascension

`run/ascension.py` -- `ASCENSION_LEVELS[i]` is the one rule Ascension i+1 adds; `modifiers_for(level)`
folds levels 1..level into one `AscensionModifiers` (multiplicative fields multiply, the one additive
field `reward_tower_count_delta` adds). Snapshotted once onto `RunState.ascension` at
`start_new_run` (Daily Runs force 0), serialized and range-checked by `save_state`. Application points:
`_floor_load_context` (`apply_to_escalation`: enemy HP/speed, starting gold, plus elite/boss HP by
node type), `_load_combat_node`'s first-node lives capture, `_enter_rest_node`'s heal,
`_shop_price_multiplier`, and `_enter_reward_screen`'s tower count. The account's highest unlocked
level is meta_progression's `highest_ascension` counter (raised via `threshold_unlocks.set_counter`'s
max semantics, never a threshold registry entry), cached on `Game.highest_ascension` so the menu never
re-reads the file per frame; `_handle_boss_defeated` -> `_unlock_next_ascension` raises it (never for
Daily/Sandbox) and auto-advances `selected_ascension` if the player was at the top. The menu's
Left/Right (`change_selected_ascension`) is caught before the "any key starts a run" catch-all.

## Acts

`RunState.act` (0-based, `< run_map.ACT_COUNT`) says which act's map `RunState.map` is. Only the last
act's boss is endless (`RunState.is_final_floor` = final act *and* final row); an earlier act's boss is
an ordinary finite floor, so `update()`'s win-check routes it through `_advance_run_floor` like any
floor (which also bumps `bosses_defeated` + the `acts_cleared` achievement counter there -- the endless
final boss still goes through `_handle_boss_defeated` instead, the only place Ascension unlocks).
Its reward (`rewards.build_combat_reward(..., is_boss=True)`) is a pick-one `boss_relic_choices` row
plus a potion, no towers; leaving it calls `Game._leave_reward_screen` -> `_advance_act`: bank
`floors_cleared` into `floors_cleared_prior_acts`, bump `act`, generate a fresh map from
`Random(f"{seed}:act:{act}")` (act 0 still uses `Random(seed)`, so existing seeds are unchanged), clear
`visited_node_ids`/`current_node_id`, heal `ACT_HEAL_LIVES`. Node ids repeat across acts, so
`_run_rng` folds `act{n}:` into the key for act >= 1 (again leaving act 0 byte-identical). Everything
that scaled by `node.row` now reads `run.depth_of(node.row)` (= `act * ROW_COUNT + row`): escalation,
relic modifiers, shop income, rest heal, treasure, Liquid Gold. The first-node lives capture is
gated on `act == 0` so act 2's first node restores the carried lives instead of re-capturing.
`floors_cleared` counts combat/elite/boss nodes (a visited boss is always an earlier act's).

## Commanders

`run/commanders.py` -- `COMMANDERS` registry (starter towers, starting relics/potions/forged towers).
MENU's "any key" now goes to `GameState.COMMANDER_SELECT` (`Game._enter_commander_select`, which
re-reads `meta_progression.unlocked_commanders`); clicking an unlocked card calls
`start_new_run(commander=key)`, which copies the Commander's kit onto the new `RunState` (no
`_grant_relic`, so starting relics don't bump `relics_collected`; a starting relic must not rely on
`_apply_one_time_relic_bonus`, since lives are only captured on the first node -- a test enforces
this). Gating is `meta_progression.COMMANDER_META_UNLOCKS` (a 5th class in `ALL_UNLOCKS`, so the
Unlocks screen and unlock toasts pick it up); `unlocked_commanders` also honours a counter already
at goal, so pre-existing accounts don't wait for the next bump. Daily Runs force
`DEFAULT_COMMANDER`. `RunState.commander` is saved and validated.
