# Relics (`run/relics.py`)

- `run/relics.py` -- `RELICS`, a registry of run-wide passive modifiers, plus `relic_offer()` (mirroring
  `draft_offer`) and `compose_relic_modifiers()`. Mostly not unlock-gated, unlike tower cards -- only
  6 of the 74 (the category-gaps batch's `flak_rounds`/`breach_charges`/`containment_charges`, the
  cross-status combo-capstone batch's `frostbitten_mark`/`plague_mark`, and that same batch's
  `seismic_slam`) are gated at all, via `meta_progression.RELIC_META_UNLOCKS`; `relic_offer()`'s own
  optional `unlocked_pool`/
  `meta_progression_path` params mirror `draft_offer`'s exactly (see the `progression/meta_progression.py` bullet
  below). 74 relics across eight effect shapes -- the original
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
  mechanic, none gated -- plus a tenth batch of two giving Basic tower its own crit-boosting pair
  (`adrenaline_rounds`/`twitch_reflex`, `basic_crit_damage_multiplier`/`basic_crit_chance_multiplier`,
  read only in `BasicTower.create_projectile()` (`entities/tower.py:929-930`) against that tower's own native
  `crit_chance`/`crit_damage_multiplier` -- distinct from the generic, `max()`-composed
  `RelicModifiers.crit_chance`/`crit_damage_multiplier` `lucky_strikes`/`focused_fire`/
  `precision_engineering` already grant every tower, so the two families stack rather than collide)
  -- plus an eleventh batch doing the same for Sniper's execute mechanic (`kill_shot`/`wounded_prey`,
  `execute_damage_multiplier`/`execute_threshold_multiplier`, read in `SniperTower.
  create_projectile()` at `entities/tower.py:1173-1174`) -- plus a twelfth for Frost's slow (`glacial_core`/
  `permafrost`, `frost_slow_multiplier`/`frost_duration_multiplier`, read in `FrostTower.
  create_projectile()` at `entities/tower.py:1019-1020`; `glacial_core` is 0.8, not 1.25, the same
  inverted-direction quirk `slow_factor` itself already has) -- plus a thirteenth for Poison's own
  tower-side DoT (`toxic_payload`/`festering_wound`, `poison_tower_tick_multiplier`/
  `poison_tower_duration_multiplier`, read in `PoisonTower.create_projectile()` at
  `entities/tower.py:1216-1218`) -- plus a fourteenth, cross-status combo-capstone batch of three
  (`frostbitten_mark`/`plague_mark`/`chill_rot`, `damage_vs_marked_and_slowed_multiplier`/
  `damage_vs_marked_and_poisoned_multiplier`/`damage_vs_slowed_and_poisoned_multiplier`, all 1.35x --
  the highest per-relic power multiplier in the registry, since assembling two towers' worth of build
  investment to trigger at all is a harder condition than holding any single-status relic -- read
  generically in `Projectile._apply_hit_effects()` (`entities/projectile.py:398-417`) against pre-hoisted
  `is_slowed`/`is_marked`/`is_poisoned` booleans, the same per-enemy-status group
  `damage_vs_flying_multiplier`/`damage_vs_shielded_multiplier`/`damage_vs_healer_multiplier` already
  established) plus `seismic_slam` in the same batch, Knockback's second exclusive relic
  (`knockback_duration_multiplier`, read in `KnockbackTower.create_projectile()` at `entities/tower.py:1073`,
  same shape as `heavy_ordnance` before it) -- every field across all five of these batches is copied
  onto the tower once at construction (`Game._construct_tower`, alongside every other per-tower relic
  field), exactly the block at `core/game.py:1887-1898`, and multiplied in verbatim at each owning tower's
  own `create_projectile()`, so none needed new `Tower`/`Projectile` plumbing beyond the field itself,
  and none are gated (see the meta-progression bullet below for the two of these fourteen batches'
  relics that now are):
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
  current_row`), but still named `floor_index` throughout `run/relics.py` since the escalation math itself
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

  A fifth wave of six independent sessions, landed the same day (PRs #82-87), added six more
  batches past the capstone above -- 74 relics total as of this writing, none needing a genuinely
  new effect shape beyond the eight already described, each cited below against whichever existing
  shape it reuses -- alongside two new towers, `OverloadCannonTower`/`SiphonTower` (see their own
  dedicated sections below), each shipping with its own exclusive pair in the same wave, matching
  every prior new-tower precedent (Beacon's own launch batch, for instance): a fifteenth batch closes
  Cannon's own last gap -- of the ten towers that existed before this wave, Cannon alone had zero
  fully-exclusive relics (only `heavy_ordnance`, shared 50/50 with Knockback, and the generic
  `shockwave_rounds`) -- via `aerial_targeting_array` (`cannon_targets_flying`, a boolean
  OR-composed exactly like `poison_ignores_shield`, requiring `CannonTower.can_target_flying` to
  become a property reading it rather than staying a plain class attribute -- `KnockbackTower` keeps
  its own separate `can_target_flying = False` untouched, so the relic can never leak there; both
  towers pass their `can_target_flying` into `Projectile(can_hit_flying=...)`, which is what keeps
  a ground-only shot's splash and any Arcing Rounds bounce/Overkill carry off it from landing on a
  flyer that merely happened to be nearby -- `acquire_target()` alone only stops *aiming* at one) and
  `high_velocity_shells` (`cannon_projectile_speed_multiplier`, the first relic in the registry to
  ever touch `projectile_speed`, a plain `create_projectile()` multiply); a sixteenth batch is
  Overload Cannon's own launch pair, `overcharged_capacitors` (`overload_burst_multiplier`,
  plain-multiply on that tower's own `burst_multiplier`) and `fusion_core`
  (`overload_damage_multiplier`, via a `_relic_family_damage_bonus()` override identical in shape to
  `storm_core`/`heavy_ordnance`); a seventeenth batch is Siphon Tower's own launch pair,
  `refined_extraction` (`siphon_gold_fraction_multiplier`, the one relic in the whole registry read
  at `Projectile._apply_direct_damage()` rather than `create_projectile()`/`_apply_hit_effects()` --
  see Siphon Tower's own section below for why) and `amplified_coils` (`siphon_damage_multiplier`,
  the same `_relic_family_damage_bonus()` shape again); an eighteenth batch deepens two existing
  archetypes with a third relic each, reusing their existing shapes verbatim rather than inventing
  new ones -- `overclocked_circuits` (a third density relic, but a fire-rate bonus instead of
  damage: reuses `Tower.set_nearby_tower_bonus()`'s own already-computed neighbor count for a
  second output rather than a second scan, and sets its own independent `tower_density_radius` so
  it's functional standalone, the same "own numbers" precedent `reinforced_chassis` already set) and
  `desperate_reach` (a third last-stand relic, `last_stand_range_multiplier`, `max()`'d exactly like
  `last_stand_damage_multiplier`/`last_stand_fire_rate_multiplier`, folded into `effective_range()`
  as one more additive term alongside the aura/generic-relic ones); a nineteenth batch closes out two
  more gaps in the same "ungated per-enemy multiplier"/"cross-status combo" families the capstone
  batch above established -- `titan_slayer` (`damage_vs_boss_multiplier`, the first relic to key off
  a Boss-tier enemy, via a new `Enemy.IS_BOSS` class flag -- see "Boss enemy mechanics" below) and
  `overwhelming_affliction` (`damage_vs_marked_and_slowed_and_poisoned_multiplier`, the triple-status
  capstone the three pairwise combos above were always one relic short of, at 1.60x -- higher than
  their own 1.35x, since it needs all three of Beacon/Frost/Poison invested in the same run to ever
  trigger, reusing the exact same pre-hoisted `is_marked`/`is_slowed`/`is_poisoned` booleans with
  zero new `getattr` calls, and threaded through **both** copies of the relic-tagging block --
  `Tower.update()`'s own and `OverloadCannonTower.update()`'s duplicate, see that tower's own section
  below for why two copies exist at all); and a twentieth, round-out batch of three closing an
  economy-safety-net gap and two enemy-counterplay gaps rather than deepening an existing archetype
  -- `emergency_reserves` (no `RelicModifiers` field at all, the second relic in this exact shape
  after `guardians_reprieve`: a one-time-per-run gold refund checked directly against `run.relics`
  inside `Game._spend_gold()`, gated on a new `RunState.used_emergency_reserves` flag),
  `fracture_rounds` (`splitter_child_hp_multiplier`, the second relic in `containment_charges`' own
  "flat, non-tower" shape, read from the identical `pending_spawns` drain loop -- structurally can
  never touch `FinalBossEnemy`'s own live reinforcement summons, since those populate
  `pending_spawns` while the boss is still alive, not inside the `enemy.is_dead` branch this relic's
  own check is gated on), and `numbing_toxins` (`healer_heal_rate_multiplier`, threaded into
  `WaveManager`'s own constructor kwargs exactly like `enemy_speed_multiplier`/`enemy_gold_multiplier`
  above, applied post-construction via the same `hasattr`-gated patch-up pattern
  `WaveManager._spawn_enemy` already uses for `ShieldedEnemy`'s own `max_shield`).

## Curses

`Relic.is_curse` marks a relic with only downsides, using the ordinary RelicModifiers fields set "the
wrong way round" -- so `compose_relic_modifiers` needs no special case. `_default_relic_pool` excludes
curses, so `relic_offer` (Shop/Treasure/Elite/boss/Event grants) never offers one. They only arrive
via an Event option's `add_curse` (`relics.curse_offer`, one not yet held), and leave via an Event's
`remove_curse` or the Shop's once-per-visit service (`Game._try_remove_curse`, `shop.
CURSE_REMOVAL_PRICE` times the run's shop price multiplier; not an offer card, so no
`PRICE_ESCALATION`). Both removal paths lift the *oldest* curse (`relics.held_curses` keeps
acquisition order). A curse can also be given up through a `relic_cost` Event option like any relic.

## Potion relics

`potion_slot_bonus`/`lives_per_potion`/`guaranteed_potion_drop` are Relic-only fields read straight off
`RELICS` (never composed into RelicModifiers -- potions live on RunState, not on a floor's towers):
`potions.slot_count(run)` (the belt's size, which `Game.potion_slot_rects` -- a property -- rebuilds on
every read, shrinking slots to fit the panel), `Game.use_potion`, and `rewards.build_combat_reward`
(which still draws its `rng.random()` when the drop is guaranteed, so the same seed rolls the same
potion either way).

## Boss relics

`Relic.is_boss_relic` -- excluded from `_default_relic_pool`; `relics.boss_relic_offer` (used only by
`rewards.build_combat_reward(..., is_boss=True)`) draws from `BOSS_RELICS`, topped up from the
ordinary pool once fewer are left. Downsides use ordinary fields where one exists (Siege Engine's
`enemy_speed_multiplier`, Reckless Arsenal's negative `starting_lives_bonus` -- `_apply_one_time_relic_
bonus` clamps lives at 1) and three Relic-only switches otherwise, each read in one place:
`blocks_rest_heal` (`Game._enter_rest_node` -> `rest_heal_blocked`, Rest option disabled, Smith still
works), `blocks_shop_income` (`_advance_run_floor`), `blocks_potions` (`potions.has_free_slot`, so
rewards/Shop stand/Events all refuse new potions while held ones stay usable).

`compose_relic_modifiers`' `floor_index` is fed `run.floors_cleared` (fights actually won so far, across
every act), not the node's row/depth -- Veteran's Momentum, its only reader, promises "+2% per floor
cleared", and depth also counts Shop/Event/Rest rows and every row of earlier acts.

## Placement relics

`variety_damage_bonus_per_type` (Combined Arms) and `isolation_damage_bonus` (Lone Sentinel) compose
additively like the density fields and are copied onto each tower in `_construct_tower`. They are
resolved in `Tower.set_nearby_tower_bonus` (so only when the board changes) into
`Tower.placement_damage_bonus`, one more additive `effective_damage()` source. Radii and the variety
cap are module constants in `entities/tower.py` (`VARIETY_RADIUS`, `VARIETY_BONUS_CAP`,
`ISOLATION_RADIUS`). "Different type" means a different tower class.

## Construction relics

`structure_hp_multiplier`, `dead_zone_multiplier` and `module_fire_rate_bonus` are Relic-only fields
read by `Game._apply_construction_relics` at the end of `_construct_tower` (after modules): it calls
`Tower.scale_structure_hp` (a no-op except on `BarricadeTower`), shrinks an instance's `MIN_RANGE`
(never the class's), and boosts fire rate for a type that has a module fitted.

## Ground fire (Incendiary Shells)

`Relic.mortar_ground_fire` ((damage fraction per second, seconds), Relic-only) is copied onto every
tower as `relic_ground_fire` by `_construct_tower`; only `MortarTower.create_projectile` reads it, as
`Projectile.ground_fire`. The impact drain in `Game.update` turns such an impact into an
`effects.GroundFire` (`Game.ground_fires`, reset per floor), which `Game._update_ground_fires` ticks
before enemies move: ground enemies (not flying, not burrowed) inside it take `dps * dt`, credited to
the Mortar's `damage_dealt`/`kills`. Fires draw under towers and enemies.
