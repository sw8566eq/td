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
pytest -v --cov=. --cov-report=term-missing   # what CI runs (.github/workflows/tests.yml)

ruff check .                       # lint -- also what CI runs, gates the same workflow

pyinstaller --onedir --name td --add-data "assets:assets" main.py   # build a Linux release binary locally -- see "Release binary" below
```

`ruff` (lint) and `pytest-cov` (coverage reporting only, no enforced floor yet) are configured in
`pyproject.toml`'s `[tool.ruff]`/`[tool.coverage.run]` sections -- no formatter, and no type checker
(mypy/pyright) yet. `tower.py`'s per-file `RUF012` ignore is deliberate: every `Tower` subclass's
class-level `EXTRA_STATS`/`SPECIALIZATIONS` dicts are read-only content tables (see "Content is
registries, not conditionals" below), never mutated at runtime, which is exactly what that rule
can't tell apart from a genuine mutable-default footgun.

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
`_load_combat_node()` for a run's floor, `resume_saved_run()` for a save) -- so `reset()` /
`advance_or_replay_level()` are just "call it again."

**The game is a roguelike deckbuilder, and the run loop is its primary loop.** A single level
played on its own still works exactly as it always did, but that's now Practice, a side path; the
main path is a run. Read the next section before anything else here.

### The roguelike run loop is the primary loop

A **run** is a seeded, full branching map of nodes (see "The run's branching map" below), shown to
the player from the very start, each combat/elite node one full `_load_level_object()` pass on one
`Level` -- the same complete `Grid`/`Economy`/`WaveManager`/towers/enemies reset a level load always
did. What's new is `RunState` (`run_state.py`), the small bundle that survives *across* those resets:
seed, `map`, `current_node_id`, `visited_node_ids`, `difficulty`, lives, `shop_currency`,
`unlocked_towers`, and `relics`. Battle gold (`Economy.gold`) is deliberately *not* one of these --
see "Two currencies: battle gold and the Shop" below for the split this reflects. Placed towers and
the grid stay floor-scoped, deliberately -- a deckbuilder doesn't carry
board state between combats, only your deck and your HP. `Game.active_run` holds it, and is reset to
`None` inside `_load_level_object()` itself (not at each call site), so any loader that doesn't know
about runs -- `resume_saved_run()` for a classic save, say -- structurally can't leak a stale
`RunState` into a non-run level.

The pieces, each a small module in this codebase's registry-or-bare-function style:

- `run_map.py` -- `generate_run_map(rng)`: the whole branching map, generated once, up front (see
  "The run's branching map" below for the full shape). Combat/elite level ids are still sampled from
  `LEVELS`, but no longer read as a single flat ascending ramp the way the old, retired
  `run_floors.sample_floor_sequence` did -- see that section for what replaced it.
- `card_pool.py` -- a "card" is, for v1, exactly a `TOWER_TYPES` key. `STARTER_TOWERS` is what every
  run begins with; `draft_offer(rng, run, ...)` samples `count` names from the account-wide unlocked
  pool minus what the run already holds, returning *fewer* than `count` once exhausted rather than
  raising. `_default_unlocked_pool` reorders into `TOWER_TYPES`' own registry order before sampling
  -- `rng.sample`'s result depends on its input's order, so feeding it a raw `set` would silently
  break "the same seed offers the same cards" across two process launches.
- `relics.py` -- `RELICS`, a registry of run-wide passive modifiers, plus `relic_offer()` (mirroring
  `draft_offer`) and `compose_relic_modifiers()`. Mostly not unlock-gated, unlike tower cards -- only
  3 of the 49 (the category-gaps batch's `flak_rounds`/`breach_charges`/`containment_charges`) are
  gated at all, via `meta_progression.RELIC_META_UNLOCKS`; `relic_offer()`'s own optional
  `unlocked_pool`/`meta_progression_path` params mirror `draft_offer`'s exactly (see the
  `meta_progression.py` bullet below). Forty-nine relics across eight effect shapes -- the original
  three, plus five more added since, plus a fourth batch of four closing archetype/coverage gaps
  (`shockwave_rounds`/`arc_conductor` for the previously-unsupported Chain/AoE archetype,
  `interceptor_rounds` for fast enemies, `haggling_permit` for Shop-currency prices -- none gated),
  plus a fifth batch of two deepening two archetypes that had only one dedicated relic each
  (`reinforced_chassis`, a second density relic alongside `overcrowded_circuits`;
  `overdrive_array`, a second Support-aura-strength relic alongside `resonant_field`) -- both reuse
  existing `RelicModifiers` fields verbatim (no new fields, no new `Tower`/`Projectile` plumbing),
  none gated -- plus a sixth batch of three deepening three more archetypes the same way
  (`precision_engineering`, a third crit relic with its own standalone chance/multiplier;
  `storm_core`, a Lightning-tower-exclusive damage multiplier; `heavy_ordnance`, the Cannon/
  Knockback-exclusive counterpart) -- `storm_core`/`heavy_ordnance` are the two fields in this batch
  that DO need new `Relic`/`RelicModifiers` fields (`lightning_damage_multiplier`/`cannon_knockback_
  damage_multiplier`) plus a `Game._construct_tower` copy line each, none gated. Unlike every other
  tower-exclusive relic multiplier in this file (`arc_conductor`/`shockwave_rounds`, read as a plain
  `create_projectile()` multiply since chain_range/splash_radius aren't part of `effective_damage()`'s
  own stack), these two *are* a damage bonus, so they fold into that stack instead, additively, via a
  `Tower._relic_family_damage_bonus()` hook (0.0 on the base class, overridden identically by
  `LightningTower` and by both `CannonTower`/`KnockbackTower`) -- multiplying either into an
  already-resolved `effective_damage()` result at the `create_projectile()` call site instead (an
  earlier version of this batch did exactly that) would compound multiplicatively against every other
  damage source there rather than adding to them, the one stacking rule that method's own docstring
  exists to guarantee -- plus a seventh batch of two deepening the Mark archetype, both Beacon-
  tower-exclusive and both the plain-multiply shape (`beacon_splash_radius_multiplier`/`beacon_
  mark_multiplier`, read only in `BeaconTower.create_projectile()` against `mark_splash_radius`/
  `mark_damage_multiplier` respectively -- neither is this tower's own shot damage, so neither needs
  the `_relic_family_damage_bonus()` hook above), none gated -- plus an eighth batch of two deepening
  Beam's ramp mechanic, also Beam-tower-exclusive and also plain-multiply/read
  (`beam_ramp_multiplier`, `beam_max_ramp_bonus` -- the latter additive, mirroring `sell_refund_
  bonus`'s own shape, since `max_ramp_multiplier` is already itself a multiplier), read only in
  `BeamTower.create_projectile()` scaling `ramp_per_hit`/`max_ramp_multiplier`, the two inputs to
  that tower's own `ramp = min(1.0 + consecutive_hits * ramp_per_hit, max_ramp_multiplier)` formula
  -- worth noting even though `ramp` *does* multiply straight into this tower's actual shot damage
  (`damage = effective_damage() * ramp`), unlike Beacon's genuinely-separate mark mechanic: that
  multiplicative relationship between `ramp` and `effective_damage()` is pre-existing, deliberate
  `BeamTower` design (see that class's own docstring on why it was tuned down after a real
  playtest), not something either relic changes, so scaling ramp's own two inputs directly was judged
  the right shape over routing through `_relic_family_damage_bonus()` -- plus a ninth batch of one,
  `virulent_bloom` (`poison_spread_radius`), the one relic in the whole registry that isn't a numeric
  extension of an existing hook: see the **flat, non-tower** bullet below for the actual new
  mechanic, none gated:
  **per-floor**
  (composed into `RelicModifiers`, threaded into `WaveManager`/`Economy` construction every floor --
  `starting_gold_multiplier`/`gold_per_floor_bonus`/`enemy_gold_multiplier`/`enemy_speed_multiplier`);
  **one-time** (`starting_lives_bonus`, applied directly at draft-pick time instead, see
  `Game._apply_one_time_relic_bonus` -- `RelicModifiers` has no field for this one). `starting_gold_
  multiplier` (`war_chest`) used to be one-time too, back when battle gold carried forward and
  "starting gold" only existed once, at floor 0 -- see "Two currencies: battle gold and the Shop"
  below for why it's a normal per-floor field now instead; **per-tower**
  (`tower_range_multiplier`/`tower_fire_rate_multiplier`/`tower_damage_multiplier`/`poison_chance`+
  `poison_effect`/`crit_chance`+`crit_damage_multiplier`/`chain_chance`+`chain_effect`/
  `tower_footprint_shrink`/`tower_upgrade_cost_multiplier`/`sell_refund_bonus`/`support_aura_range_
  multiplier`+`support_aura_strength_multiplier`/`damage_vs_slowed_multiplier`/`slow_chance`+
  `slow_effect`/`poison_ignores_shield`/`damage_vs_early_route_multiplier`/`damage_vs_high_hp_
  multiplier`/`overkill_carry_fraction`, read once per tower at construction time -- see
  `Game._construct_tower`/`_current_footprint_subtiles`, and `Tower.effective_range()`/
  `effective_fire_rate()`/`effective_damage()`/`upgrade_cost()`/`specialization_cost()`/`sell_value()`/
  `SupportTower.update()`/`Projectile._apply_hit_effects()` for where each actually applies -- the six
  newest of these are copied onto `Projectile` the same way `poison_chance`/`crit_chance`/
  `chain_chance` already are, then resolved per enemy actually hit rather than once per shot: Chilling
  Precision/Choke Point/Giant Slayer are ungated per-enemy multipliers (`enemy.slow_timer`/
  `distance_traveled`/`max_hp`, read via `getattr` with a neutral default so a lightweight test double
  is unaffected), Aftershock is a chance-gated `apply_slow()` roll following `poison_chance`'s exact
  shape, `poison_ignores_shield` threads through both the tower's own `poison_effect` and a Venomous
  Coating-style relic roll into `enemy.apply_poison()`'s new `ignore_shield` parameter, and Overkill
  fires once a hit's `applied` damage exceeds the target's pre-hit hp, bouncing the excess to the
  nearest other enemy within `projectile.OVERKILL_CARRY_RANGE` via the same non-recursive
  `_find_chain_target`/`_apply_direct_damage` hop `arcing_rounds`' own bounce uses). A later batch
  added five more per-tower fields the same way: `knockback_chance`+`knockback_effect` and
  `mark_chance`+`mark_effect` are chance-gated rolls following `poison_chance`/`slow_chance`'s exact
  shape (calling `enemy.apply_knockback()`/`apply_mark()`), and `damage_vs_flying_multiplier`/
  `damage_vs_shielded_multiplier`/`damage_vs_healer_multiplier` join the ungated per-enemy multiplier
  group above them, checked against the target's own current `is_flying`/`shield`/`heal_rate` state
  (each guarded on the relic's own multiplier being non-neutral before the `getattr`, since `shield`/
  `heal_rate` -- unlike `is_flying`, a base `Enemy` attribute -- only exist on `ShieldedEnemy`/
  `HealerEnemy` instances);
  **escalating-per-floor** (`veterans_momentum`'s `tower_damage_growth_per_floor`, folded into
  `tower_damage_multiplier` via `compose_relic_modifiers`' `floor_index` parameter -- fed the current
  node's *row* now that a run is a branching map rather than a flat sequence (see `RunState.
  current_row`), but still named `floor_index` throughout `relics.py` since the escalation math itself
  doesn't care what kind of int it's handed; grows with the row reached instead of being a flat
  per-floor constant); **conditionally-revocable** (`misers_coffer`'s
  `gold_per_floor_bonus_while_unspent`, folded into `gold_per_floor_bonus` gated on the new
  `has_spent_gold` parameter -- `RunState.has_spent_gold` flips permanently true the run's first
  successful spend, tracked via `Game._spend_gold()`, the one choke point `try_place_tower`/
  `try_upgrade_tower`/`try_specialize_tower` all route through instead of calling `Economy.spend()`
  directly);
  **live-reactive** (`last_stand_charm`'s `last_stand_damage_multiplier` and `adrenaline_rush`'s own
  `last_stand_fire_rate_multiplier`, both relic effects resolved every frame against changing game
  state -- `Economy.is_on_last_life` -- rather than once at floor-load/construction time, via a single
  `Tower.set_last_stand_multiplier()` call, called from `Game.update()`'s existing two-pass tower
  loop, that sets both live values together since both relics key off the exact same condition);
  **per-tower-density (live-reactive)** (`overcrowded_circuits`' `tower_density_radius`/
  `tower_density_damage_bonus_per_neighbor`/`tower_density_damage_bonus_cap`, resolved from each
  tower's own live neighbor count rather than one global condition -- but, unlike the other
  live-reactive fields above, event-driven rather than re-resolved every frame: a tower's own `.pos`
  never moves once placed, so `Game._recompute_tower_density_bonuses()` only needs to call
  `Tower.set_nearby_tower_bonus(self.towers)` -- which does its own neighbor scan over the list it's
  handed, the same shape `SupportTower.update()` already uses for its own aura broadcast, rather than
  a caller reducing it to a bare count first -- for every tower whenever the board's own tower set
  actually changes (`try_place_tower`/`try_sell_tower`/`resume_saved_run`), not from `Game.update()`'s
  per-frame loop at all); and **flat, non-tower** (`containment_charges`' `splitter_child_damage` --
  unlike every field above, has no per-tower or per-shot variation to justify threading through
  `Tower`/`Projectile` at all, so `Game.update()`'s own dead-enemy drain loop reads it straight off
  `self.relic_modifiers` and applies it once to each of a killed `SplitterEnemy`'s own children,
  right where `Enemy.pending_spawns` is already the one place that list is ever read; `virulent_
  bloom`'s `poison_spread_radius` reads the exact same way -- 0 (not granted) or a spread radius,
  `max()`'d across relics like `tower_density_radius` -- but from the *other* half of that same
  drain loop, the `if enemy.is_dead:` branch itself: every enemy that dies still actively poisoned
  (`enemy.poison_time_remaining > 0`) is collected into a small list as the loop runs, then, only
  after `self.enemies = still_alive` lands, each collected death re-applies its own live poison
  state -- `poison_damage_per_tick`/`poison_tick_interval`/`poison_time_remaining`/
  `poison_ignores_shield`, not a number this relic itself carries -- via `Enemy.apply_poison()` to
  every enemy still within `poison_spread_radius` of where it died. Deferring the actual spread to
  after the drain, rather than inline per-enemy, is load-bearing, not just tidy: it's what lets a
  spread reach an enemy that died-and-was-replaced this same frame (a `SplitterEnemy`'s own
  children, already joined via `pending_spawns` above) while never touching an enemy that's
  actually gone, regardless of which order the loop happened to visit deaths in. It also can't
  cascade within one frame even if a freshly-spread-to enemy also dies from something else that same
  tick: `apply_poison()` only sets state, the tick damage itself is `Enemy.update()`'s job on a
  later frame). `guardians_reprieve` has no `RelicModifiers` field at all
  (same shape as `war_chest`/`sturdy_gate`) -- checked directly against `run.relics` in
  `Game._lose_a_life()`, the interception point for the enemy-reached-goal life loss, gated on
  `RunState.used_guardians_reprieve` (a one-time-per-run charge) and a no-op under
  `Economy.invulnerable` (sandbox/Creative -- nothing to save there); `Economy.is_on_last_life` is the
  one shared answer to "is this run on its last life" every relic that asks reads, rather than each
  re-deriving `lives <= 1` on its own.
  `compose_relic_modifiers()`'s per-tower fields aggregate
  the same "flat sums, multipliers multiply" way as the per-floor ones, except `crit_damage_multiplier`
  and `last_stand_damage_multiplier` (both `max()` across relics, not multiplied -- two such relics
  compounding multiplicatively would spike far faster than two flat +chance relics summing),
  `poison_effect`/`chain_effect` (each a tuple combined via `max()`/`max()`, `poison_effect` with one
  last-write field -- see below), and `tower_damage_multiplier` (composed from *two* different `Relic`
  fields, a flat per-relic multiplier and the escalating-per-floor one, since a run-long stacking bonus
  like `veterans_momentum` has nowhere else to live). Composing two poison-granting relics combines
  their `(damage_per_tick, tick_interval, duration)` tuples the exact same way `Enemy.apply_poison()`
  already combines two poison *hits* on one enemy (keep the harsher tick damage and longer duration,
  last-write on interval), so drafting a second poison relic behaves exactly like landing a second
  poison hit already does; `chain_effect` (`damage_fraction, chain_range`) combines via plain `max()`
  on both elements, the same conservative choice. `arcing_rounds`' chain-on-hit bounce
  (`Projectile._apply_hit_effects`/`_find_chain_target`/`_apply_direct_damage`) is a separate,
  independent mechanism from `LightningTower`'s own tower-driven `chain_range`/`max_chain_targets` --
  it fires on any hit via a chance roll and is always exactly one non-recursive bounce, never a
  multi-link chain.
- `run_escalation.py` -- `escalation_for_floor(floor_index)`, a bare formula rather than a registry
  precisely because `floor_index` (the current node's row) is unbounded once the boss node's endless
  tail runs. `apply_elite_multiplier()` layers an Elite node's own extra bump on top -- the difficulty
  half of the risk/reward trade an Elite node offers; see `shop.income_for_floor`'s own
  `ELITE_INCOME_MULTIPLIER` for the reward half.
- `events.py` -- `EVENTS`, a registry of Random Event nodes (a short prompt plus 2-3 options), plus
  `pick_event()` (deterministic per node) and `resolve_event_option()`. See "The run's branching map"
  below for the full node-type writeup.
- `meta_progression.py` / `run_history.py` -- cross-run persistence; see the on-disk-state section.

`Game.start_new_run(seed=None, is_daily=False)` builds the `RunState` (map generated once, up front,
via `run_map.generate_run_map`) and calls `_enter_map()` -- unlike the old flat sequence, a run no
longer auto-loads its first floor; the player's first act is picking one of the map's row-0 nodes
(always Combat, see below) themselves. `Game._enter_node(node_id)` sets `run.current_node_id` and
dispatches on that node's own type; for a Combat/Elite node that's `_load_combat_node(node)`, which
composes *three* independent extra factors into the one `_load_level_object()` call -- the run's
snapshotted `difficulty`, `escalation_for_floor(node.row)` (bumped further by
`apply_elite_multiplier` for an Elite node), and `compose_relic_modifiers(run.relics, node.row, ...)`
-- each an extra multiplier on top of what's already there, never a replacement, per `difficulty.py`'s
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

A run ends **only** by permadeath. The map's boss node (the sole node in its final row) always loads
`endless=True`, so `all_waves_complete` structurally can never fire for it, and `update()`'s win-check
routes a run to `_advance_run_floor()` rather than `VICTORY` regardless -- there is no "you won the
run" event by construction, not by a missing branch. `_record_run_permadeath()` writes the outcome to
`run_history.py` and bumps the meta-progression counters; `RunState.floors_cleared` (what both of
those read) counts only visited Combat/Elite nodes, not every node stopped at -- a Shop/Event/Rest/
Treasure detour doesn't inflate the score.

Every rng a node needs (its own enemy routing, its Shop offer, a Random Event's own pick and its
chosen option's item grant, a Treasure's own relic pick) is re-derived on demand via `Game._run_rng
(run, stream, key)` rather than carried as one continuously-consumed `random.Random`. That's what
lets `save_state.py` serialize a run without serializing any RNG state at all -- a resumed run just
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
`run_history.py` already tracks `{seed: best_floors_cleared}` for any seed, so a date-derived seed
needs no special handling anywhere. The whole map is generated from that same date-derived seed, so
every player sees the identical branching map (and Shop/Event offers) on a given day too.

### The run's branching map

A run's map (`run_map.py`) is a Slay-the-Spire-style row-based DAG, generated once, up front (`Game.
start_new_run`), and shown to the player in full from the start -- not fog-of-war, not revealed
fork-by-fork. `ROW_COUNT` rows (6, unchanged from the old flat sequence's own floor count, which
keeps `run_escalation.py`'s tuned growth constants meaning the same thing they always did); edges
only ever run from one row to the next, never skip a row or point backward, which is what keeps
"every node reachable, every node can reach the boss" provable by simple induction (see
`_generate_edges`' own docstring) rather than needing a general graph-reachability pass after the
fact (tests still verify it via BFS over many seeds anyway). Row 0 is a fixed-width, all-Combat
choice (which of `START_ROW_WIDTH` same-difficulty layouts to open the run on, not a difficulty
choice at all) -- the run's very first resolved node is always guaranteed to be a real level load,
keeping the lives-capture special case above simple. The final row is always exactly one node of its
own dedicated `"boss"` type (`RunMap.boss_node_id`) -- fixing its width at 1 is what keeps
`is_final_floor`/`endless=True` trivial, no "did every path converge" check needed.

Every other row is a weighted-random mix of the six ordinary `NODE_TYPES` (`NODE_TYPE_WEIGHTS`) --
`"boss"` is a seventh registered type with no entry in that weight table at all, since it's never
drawn by the mix, only forced onto the final row exactly like `"combat"` is forced onto row 0 -- capped
at half the row per type (`MAX_SAME_TYPE_PER_ROW_FRACTION`) so a wide row can't degenerate into one
repeated type. `MIN_ELITE_ROW` keeps Elite off the run's opening rows; `GUARANTEED_REST_ROW` forces
at least one Rest node onto that one row if the weighted draw didn't already produce one, and
`GUARANTEED_TREASURE_ROW` (a distinct row, same injection shape) does the same for Treasure -- whose
own 4/100 weight and lack of any guarantee otherwise meant a run could plausibly see zero of them.
Both are deliberately **not** mirrored for Shop, which stays pure chance (a run's Shop cadence is
meant to vary, unlike Rest's "never go the whole back half with no way to recover lives" guarantee,
or Treasure's "always at least one guaranteed relic-shopping stop"). A Combat/Elite node's own
level id is drawn from whichever tier its row falls in (`_level_pool_for_row`, partitioned by
structure -- single-spawn "corridor" levels for earlier rows, multi-spawn "multi-lane" ones for later
rows -- not a hardcoded id list, so it stays self-maintaining as levels are added) rather than sampled
freely across all of `LEVELS`, preserving the same corridor-then-multi-lane authored ramp the old
flat, ascending `floor_sequence` used to give for free. The final row's own boss node is a further
special case on top of that tiering, not just "whichever multi-lane level a late row would otherwise
draw" -- see the Boss bullet below.

The seven node types:
- **Combat**: a normal floor, exactly what a run's only node type used to be.
- **Elite**: a harder floor (`run_escalation.apply_elite_multiplier`, layered on top of the row's own
  escalation) that pays out more shop currency on clear (`shop.income_for_floor`'s own
  `ELITE_INCOME_MULTIPLIER`) -- risk/reward, not "harder for its own sake."
- **Shop**: `GameState.DRAFT` (see its own naming note just below) -- reuses `shop.py` verbatim, only
  reached via a map node now rather than automatically after every floor clear (see "Two currencies"
  below for what this replaced).
- **Event**: `GameState.EVENT` -- a short prompt and 2-3 options (`events.py`), each a fixed,
  honestly-described delta (shop currency, lives, a relic grant, a tower unlock, or -- since the
  gaps-and-synergies batch -- giving up a relic already held, `EventOption.relic_cost`) rather than
  a hidden-odds gamble, same "say exactly what it does" precedent `relics.py`'s own registry sets.
  `Game.event_options` (`events.available_options(event, run)`) is the actual rendered/clickable
  subset -- may be shorter than the event's own full `options` tuple if a `relic_cost` option got
  dropped for holding no relics; a `relic_cost` option must always be the last in its tuple, since
  filtering only ever truncates the tail, keeping every other option's index stable regardless.
  Two-phase (`Game.event_phase`, "choose" then "resolved") -- `_handle_event_click`/
  `_resolve_event_choice` apply the chosen option's effect (indexing into `event_options`, never the
  raw `current_event.options`) and show what happened; any further click/key then returns to the
  map.
- **Rest**: `GameState.REST` -- auto-resolves the instant it's entered (`Game._enter_rest_node`), no
  player choice, healing `run.lives` by `run_map.heal_amount_for_row(node.row)` and showing a static
  confirmation screen.
- **Treasure**: `GameState.TREASURE` -- also auto-resolves on entry (`Game._enter_treasure_node`): a
  guaranteed shop-currency payout (`run_map.treasure_shop_currency_for_row`) plus one guaranteed relic
  pick, degrading gracefully to currency-only once every relic is already held (`relics.relic_offer`'s
  own empty-once-exhausted precedent).
- **Boss**: the run's climactic final-row node -- dispatched through `Game._load_combat_node` exactly
  like Combat/Elite (`Game._enter_node`'s `("combat", "elite", "boss")` check), escalated further still
  by `run_escalation.apply_boss_multiplier` (tuned higher than Elite's own bump), and drawn from its
  own dedicated `run_map.BOSS_LEVEL_IDS` pool (two levels, ids 16/17) rather than the ordinary
  multi-lane tier -- `_level_pool_for_row` excludes `BOSS_LEVEL_IDS` from that ordinary complex pool
  entirely, so an ordinary mid-run Elite/Combat node can never draw one early. Each ends its final
  wave in `{"final_boss": N}` (`enemy.FinalBossEnemy`, an `ENEMY_TYPES` entry reserved for these two
  levels) rather than the ordinary `{"boss": N}` every other level's own final wave still uses.
  `FinalBossEnemy` inherits `BossEnemy`'s Enrage/Armor mechanics unmodified and adds a one-time-per-run
  live mechanic of its own: while still alive, it periodically summons `SUMMON_COUNT` `ScoutEnemy`
  reinforcements at its own current position along the route, via `Enemy.pending_spawns` -- the same
  channel `SplitterEnemy` already uses, just populated repeatedly while alive rather than once at
  death, which is what required generalizing `Game.update()`'s own drain of that list: every enemy's
  own `pending_spawns` is now drained into `still_alive` and cleared *before* the dead/goal/alive split
  runs, not only inside the `if enemy.is_dead:` branch the way it worked before `FinalBossEnemy`
  existed. Since the boss node is always loaded `endless=True` (see below), there is no "you defeated
  the boss, run over" screen -- `WaveManager.authored_waves_cleared` (a new flag, distinct from
  `all_waves_complete`, which never fires under `endless=True`) is what `Game.update()`'s own
  before/after check reads to detect the boss node's authored waves running out for the first time,
  firing `Game._handle_boss_defeated()`: a one-shot-per-run toast, a `bosses_defeated` bump on both
  `meta_progression.py` and `achievements.py` (the `"boss_slayer"` achievement), and a persistent
  `RunState.boss_defeated` flag that appends "-- Boss defeated!" onto the HUD's existing Wave line for
  the rest of the (still-ongoing, still-endless) fight -- piggybacked onto that line rather than a new
  one, same headroom reasoning `shop_currency`'s own comment in `ui.draw_hud` already gives.
  `RunState.boss_defeated` (guarded the same one-shot way `used_guardians_reprieve` is) is what stops
  a mid-boss-fight Restart -- which rebuilds a fresh `WaveManager` whose own `authored_waves_cleared`
  starts `False` again -- from double-counting `bosses_defeated` a second time.

`Game._enter_map()` (re-)shows the map screen, rebuilding `self.map_node_rects` fresh every time
(`ui.build_map_node_rects`) -- the same "computed fresh, not a persistent cache" spirit
`draft_choices` already follows, though unlike a Shop visit's own offer this never needs a
scroll-aware rebuild (the map never scrolls at `ROW_COUNT=6`). `Game._available_node_ids()` (`run.
map.start_node_ids` if nothing's been picked yet, else the current node's own edges) is the single
source of truth both `_handle_map_click`'s legality check and `ui.draw_map_screen`'s "available"
visual state read from. `Game._enter_node(node_id)` sets `run.current_node_id` and dispatches to
whichever `_enter_*_node`/`_load_combat_node` method that node type needs; `Game._finish_node
(node_id)` is the shared terminal step every non-combat resolution (a Shop's Continue, an Event's
chosen option, Rest/Treasure's auto-resolve) routes through -- mark the node visited, return to the
map. A Combat/Elite node's own clear already appends its own id in `_advance_run_floor`, so it never
goes through `_finish_node` -- there's no separate "leave the results screen" step distinct from
pressing any key on `FLOOR_CLEARED`, which goes straight to `_enter_map()`.

`GameState.MAP`/`DRAFT`/`EVENT`/`REST`/`TREASURE` are all full-screen states (like `LEVEL_SELECT`/
`EDITOR` -- see `render()`'s early-return block), not overlays drawn atop a frozen board the way
`PAUSED`/`GAME_OVER`/`VICTORY`/`FLOOR_CLEARED` are: `MAP` can be shown before any floor of the run has
ever loaded (right after `start_new_run()`, before `self.grid`/`self.economy` exist at all), so
there's structurally no board to freeze behind it -- the other four are reached from `MAP` and follow
the same full-screen convention for consistency, even on a node sequence where a board technically
still exists from an earlier floor.

### Two currencies: battle gold and the Shop

A run tracks two independent currencies, deliberately never convertible into each other: **battle
gold** (`Economy.gold`, unchanged as a concept -- what places/upgrades/specializes/sells towers
mid-floor) resets fresh every floor rather than carrying forward, and **shop currency**
(`RunState.shop_currency`) persists across the whole run and is what actually buys cards at the Shop
(`GameState.DRAFT` -- see its own naming note in `game.py` for why the code still says "draft"
throughout even though the screen is a shop now, only reached via a map node -- see "The run's
branching map" above -- rather than automatically after every floor clear). A Treasure node and a
Random Event's own `grant_relic`/`unlock_random_tower` options also grant cards/currency directly
(see above), independent of the Shop entirely. Before this split, `RunState.gold` carried battle
gold forward the same unconditional way `lives` still does; there is no such field any more --
`_load_combat_node` never restores or captures battle gold, it's simply rebuilt fresh by every
floor's own `_load_level_object()` call (relic-adjustable via `RelicModifiers.starting_gold_
multiplier`/`gold_per_floor_bonus`, both applied every floor now with no first-node special case
left).

`shop.py` is where the Shop's own logic lives, mirroring `card_pool.py`/`relics.py`'s own
registry-and-bare-function shape:

- `build_offer(rng, run, meta_progression_path=None)` -- this shop visit's items, mixing both card
  types together in one offer (`TOWER_OFFER_COUNT` towers via `card_pool.draft_offer`, then
  `RELIC_OFFER_COUNT` relics via `relics.relic_offer`, same exclude-what's-already-held rules as
  before). Either half can come back shorter once its own pool is exhausted; `Game._enter_shop_node()`
  still skips the screen entirely only if the *combined* offer is empty.
- `price_for(item, purchases_this_visit, discount_multiplier=1.0)` -- an item's actual cost,
  escalated by `PRICE_ESCALATION` for every other item this same shop visit has already bought (0
  for the first purchase), then discounted by a Haggling Permit-style relic's own
  `RelicModifiers.shop_price_multiplier` (default 1.0, a no-op -- `quartermasters_favor` already
  covers the battle-gold half of the economy, this is the shop-currency half). Kept as a pure
  function of a purchase *count* (and this one relic-driven multiplier), not mutable per-item state,
  so `ui.draw_draft_screen` (showing what the *next* purchase would cost) and `Game._try_buy_shop_item`
  (actually charging it) can't drift apart on what "the current price" means.
- `income_for_floor(floor_index, leftover_gold, is_elite=False)` -- shop currency earned at a floor
  clear (`Game._advance_run_floor`): a small flat amount that escalates with `floor_index` (the
  cleared node's own row, mirroring `run_escalation.py`'s own per-floor growth on a much smaller
  scale) plus `LEFTOVER_GOLD_CONVERSION_RATE` of whatever battle gold was still unspent at that
  moment -- since battle gold itself never carries forward (see above), this is what makes hoarding
  it in an already-won fight pay off instead of the surplus just vanishing when the floor resets.
  `is_elite` scales the whole result up by `ELITE_INCOME_MULTIPLIER` -- an Elite node's own reward for
  its extra risk (see "The run's branching map" above).

Buying is `Game._try_buy_shop_item(index)`: a silent no-op if unaffordable (same "click does nothing"
precedent `try_place_tower`'s own unbuildable-spot case sets), otherwise it deducts the escalated
price, records the index in `self.shop_purchased_indices` (drawn as SOLD and no longer clickable --
see `ui.draw_draft_screen`), and applies the card: a tower name onto `run.unlocked_towers`, or a relic
key via `Game._grant_relic()` (appends to `run.relics` and applies `_apply_one_time_relic_bonus()` --
the one choke point every relic-granting path, a Shop purchase or a Treasure node's guaranteed pick
alike, routes through). Buying never leaves the shop by itself -- the player can buy several items (or
none) in one visit, then explicitly clicks Continue (`ui.build_shop_continue_button_rect()`) to call
`Game._finish_node()` and return to the map, the same terminal step every other non-combat node
resolution uses. `self.economy.unlimited_gold` (already exactly `self.unlimited_gold or sandbox`, see
"Economy debug flag" below) makes every shop item free the same way it already makes battle gold
spending free -- there's no separate sandbox flag for shop currency.

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
one subclass per tower -- splash/slow/knockback/chain/mark are just constructor args a tower's
`create_projectile()` passes in, and the hit-resolution algorithm doesn't care which combination
it got (see "Mark and Corrosive Poison's shield-bypass hook" below for why Mark's own
amplification math still lives in `Enemy`, not here).

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

`FinalBossEnemy` (the run map's own boss-node species -- see the Boss bullet under "The run's
branching map" above) subclasses `BossEnemy` directly and inherits both mechanics completely
unmodified -- `take_damage()` isn't overridden a second time. Its own reinforcement-summon mechanic
lives entirely in `update()`, guarded the same `if self.is_dead or self.reached_goal: return` way
every other one-time enemy mechanic in this file is.

`FinalBossShieldedEnemy` is a second final-boss species, giving the run's two boss-tier levels
(`run_map.BOSS_LEVEL_IDS`, 16 and 17) genuinely distinct fights rather than an identical script
behind different topology -- Level 16 still uses `FinalBossEnemy`, Level 17 uses this one instead
(`levels.py`'s own `LEVEL_17_WAVE_SPECS`, the only line that changed to wire it in). It also
subclasses `BossEnemy` directly and inherits Enrage/Armor unmodified, but its own extra mechanic is
a periodic self-shield pulse in place of summoned reinforcements: every `SHIELD_PULSE_INTERVAL`
seconds while alive, it grants itself `pulse_shield` worth `SHIELD_PULSE_FRACTION` of its own
*current* `max_hp` (read live, same reasoning as Enrage/Armor's own thresholds above), which
`take_damage()` *does* override this time -- absorbing from `pulse_shield` first, then delegating
whatever's left to `BossEnemy.take_damage()` so armor/enrage still evaluate correctly on the
remainder, the same absorb-then-delegate shape `ShieldedEnemy.take_damage()` already establishes,
just pulsed on a timer rather than continuously regenerating. Deliberately named `pulse_shield`, not
`shield`/`max_shield` -- reusing either name would silently trigger `WaveManager._spawn_enemy`'s
`hasattr(enemy, "max_shield")` patch-up above, which is hardcoded for `ShieldedEnemy`'s own
difficulty-scaling model and sizes things a completely different way. It also needs its own
`take_poison_damage()` override, unlike `FinalBossEnemy` -- see "Mark and Corrosive Poison's
shield-bypass hook" below for why.

### Mark and Corrosive Poison's shield-bypass hook

Two mechanics from the tower/relic synergy batch live inside `Enemy` itself rather than
`Projectile`/a per-species special case, because each has to affect *every* damage source
uniformly, not just a tower's own direct hit resolution:

- **Mark** (`BeaconTower`'s own mechanic, `tower.py`) is `Enemy.mark_damage_multiplier`/
  `mark_timer`, decayed in `update()` exactly like `slow_timer`/`slow_multiplier`, and set via
  `Enemy.apply_mark(multiplier, duration)` -- same guard/refresh shape as `apply_slow()`, except
  both the multiplier *and* the duration combine via `max()`, not `min()`/`max()`, since a bigger
  `mark_damage_multiplier` is always the stronger effect (the opposite of `slow_factor`).
  `Enemy.take_damage()` multiplies `amount` by `mark_damage_multiplier` at the very top of the
  *base class's own* method, before anything else -- which is what makes it compose correctly
  under every subclass's own override with zero subclass changes: `BossEnemy`/`ShieldedEnemy` each
  reduce `amount` for armor/shield absorption *before* calling `super().take_damage()`, so Mark
  always amplifies whatever's left after that absorption, never before it; `SplitterEnemy` calls
  `super().take_damage()` first, unmodified, so its split-on-death logic is indifferent to the
  exact number Mark produces. `Projectile`'s own `mark_effect` constructor field (a
  `(damage_multiplier, duration)` pair, the same shape as `slow_effect`/`poison_effect`) is how
  `BeaconTower.create_projectile()` reaches it -- reusing `Projectile` verbatim, per this
  codebase's own "one data-parametrized class" architecture, which also means Beacon's own tiny
  hits go through the full existing relic pipeline for free.
- **Corrosive Poison** (`poison_ignores_shield`, a `RelicModifiers` field) needs a dedicated hook
  because a poison tick applies via a *direct* `self.take_damage(...)` call inside `Enemy.update()`
  itself, not through `Projectile` -- so bypassing a shield-style absorption can't be an inline
  check in `Projectile`. `Enemy.take_poison_damage(amount, ignore_shield)` is the hook `update()`'s
  poison-tick handling calls instead of `take_damage()` directly: the base implementation is just a
  polymorphic call to `take_damage()` (meaningless without a shield to ignore), and exactly two
  species override it -- `ShieldedEnemy` (its regenerating shield) and `FinalBossShieldedEnemy`
  (its periodic self-shield pulse -- see the run's branching map section above) -- each bypassing
  its own shield-absorbing `take_damage()` override by calling the shield-less base class's
  `take_damage()` directly (`Enemy.take_damage(self, amount)` for `ShieldedEnemy`,
  `BossEnemy.take_damage(self, amount)` for `FinalBossShieldedEnemy`, since the latter still needs
  to fall through to `BossEnemy`'s own armor/enrage checks) when `ignore_shield` is set.
  `ShieldedEnemy` also resets its shield's regen timer on this path, the same way a normal absorbed
  hit would -- `FinalBossShieldedEnemy`'s pulse has no equivalent regen timer to reset, since it
  refills on a fixed schedule regardless of whether it was hit. Every other species inherits the
  base hook unmodified, which is what keeps `BossEnemy`'s armor phase and `SplitterEnemy`'s
  split-on-death structurally untouched by Corrosive Poison -- not via a runtime species check
  anywhere, but because only those two species ever override the hook at all.
  `Enemy.apply_poison()`'s own `ignore_shield` parameter follows a
  one-way-ratchet rule, not the `min()`/`max()` its numeric fields use: a genuinely fresh
  application sets it directly, but a refresh of already-active poison ORs it in, so the stronger
  property (bypassing a shield) can never be silently downgraded by a second, weaker application.

### Grid has two coordinate systems

`Grid` (`grid.py`) tracks the map at two granularities at once:
- **Coarse tile coords** (`col, row`; unit = `TILE_SIZE`, 64px) -- path, blocked cells, and the
  rendered mosaic. Comes straight from a `Level`'s `path_cells`/`spawn_cells`/`goal_cells`/
  `blocked_cells` (see "Paths are a graph, not a route" below).
- **Subtile coords** (`anchor_col, anchor_row`; unit = `SUBTILE_SIZE`, `TILE_SIZE /
  SUBTILES_PER_TILE`) -- tower placement. A tower's footprint is normally one tile's worth of area
  (`SUBTILES_PER_TILE x SUBTILES_PER_TILE` subtiles, currently 8x8) but can be *anchored* at any
  subtile, not just a tile boundary, which is what gives placement finer-than-a-tile precision.
  `SUBTILES_PER_TILE` must evenly divide `TILE_SIZE` (enforced in `Grid.__init__`) so every
  pixel<->subtile conversion is exact integer math.

`is_buildable`/`occupy`/`placement_anchor`/`anchor_to_pixel_center`/`_footprint_subtiles` all take an
optional `footprint_subtiles` (default `None`, meaning a full tile) -- the one hook a Compact
Framework-style relic uses to shrink every tower's footprint for a floor (see
`Game._current_footprint_subtiles`, clamped to `settings.MIN_TOWER_FOOTPRINT_SUBTILES` so a relic
can never collapse it to nothing). `remove(anchor_col, anchor_row)` keeps its original 2-argument
signature regardless -- `occupy()` records what size it actually reserved in
`Grid._footprint_size_by_anchor`, so `remove()` can free exactly that without the caller (or the
tower object itself, which several tests stand in for with a bare placeholder) needing to repeat it.
`Tower` mirrors this as its own `footprint_subtiles` instance attribute (set once at construction by
`Game._construct_tower`, read by `tile_rect()`/`upgrade_badge_center()`/`draw()` in place of the
`settings.TILE_SIZE`/`SUBTILE_SIZE` those methods used to hardcode directly) so a shrunk footprint's
sprite, hit-box, and click target all shrink together rather than the grid and the tower silently
disagreeing about how much space one occupies.

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
stats shown in the sidebar and its actual shots always agree. `effective_range()` also folds in
`relic_range_bonus_multiplier` (a Spyglass Array-style relic's own bonus, set once at construction
by `Game._construct_tower`, never reset) -- deliberately **additive** with `aura_range_multiplier`
(`range * (1.0 + (aura - 1.0) + (relic - 1.0))`), not multiplicative and not `max()`'d, so a relic
and a nearby Support tower's own buff genuinely stack rather than the stronger one silently winning
the way two overlapping Support towers already do. `SupportTower.update()`'s own reach check uses
`effective_range()` too, for the same "no relic singles out one tower type" reason -- a Range relic
widens a Support tower's own aura radius, not just its role as an aura *recipient*. `ui.py`'s stats
panel and
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
  `total_floors_cleared` *before* the player can reach any Shop node, so a brand-new player's very
  first shop visit has a real card to offer instead of finding `STARTER_TOWERS` exhausted and silently
  skipping -- strengthened, not weakened, by the branching map: row 0 is always Combat (see "The
  run's branching map" above), so a Shop node can never be reachable before at least one floor has
  cleared.
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
  -- "beat the boss once" rather than a grind threshold.
  `ALL_UNLOCKS` (`{**META_UNLOCKS, **RELIC_META_UNLOCKS, **LEVEL_META_UNLOCKS}`) is what `bump()`
  actually passes to `threshold_unlocks.bump_counter()` -- a single shared JSON file's flat
  `{"counters": .., "unlocked": {key, ...}}` state already spans all three content kinds (key
  namespaces never collide), so one bump of a shared counter name (`bosses_defeated`,
  `total_floors_cleared`, `runs_played`) can cross thresholds in more than one registry at once
  without the caller needing to know which kind a given counter happens to gate.
  `unlocked_relic_pool()`/`unlocked_level_pool()` mirror `unlocked_tower_pool()`'s shape, with one
  difference: `unlocked_level_pool()` returns the whole ready-to-use `LEVELS`-minus-locked-ids pool
  directly (passed straight into `run_map.generate_run_map`'s own `level_pool` param from
  `Game.start_new_run`) rather than just the small "what's been added" set the other two return,
  since only 1 of 15 levels is ever gated -- making every caller re-derive "everything else" would be
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

### Audio

`audio.py` mirrors `assets.py` closely (read that module's own docstring first): every sound is
referenced elsewhere by a logical name (`"tower_placed"`, `"enemy_killed"`, ...), never a file
path. `SoundManager` (constructed once on `Game` as `self.audio`, right after `self.assets`,
reusing `assets.DEFAULT_ASSET_ROOT` directly rather than recomputing the same path a second way --
both modules' files live in the same directory, so it's the identical root) looks the name up in
`SOUND_MANIFEST` for a relative path under `assets/sfx/` plus a fallback synthesis recipe -- a
tuple of `SynthSpec` "notes" (waveform, an optional linear frequency sweep, a simple
attack/decay/sustain/release envelope) -- if the file exists it's loaded and decoded by SDL exactly
like a real sprite; otherwise it's synthesized in pure Python (`array`/`math`/`random`, no numpy)
into a raw PCM buffer handed to `pygame.mixer.Sound(buffer=...)`. This is audio's counterpart to
`AssetManager`'s colored-rect placeholders -- a deliberately "chiptune" aesthetic matching the
game's own placeholder-shape visual style, not an attempt at realism -- and the same "dropping a
real file in is a files-only change" precedent applies to `assets/sfx/`. Synthesized sounds are
cached per `SoundManager` instance for the process's own lifetime, never written to disk --
`assets/sfx/` stays empty except its own `.gitkeep` until a human drops real files in, exactly like
every other `assets/` subfolder. Like `AssetManager`, `get()` itself stays lazy (synthesizes/loads a
cue on its own first request), but `SoundManager.preload_all()` exists to pay every cue's one-time
synthesis cost up front instead, on demand -- a rare cue (`"boss_defeated"`, played once per run at
a dramatic moment) landing its own ~15-20ms of synthesis as a frame hitch on exactly the frame it
needs to play cleanly would be the worst possible time for that cost. `main.py` (a real launch
only) calls it once, right after constructing `Game()` and before `game.run()` starts the frame
loop, so play sees a warm cache before combat ever starts. It's deliberately *not* called from
`SoundManager.__init__`/`Game.__init__` themselves, though -- every test's own `Game()`/
`playing_game` fixture (and the `run-td` skill's own driver) also constructs a real `Game()`, many
times over, with no use for a warm cache; folding preloading into construction itself would make
every one of those pay the full ~100ms manifest-wide synthesis cost too, for no benefit any of them
can use -- measured to nearly triple the whole test suite's wall time for exactly that reason.

Unlike a placeholder `Surface`, a synthesized sound's raw bytes are coupled to the mixer's *actual*
initialized sample format -- `pygame.mixer.get_init()`'s own return (frequency/size/channels), not
necessarily what `Game.__init__` requested it with -- so `SoundManager` reads that back once at
construction and builds a matching encoder (bit depth, signedness, channel count) generically
rather than assuming one fixed shape (`audio._encoder_for`). An unrecognized format disables
*synthesis only*; a real on-disk file still plays regardless, since SDL decodes those independently
of anything this module builds by hand. `pygame.mixer.init()` itself is wrapped in a `try`/`except`
in `Game.__init__`, same "fall back gracefully rather than crash" spirit as `AssetManager`'s own
placeholder fallback -- a machine with genuinely no audio device (not even a dummy/null one
configured) leaves the game fully playable with sound silently, permanently disabled for that
session; `SoundManager` itself independently checks `pygame.mixer.get_init()` right after, so it
finds out the mixer never came up regardless of which branch ran, with no result needing to thread
through from `Game.__init__`. `SoundManager.__init__` also raises `pygame.mixer.set_num_channels()`
from SDL_mixer's default of 8 to `audio.NUM_CHANNELS` (32) itself, right there rather than at
whichever call site happens to construct it -- a busy board can have well over a dozen towers
firing, several projectiles resolving, and an enemy dying all in the same frame, and `Sound.play()`
simply drops a cue rather than stealing a channel once every one is already busy, so every
`SoundManager` gets this fix for free regardless of construction path (`Game.__init__`, a test, ...)
rather than needing each caller to remember the extra call.

`Tower.FIRE_SOUND` (a single logical-name string, the same shape as `sprite_name`, not a registry
like `EXTRA_STATS`/`SPECIALIZATIONS`, since a tower only ever has one fire cue) names which cue a
tower's own shot plays; a couple of subclasses override the base class's generic default to group
towers into a few audibly distinct families rather than one bespoke sound per tower type
(`CannonTower`'s heavier thump, `LightningTower`'s zap) -- `SupportTower` sets it to `None`
(defense in depth; it never attacks at all, so it never reaches the code path below regardless).
`Tower.fired_this_frame` extends the *spirit* of the drain-a-per-frame-event-list idiom above to
sound, but as a plain bool rather than a list: set once per successful shot in `update()` (the
exact spot `shots_fired` increments), read and reset by `Game.update()`'s existing two-pass tower
loop into a `self.audio.play(tower.FIRE_SOUND)` call. A bool, not a list, because one `update()`
call can structurally fire at most once -- unlike `Enemy.damage_events`/`Projectile.impact_events`,
there's nothing here that could ever accumulate more than one same-frame entry to iterate, so a
list would only add an allocate/iterate/clear cost every frame for every tower with nothing to show
for it. Every other cue reuses an event list or call site this codebase already had for an
unrelated reason, rather than any new
plumbing into `Tower`/`Enemy`/`WaveManager` themselves (same "never call out to a presentation
concern from inside simulation code" rule the visual-effects idiom already establishes): enemy-hit
(small vs. splash, keyed off `splash_radius is not None`) and enemy-killed ride
`Projectile.impact_events`/the existing death-poof `ExpandingRing` spawn site; wave start is a new
before/after check on `WaveManager.state` transitioning into `SPAWNING`, mirroring the existing
`current_wave_number`/`authored_waves_cleared` before/after checks right next to it in
`Game.update()` (catches wave 1 via `skip_delay()`, every later authored wave, and every
endless-generated wave uniformly, since `_begin_wave()` is the only place that state is ever
entered); tower placed/upgraded/specialized/sold, floor cleared, boss defeated, game over/victory,
a Shop-purchased relic or plain tower unlock, and a Treasure/Random-Event-granted relic or tower
(the latter two resolved inside `events.resolve_event_option`, which can't call back into `Game` --
see its own docstring -- so `Game._resolve_event_choice` plays the matching cue itself, off that
function's own `{"relic": key}`/`{"tower": name}` return, rather than inheriting one from
`_grant_relic`/`_try_buy_shop_item` the way the Shop and Treasure paths do) all play from whichever
`Game`-level method already owned that event. Achievement/meta-progression unlocks share one cue
via `_queue_toast()`'s own single choke point, which also means a boss-defeat frame layers its own
dedicated fanfare underneath that same generic toast ding -- accepted as reasonable layering, not a
bug. Every failure path (an unaffordable purchase, an unbuildable placement, ...) stays exactly as
silent as it already was -- no new "denied" sound anywhere, mirroring each of those methods'
existing silent-no-op precedent.

`GameState.SETTINGS`'s "Sound: On/Off" row is `self.sound_enabled`, persisted via
`player_settings.py` exactly like `fullscreen` (`Game.set_sound_enabled()` mirrors
`set_fullscreen()`'s own shape: mutate, apply -- `self.audio.set_enabled()` -- save). Sound has no
volume slider in v1, just the one toggle.

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
concept -- `Economy.invulnerable` is the one genuinely new flag Sandbox needed. The Shop (see "Two
currencies" above) reuses this same flag for shop currency too, rather than a third parallel concept.

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
