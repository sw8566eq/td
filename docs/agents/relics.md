# Relics (`run/relics.py`)

How relics are offered and gated, the effect shapes every relic fits into, how
`compose_relic_modifiers()` stacks them, the tower-exclusive and per-enemy relic families, and then
the special relic kinds (curses, potion, trophy/boss, placement, construction, ground fire, counter).

## Overview and gating

`run/relics.py` holds `RELICS`, a registry of run-wide passive modifiers, plus `relic_offer()` (mirroring
`card_pool.draft_offer`) and `compose_relic_modifiers()`. Curses (`Relic.is_curse`) and trophy relics
(`Relic.is_boss_relic`) live in the same registry, told apart by flags. The registry is the source of
truth for how many relics exist, so don't hard-code a count in docs.

Unlike tower cards, relics are mostly not unlock-gated. Only six are, via
`meta_progression.RELIC_META_UNLOCKS`: `flak_rounds`, `breach_charges`, `containment_charges`,
`frostbitten_mark`, `plague_mark` and `seismic_slam`. `relic_offer()`'s optional `unlocked_pool`/
`meta_progression_path` params mirror `draft_offer`'s exactly (see [persistence.md](persistence.md)
"`progression/meta_progression.py`").

**Adding a relic.** Reuse one of the effect shapes below wherever possible. Most new relics need only
a `Relic` field, a `RelicModifiers` field plus its composition rule, and one copy line in
`Game._construct_tower`. If `Tower.update()` tags the new field onto projectiles, mirror it into
`OverloadCannonTower.update()`'s duplicate block (see [towers.md](towers.md) "Overload Cannon's
charge-and-burst cycle").

## Effect shapes

### Per-floor

Composed into `RelicModifiers` and threaded into `WaveManager`/`Economy` construction every floor:
`starting_gold_multiplier`/`gold_per_floor_bonus`/`enemy_gold_multiplier`/`enemy_speed_multiplier`.
`starting_gold_multiplier` (`war_chest`) used to be one-time too, back when battle gold carried forward
and "starting gold" only existed once, at floor 0 -- see [economy-shop.md](economy-shop.md) "Two
currencies: battle gold and the Shop" for why it's a normal per-floor field now.

`numbing_toxins` (`healer_heal_rate_multiplier`) is threaded into `WaveManager`'s own constructor kwargs
exactly like `enemy_speed_multiplier`/`enemy_gold_multiplier`, applied post-construction via the same
`hasattr`-gated patch-up pattern `WaveManager._spawn_enemy` already uses for `ShieldedEnemy`'s own
`max_shield`.

### One-time

`starting_lives_bonus` (`sturdy_gate`) is applied directly when the relic is granted, in
`Game._apply_one_time_relic_bonus`. `RelicModifiers` has no field for it.

### Per-tower (read once at construction)

`tower_range_multiplier`/`tower_fire_rate_multiplier`/`tower_damage_multiplier`/`poison_chance`+
`poison_effect`/`crit_chance`+`crit_damage_multiplier`/`chain_chance`+`chain_effect`/
`tower_footprint_shrink`/`tower_upgrade_cost_multiplier`/`sell_refund_bonus`/`support_aura_range_
multiplier`+`support_aura_strength_multiplier`/`damage_vs_slowed_multiplier`/`slow_chance`+
`slow_effect`/`poison_ignores_shield`/`damage_vs_early_route_multiplier`/`damage_vs_high_hp_
multiplier`/`overkill_carry_fraction` are read once per tower at construction time -- see
`Game._construct_tower`/`_current_footprint_subtiles`, and `Tower.effective_range()`/
`effective_fire_rate()`/`effective_damage()`/`upgrade_cost()`/`specialization_cost()`/`sell_value()`/
`SupportTower.update()`/`Projectile._apply_hit_effects()` for where each actually applies.

The on-hit ones are copied onto `Projectile` the same way `poison_chance`/`crit_chance`/`chain_chance`
are, then resolved per enemy actually hit rather than once per shot:

- **Chance-gated rolls** following `poison_chance`'s exact shape: Aftershock (`slow_chance`, calling
  `apply_slow()`), `knockback_chance`+`knockback_effect` (`enemy.apply_knockback()`) and
  `mark_chance`+`mark_effect` (`enemy.apply_mark()`).
- **Ungated per-enemy multipliers**: Chilling Precision/Choke Point/Giant Slayer (`enemy.slow_timer`/
  `distance_traveled`/`max_hp`) and `damage_vs_flying_multiplier`/`damage_vs_shielded_multiplier`/
  `damage_vs_healer_multiplier`/`damage_vs_fast_multiplier`/`damage_vs_boss_multiplier`, checked against
  the target's current state. They read via `getattr` with a neutral default so a lightweight test
  double is unaffected; `shield`/`heal_rate` exist only on `ShieldedEnemy`/`HealerEnemy`, so those checks
  are guarded on the relic's own multiplier being non-neutral first. `damage_vs_boss_multiplier`
  (`titan_slayer`) keys off `Enemy.IS_BOSS` (see [enemies.md](enemies.md) "Boss enemy mechanics").
- **Corrosive Poison** (`poison_ignores_shield`) threads through both the tower's own `poison_effect`
  and a Venomous Coating-style relic roll into `enemy.apply_poison()`'s `ignore_shield` parameter (see
  [enemies.md](enemies.md) "Mark and Corrosive Poison's shield-bypass hook").
- **Overkill** fires once a hit's `applied` damage exceeds the target's pre-hit hp, bouncing the excess
  to the nearest other enemy within `projectile.OVERKILL_CARRY_RANGE` via the same non-recursive
  `_find_chain_target`/`_apply_direct_damage` hop `arcing_rounds`' own bounce uses.

### Escalating-per-floor

`veterans_momentum`'s `tower_damage_growth_per_floor` is folded into `tower_damage_multiplier` via
`compose_relic_modifiers`' `floor_index` parameter. `Game` feeds it `run.floors_cleared` (fights
actually won so far, across every act), not the node's row/depth: Veteran's Momentum, its only reader,
promises "+2% per floor cleared", and depth also counts Shop/Event/Rest rows and every row of earlier
acts.

### Conditionally-revocable

`misers_coffer`'s `gold_per_floor_bonus_while_unspent` is folded into `gold_per_floor_bonus`, gated on
the `has_spent_gold` parameter. `RunState.has_spent_gold` flips permanently true on the run's first
successful spend, tracked via `Game._spend_gold()`, the one choke point `try_place_tower`/
`try_upgrade_tower`/`try_specialize_tower` all route through instead of calling `Economy.spend()`
directly.

### Live-reactive

`last_stand_charm`'s `last_stand_damage_multiplier`, `adrenaline_rush`'s `last_stand_fire_rate_multiplier`
and `desperate_reach`'s `last_stand_range_multiplier` are resolved every frame against changing game
state -- `Economy.is_on_last_life` -- rather than once at floor-load/construction time, via a single
`Tower.set_last_stand_multiplier()` call from `Game.update()`'s two-pass tower loop that sets all of
them together, since they key off the same condition. The range one is one more additive term in
`effective_range()` alongside the aura/generic-relic ones. `Economy.is_on_last_life` is the one shared
answer to "is this run on its last life" for every relic that asks, rather than each re-deriving
`lives <= 1`.

### Per-tower density (event-driven)

`overcrowded_circuits`' `tower_density_radius`/`tower_density_damage_bonus_per_neighbor`/
`tower_density_damage_bonus_cap` resolve from each tower's own live neighbor count rather than one
global condition. Unlike the live-reactive fields, this is event-driven rather than re-resolved every
frame: a tower's `.pos` never moves once placed, so `Game._recompute_tower_density_bonuses()` only
calls `Tower.set_nearby_tower_bonus(self.towers)` -- which does its own neighbor scan, the same shape
`SupportTower.update()` uses for its aura broadcast -- for every tower whenever the board's tower set
actually changes (`try_place_tower`/`try_sell_tower`/`resume_saved_run`).

`reinforced_chassis` is a second damage density relic, and `overclocked_circuits` a third that gives
fire rate instead: it reuses `set_nearby_tower_bonus()`'s already-computed neighbor count for a second
output rather than a second scan. Each sets its own independent `tower_density_radius`, so it works
standalone. Placement relics (see "Placement relics") resolve in the same method.

### Flat, non-tower

These have no per-tower or per-shot variation, so they skip `Tower`/`Projectile` entirely and are read
straight off `self.relic_modifiers` in `Game.update()`'s dead-enemy drain loop:

- `containment_charges`' `splitter_child_damage` applies once to each of a killed `SplitterEnemy`'s
  children, right where `Enemy.pending_spawns` is read.
- `fracture_rounds`' `splitter_child_hp_multiplier` reads from the same `pending_spawns` drain. It
  structurally never touches `FinalBossEnemy`'s live reinforcement summons, since those populate
  `pending_spawns` while the boss is still alive, not inside the `enemy.is_dead` branch this check is
  gated on.
- `virulent_bloom`'s `poison_spread_radius` (0 when not granted, `max()`'d across relics) reads from the
  `if enemy.is_dead:` branch: every enemy that dies still poisoned (`enemy.poison_time_remaining > 0`) is
  collected as the loop runs. Only after `self.enemies = still_alive` lands does each collected death
  re-apply its own live poison state (`poison_damage_per_tick`/`poison_tick_interval`/
  `poison_time_remaining`/`poison_ignores_shield`, not a number the relic carries) via
  `Enemy.apply_poison()` to every enemy within `poison_spread_radius`. Deferring the spread until after
  the drain is load-bearing: it reaches enemies that joined this frame (a `SplitterEnemy`'s children)
  while never touching one that's gone, regardless of death order. It also can't cascade within a
  frame, because `apply_poison()` only sets state and the tick damage happens in `Enemy.update()` on a
  later frame.

### No `RelicModifiers` field (checked against `run.relics`)

- `guardians_reprieve` is checked in `Game._lose_a_life()`, the interception point for the
  enemy-reached-goal life loss. It is gated on `RunState.used_guardians_reprieve` (one charge per run)
  and is a no-op under `Economy.invulnerable` (Sandbox has nothing to save).
- `emergency_reserves` is a one-time-per-run gold refund checked inside `Game._spend_gold()`, gated on
  `RunState.used_emergency_reserves`.
- Potion, trophy, construction and counter relics also use Relic-only fields; see their own sections
  below.

## Stacking rules (`compose_relic_modifiers`)

Per-tower fields aggregate the same way as per-floor ones: flat values sum, multipliers multiply.
The exceptions:

- `crit_damage_multiplier` and the `last_stand_*` multipliers are `max()`'d across relics, not
  multiplied. Two such relics compounding multiplicatively would spike far faster than two flat
  +chance relics summing.
- `poison_effect` (`damage_per_tick, tick_interval, duration`) combines the same way
  `Enemy.apply_poison()` combines two poison *hits* on one enemy: keep the harsher tick damage and
  longer duration, last-write on interval. Drafting a second poison relic behaves exactly like landing
  a second poison hit.
- `chain_effect` (`damage_fraction, chain_range`) combines via plain `max()` on both elements.
- Booleans (`poison_ignores_shield`, `cannon_targets_flying`) are OR-composed.
- `tower_damage_multiplier` is composed from *two* `Relic` fields: a flat per-relic multiplier and the
  escalating-per-floor one.

`arcing_rounds`' chain-on-hit bounce (`Projectile._apply_hit_effects`/`_find_chain_target`/
`_apply_direct_damage`) is independent of `LightningTower`'s own `chain_range`/`max_chain_targets`: it
fires on any hit via a chance roll and is always exactly one non-recursive bounce, never a multi-link
chain.

## Tower-exclusive and per-enemy relics

Every field below is copied onto the tower once in `Game._construct_tower` (as a `relic_*` attribute)
and read only by the owning tower class, so none needed `Tower`/`Projectile` plumbing beyond the field
itself. They come in two shapes, and picking the wrong one is the classic mistake:

- **Damage bonus -> `_relic_family_damage_bonus()` hook.** `Tower._relic_family_damage_bonus()` returns
  0.0 on the base class and is overridden by the owning tower, so the bonus adds into
  `effective_damage()`'s additive stack. Multiplying an already-resolved `effective_damage()` at the
  `create_projectile()` call site instead (an early version did) compounds against every other damage
  source -- the one stacking rule `effective_damage()`'s docstring exists to guarantee.
- **Any other input -> plain multiply** in the tower's own `create_projectile()` (or wherever that input
  is read), because chain range, splash radius, ramp, crit and so on aren't part of
  `effective_damage()`'s stack.

| Tower | Relic | `Relic` field | Shape / where read |
|---|---|---|---|
| Lightning | `storm_core` | `lightning_damage_multiplier` | damage hook |
| Lightning | `arc_conductor` | `lightning_chain_range_multiplier` | plain multiply |
| Cannon, Knockback | `heavy_ordnance` | `cannon_knockback_damage_multiplier` | damage hook (both classes override) |
| every splash tower | `shockwave_rounds` | `tower_splash_radius_multiplier` | plain multiply |
| Cannon | `aerial_targeting_array` | `cannon_targets_flying` | OR'd bool; `CannonTower.can_target_flying` is a property reading it |
| Cannon | `high_velocity_shells` | `cannon_projectile_speed_multiplier` | plain multiply on `projectile_speed` |
| Knockback | `seismic_slam` | `knockback_duration_multiplier` | plain multiply |
| Beacon | `luminous_field` | `beacon_splash_radius_multiplier` | plain multiply on `mark_splash_radius` |
| Beacon | `signal_amplifier` | `beacon_mark_multiplier` | plain multiply on `mark_damage_multiplier` |
| Beam | `focused_optics` | `beam_ramp_multiplier` | plain multiply on `ramp_per_hit` |
| Beam | `sustained_barrage` | `beam_max_ramp_bonus` | additive on `max_ramp_multiplier` |
| Basic | `adrenaline_rounds` | `basic_crit_damage_multiplier` | plain multiply on the tower's native crit |
| Basic | `twitch_reflex` | `basic_crit_chance_multiplier` | plain multiply on the tower's native crit |
| Sniper | `kill_shot` | `execute_damage_multiplier` | plain multiply |
| Sniper | `wounded_prey` | `execute_threshold_multiplier` | plain multiply |
| Frost | `glacial_core` | `frost_slow_multiplier` | plain multiply; 0.8, since smaller `slow_factor` is stronger |
| Frost | `permafrost` | `frost_duration_multiplier` | plain multiply |
| Poison | `toxic_payload` | `poison_tower_tick_multiplier` | plain multiply |
| Poison | `festering_wound` | `poison_tower_duration_multiplier` | plain multiply |
| Overload Cannon | `overcharged_capacitors` | `overload_burst_multiplier` | plain multiply on `burst_multiplier` |
| Overload Cannon | `fusion_core` | `overload_damage_multiplier` | damage hook |
| Siphon | `refined_extraction` | `siphon_gold_fraction_multiplier` | read in `Projectile._apply_direct_damage()` (see [towers.md](towers.md) "Siphon Tower's damage-to-gold mechanic") |
| Siphon | `amplified_coils` | `siphon_damage_multiplier` | damage hook |
| Spike Trap | `serrated_spikes` | `spike_trap_damage_multiplier` | damage hook |
| Tar Pit | `clinging_tar` | `tar_pit_marks` | OR'd bool; hits also Mark |
| path traps | `hair_trigger` | `trap_fire_rate_multiplier` | fire-rate bonus for `PLACEMENT == "path"` towers |
| path traps | `kill_corridor` | `trap_damage_vs_slowed_multiplier` | applied in `Game._apply_construction_relics` |
| Mortar | `incendiary_shells` | `mortar_ground_fire` | see "Ground fire (Incendiary Shells)" |
| Harpoon | `barbed_tethers` | `harpoon_ground_duration_multiplier` | Relic-only, multiplied in `_apply_construction_relics`; plain multiply on `ground_duration` |

Notes:

- `glacial_core`'s 0.8 is the inverted-direction quirk `slow_factor` itself has.
- The Basic crit pair is distinct from the generic, `max()`-composed `crit_chance`/
  `crit_damage_multiplier` that `lucky_strikes`/`focused_fire`/`precision_engineering` grant every
  tower, so the two families stack rather than collide.
- `ramp` multiplies straight into Beam's shot damage (`damage = effective_damage() * ramp`). That
  multiplicative relationship is deliberate, pre-existing `BeamTower` design (see its docstring), so the
  Beam relics scale ramp's two inputs directly rather than going through the damage hook.
- `aerial_targeting_array`: `KnockbackTower` keeps its own `can_target_flying = False`, so the relic
  never leaks there. Both towers pass `can_target_flying` into `Projectile(can_hit_flying=...)`, which
  keeps a ground-only shot's splash, Arcing Rounds bounce and Overkill carry off flyers;
  `acquire_target()` alone only stops *aiming* at one.

**Cross-status combo relics** are read generically in `Projectile._apply_hit_effects()` against
pre-hoisted `is_slowed`/`is_marked`/`is_poisoned` booleans: `frostbitten_mark`
(`damage_vs_marked_and_slowed_multiplier`), `plague_mark` (`..._marked_and_poisoned_...`) and `chill_rot`
(`..._slowed_and_poisoned_...`) at 1.35x, and `overwhelming_affliction`
(`damage_vs_marked_and_slowed_and_poisoned_multiplier`) at 1.60x. They are the strongest per-relic
multipliers in the registry because triggering them takes two or three towers' worth of investment.
`chill_rot` stays ungated so the mechanic is reachable early.

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

## Boss relics (player-facing: trophy relics)

`Relic.is_boss_relic` -- excluded from `_default_relic_pool`; `relics.boss_relic_offer` (used only by
`rewards.build_combat_reward(..., is_boss=True)`) draws from `BOSS_RELICS`, topped up from the
ordinary pool once fewer are left. Downsides use ordinary fields where one exists (Siege Engine's
`enemy_speed_multiplier`, Reckless Arsenal's negative `starting_lives_bonus` -- `_apply_one_time_relic_
bonus` clamps lives at 1) and three Relic-only switches otherwise, each read in one place:
`blocks_rest_heal` (`Game._enter_rest_node` -> `rest_heal_blocked`, Rest option disabled, Smith still
works), `blocks_shop_income` (`_advance_run_floor`), `blocks_potions` (`potions.has_free_slot`, so
rewards/Shop stand/Events all refuse new potions while held ones stay usable).

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

## Counter relics

`traps_hit_burrowed` (Seismic Sensors) sets `HITS_BURROWED = True` on a path trap's instance in
`_apply_construction_relics`. `barricade_burst_fraction` (Booby-Trapped Walls) makes
`_hold_enemies_at_barricades` call `Game._barricade_burst` for a breaking Barricade: max hp x fraction
to every ground enemy within `BARRICADE_BURST_RADIUS`, credited to the barricade.
