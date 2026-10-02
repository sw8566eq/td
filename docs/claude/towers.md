# Towers

## Tower progression is two separate axes

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

## Support towers and the two-pass update loop

`SupportTower` (`entities/tower.py`) is the one `TOWER_TYPES` entry that never attacks at all
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
`relic_adjusted_range()` (times its own `relic_aura_range_bonus_multiplier`), for the same "no relic
singles out one tower type" reason -- a Range relic widens a Support tower's own aura radius, not
just its role as an aura *recipient* -- but deliberately *not* `effective_range()`: folding the
transient aura term in would let one Support tower's buff on another widen that other tower's own
broadcast within the same frame, an order-dependent chain reaction (see `relic_adjusted_range()`'s
own docstring). `presentation/ui.py`'s stats
panel and
`Game._handle_panel_action_click` both check `IS_SUPPORT` to skip the targeting-mode row and the
plain Damage/Range/Fire-rate stat block, which would otherwise show a meaningless
`"Damage: 0.0"`/a clickable targeting mode a support tower never reads.

## Overload Cannon's charge-and-burst cycle

`OverloadCannonTower` doesn't fire on the steady cooldown every other tower does -- it locks onto
one target, charges for `1.0 / effective_fire_rate()` seconds (so every existing fire-rate relic,
Support aura included, already speeds or slows the charge for free), then fires a single burst
(`effective_damage() * burst_multiplier`, `burst_multiplier` a flat 1.8x moved only by
specialization/relics, the same shape `BasicTower.crit_chance` already uses) and goes idle to start
a fresh charge. The target is locked exactly once, when a charge begins -- `acquire_target()` is
never called again mid-charge, deliberately: re-acquiring every frame would mean the tower never
really commits to anything, which would remove the actual risk/reward tension this tower exists for.
If the locked target dies, reaches the goal, or leaves range at any point while charging, the charge
resets to zero outright -- no partial burst, no carry-over credit to a new target, mirroring
`BeamTower`'s own "target switch resets the ramp" precedent.

Needing its own `update()` override (its cadence doesn't match the base class's cooldown-then-fire
loop) meant it also needs its own copy of the ~20-line relic-tagging block `Tower.update()` uses to
copy every `relic_*` field onto a freshly-fired projectile -- a deliberate, accepted duplication
rather than a shared-helper extraction, so that every other session adding a relic field to the base
class's copy (as the nineteenth relic batch above already had to) only has to remember to mirror the
same two lines into this tower's own copy, not refactor a shared call site every batch touches.
Cross-referencing comments live at both sites; `test_tower.py`'s own dedicated regression test
diffs the two blocks' actual output (via real fired projectiles, not a hardcoded field list) rather
than trusting a static read, specifically to catch a future desync here.

## Siphon Tower's damage-to-gold mechanic

`SiphonTower` deals little direct damage, but converts a fraction of damage *dealt* --
`siphon_gold_fraction`, flat across levels like `PoisonTower.poison_damage_per_tick`, only moved by
specialization/relics -- into battle gold: the first tower whose own mechanic generates economy from
damage rather than from a kill (`bounty_hunters_ledger` is the closest existing precedent, and that's
a kill-gold-only relic, not a tower mechanic). It deliberately introduces **no** new `Tower`<->
`Economy`/`Game` coupling -- neither class has ever held a live reference to the other, and this
tower doesn't start now. Instead it extends the exact "drain a per-frame/accumulated value in
`Game.update()`" idiom `fired_this_frame`/`impact_events`/`damage_events` already establish (see
"Visual effects" below) to a non-visual use for the first time: `Tower.pending_siphon_gold`
accumulates in `Projectile._apply_direct_damage()` -- the one true per-hit damage-attribution choke
point, right next to the existing `damage_dealt`/`kills` bookkeeping, so an Arcing Rounds-style chain
bounce or an Overkill-style carry-over hit generates Siphon gold too, for free -- and `Game.update()`
drains only the whole-gold portion into `self.economy.add_gold()` each frame, carrying any sub-1-gold
remainder forward rather than resetting it to zero, so fractional credit is never silently lost. The
credit is capped at the hp a hit actually removed (`min(applied, hp_before)`), not `applied` itself --
`Enemy.take_damage()` reports an overkill hit's full nominal amount, which would otherwise pay out gold
for damage past a nearly-dead target's remaining hp. Not
serialized in `persistence/save_state.py`: a save only ever happens between waves, with no live combat state
captured at all, and the remainder is worth less than 1 gold regardless.

## Tower targeting is broad-phase, not brute-force

`Tower.acquire_target()` scans candidate enemies every time a tower's cooldown allows a shot, so
naively this is an O(towers x enemies) pass every frame -- fine at the game's original scale, but
endless mode's design is *unbounded* enemy growth by intent (`entities/waves.py`'s `_default_endless_wave`
compounds every generated wave off the last), so this is exactly the place that growth eventually
gets felt. `spatial_index.EnemySpatialIndex` (`world/spatial_index.py`) narrows the scan without changing
what any tower actually targets: a uniform grid of `(cell_x, cell_y) -> [enemy, ...]` buckets (a
tree wasn't worth it -- the play area is small and fixed-size regardless of enemy count, so a flat
dict is both simpler and, at this scale, at least as fast), rebuilt from scratch once per frame in
`Game.update()` right before the tower loop (enemy positions change every frame regardless, so an
incrementally-maintained structure would re-bucket most enemies every frame anyway, for no less work
than a fresh O(enemies) rebuild) and threaded through every tower's `update()`/`acquire_target()`
call as an optional `enemy_index` parameter. `near(pos, radius)` is deliberately **over-inclusive**
-- a circular query against square cells can return an enemy slightly further than `radius` away --
since every caller already re-filters with its own exact `in_range()`/`distance_to()` check
afterward; the index only ever narrows the candidate *pool*, so passing one changes performance, not
results (see `test_acquire_target_with_an_enemy_index_matches_the_raw_list_scan` in
`tests/test_tower_targeting.py`). Bucket exclusion already drops dead/reached-goal enemies at build
time, mirroring `acquire_target()`'s own candidate filter, but buckets hold the enemy objects
themselves, not copies, so an enemy another tower kills earlier in the same frame (`Game.update()`
builds the index once, before the *whole* tower loop runs) is still reflected immediately through
that same re-check, with no rebuild needed mid-frame. `enemy_index` defaults to `None` everywhere,
falling back to scanning the raw `enemies` list exactly as before -- every existing call site,
chiefly the whole test suite, needed no changes; `SupportTower.update()` accepts the same parameter
for call-signature parity with `Game.update()`'s uniform per-tower call but never reads it, since it
never attacks and so never calls `acquire_target()` at all.

## Post-level results

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

## Veterancy

`run/veterancy.py` (pure, strict-mypy): `RANKS` thresholds, `rank_for`, `floor_xp`. `RunState.tower_xp`
(`{tower type: xp}`, saved and validated) grows only in `Game._award_veterancy`, called from
`_advance_run_floor` -- a restart or loss earns nothing. Every tower of a type (sold ones included, via
`sold_towers`) contributes its `kills`; a class's `VETERANCY_ASSIST_FRACTION` adds that share of the
floor's total kills (Support/Beacon). `Game.veterancy_rank(name)` adds `Relic.veterancy_rank_bonus` and
clamps to `MAX_RANK`; `_construct_tower` calls `_apply_veterancy`, which calls the tower's own
`apply_veterancy(rank)` -- base `Tower` adds `veterancy_damage_bonus` (one more additive
`effective_damage()` source), `SupportTower` scales its aura's bonus portion, `BeaconTower` scales
`relic_beacon_mark_bonus_multiplier` -- plus `Relic.veteran_fire_rate_bonus` at `VETERAN_RANK`. The
panel text comes from each class's `VETERANCY_BONUS_LABEL`/`VETERANCY_BONUS_PER_RANK`, so a new tower
type that overrides `apply_veterancy` describes itself. `TOWER_TYPE_NAMES` is the class->key reverse
lookup.

## Path traps

`Tower.PLACEMENT` is `"ground"` by default; `"path"` makes a trap (`SpikeTrapTower`, `TarPitTower`).
Every placement goes through three Game helpers: `placement_anchor_at(x, y, tower_cls)` (a trap snaps
to the tile under the cursor), `_footprint_for(tower_cls)` (a trap always fills one whole tile, ignoring
footprint-shrinking relics) and `_is_buildable_for` (`Grid.is_buildable(..., on_path=True)` flips the
path rule: every footprint cell must be path). The click handler, the placement preview,
`try_place_tower` and `_construct_tower` all use them, so the rest of the tower lifecycle (save/resume,
sell, upgrade, veterancy) is unchanged. Traps fire ordinary splash projectiles from their own tile, so
relics, kill credit and stats all work as for any tower. HUD build buttons are 40px with 6px gaps to
fit 14 towers next to the worst-case Gold/Lives text (`test_hud_gold_lives_wave_text_fits...`).

## Modules

`run/modules.py` (strict mypy): `MODULES` registry and `module_offer(rng, run, damaging_types)` -> a
(module, tower type) pair, preferring a type with no module and never re-offering its current one
(damage-only modules skip non-damaging types). `RunState.tower_modules` ({type: module}, saved and
validated). `rewards.build_combat_reward` draws one *last* for an Elite (`CombatReward.module`) and
drops the Elite's potion in its place unless a guaranteed-potion relic is held (then the reward is 6
cards -- `build_draft_choice_rects`' narrow layout). `Game._take_reward_card` kind `"module"` fits it.
`_construct_tower` calls `modules.apply_module` after relic fields and veterancy: `module_damage_bonus`
(an additive `effective_damage()` source), range/fire-rate multipliers on the relic bonus fields, and
on-hit slow/poison via `relic_slow_*`/`relic_poison_*` (copied onto projectiles by `Tower.update()`).

The Shop's module stand (`Game.shop_module`, `_try_buy_shop_module`, `shop.MODULE_PRICE`, right of
Continue via `ui.build_shop_module_rect`) is rolled last from the visit's rng, once per visit.

## Minimum range (Mortar)

`Tower.MIN_RANGE` (0 by default) is a dead zone `acquire_target` filters out; `MortarTower` sets it to
80. Both range previews draw it as a red ring. HUD build buttons are now 36px with 5px gaps (15 towers);
icons are `BUTTON_SIZE - 14`.
