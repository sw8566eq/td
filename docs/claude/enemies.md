# Content registries and enemy mechanics

## Content is registries, not conditionals

Towers (`TOWER_TYPES` in `entities/tower.py`), enemies (`ENEMY_TYPES` in `entities/enemy.py`), and levels (`LEVELS`
in `world/levels.py`) are all `{name: class_or_instance}` dicts. `Grid`, `WaveManager`, `presentation/ui.py`'s build
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
stats panel automatically. `Projectile` (`entities/projectile.py`) is a single data-parametrized class, not
one subclass per tower -- splash/slow/knockback/chain/mark are just constructor args a tower's
`create_projectile()` passes in, and the hit-resolution algorithm doesn't care which combination
it got (see "Mark and Corrosive Poison's shield-bypass hook" below for why Mark's own
amplification math still lives in `Enemy`, not here).

## Boss enemy mechanics

`BossEnemy` (`entities/enemy.py`) layers two self-contained, one-time mechanics on top of the generic
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
(`world/levels.py`'s own `LEVEL_17_WAVE_SPECS`, the only line that changed to wire it in). It also
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

`Enemy.IS_BOSS` (`False` on the base class, `True` on `BossEnemy` only) is a class-level flag added
for `titan_slayer` (see the `run/relics.py` bullet above), mirroring `Tower.IS_SUPPORT`'s own shape
exactly -- a plain boolean neither subclass ever needs to check dynamically, just inherit or
override once. `FinalBossEnemy`/`FinalBossShieldedEnemy` both subclass `BossEnemy` directly and
never override class-level flags like this one, so they inherit `IS_BOSS = True` for free, same as
they already inherit Enrage/Armor unmodified. `Projectile._apply_hit_effects()` reads it via
`getattr(enemy, "IS_BOSS", False)`, the same neutral-default idiom every other ungated per-enemy
multiplier check here already uses, so a lightweight `FakeEnemy` test double that never sets the
attribute is treated as non-boss rather than raising.

## Mark and Corrosive Poison's shield-bypass hook

Two mechanics from the tower/relic synergy batch live inside `Enemy` itself rather than
`Projectile`/a per-species special case, because each has to affect *every* damage source
uniformly, not just a tower's own direct hit resolution:

- **Mark** (`BeaconTower`'s own mechanic, `entities/tower.py`) is `Enemy.mark_damage_multiplier`/
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

## Breach strength and Sappers

`Enemy.BREACH_MULTIPLIER` scales how hard an enemy batters a Barricade (`Game._hold_enemies_at_barricades`):
1 by default, 6 for `BossEnemy` (and its subclasses), 5 for `SapperEnemy`. Sappers (and Burrowers) are never in an
authored level: `Game._level_for_node` adds every `run_escalation.RUN_REINFORCEMENTS` entry's
`count_for_depth(depth)` to each wave's first spawn cell (`run_escalation.add_species`, a copy -- the same private-copy path the
Swarming affix uses, so a mid-floor save keeps them) from `SAPPER_MIN_DEPTH` (Act 2's first row) on.

`Enemy.BURROWS` (Burrower): `Tower.HITS_BURROWED` is False on path traps, checked in `acquire_target`
and passed into `Projectile(can_hit_burrowed=...)` so their splash skips it too; the barricade hold
skips it. Trap and Mortar shots also pass `can_hit_flying` now (their splash used to touch flyers).

## Knockback stagger resistance

`Enemy.knockback_resistance` (0..`KNOCKBACK_RESISTANCE_CAP`) scales every `apply_knockback` distance by
`1 - resistance`, then grows by `KNOCKBACK_RESISTANCE_PER_SHOVE`; `update()` decays it by
`KNOCKBACK_RESISTANCE_DECAY` per second. Applies to every knockback source (tower, relic, potion).
Added after a fixed-budget, single-tower-type bench showed 3+ Knockback towers holding Act 3 waves
forever with zero leaks.

## Knockback stagger resistance

`Enemy.knockback_resistance` (0..`KNOCKBACK_RESISTANCE_CAP`) scales every `apply_knockback` distance by
`1 - resistance`, then grows by `KNOCKBACK_RESISTANCE_PER_SHOVE`; `update()` decays it by
`KNOCKBACK_RESISTANCE_DECAY` per second. Applies to every knockback source (tower, relic, potion).
Added after a fixed-budget, single-tower-type bench showed 3+ Knockback towers holding Act 3 waves
forever with zero leaks.
