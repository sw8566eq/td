"""Run-wide passive modifier cards ("relics") -- a second, genuinely
optional card type alongside tower cards (see card_pool.py), offered
together with them in the same Shop visit (see shop.build_offer/Game.
_enter_draft). Every relic's numeric effect is one of three shapes:

- Per-floor (RelicModifiers' own fields), composed into a run's
  floor-load the same way difficulty.DIFFICULTY_MODES/
  run_escalation.FloorEscalation already are: an extra factor on top of
  what's already there, never replacing it. Some of these feed
  WaveManager/Economy construction directly (gold_per_floor_bonus/
  enemy_gold_multiplier/enemy_speed_multiplier); others are read once per
  tower at construction time instead (tower_range_multiplier/
  tower_fire_rate_multiplier/poison_chance/poison_effect/crit_chance/
  crit_damage_multiplier/tower_footprint_shrink) -- see RelicModifiers'
  own docstring and Game._construct_tower/_current_footprint_subtiles.
- One-time (sturdy_gate's starting_lives_bonus), applied once instead,
  directly, the instant the card is drafted (Game._apply_one_time_relic_
  bonus) -- see RelicModifiers' own docstring for why a one-time bonus
  can't be folded into the per-floor composition above. war_chest's own
  starting_gold_multiplier *used* to need this same one-time treatment,
  back when battle gold carried forward across floors and "starting gold"
  only existed once, at floor 0 -- now that battle gold resets fresh every
  floor instead (see CLAUDE.md's "Two currencies" section), it's just
  another per-floor RelicModifiers field like gold_per_floor_bonus, applied
  by Game._load_level_object's own Economy construction on every floor,
  not a special case anymore.

A later batch added three more shapes that don't fit either bullet above:
escalating-per-floor (veterans_momentum's tower_damage_growth_per_floor,
folded into RelicModifiers.tower_damage_multiplier via compose_relic_
modifiers' new floor_index parameter -- the per-floor bucket above is a
flat constant every floor, this one grows with floors_cleared instead),
conditionally-revocable (misers_coffer's gold_per_floor_bonus_while_
unspent, gated on the new has_spent_gold parameter -- a per-floor bonus
that can permanently stop applying partway through a run), and
live-reactive (last_stand_charm's last_stand_damage_multiplier, the only
relic effect resolved every frame against changing game state --
Economy.lives -- rather than once at floor-load or tower-construction
time; see Tower.set_last_stand_multiplier/Game.update()).

A further batch added a 7th shape, per-tower-density (also live-reactive,
but per-tower rather than global, and event-driven rather than every
frame): overcrowded_circuits' tower_density_radius/tower_density_damage_
bonus_per_neighbor/tower_density_damage_bonus_cap, resolved from each
tower's own live neighbor count (see Tower.set_nearby_tower_bonus())
whenever the board's tower set actually changes -- a placement, a sale, a
save restore (Game._recompute_tower_density_bonuses()) -- rather than
continuously every frame the way last_stand_damage_multiplier's own live
check is: a tower's position never changes once placed, so nothing about
its neighbor count can change between one of those events and the next.

A later batch filling in remaining category gaps (knockback/mark-chance,
anti-flying/shielded/healer damage, Splitter counterplay) mostly extended
the existing per-tower shape (knockback_chance/knockback_effect and
mark_chance/mark_effect follow poison/slow's exact chance-gated pattern;
damage_vs_flying_multiplier/damage_vs_shielded_multiplier/damage_vs_
healer_multiplier join the ungated per-tower multiplier group). One
relic in that batch, containment_charges, doesn't fit per-tower at all,
though -- an 8th shape: splitter_child_damage is a flat per-floor value
read straight off RelicModifiers by Game.update()'s own dead-enemy drain
loop (the one place Enemy.pending_spawns is ever read), not threaded
through Tower/Projectile construction like every per-tower field above,
since nothing about it varies by which tower landed the killing blow.

Unlike a tower card, most relics aren't gated by meta_progression.py --
every relic that shipped before the relic-category-gaps batch (all 29 of
them) is always eligible to be offered in any run; there are few enough
relics, and few enough relic-draft floors per run, that account-wide
unlock-gating every relic would add a second progression system for a
card type explicitly framed as secondary/optional (see the plan's design
resolution), not a proportional amount of extra depth. Once the original
tower curve started feeling exhausted too quickly, though, a handful of
the *newest* relics became a natural place to extend it further -- see
meta_progression.RELIC_META_UNLOCKS and _default_relic_pool() below,
mirroring card_pool._default_unlocked_pool's own shape exactly.
"""

from dataclasses import dataclass

import meta_progression
from rng_sampling import sample_up_to


@dataclass(frozen=True)
class Relic:
    key: str
    display_name: str
    description: str
    gold_per_floor_bonus: int = 0
    starting_gold_multiplier: float = 1.0
    starting_lives_bonus: int = 0
    enemy_gold_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    # Tower-facing fields below -- composed into RelicModifiers the same
    # "flat bonuses add, multipliers multiply" way as everything above,
    # then copied onto each Tower instance at construction time
    # (Game._construct_tower) rather than threaded through
    # WaveManager/Economy like the per-floor fields above. Neutral
    # defaults (0.0/1.0/0/None) mean a relic that doesn't set one simply
    # doesn't contribute to it -- see compose_relic_modifiers.
    tower_range_multiplier: float = 1.0
    tower_fire_rate_multiplier: float = 1.0
    poison_chance: float = 0.0
    poison_damage_per_tick: float = 0.0
    poison_tick_interval: float = 0.0
    poison_duration: float = 0.0
    crit_chance: float = 0.0
    crit_damage_multiplier: float = 1.0
    # Footprint shrink is the one tower-facing field that ISN'T copied onto
    # a Tower's own attribute by _construct_tower -- see
    # Game._current_footprint_subtiles()/_construct_tower instead, since
    # it has to be resolved *before* a Tower's pixel_pos is even computed,
    # not after the tower object already exists.
    tower_footprint_shrink: int = 0
    tower_damage_multiplier: float = 1.0
    # Relic-only -- never appears on RelicModifiers itself. Folded into
    # RelicModifiers.tower_damage_multiplier by compose_relic_modifiers via
    # `*= (1.0 + tower_damage_growth_per_floor * floor_index)`, so a relic
    # granting this escalates every floor instead of being a flat constant
    # like every tower_*_multiplier field above.
    tower_damage_growth_per_floor: float = 0.0
    # chain_chance follows poison_chance's exact shape (chance-gated,
    # summed, no "every floor"/"for this run" suffix in its description --
    # see RELICS' own comment on venomous_coating/lucky_strikes).
    # chain_damage_fraction/chain_range are Relic-only, folded into
    # RelicModifiers.chain_effect the same way poison's own raw per-tick
    # fields fold into poison_effect. See Projectile._apply_hit_effects/
    # _find_chain_target for where this actually applies.
    chain_chance: float = 0.0
    chain_damage_fraction: float = 0.0
    chain_range: float = 0.0
    # Relic-only -- misers_coffer's own conditional bonus. Folded into
    # RelicModifiers' shared gold_per_floor_bonus accumulator by
    # compose_relic_modifiers, gated on the new has_spent_gold parameter
    # rather than on anything this dataclass itself tracks -- see
    # Game._spend_gold for where that flag actually gets set.
    gold_per_floor_bonus_while_unspent: int = 0
    # last_stand_charm's own bonus -- see RelicModifiers' matching field
    # and Tower.set_last_stand_multiplier/effective_damage() for where it
    # actually applies; aggregated via max(), the same conservative choice
    # crit_damage_multiplier already makes, since it's dormant today (only
    # one such relic exists).
    last_stand_damage_multiplier: float = 1.0
    # quartermasters_favor's own discount -- see Tower.upgrade_cost()/
    # specialization_cost().
    tower_upgrade_cost_multiplier: float = 1.0
    # liquidation_rights' own bonus -- added to (not multiplied against)
    # settings.SELL_REFUND_FRACTION, see Tower.sell_value().
    sell_refund_bonus: float = 0.0
    # resonant_field's own pair -- see RelicModifiers' matching fields and
    # SupportTower.update() for where they actually apply. Deliberately
    # separate from tower_range_multiplier above -- see that method's own
    # comment for why.
    support_aura_range_multiplier: float = 1.0
    support_aura_strength_multiplier: float = 1.0
    # chilling_precision's own bonus -- multiplies straight into
    # effective_damage() (ungated, like tower_damage_multiplier) whenever
    # Projectile._apply_hit_effects() finds enemy.slow_timer > 0 *before*
    # this same hit's own slow application, so a Frost tower's first-ever
    # hit on a target never retroactively counts itself as "vs. slowed".
    damage_vs_slowed_multiplier: float = 1.0
    # aftershock's own chance-gated roll, same shape as poison_chance/
    # chain_chance above -- slow_factor/slow_duration are the *raw* per-
    # relic values, folded into RelicModifiers.slow_effect the same way
    # poison's own raw per-tick fields fold into poison_effect.
    slow_chance: float = 0.0
    slow_factor: float = 0.0
    slow_duration: float = 0.0
    # corrosive_poison's own bypass -- see Enemy.take_poison_damage/
    # ShieldedEnemy's override. Boolean OR across held relics: once any
    # one of them grants it, it stays granted.
    poison_ignores_shield: bool = False
    # overcrowded_circuits' own density bonus -- resolved live, every
    # frame, from each tower's own neighbor count (Game.update()'s
    # existing two-pass tower loop; see Tower.set_nearby_tower_bonus), not
    # once at construction time like every tower_*_multiplier field above.
    # tower_density_radius is a reach value (max()'d across relics, same
    # precedent as chain_effect's chain_range); the per-neighbor rate and
    # cap are flat magnitudes (summed, same as gold_per_floor_bonus).
    tower_density_radius: float = 0.0
    tower_density_damage_bonus_per_neighbor: float = 0.0
    tower_density_damage_bonus_cap: float = 0.0
    # adrenaline_rush's own bonus -- see RelicModifiers' matching field and
    # Tower.set_last_stand_multiplier()/effective_fire_rate() for where it
    # actually applies; aggregated via max(), the same conservative choice
    # last_stand_damage_multiplier already makes.
    last_stand_fire_rate_multiplier: float = 1.0
    # choke_point's own bonus -- multiplies straight in (ungated), same
    # shape as damage_vs_slowed_multiplier above. See
    # projectile.CHOKE_POINT_DISTANCE_THRESHOLD for the fixed pixel cutoff
    # this checks against -- a plain module constant in projectile.py, not
    # a Relic field, since relics.py has no import dependency on
    # tower.py/projectile.py today and every existing per-mechanic
    # constant already lives beside the mechanic that consumes it.
    damage_vs_early_route_multiplier: float = 1.0
    # giant_slayer's own bonus -- same ungated-multiply shape, checked
    # against projectile.GIANT_SLAYER_HP_THRESHOLD.
    damage_vs_high_hp_multiplier: float = 1.0
    # overkill's own bonus -- see projectile.OVERKILL_CARRY_RANGE for the
    # fixed pixel range its carry-over bounce searches within.
    overkill_carry_fraction: float = 0.0
    # concussive_rounds' own chance-gated roll, same shape as poison_
    # chance/slow_chance/chain_chance above -- knockback_duration is the
    # *raw* per-relic value (seconds of forward path progress undone, the
    # same unit KnockbackTower's own knockback_duration already uses),
    # folded into RelicModifiers.knockback_effect the same way slow's own
    # raw factor/duration fold into slow_effect.
    knockback_chance: float = 0.0
    knockback_duration: float = 0.0
    # disorienting_flash's own chance-gated roll -- mark_multiplier/
    # mark_duration are the *raw* per-relic values, folded into
    # RelicModifiers.mark_effect the same way slow's own raw fields fold
    # into slow_effect. Combined via max()/max() across relics, matching
    # Enemy.apply_mark()'s own combine semantics exactly (see its
    # docstring) -- unlike slow_factor, a bigger mark multiplier is always
    # the stronger effect.
    mark_chance: float = 0.0
    mark_multiplier: float = 1.0
    mark_duration: float = 0.0
    # flak_rounds'/breach_charges' own bonuses -- ungated straight
    # multiplies, same shape as damage_vs_slowed_multiplier/damage_vs_
    # early_route_multiplier/damage_vs_high_hp_multiplier above. Checked
    # against the target's own *current* is_flying/shield state at hit
    # time (duck-typed via getattr, like every other per-enemy check in
    # Projectile._apply_hit_effects), not its species identity.
    damage_vs_flying_multiplier: float = 1.0
    damage_vs_shielded_multiplier: float = 1.0
    # containment_charges' own bonus -- a flat damage magnitude (summed
    # across relics, same as overkill_carry_fraction's own shape, not a
    # multiplier), applied once to each of a killed SplitterEnemy's own
    # freshly-spawned children before they ever join self.enemies. Unlike
    # every other tower-facing field on this class, this one is read
    # straight off RelicModifiers by Game.update()'s own dead-enemy drain
    # loop, not threaded through Tower/Projectile -- it has no per-tower
    # or per-shot variation to justify that plumbing.
    splitter_child_damage: float = 0.0
    # suppression_directive's own bonus -- ungated straight multiply, same
    # shape as flak_rounds/breach_charges above. Checked against the
    # target's own current heal_rate > 0 (HealerEnemy's own attribute),
    # duck-typed the same way.
    damage_vs_healer_multiplier: float = 1.0
    # interceptor_rounds' own bonus -- ungated straight multiply, same
    # shape as flak_rounds/breach_charges/suppression_directive above.
    # Checked against the target's own max_speed (a fixed per-species
    # ceiling, not its live speed) against projectile.
    # FAST_ENEMY_SPEED_THRESHOLD.
    damage_vs_fast_multiplier: float = 1.0
    # shockwave_rounds' own bonus -- ungated straight multiply, read once
    # per tower at construction time (Game._construct_tower), same
    # pipeline as tower_range_multiplier, applied to any tower with a
    # splash_radius attribute (Cannon, Knockback -- not Beacon, whose
    # mark_splash_radius is a distinctly-named field this doesn't touch).
    tower_splash_radius_multiplier: float = 1.0
    # arc_conductor's own bonus -- Lightning-tower-exclusive, mirroring
    # support_aura_range_multiplier's own shape: set on every tower
    # harmlessly at construction time, but only ever read inside
    # LightningTower.create_projectile(). max_chain_targets is
    # deliberately not a field here -- it's already unbounded, so a
    # "+N targets" relic would be meaningless.
    lightning_chain_range_multiplier: float = 1.0
    # haggling_permit's own bonus -- ungated straight multiply, read by
    # shop.price_for()'s own discount_multiplier parameter rather than
    # through Tower/Projectile at all (the Shop's own prices aren't a
    # per-tower or per-shot concern), the one relic-driven discount on the
    # shop-currency side of the economy -- quartermasters_favor already
    # covers the battle-gold side (Tower.upgrade_cost()/specialization_
    # cost()).
    shop_price_multiplier: float = 1.0
    # storm_core's own bonus -- Lightning-tower-exclusive, set on every
    # tower harmlessly at construction time like lightning_chain_range_
    # multiplier, but folded into effective_damage()'s own additive stack
    # via LightningTower._relic_family_damage_bonus() rather than a plain
    # create_projectile() multiply -- a damage bonus has to combine with
    # every other damage source the same additive way, unlike chain_range/
    # splash_radius below, which aren't part of that stack at all. See
    # Tower._relic_family_damage_bonus's own docstring for why this needs
    # a per-class hook instead of a field effective_damage() reads
    # directly.
    lightning_damage_multiplier: float = 1.0
    # heavy_ordnance's own bonus -- Cannon/Knockback-exclusive, same
    # family_damage_bonus() hook shape as lightning_damage_multiplier
    # immediately above, just overridden identically by both CannonTower
    # and KnockbackTower -- the same two towers relic_splash_radius_bonus_
    # multiplier already reads identically in (that one's still a plain
    # create_projectile() multiply, since splash_radius isn't part of
    # effective_damage()'s stack).
    cannon_knockback_damage_multiplier: float = 1.0
    # luminous_field's own bonus -- Beacon-tower-exclusive, mirroring
    # tower_splash_radius_multiplier's exact shape (a plain create_
    # projectile() multiply, not the family_damage_bonus() hook -- this
    # scales mark_splash_radius, not damage, so it isn't part of
    # effective_damage()'s stack at all). Beacon-specific because
    # shockwave_rounds deliberately excludes Beacon (see that relic's own
    # comment): Beacon's splash is a marking area, not a damage-dealing
    # blast radius, so it needs its own dedicated relic rather than
    # reusing that one.
    beacon_splash_radius_multiplier: float = 1.0
    # signal_amplifier's own bonus -- Beacon-tower-exclusive, same plain-
    # multiply shape as beacon_splash_radius_multiplier immediately above,
    # but scaling mark_damage_multiplier instead of mark_splash_radius.
    # Also not a family_damage_bonus() case: mark_damage_multiplier isn't
    # this tower's own shot damage either -- it is Enemy.apply_mark()'s
    # own bonus multiplier applied to *every* source's damage against a
    # marked enemy later (see Enemy.take_damage()), a separate mechanism
    # from effective_damage() entirely, the same way slow_effect/
    # chain_effect are.
    beacon_mark_multiplier: float = 1.0
    # focused_optics' own bonus -- Beam-tower-exclusive, same plain-
    # create_projectile()-read shape as the Beacon-exclusive pair above:
    # ramp_per_hit is an input to BeamTower's own ramp formula
    # (`ramp = min(1.0 + consecutive_hits * ramp_per_hit, max_ramp_
    # multiplier)`, then `damage = effective_damage() * ramp`), not one of
    # effective_damage()'s own additive sources -- the multiplicative
    # relationship between ramp and effective_damage() is pre-existing,
    # deliberate BeamTower design (see that class's own docstring on why
    # it was tuned down after a real playtest), not something this relic
    # changes, so it doesn't belong in the family_damage_bonus() hook.
    beam_ramp_multiplier: float = 1.0
    # sustained_barrage's own bonus -- same Beam-exclusive, plain-read
    # shape as beam_ramp_multiplier immediately above, but ADDITIVE (not
    # multiplicative) onto max_ramp_multiplier -- mirrors sell_refund_
    # bonus's own additive shape, since max_ramp_multiplier is already
    # itself a multiplier and stacking two multiplicative bonuses on it
    # would compound oddly.
    beam_max_ramp_bonus: float = 0.0
    # virulent_bloom's own bonus -- a ninth shape, mirroring containment_
    # charges'/splitter_child_damage's own "flat, non-tower" read site
    # (Game.update()'s own dead-enemy drain loop) rather than anything
    # threaded through Tower/Projectile: 0 (not granted) or a spread
    # radius, max()'d across relics the same way tower_density_radius is.
    # No per-relic damage/duration numbers needed at all -- the spread
    # carries over whatever poison was actually killing the enemy (from a
    # PoisonTower hit, venomous_coating, or both combined), read straight
    # off the dying enemy's own live poison_damage_per_tick/poison_tick_
    # interval/poison_time_remaining/poison_ignores_shield (see enemy.py's
    # apply_poison()/update()) rather than any number this relic itself
    # carries.
    poison_spread_radius: float = 0.0
    # kill_shot's own bonus -- Sniper-tower-exclusive, same plain-multiply
    # shape as beacon_mark_multiplier/beam_ramp_multiplier above:
    # execute_damage_multiplier is a conditional per-hit bonus resolved
    # inside Projectile (see tower.py's own Kill Shot comment), not part
    # of effective_damage()'s additive stack, so it skips the
    # family_damage_bonus() hook. No existing relic references Execute at
    # all before this pair.
    execute_damage_multiplier: float = 1.0
    # wounded_prey's own bonus -- Sniper-tower-exclusive, same plain-
    # multiply shape as execute_damage_multiplier immediately above,
    # scaling execute_hp_threshold instead (a bigger threshold is the buff
    # direction -- see tower.py's own Wounded Prey comment).
    execute_threshold_multiplier: float = 1.0


RELICS = {
    "prospectors_charm": Relic(
        "prospectors_charm", "Prospector's Charm", "+20 gold at the start of every floor.",
        gold_per_floor_bonus=20,
    ),
    # sturdy_gate is a deliberately one-time bonus, not a per-floor one --
    # its description text says so honestly, rather than promising a
    # recurring effect. Applied directly onto the run's carried lives the
    # instant the card is drafted (Game._apply_one_time_relic_bonus), not
    # folded into Economy construction the way every other relic modifier
    # is (see RelicModifiers' own docstring for why a one-time bonus can't
    # be folded into the per-floor composition above). war_chest used to
    # need this same one-time treatment -- see this module's own docstring
    # above for why it's now a normal per-floor RelicModifiers field
    # instead.
    "war_chest": Relic(
        "war_chest", "War Chest", "+25% starting gold, every floor.",
        starting_gold_multiplier=1.25,
    ),
    "sturdy_gate": Relic(
        "sturdy_gate", "Sturdy Gate", "+3 extra lives for this run.",
        starting_lives_bonus=3,
    ),
    "bounty_hunters_ledger": Relic(
        "bounty_hunters_ledger", "Bounty Hunter's Ledger", "+15% gold from every kill.",
        enemy_gold_multiplier=1.15,
    ),
    "tangled_roots": Relic(
        "tangled_roots", "Tangled Roots", "Enemies move 10% slower, every floor.",
        enemy_speed_multiplier=0.90,
    ),
    "spyglass_array": Relic(
        "spyglass_array", "Spyglass Array", "+10% range for every tower, every floor.",
        tower_range_multiplier=1.10,
    ),
    "quickfire_rounds": Relic(
        "quickfire_rounds", "Quickfire Rounds", "+8% fire rate for every tower, every floor.",
        tower_fire_rate_multiplier=1.08,
    ),
    # Deliberately weaker than PoisonTower's own base poison (4 damage/tick,
    # 0.5s interval, 3.0s duration -> 24 total) -- Enemy.apply_poison()'s
    # own max()-per-field refresh semantics (see its own docstring) mean a
    # successful roll here on a hit that's already poisoning from
    # PoisonTower itself is usually absorbed without visibly changing
    # anything, but the dedicated tower keeps its identity as the
    # strongest poison source in the game either way.
    "venomous_coating": Relic(
        "venomous_coating", "Venomous Coating", "15% chance for any hit to poison its target.",
        poison_chance=0.15, poison_damage_per_tick=3, poison_tick_interval=0.5, poison_duration=2.0,
    ),
    "lucky_strikes": Relic(
        "lucky_strikes", "Lucky Strikes", "12% chance for any hit to deal double damage.",
        crit_chance=0.12, crit_damage_multiplier=2.0,
    ),
    # tower_footprint_shrink=2 drops the footprint from 8x8 to 6x6 subtiles
    # -- 75% of the width/height, but 75%^2 = 56.25% of the *area*, so the
    # card text below describes the actual ~44% space reduction, not the
    # smaller 25% per-side shrink the raw field name might suggest.
    "compact_framework": Relic(
        "compact_framework", "Compact Framework", "Towers take up about 44% less space on the grid, every floor.",
        tower_footprint_shrink=2,
    ),
    "overdrive_coils": Relic(
        "overdrive_coils", "Overdrive Coils", "+20% fire rate for every tower, but -15% damage, every floor.",
        tower_fire_rate_multiplier=1.20, tower_damage_multiplier=0.85,
    ),
    # The inverse trade of overdrive_coils above -- reuses the same
    # tower_damage_multiplier field tuned the opposite direction, so the
    # two together are a real fire-rate/damage build axis, not two
    # unrelated numbers.
    "snipers_discipline": Relic(
        "snipers_discipline", "Sniper's Discipline", "+25% damage for every tower, but -20% fire rate, every floor.",
        tower_damage_multiplier=1.25, tower_fire_rate_multiplier=0.80,
    ),
    # Escalating, not flat -- see compose_relic_modifiers' floor_index
    # parameter and relics.py's own module docstring for why this doesn't
    # fit the "every floor"/"for this run" description convention above.
    "veterans_momentum": Relic(
        "veterans_momentum", "Veteran's Momentum", "+2% tower damage for every floor cleared this run.",
        tower_damage_growth_per_floor=0.02,
    ),
    "arcing_rounds": Relic(
        "arcing_rounds", "Arcing Rounds", "20% chance for any hit to also strike a nearby enemy for 50% damage.",
        chain_chance=0.20, chain_damage_fraction=0.5, chain_range=70,
    ),
    # Bigger than prospectors_charm's flat +20 since it's conditional --
    # closer to Slay the Spire's actual Maw Bank than a per-floor reset:
    # one run-long deactivation (Game._spend_gold/RunState.has_spent_
    # gold), not something that comes back next floor.
    "misers_coffer": Relic(
        "misers_coffer", "Miser's Coffer",
        "+40 gold at the start of every floor -- until you spend any gold, then never again this run.",
        gold_per_floor_bonus_while_unspent=40,
    ),
    # No numeric fields at all -- same shape as war_chest/sturdy_gate,
    # checked directly against run.relics rather than through RelicModifiers
    # (see Game._lose_a_life). There's nothing here to aggregate.
    "guardians_reprieve": Relic(
        "guardians_reprieve", "Guardian's Reprieve",
        "The first time you'd lose your last life this run, survive with 1 life instead.",
    ),
    "last_stand_charm": Relic(
        "last_stand_charm", "Last Stand Charm",
        "+30% damage for every tower while you're down to your last life.",
        last_stand_damage_multiplier=1.30,
    ),
    "quartermasters_favor": Relic(
        "quartermasters_favor", "Quartermaster's Favor",
        "Tower upgrades and specializations cost 15% less gold, every floor.",
        tower_upgrade_cost_multiplier=0.85,
    ),
    "liquidation_rights": Relic(
        "liquidation_rights", "Liquidation Rights",
        "Selling a tower refunds an extra 15% of what you paid for it, every floor.",
        sell_refund_bonus=0.15,
    ),
    "resonant_field": Relic(
        "resonant_field", "Resonant Field",
        "Support tower auras reach 20% further and buff 20% more, every floor.",
        support_aura_range_multiplier=1.20, support_aura_strength_multiplier=1.20,
    ),
    "chilling_precision": Relic(
        "chilling_precision", "Chilling Precision",
        "Towers deal 20% more damage to enemies that are currently slowed.",
        damage_vs_slowed_multiplier=1.20,
    ),
    # Deliberately weaker than FrostTower's own base slow (0.5 factor,
    # 2.0s duration) -- same "the dedicated tower stays the strongest
    # source" reasoning venomous_coating's own comment gives for poison.
    "aftershock": Relic(
        "aftershock", "Aftershock", "18% chance for any hit to also slow its target.",
        slow_chance=0.18, slow_factor=0.75, slow_duration=1.5,
    ),
    "corrosive_poison": Relic(
        "corrosive_poison", "Corrosive Poison", "Poison damage always breaks through enemy shields.",
        poison_ignores_shield=True,
    ),
    "overcrowded_circuits": Relic(
        "overcrowded_circuits", "Overcrowded Circuits",
        "+2% tower damage for every other tower within 80 pixels of it, capped at +20%, every floor.",
        tower_density_radius=80, tower_density_damage_bonus_per_neighbor=0.02,
        tower_density_damage_bonus_cap=0.20,
    ),
    "adrenaline_rush": Relic(
        "adrenaline_rush", "Adrenaline Rush",
        "+15% tower fire rate while you're down to your last life.",
        last_stand_fire_rate_multiplier=1.15,
    ),
    "choke_point": Relic(
        "choke_point", "Choke Point",
        "Towers deal 25% more damage to enemies that haven't traveled far along their route yet.",
        damage_vs_early_route_multiplier=1.25,
    ),
    "giant_slayer": Relic(
        "giant_slayer", "Giant Slayer", "+25% damage to enemies with more than 100 max HP.",
        damage_vs_high_hp_multiplier=1.25,
    ),
    # Reuses lucky_strikes' own two fields verbatim, tuned to its own
    # numbers -- no new plumbing needed anywhere (see compose_relic_
    # modifiers' existing crit_chance/crit_damage_multiplier handling).
    "focused_fire": Relic(
        "focused_fire", "Focused Fire", "+10% crit chance for every tower, every floor.",
        crit_chance=0.10, crit_damage_multiplier=1.5,
    ),
    "overkill": Relic(
        "overkill", "Overkill",
        "Damage beyond what's needed to kill an enemy carries over to a nearby enemy, at 50% strength.",
        overkill_carry_fraction=0.5,
    ),
    "concussive_rounds": Relic(
        "concussive_rounds", "Concussive Rounds",
        "18% chance for any hit to also knock its target back.",
        knockback_chance=0.18, knockback_duration=0.3,
    ),
    # Deliberately weaker than BeaconTower's own base mark (1.20x, 3.0s) --
    # same "the dedicated tower stays the strongest source" reasoning
    # venomous_coating's own comment gives for poison.
    "disorienting_flash": Relic(
        "disorienting_flash", "Disorienting Flash",
        "15% chance for any hit to also mark its target.",
        mark_chance=0.15, mark_multiplier=1.15, mark_duration=2.0,
    ),
    "flak_rounds": Relic(
        "flak_rounds", "Flak Rounds", "+25% damage to airborne enemies.",
        damage_vs_flying_multiplier=1.25,
    ),
    "breach_charges": Relic(
        "breach_charges", "Breach Charges",
        "+25% damage to enemies currently protected by a shield.",
        damage_vs_shielded_multiplier=1.25,
    ),
    "containment_charges": Relic(
        "containment_charges", "Containment Charges",
        "Killing an enemy that splits on death also damages what it splits into.",
        splitter_child_damage=18,
    ),
    "suppression_directive": Relic(
        "suppression_directive", "Suppression Directive",
        "+20% damage to enemies that heal others.",
        damage_vs_healer_multiplier=1.20,
    ),
    "interceptor_rounds": Relic(
        "interceptor_rounds", "Interceptor Rounds",
        "+20% damage to enemies that move especially fast.",
        damage_vs_fast_multiplier=1.20,
    ),
    "shockwave_rounds": Relic(
        "shockwave_rounds", "Shockwave Rounds",
        "+20% splash radius for every tower that has one, every floor.",
        tower_splash_radius_multiplier=1.20,
    ),
    "arc_conductor": Relic(
        "arc_conductor", "Arc Conductor",
        "Lightning tower chains reach 25% further, every floor.",
        lightning_chain_range_multiplier=1.25,
    ),
    "haggling_permit": Relic(
        "haggling_permit", "Haggling Permit",
        "Shop prices are 15% lower, every floor.",
        shop_price_multiplier=0.85,
    ),
    # A second, independently-functional density relic -- same shape as
    # overcrowded_circuits itself (own radius/per-neighbor rate/cap, no
    # dependency on that relic to do something), so this alone is never a
    # dud; the two combine via compose_relic_modifiers' existing max()/sum/
    # sum aggregation (radius max()'d, rate and cap summed) the exact same
    # way two poison- or slow-granting relics already combine.
    "reinforced_chassis": Relic(
        "reinforced_chassis", "Reinforced Chassis",
        "+1.5% tower damage for every other tower within 100 pixels of it, capped at +15%, every floor.",
        tower_density_radius=100, tower_density_damage_bonus_per_neighbor=0.015,
        tower_density_damage_bonus_cap=0.15,
    ),
    # A second support_aura_strength_multiplier relic -- resonant_field
    # already covers both range and strength together; this one is
    # strength-only, so a Support-focused run doesn't need to draft the
    # exact same card twice to feel its aura compound. Ungated straight
    # multiply, same as resonant_field's own two fields.
    "overdrive_array": Relic(
        "overdrive_array", "Overdrive Array",
        "Support tower auras buff 20% more, every floor.",
        support_aura_strength_multiplier=1.20,
    ),
    # A third crit relic -- own chance and multiplier, tuned lower than
    # lucky_strikes/focused_fire on both (so it doesn't dominate when
    # combined) but fully standalone-functional on its own, same "own
    # numbers, no dependency on another relic" shape reinforced_chassis
    # sets for density above.
    "precision_engineering": Relic(
        "precision_engineering", "Precision Engineering",
        "+8% crit chance for every tower, every floor.",
        crit_chance=0.08, crit_damage_multiplier=1.3,
    ),
    # Lightning-tower-exclusive damage multiplier -- see
    # lightning_damage_multiplier's own comment on the Relic dataclass
    # above for the read site (LightningTower._relic_family_damage_bonus()).
    "storm_core": Relic(
        "storm_core", "Storm Core",
        "Lightning tower deals 20% more damage, every floor.",
        lightning_damage_multiplier=1.20,
    ),
    # Cannon/Knockback-exclusive damage multiplier -- see
    # cannon_knockback_damage_multiplier's own comment on the Relic dataclass
    # above for the read sites (Cannon/KnockbackTower's own identical
    # _relic_family_damage_bonus() overrides).
    "heavy_ordnance": Relic(
        "heavy_ordnance", "Heavy Ordnance",
        "Cannon and Knockback towers deal 20% more damage, every floor.",
        cannon_knockback_damage_multiplier=1.20,
    ),
    # Beacon-tower-exclusive -- see beacon_splash_radius_multiplier's own
    # comment on the Relic dataclass above for the read site
    # (BeaconTower.create_projectile()).
    "luminous_field": Relic(
        "luminous_field", "Luminous Field",
        "Beacon tower marks a 25% larger area, every floor.",
        beacon_splash_radius_multiplier=1.25,
    ),
    # Beacon-tower-exclusive -- see beacon_mark_multiplier's own comment on
    # the Relic dataclass above for the read site
    # (BeaconTower.create_projectile()).
    "signal_amplifier": Relic(
        "signal_amplifier", "Signal Amplifier",
        "Beacon tower's mark deals 25% more bonus damage, every floor.",
        beacon_mark_multiplier=1.25,
    ),
    # Beam-tower-exclusive -- see beam_ramp_multiplier's own comment on
    # the Relic dataclass above for the read site
    # (BeamTower.create_projectile()).
    "focused_optics": Relic(
        "focused_optics", "Focused Optics",
        "Beam tower ramps 25% faster per hit, every floor.",
        beam_ramp_multiplier=1.25,
    ),
    # Beam-tower-exclusive -- see beam_max_ramp_bonus's own comment on the
    # Relic dataclass above for the read site
    # (BeamTower.create_projectile()).
    "sustained_barrage": Relic(
        "sustained_barrage", "Sustained Barrage",
        "Beam tower's max ramp is 0.3x higher, every floor.",
        beam_max_ramp_bonus=0.3,
    ),
    # See poison_spread_radius's own comment on the Relic dataclass above
    # for the read site (Game.update()'s dead-enemy drain loop).
    "virulent_bloom": Relic(
        "virulent_bloom", "Virulent Bloom",
        "When a poisoned enemy dies, its poison spreads to enemies within 60 pixels.",
        poison_spread_radius=60,
    ),
    # Sniper-tower-exclusive -- see execute_damage_multiplier's own
    # comment on the Relic dataclass above for the read site
    # (SniperTower.create_projectile()).
    "kill_shot": Relic(
        "kill_shot", "Kill Shot",
        "Sniper tower's execute deals 25% more bonus damage, every floor.",
        execute_damage_multiplier=1.25,
    ),
    # Sniper-tower-exclusive -- see execute_threshold_multiplier's own
    # comment on the Relic dataclass above for the read site
    # (SniperTower.create_projectile()).
    "wounded_prey": Relic(
        "wounded_prey", "Wounded Prey",
        "Sniper tower's execute triggers against tougher targets, every floor.",
        execute_threshold_multiplier=1.25,
    ),
}

DEFAULT_RELIC_OFFER_COUNT = 3


def _default_relic_pool(meta_progression_path):
    """Every RELICS key not gated by meta_progression.RELIC_META_UNLOCKS,
    plus whatever that registry says this player has unlocked account-wide
    so far, in RELICS' own stable registry order -- same "stable order
    feeds rng.sample" reasoning card_pool._default_unlocked_pool documents
    for towers."""
    gated = {unlock.relic_key for unlock in meta_progression.RELIC_META_UNLOCKS.values()}
    unlocked_gated = meta_progression.unlocked_relic_pool(meta_progression_path)
    return [key for key in RELICS if key not in gated or key in unlocked_gated]


def relic_offer(rng, run, count=DEFAULT_RELIC_OFFER_COUNT, unlocked_pool=None, meta_progression_path=None):
    """`count` relic keys offered as a relic draft's choices, drawn from
    `unlocked_pool` (default: _default_relic_pool() above, reading
    `meta_progression_path` -- same injectable-path convention every
    on-disk-state module in this codebase uses) minus whatever `run.relics`
    already has -- same shape as card_pool.draft_offer, just for the other
    card type. Returns fewer than `count` once the pool is exhausted
    rather than raising (see rng_sampling.sample_up_to)."""
    if unlocked_pool is None:
        unlocked_pool = _default_relic_pool(meta_progression_path or meta_progression.META_PROGRESSION_PATH)
    candidates = [key for key in unlocked_pool if key not in run.relics]
    return sample_up_to(rng, candidates, count)


@dataclass(frozen=True)
class RelicModifiers:
    """Aggregated per-floor modifiers -- everything a Relic can contribute
    that genuinely recurs, every floor, for as long as it's held:

    - starting_gold_multiplier: folded into Game._load_level_object's own
      Economy construction (the same _scaled_starting_gold() call every
      floor already uses), since battle gold is freshly constructed from
      scratch every floor now -- see CLAUDE.md's "Two currencies" section.
    - gold_per_floor_bonus: Game._load_floor adds it to self.economy.gold
      on every floor load, explicitly, on top of whatever starting_gold_
      multiplier above already produced -- a flat bonus and a multiplier
      on the same currency, kept as two separate fields/relics rather than
      merged, the same way tower_damage_multiplier and tower_range_
      multiplier stay separate fields below despite both being tower
      multipliers.
    - enemy_gold_multiplier/enemy_speed_multiplier: threaded into
      WaveManager's own constructor kwargs in _load_level_object, and
      WaveManager itself is always rebuilt fresh every floor, so these
      need no special per-floor handling to keep applying.
    - tower_range_multiplier/tower_fire_rate_multiplier/tower_damage_multiplier/
      poison_chance/poison_effect/crit_chance/crit_damage_multiplier/
      chain_chance/chain_effect/tower_footprint_shrink: read once per tower, at construction time
      (Game._construct_tower/_current_footprint_subtiles), rather than
      through WaveManager/Economy -- see Tower.effective_range()/
      effective_fire_rate()/effective_damage() and Projectile.
      _apply_hit_effects() for where the tower-facing ones actually apply,
      and _current_footprint_subtiles() for the footprint one.
      tower_damage_multiplier is itself composed from two different Relic
      fields (see compose_relic_modifiers) -- a flat per-relic multiplier
      and an escalating-per-floor one, since a run-long stacking bonus
      like veterans_momentum has nowhere else to live but this same field.

    A Relic's own starting_lives_bonus (a genuinely one-time bonus, not a
    per-floor one -- see RELICS' own comment on sturdy_gate) is
    deliberately NOT one of these fields: this type only ever gets composed
    once, from whatever relics a run holds *at floor-load time*, and reused
    across every floor of that load -- but a one-time bonus has to fire
    exactly once, the instant the card is drafted (Game._apply_one_time_
    relic_bonus), never re-applied on a later floor's own load. Folding it
    in here would either double-apply it on every subsequent floor or
    require this type to start tracking which relics it's already "spent,"
    neither of which this simple aggregate-and-reuse shape is built for.
    starting_gold_multiplier isn't in this category despite the name it
    shares with starting_lives_bonus -- see this field's own comment above
    for why it's a normal per-floor field instead.

    Three more fields don't fit the "recurs every floor, for as long as
    it's held" framing above either, and are resolved elsewhere entirely:
    misers_coffer's gold_per_floor_bonus_while_unspent folds into
    gold_per_floor_bonus above, but only conditionally (see compose_relic_
    modifiers' has_spent_gold parameter and Game._spend_gold) --
    once revoked, it stays revoked for the rest of the run, unlike every
    other field here which stays constant for as long as the relic is
    held. guardians_reprieve has no field here at all (see RELICS' own
    comment on it) -- checked directly against run.relics in
    Game._lose_a_life instead. splitter_child_damage (containment_charges'
    own bonus) does have a field here, unlike guardians_reprieve, but
    -- unlike every tower-facing field above -- is read straight off this
    class by Game.update()'s own dead-enemy drain loop rather than
    threaded through Tower/Projectile: it's a flat per-floor value with no
    per-tower or per-shot variation to justify that plumbing. shop_price_
    multiplier (haggling_permit's own bonus) is a fourth outlier of this
    same kind -- read straight off this class by shop.price_for()'s own
    discount_multiplier parameter, since the Shop's own prices aren't a
    per-tower or per-shot concern either."""
    starting_gold_multiplier: float = 1.0
    gold_per_floor_bonus: int = 0
    enemy_gold_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    tower_range_multiplier: float = 1.0
    tower_fire_rate_multiplier: float = 1.0
    poison_chance: float = 0.0
    poison_effect: tuple = None
    crit_chance: float = 0.0
    crit_damage_multiplier: float = 1.0
    tower_footprint_shrink: int = 0
    tower_damage_multiplier: float = 1.0
    chain_chance: float = 0.0
    chain_effect: tuple = None
    last_stand_damage_multiplier: float = 1.0
    tower_upgrade_cost_multiplier: float = 1.0
    sell_refund_bonus: float = 0.0
    support_aura_range_multiplier: float = 1.0
    support_aura_strength_multiplier: float = 1.0
    damage_vs_slowed_multiplier: float = 1.0
    slow_chance: float = 0.0
    slow_effect: tuple = None
    poison_ignores_shield: bool = False
    tower_density_radius: float = 0.0
    tower_density_damage_bonus_per_neighbor: float = 0.0
    tower_density_damage_bonus_cap: float = 0.0
    last_stand_fire_rate_multiplier: float = 1.0
    damage_vs_early_route_multiplier: float = 1.0
    damage_vs_high_hp_multiplier: float = 1.0
    overkill_carry_fraction: float = 0.0
    knockback_chance: float = 0.0
    knockback_effect: float = None
    mark_chance: float = 0.0
    mark_effect: tuple = None
    damage_vs_flying_multiplier: float = 1.0
    damage_vs_shielded_multiplier: float = 1.0
    splitter_child_damage: float = 0.0
    damage_vs_healer_multiplier: float = 1.0
    damage_vs_fast_multiplier: float = 1.0
    tower_splash_radius_multiplier: float = 1.0
    lightning_chain_range_multiplier: float = 1.0
    shop_price_multiplier: float = 1.0
    lightning_damage_multiplier: float = 1.0
    cannon_knockback_damage_multiplier: float = 1.0
    beacon_splash_radius_multiplier: float = 1.0
    beacon_mark_multiplier: float = 1.0
    beam_ramp_multiplier: float = 1.0
    beam_max_ramp_bonus: float = 0.0
    poison_spread_radius: float = 0.0
    execute_damage_multiplier: float = 1.0
    execute_threshold_multiplier: float = 1.0


def compose_relic_modifiers(relic_keys, floor_index=0, has_spent_gold=False):
    """Aggregate every relic in `relic_keys` into one RelicModifiers bundle
    -- flat bonuses add, multipliers multiply, so composing several relics
    is order-independent regardless of which was drafted first.

    `floor_index` and `has_spent_gold` both default so every pre-existing
    call site (and every existing test) is unaffected -- they only matter
    to veterans_momentum's escalating bonus and misers_coffer's
    conditionally-revoked one, respectively; see relics.py's own module
    docstring for both.

    poison_effect and crit_damage_multiplier are two of several fields that
    aren't a plain sum/multiply (chain_effect/slow_effect/mark_effect/
    knockback_effect are each a chance-gated tuple-or-max() too, following
    the same shape poison_effect sets below), and both are gated on the
    relic actually granting the chance that uses them (poison_chance > 0 /
    crit_chance > 0 respectively) -- a relic with a nonzero damage/multiplier field but
    zero chance of its own contributes nothing, the same way a relic with
    zero of everything already contributes nothing. crit_damage_multiplier
    takes the max() across relics rather than multiplying -- two crit
    relics compounding multiplicatively would spike far faster than two
    flat +chance relics summing, the same conservative choice poison's own
    tick damage below already makes. poison_effect's aggregation is the
    more involved one: each poison-granting relic contributes its own
    (damage_per_tick, tick_interval, duration), folded together the exact
    same way Enemy.apply_poison() itself already combines two *hits* of
    poison on the same enemy -- keep the harsher tick damage and the
    longer duration (max(), so composing two poison relics is
    order-independent on those two), last-write on tick interval (the one
    genuinely order-dependent piece of this whole function -- dormant
    today since only one poison-granting relic exists, so no two-relic
    ordering can yet actually differ)."""
    starting_gold_multiplier = 1.0
    gold_per_floor_bonus = 0
    enemy_gold_multiplier = 1.0
    enemy_speed_multiplier = 1.0
    tower_range_multiplier = 1.0
    tower_fire_rate_multiplier = 1.0
    poison_chance = 0.0
    poison_effect = None
    crit_chance = 0.0
    crit_damage_multiplier = 1.0
    tower_footprint_shrink = 0
    tower_damage_multiplier = 1.0
    chain_chance = 0.0
    chain_effect = None
    last_stand_damage_multiplier = 1.0
    tower_upgrade_cost_multiplier = 1.0
    sell_refund_bonus = 0.0
    support_aura_range_multiplier = 1.0
    support_aura_strength_multiplier = 1.0
    damage_vs_slowed_multiplier = 1.0
    slow_chance = 0.0
    slow_effect = None
    poison_ignores_shield = False
    tower_density_radius = 0.0
    tower_density_damage_bonus_per_neighbor = 0.0
    tower_density_damage_bonus_cap = 0.0
    last_stand_fire_rate_multiplier = 1.0
    damage_vs_early_route_multiplier = 1.0
    damage_vs_high_hp_multiplier = 1.0
    overkill_carry_fraction = 0.0
    knockback_chance = 0.0
    knockback_effect = None
    mark_chance = 0.0
    mark_effect = None
    damage_vs_flying_multiplier = 1.0
    damage_vs_shielded_multiplier = 1.0
    splitter_child_damage = 0.0
    damage_vs_healer_multiplier = 1.0
    damage_vs_fast_multiplier = 1.0
    tower_splash_radius_multiplier = 1.0
    lightning_chain_range_multiplier = 1.0
    shop_price_multiplier = 1.0
    lightning_damage_multiplier = 1.0
    cannon_knockback_damage_multiplier = 1.0
    beacon_splash_radius_multiplier = 1.0
    beacon_mark_multiplier = 1.0
    beam_ramp_multiplier = 1.0
    beam_max_ramp_bonus = 0.0
    poison_spread_radius = 0.0
    execute_damage_multiplier = 1.0
    execute_threshold_multiplier = 1.0
    for key in relic_keys:
        relic = RELICS[key]
        starting_gold_multiplier *= relic.starting_gold_multiplier
        gold_per_floor_bonus += relic.gold_per_floor_bonus
        if not has_spent_gold:
            gold_per_floor_bonus += relic.gold_per_floor_bonus_while_unspent
        last_stand_damage_multiplier = max(last_stand_damage_multiplier, relic.last_stand_damage_multiplier)
        tower_upgrade_cost_multiplier *= relic.tower_upgrade_cost_multiplier
        sell_refund_bonus += relic.sell_refund_bonus
        support_aura_range_multiplier *= relic.support_aura_range_multiplier
        support_aura_strength_multiplier *= relic.support_aura_strength_multiplier
        enemy_gold_multiplier *= relic.enemy_gold_multiplier
        enemy_speed_multiplier *= relic.enemy_speed_multiplier
        tower_range_multiplier *= relic.tower_range_multiplier
        tower_fire_rate_multiplier *= relic.tower_fire_rate_multiplier
        tower_footprint_shrink += relic.tower_footprint_shrink
        # Neutral defaults (1.0 / 0.0) make both lines a no-op for a relic
        # that doesn't grant either -- no gating needed, unlike the
        # chance-gated fields below.
        tower_damage_multiplier *= relic.tower_damage_multiplier
        tower_damage_multiplier *= 1.0 + relic.tower_damage_growth_per_floor * floor_index
        if relic.crit_chance > 0:
            crit_chance += relic.crit_chance
            crit_damage_multiplier = max(crit_damage_multiplier, relic.crit_damage_multiplier)
        if relic.poison_chance > 0:
            poison_chance += relic.poison_chance
            if poison_effect is None:
                poison_effect = (relic.poison_damage_per_tick, relic.poison_tick_interval, relic.poison_duration)
            else:
                poison_effect = (
                    max(poison_effect[0], relic.poison_damage_per_tick),
                    relic.poison_tick_interval,
                    max(poison_effect[2], relic.poison_duration),
                )
        if relic.chain_chance > 0:
            chain_chance += relic.chain_chance
            if chain_effect is None:
                chain_effect = (relic.chain_damage_fraction, relic.chain_range)
            else:
                chain_effect = (
                    max(chain_effect[0], relic.chain_damage_fraction),
                    max(chain_effect[1], relic.chain_range),
                )
        # Ungated, straight multiplies -- same neutral-default-means-no-op
        # shape as tower_damage_multiplier above.
        damage_vs_slowed_multiplier *= relic.damage_vs_slowed_multiplier
        damage_vs_early_route_multiplier *= relic.damage_vs_early_route_multiplier
        damage_vs_high_hp_multiplier *= relic.damage_vs_high_hp_multiplier
        poison_ignores_shield = poison_ignores_shield or relic.poison_ignores_shield
        tower_density_radius = max(tower_density_radius, relic.tower_density_radius)
        tower_density_damage_bonus_per_neighbor += relic.tower_density_damage_bonus_per_neighbor
        tower_density_damage_bonus_cap += relic.tower_density_damage_bonus_cap
        last_stand_fire_rate_multiplier = max(last_stand_fire_rate_multiplier, relic.last_stand_fire_rate_multiplier)
        overkill_carry_fraction += relic.overkill_carry_fraction
        if relic.slow_chance > 0:
            slow_chance += relic.slow_chance
            if slow_effect is None:
                slow_effect = (relic.slow_factor, relic.slow_duration)
            else:
                # min() on the factor, not max() -- slow_factor is the one
                # stat in this codebase where *smaller* is the stronger
                # effect (see FrostTower's own note), so "keep the harsher
                # slow" means taking the minimum here, unlike every other
                # tuple-merge in this function.
                slow_effect = (
                    min(slow_effect[0], relic.slow_factor),
                    max(slow_effect[1], relic.slow_duration),
                )
        if relic.knockback_chance > 0:
            knockback_chance += relic.knockback_chance
            if knockback_effect is None:
                knockback_effect = relic.knockback_duration
            else:
                knockback_effect = max(knockback_effect, relic.knockback_duration)
        if relic.mark_chance > 0:
            mark_chance += relic.mark_chance
            if mark_effect is None:
                mark_effect = (relic.mark_multiplier, relic.mark_duration)
            else:
                mark_effect = (
                    max(mark_effect[0], relic.mark_multiplier),
                    max(mark_effect[1], relic.mark_duration),
                )
        damage_vs_flying_multiplier *= relic.damage_vs_flying_multiplier
        damage_vs_shielded_multiplier *= relic.damage_vs_shielded_multiplier
        damage_vs_healer_multiplier *= relic.damage_vs_healer_multiplier
        splitter_child_damage += relic.splitter_child_damage
        damage_vs_fast_multiplier *= relic.damage_vs_fast_multiplier
        tower_splash_radius_multiplier *= relic.tower_splash_radius_multiplier
        lightning_chain_range_multiplier *= relic.lightning_chain_range_multiplier
        shop_price_multiplier *= relic.shop_price_multiplier
        lightning_damage_multiplier *= relic.lightning_damage_multiplier
        cannon_knockback_damage_multiplier *= relic.cannon_knockback_damage_multiplier
        beacon_splash_radius_multiplier *= relic.beacon_splash_radius_multiplier
        beacon_mark_multiplier *= relic.beacon_mark_multiplier
        beam_ramp_multiplier *= relic.beam_ramp_multiplier
        beam_max_ramp_bonus += relic.beam_max_ramp_bonus
        poison_spread_radius = max(poison_spread_radius, relic.poison_spread_radius)
        execute_damage_multiplier *= relic.execute_damage_multiplier
        execute_threshold_multiplier *= relic.execute_threshold_multiplier
    return RelicModifiers(
        starting_gold_multiplier=starting_gold_multiplier,
        gold_per_floor_bonus=gold_per_floor_bonus,
        enemy_gold_multiplier=enemy_gold_multiplier,
        enemy_speed_multiplier=enemy_speed_multiplier,
        tower_range_multiplier=tower_range_multiplier,
        tower_fire_rate_multiplier=tower_fire_rate_multiplier,
        poison_chance=poison_chance,
        poison_effect=poison_effect,
        crit_chance=crit_chance,
        crit_damage_multiplier=crit_damage_multiplier,
        tower_footprint_shrink=tower_footprint_shrink,
        tower_damage_multiplier=tower_damage_multiplier,
        chain_chance=chain_chance,
        chain_effect=chain_effect,
        last_stand_damage_multiplier=last_stand_damage_multiplier,
        tower_upgrade_cost_multiplier=tower_upgrade_cost_multiplier,
        sell_refund_bonus=sell_refund_bonus,
        support_aura_range_multiplier=support_aura_range_multiplier,
        support_aura_strength_multiplier=support_aura_strength_multiplier,
        damage_vs_slowed_multiplier=damage_vs_slowed_multiplier,
        slow_chance=slow_chance,
        slow_effect=slow_effect,
        poison_ignores_shield=poison_ignores_shield,
        tower_density_radius=tower_density_radius,
        tower_density_damage_bonus_per_neighbor=tower_density_damage_bonus_per_neighbor,
        tower_density_damage_bonus_cap=tower_density_damage_bonus_cap,
        last_stand_fire_rate_multiplier=last_stand_fire_rate_multiplier,
        damage_vs_early_route_multiplier=damage_vs_early_route_multiplier,
        damage_vs_high_hp_multiplier=damage_vs_high_hp_multiplier,
        overkill_carry_fraction=overkill_carry_fraction,
        knockback_chance=knockback_chance,
        knockback_effect=knockback_effect,
        mark_chance=mark_chance,
        mark_effect=mark_effect,
        damage_vs_flying_multiplier=damage_vs_flying_multiplier,
        damage_vs_shielded_multiplier=damage_vs_shielded_multiplier,
        splitter_child_damage=splitter_child_damage,
        damage_vs_healer_multiplier=damage_vs_healer_multiplier,
        damage_vs_fast_multiplier=damage_vs_fast_multiplier,
        tower_splash_radius_multiplier=tower_splash_radius_multiplier,
        lightning_chain_range_multiplier=lightning_chain_range_multiplier,
        shop_price_multiplier=shop_price_multiplier,
        lightning_damage_multiplier=lightning_damage_multiplier,
        cannon_knockback_damage_multiplier=cannon_knockback_damage_multiplier,
        beacon_splash_radius_multiplier=beacon_splash_radius_multiplier,
        beacon_mark_multiplier=beacon_mark_multiplier,
        beam_ramp_multiplier=beam_ramp_multiplier,
        beam_max_ramp_bonus=beam_max_ramp_bonus,
        poison_spread_radius=poison_spread_radius,
        execute_damage_multiplier=execute_damage_multiplier,
        execute_threshold_multiplier=execute_threshold_multiplier,
    )
