"""Tower base class, concrete tower types, and the TOWER_TYPES registry.

Tower defines all shared behavior (targeting, cooldown/fire loop, range
check, drawing) as a template method; each concrete tower only sets
class-attribute stats and implements create_projectile(). Adding a new
tower type is: write a subclass, add one line to TOWER_TYPES. No other file
needs to change -- ui.py's build menu and game.py's placement logic both
iterate/index the registry rather than naming concrete classes.
"""

import pygame

from entities.projectile import Projectile
from support import settings


def _format_px(value):
    return f"{value:.0f}px"


def _format_seconds(value):
    return f"{value:.2f}s"


def _format_slow_percent(value):
    return f"{round((1 - value) * 100)}% slower"


def _format_count(value):
    return "Unlimited" if value == float("inf") else f"{int(value)}"


def _format_poison_tick(value):
    return f"{value:.0f} dmg/tick"


def _format_buff_percent(value):
    return f"+{round((value - 1) * 100)}%"


def _format_chance_percent(value):
    return f"{round(value * 100)}%"


def _format_ramp_per_hit(value):
    return f"+{round(value * 100)}%/hit"


class Tower:
    cost = 0
    range = 0
    damage = 0
    fire_rate = 1.0  # shots per second
    projectile_speed = 300.0
    sprite_name = ""
    display_name = "Tower"

    # Logical audio.SOUND_MANIFEST name played once per successful shot
    # (see fired_this_frame below) -- same single-string-per-class shape as
    # sprite_name, not a registry like EXTRA_STATS/SPECIALIZATIONS, since a
    # tower only ever has one fire cue. None means silent; SupportTower
    # sets that (defense in depth -- it never reaches the fire loop that
    # would set fired_this_frame at all, since it has its own update()).
    FIRE_SOUND = "tower_fire_default"

    # True only for SupportTower -- a tower that never attacks at all, just
    # buffs other towers in range (see SupportTower.update()). Gates the
    # stats panel's hard-coded Damage/Range/Fire-rate and Targeting rows
    # (ui.py's _draw_panel_stats/draw_tower_stats_panel), which would
    # otherwise show a meaningless "Damage: 0.0" and a clickable targeting
    # mode a support tower never reads.
    IS_SUPPORT = False

    # Whether this tower can hit an enemy with is_flying = True (see
    # enemy.py) -- default True. A tower whose mechanic is a ground-impact
    # blast (CannonTower's splash, KnockbackTower's shove) overrides this
    # False, since neither makes sense against something airborne.
    can_target_flying = True

    # Fraction of damage dealt that converts into battle gold -- 0.0 (no
    # conversion) on every tower except SiphonTower, which overrides this
    # with its own nonzero class attribute (siphon_gold_fraction = 0.6),
    # the same "a tower's own native stat, defaulted to a no-op on the base
    # class" shape poison_damage_per_tick/execute_hp_threshold/etc. already
    # use elsewhere in this file. Deliberately a plain CLASS attribute, not
    # an instance attribute set in __init__ below -- Projectile._apply_
    # direct_damage() reads self.source.siphon_gold_fraction on every hit
    # regardless of tower type (see that method's own comment), so this
    # needs a real, always-present value on every Tower subclass the way
    # can_target_flying/IS_SUPPORT above already are; assigning it via
    # `self.siphon_gold_fraction = 0.0` in __init__ instead would shadow
    # SiphonTower's own class-level override with an instance attribute of
    # 0.0 on every SiphonTower object, silently disabling the mechanic.
    siphon_gold_fraction = 0.0

    # Which in-range enemy acquire_target() actually fires at -- a one-time
    # choice at placement (see __init__), cycled per-tower via
    # cycle_targeting_mode() (the stats panel's "Targeting: ..." row). "first"
    # reproduces this class's original, only-ever behavior (furthest along
    # the path) exactly -- see _target_first.
    TARGETING_MODES = ("first", "last", "strongest", "closest", "weakest")

    MAX_LEVEL = 3
    # Default multiplier applied to a LEVEL_SCALED_STATS entry at a given
    # level -- level 1 is always 1.0x (no bonus, the placed/base stats).
    LEVEL_STAT_MULTIPLIERS = {1: 1.0, 2: 1.35, 3: 1.8}
    # Per-stat overrides of the above, e.g. {"damage": {1: 1.0, 2: 1.7,
    # 3: 2.6}} -- a stat not listed here just uses LEVEL_STAT_MULTIPLIERS
    # like normal. Lets one stat scale on its own curve (a tower that
    # should hit dramatically harder at max level without also reaching
    # dramatically further, say) without a whole separate mechanism.
    LEVEL_STAT_MULTIPLIER_OVERRIDES = {}
    # Which of a tower's own attributes get a level multiplier at all on
    # level-up. A subclass can extend this tuple (e.g. + ("slow_duration",))
    # to have more of its own stats scale too -- everything else about
    # levelling stays generic.
    LEVEL_SCALED_STATS = ("damage", "range")
    # Gold cost to reach level 2 / level 3, as a multiplier of this
    # tower's base `cost`.
    UPGRADE_COST_MULTIPLIERS = {2: 0.6, 3: 1.0}
    # Extra, tower-specific stats shown in the stats panel (ui.py), as
    # (label, attribute_name, format_function) tuples. Empty by default;
    # a subclass with a special mechanic (splash, slow, knockback, ...)
    # lists it here and the panel picks it up automatically.
    EXTRA_STATS = ()

    # Once a tower reaches MAX_LEVEL, it can choose one of two named
    # specializations instead of continuing to level up -- a one-time
    # branching choice, not another step of the generic LEVEL_SCALED_STATS
    # curve. Keyed by an arbitrary string id; "stat_multipliers" is
    # applied the same way a level-up's multiplier is (current value *=
    # multiplier). This base-class pair is only ever seen directly by a
    # tower with no distinctive mechanic of its own to name a
    # specialization after -- every concrete TOWER_TYPES entry now
    # overrides SPECIALIZATIONS with its own tower-specific pair (see e.g.
    # LightningTower/SupportTower/CannonTower), even BasicTower/SniperTower,
    # whose options still land on generic damage/range/fire_rate stats but
    # get their own names and tuning rather than inheriting this verbatim.
    SPECIALIZATIONS = {
        "power": {
            "display_name": "Power",
            "description": "Bigger numbers.",
            "stat_multipliers": {"damage": 1.3},
        },
        "precision": {
            "display_name": "Precision",
            "description": "+Range and fire rate.",
            "stat_multipliers": {"range": 1.2, "fire_rate": 1.2},
        },
    }
    # Gold cost to specialize, as a multiplier of this tower's base `cost`
    # -- same idea as UPGRADE_COST_MULTIPLIERS.
    SPECIALIZATION_COST_MULTIPLIER = 1.5

    def __init__(self, anchor_col, anchor_row, pixel_pos):
        self.anchor_col = anchor_col
        self.anchor_row = anchor_row
        self.pos = pygame.Vector2(pixel_pos)
        self.cooldown = 0.0
        self.level = 1
        # Snapshot each scaled stat's level-1 value once, up front, so
        # every upgrade recomputes from the true base rather than
        # compounding on an already-scaled number.
        self._base_stats = {name: getattr(self, name) for name in self.LEVEL_SCALED_STATS}
        # Total gold spent placing and upgrading this tower -- what a sale
        # refunds a fraction of, so upgrading then selling isn't a loss on
        # top of the upgrade itself. See sell_value().
        self.total_invested = self.cost
        # SPECIALIZATIONS key once chosen (see specialize()), else None.
        self.specialization = None
        # Which TARGETING_MODES strategy acquire_target() uses -- "first"
        # (furthest along the path) is this class's original, only-ever
        # default; see cycle_targeting_mode().
        self.targeting_mode = "first"

        # Lifetime stats, purely for the post-level results screen (see
        # ui.compute_tower_results) -- never read by any gameplay logic.
        # shots_fired counts every successful acquire-and-fire cycle in
        # update() (including one whose projectile turns out to be a dud,
        # e.g. its target died first -- see Projectile.update), which is
        # what makes shots_hit / shots_fired a meaningful accuracy stat.
        self.shots_fired = 0
        self.shots_hit = 0
        self.damage_dealt = 0.0
        self.kills = 0

        # A same-frame flag in the spirit of Enemy.damage_events/
        # Projectile.impact_events's own drain-a-per-frame-event-list idiom
        # (see CLAUDE.md's "Visual effects" section) -- set once per
        # successful fire in update() below, read (and reset) into an
        # audio.SoundManager.play(FIRE_SOUND) call by Game.update()'s
        # existing two-pass tower loop. A plain bool, not a list, since one
        # update() call can structurally fire at most once -- there's
        # nothing here to accumulate several same-frame events the way a
        # splash/chain hit's several impact_events entries can.
        self.fired_this_frame = False

        # Recomputed every frame by reset_aura()/receive_aura() (see
        # Game.update()'s two-pass tower loop) -- 1.0 means "no support
        # tower currently in range." Never mutates self.damage/self.range
        # directly: create_projectile()/in_range() read through these
        # multipliers instead, so a buff can never compound across
        # multiple SupportTowers in range or drift permanently once one
        # leaves range (both would happen if a SupportTower multiplied
        # self.damage/self.range in place instead).
        self.aura_damage_multiplier = 1.0
        self.aura_range_multiplier = 1.0

        # Relic-driven bonuses, resolved once at construction time from
        # whatever relics the active run holds (see Game._construct_tower)
        # -- neutral defaults here so a relic-less run's towers, and every
        # existing direct-construction test/call site, behave exactly as
        # before. Unlike aura_damage_multiplier/aura_range_multiplier
        # above, these never reset -- a relic's effect is constant for the
        # tower's whole lifetime, not a per-frame proximity buff.
        self.relic_range_bonus_multiplier = 1.0
        self.relic_fire_rate_bonus_multiplier = 1.0
        self.relic_poison_chance = 0.0
        self.relic_poison_effect = None
        self.relic_crit_chance = 0.0
        self.relic_crit_damage_multiplier = 1.0
        self.relic_damage_bonus_multiplier = 1.0
        self.relic_chain_chance = 0.0
        self.relic_chain_effect = None
        self.relic_upgrade_cost_multiplier = 1.0
        self.relic_sell_refund_bonus = 0.0
        self.relic_aura_range_bonus_multiplier = 1.0
        self.relic_aura_strength_bonus_multiplier = 1.0
        # Shockwave Rounds-style relic -- same construction-time shape as
        # relic_range_bonus_multiplier above, consumed only by whichever
        # concrete tower actually has a splash_radius attribute (Cannon,
        # Knockback) in its own create_projectile(); harmless on every
        # other tower, which never reads it.
        self.relic_splash_radius_bonus_multiplier = 1.0
        # Arc Conductor-style relic -- Lightning-tower-exclusive, mirroring
        # relic_aura_range_bonus_multiplier's own shape: set on every
        # tower harmlessly, but only ever read inside LightningTower's own
        # create_projectile().
        self.relic_lightning_chain_range_bonus_multiplier = 1.0
        # Storm Core-style relic -- Lightning-tower-exclusive damage bonus,
        # set on every tower harmlessly like relic_lightning_chain_range_
        # bonus_multiplier immediately above, but read via LightningTower's
        # own _relic_family_damage_bonus() override (see Tower.effective_
        # damage()) rather than a plain create_projectile() multiply --
        # damage bonuses have to fold into that method's own additive
        # stack, unlike chain_range/splash_radius, which aren't part of it.
        self.relic_lightning_damage_bonus_multiplier = 1.0
        # Heavy Ordnance-style relic -- Cannon/Knockback-exclusive damage
        # bonus, same shape as relic_lightning_damage_bonus_multiplier
        # immediately above (a family_damage_bonus() hook, not a plain
        # multiply), just for the Cannon/Knockback pair instead of
        # Lightning alone.
        self.relic_cannon_knockback_damage_bonus_multiplier = 1.0
        # Aerial Targeting Array-style relic -- Cannon's first fully
        # exclusive relic (heavy_ordnance immediately above is shared
        # 50/50 with Knockback), boolean OR-composed the same shape as
        # relic_poison_ignores_shield below. Set on every tower harmlessly
        # at construction time, but only ever read via CannonTower's own
        # can_target_flying property override (see that class) -- every
        # other tower still reads the plain can_target_flying class
        # attribute untouched, so this can never leak onto Knockback or
        # anything else.
        self.relic_cannon_targets_flying = False
        # High-Velocity Shells-style relic -- Cannon's second exclusive
        # relic, same plain construction-time multiply shape as relic_
        # splash_radius_bonus_multiplier above, read only inside
        # CannonTower's own create_projectile() against projectile_speed.
        self.relic_cannon_projectile_speed_bonus_multiplier = 1.0
        # Luminous Field-style relic -- Beacon-tower-exclusive, plain
        # construction-time multiply shape (like relic_splash_radius_
        # bonus_multiplier), read only inside BeaconTower's own
        # create_projectile() against mark_splash_radius. Not a damage
        # bonus, so it has no business in the family_damage_bonus() hook.
        self.relic_beacon_splash_radius_bonus_multiplier = 1.0
        # Signal Amplifier-style relic -- Beacon-tower-exclusive, same
        # plain-multiply shape as relic_beacon_splash_radius_bonus_
        # multiplier immediately above, scaling mark_damage_multiplier
        # instead -- also not this tower's own shot damage (see
        # beacon_mark_multiplier's own comment in relics.py), so this too
        # skips the family_damage_bonus() hook.
        self.relic_beacon_mark_bonus_multiplier = 1.0
        # Focused Optics-style relic -- Beam-tower-exclusive, same plain-
        # multiply shape as the Beacon-exclusive pair above, read only
        # inside BeamTower's own create_projectile() against ramp_per_hit.
        self.relic_beam_ramp_bonus_multiplier = 1.0
        # Sustained Barrage-style relic -- Beam-tower-exclusive, same
        # plain-read shape as relic_beam_ramp_bonus_multiplier immediately
        # above, but ADDITIVE onto max_ramp_multiplier (see beam_max_ramp_
        # bonus's own comment in relics.py for why).
        self.relic_beam_max_ramp_bonus = 0.0
        # Adrenaline Rounds-style relic -- Basic-tower-exclusive, same
        # plain-multiply shape as relic_beacon_mark_bonus_multiplier above:
        # crit_damage_multiplier is a per-shot chance-roll outcome (see
        # Projectile's own crit resolution), not part of effective_
        # damage()'s additive stack, so this skips the family_damage_
        # bonus() hook the same way every plain-multiply relic here does.
        self.relic_basic_crit_damage_bonus_multiplier = 1.0
        # Twitch Reflex-style relic -- Basic-tower-exclusive, same
        # plain-multiply shape as relic_basic_crit_damage_bonus_multiplier
        # immediately above, scaling crit_chance instead.
        self.relic_basic_crit_chance_bonus_multiplier = 1.0
        # Kill Shot-style relic -- Sniper-tower-exclusive, same plain-
        # multiply shape as relic_beacon_mark_bonus_multiplier above:
        # execute_damage_multiplier is a conditional per-hit bonus applied
        # inside Projectile (see execute_hp_threshold's own check), not
        # part of effective_damage()'s additive stack, so this skips the
        # family_damage_bonus() hook the same way every plain-multiply
        # relic here does. No existing relic references Execute at all, so
        # unlike the generic crit_chance/crit_damage_multiplier pair this
        # mirrors in shape, there is no reuse-vs-exclusive question here.
        self.relic_execute_damage_bonus_multiplier = 1.0
        # Wounded Prey-style relic -- Sniper-tower-exclusive, same plain-
        # multiply shape as relic_execute_damage_bonus_multiplier
        # immediately above, scaling execute_hp_threshold instead -- a
        # BIGGER threshold is the buff direction here (executes trigger
        # against tougher targets), the normal ">1.0 is stronger"
        # direction, unlike Frost's own inverted slow_factor.
        self.relic_execute_threshold_bonus_multiplier = 1.0
        # Glacial Core-style relic -- Frost-tower-exclusive, same
        # plain-multiply shape as relic_execute_damage_bonus_multiplier
        # above, scaling slow_factor instead. Buff direction is INVERTED
        # (<1.0 is stronger) -- see relics.py's own frost_slow_multiplier
        # comment, mirroring FrostTower's own slow_factor inversion.
        self.relic_frost_slow_bonus_multiplier = 1.0
        # Permafrost-style relic -- Frost-tower-exclusive, same plain-
        # multiply shape as relic_frost_slow_bonus_multiplier immediately
        # above, scaling slow_duration instead -- the normal ">1.0 is
        # stronger" direction.
        self.relic_frost_duration_bonus_multiplier = 1.0
        # Toxic Payload-style relic -- Poison-tower-exclusive, same
        # plain-multiply shape as relic_execute_damage_bonus_multiplier
        # above, scaling poison_damage_per_tick instead. Named with
        # "_tower_" in the middle (not relic_poison_tick_bonus_multiplier)
        # to stay unambiguous next to the existing generic
        # relic_poison_chance/relic_poison_effect fields below, which
        # grant/modify poison for *any* tower -- these two are exclusive to
        # PoisonTower's own innate DoT, a different mechanism entirely.
        self.relic_poison_tower_tick_bonus_multiplier = 1.0
        # Festering Wound-style relic -- Poison-tower-exclusive, same
        # plain-multiply shape as relic_poison_tower_tick_bonus_multiplier
        # immediately above, scaling poison_duration instead.
        self.relic_poison_tower_duration_bonus_multiplier = 1.0
        # The configured strength of a Last Stand Charm-style relic, set
        # once at construction like every relic_* field above -- but
        # relic_last_stand_multiplier below it is the one relic-driven
        # value on this whole class that ISN'T constant for the tower's
        # lifetime: Game.update() recomputes it every frame from live
        # Economy.lives (see Tower.set_last_stand_multiplier), since
        # "down to your last life" can turn on and off within a single
        # run, unlike any other relic effect here.
        self.relic_last_stand_bonus_multiplier = 1.0
        self.relic_last_stand_multiplier = 1.0
        # Chilling Precision-style relic -- ungated multiply, read
        # directly by Projectile._apply_hit_effects (needs the live
        # per-enemy slow_timer check that only exists at hit-resolution
        # time, not something effective_damage() can fold in once up
        # front like relic_damage_bonus_multiplier above).
        self.relic_damage_vs_slowed_multiplier = 1.0
        # Aftershock-style relic -- same chance-gated shape as
        # relic_poison_chance/relic_poison_effect above, just triggering
        # enemy.apply_slow() instead of apply_poison().
        self.relic_slow_chance = 0.0
        self.relic_slow_effect = None
        # Corrosive Poison-style relic -- threaded through to
        # enemy.apply_poison()/take_poison_damage() as ignore_shield.
        self.relic_poison_ignores_shield = False
        # Overcrowded Circuits-style relic -- relic_tower_density_radius/
        # _per_neighbor/_cap are its own configured strength (set once at
        # construction); relic_tower_density_bonus_multiplier is the live
        # value recomputed from this tower's own current neighbor count
        # whenever the board's tower set actually changes -- a placement,
        # a sale, or a save restore (see set_nearby_tower_bonus() below
        # and Game._recompute_tower_density_bonuses()) -- the
        # "per-tower-density (live-reactive)" shape relics.py's own
        # module docstring names.
        self.relic_tower_density_radius = 0.0
        self.relic_tower_density_damage_bonus_per_neighbor = 0.0
        self.relic_tower_density_damage_bonus_cap = 0.0
        self.relic_tower_density_bonus_multiplier = 1.0
        # Overclocked Circuits-style relic -- a third density channel,
        # fire rate instead of damage, reusing the exact same live
        # neighbor count set_nearby_tower_bonus() already computes above
        # rather than a second scan. _per_neighbor/_cap are its own
        # configured strength (set once at construction, like the damage
        # channel's pair above); relic_tower_density_fire_rate_bonus_
        # multiplier is the live value recomputed alongside relic_tower_
        # density_bonus_multiplier whenever set_nearby_tower_bonus() runs.
        self.relic_tower_density_fire_rate_bonus_per_neighbor = 0.0
        self.relic_tower_density_fire_rate_bonus_cap = 0.0
        self.relic_tower_density_fire_rate_bonus_multiplier = 1.0
        # Adrenaline Rush-style relic -- mirrors relic_last_stand_bonus_
        # multiplier/relic_last_stand_multiplier immediately above exactly,
        # just for fire rate instead of damage; both live values are set
        # together by set_last_stand_multiplier() below.
        self.relic_last_stand_fire_rate_bonus_multiplier = 1.0
        self.relic_last_stand_fire_rate_multiplier = 1.0
        # Desperate Reach-style relic -- a third live-reactive last-stand
        # channel, range instead of damage/fire rate, same configured-
        # strength/live-value pair shape as the two immediately above and
        # above that; toggled together with them by set_last_stand_
        # multiplier() below since all three key off the exact same
        # "down to your last life" condition.
        self.relic_last_stand_range_bonus_multiplier = 1.0
        self.relic_last_stand_range_multiplier = 1.0
        # Choke Point-style relic -- ungated multiply, read by Projectile
        # against enemy.distance_traveled.
        self.relic_damage_vs_early_route_multiplier = 1.0
        # Giant Slayer-style relic -- ungated multiply, read by Projectile
        # against enemy.max_hp.
        self.relic_damage_vs_high_hp_multiplier = 1.0
        # Overkill-style relic -- read by Projectile._apply_hit_effects
        # after a killing blow, to size the carry-over bounce.
        self.relic_overkill_carry_fraction = 0.0
        # Concussive Rounds-style relic -- same chance-gated shape as
        # relic_slow_chance/relic_slow_effect above, just triggering
        # enemy.apply_knockback() instead of apply_slow().
        self.relic_knockback_chance = 0.0
        self.relic_knockback_effect = None
        # Disorienting Flash-style relic -- same chance-gated shape,
        # triggering enemy.apply_mark() instead.
        self.relic_mark_chance = 0.0
        self.relic_mark_effect = None
        # Flak Rounds/Breach Charges-style relics -- ungated multiplies,
        # same shape as relic_damage_vs_slowed_multiplier above, read
        # against the target's own current is_flying/shield state.
        self.relic_damage_vs_flying_multiplier = 1.0
        self.relic_damage_vs_shielded_multiplier = 1.0
        # Suppression Directive-style relic -- ungated multiply, read
        # against the target's own current heal_rate.
        self.relic_damage_vs_healer_multiplier = 1.0
        # Interceptor Rounds-style relic -- ungated multiply, read by
        # Projectile against enemy.max_speed (a fixed per-species ceiling,
        # same reasoning as Giant Slayer's own max_hp check -- a slowed
        # fast enemy shouldn't lose the bonus just because its live speed
        # dropped).
        self.relic_damage_vs_fast_multiplier = 1.0
        # Titan Slayer-style relic -- ungated multiply, same shape as
        # relic_damage_vs_flying_multiplier above, read by Projectile
        # against enemy.IS_BOSS (a base Enemy class-level flag, always
        # present, True only for BossEnemy and its subclasses -- see
        # enemy.py).
        self.relic_damage_vs_boss_multiplier = 1.0
        # The game's first cross-status combo relics -- ungated multiplies,
        # same shape as relic_damage_vs_slowed_multiplier/relic_damage_vs_
        # flying_multiplier above, but each gated on TWO simultaneous enemy
        # statuses (mark_timer/slow_timer/poison_time_remaining, all base
        # Enemy attributes) rather than one. See Projectile._apply_hit_
        # effects for the actual gating.
        self.relic_damage_vs_marked_and_slowed_multiplier = 1.0
        self.relic_damage_vs_marked_and_poisoned_multiplier = 1.0
        self.relic_damage_vs_slowed_and_poisoned_multiplier = 1.0
        # Overwhelming Affliction -- the triple-status capstone on top of
        # the three combo relics just above, gated on ALL THREE statuses at
        # once instead of two. Same "ungated multiply, read by Projectile"
        # shape.
        self.relic_damage_vs_marked_and_slowed_and_poisoned_multiplier = 1.0
        # Seismic Slam-style relic -- Knockback-tower-exclusive, same
        # plain-multiply shape as relic_beam_ramp_bonus_multiplier/relic_
        # frost_slow_bonus_multiplier above, read only in KnockbackTower.
        # create_projectile() against its own knockback_duration. Distinct
        # from relic_knockback_chance/relic_knockback_effect above (a
        # generic relic that grants a knockback roll to ANY tower) and from
        # relic_cannon_knockback_damage_bonus_multiplier (Heavy Ordnance,
        # shared with Cannon, damage-only) -- this is Knockback's own
        # second exclusive relic, off its 1-relic floor.
        self.relic_knockback_duration_bonus_multiplier = 1.0
        # Refined Extraction-style relic -- SiphonTower-exclusive, scaling
        # siphon_gold_fraction above. Harmless on every other tower, which
        # never has a nonzero siphon_gold_fraction to multiply in the first
        # place. Deliberately NOT read via create_projectile() or
        # _apply_hit_effects() like every other relic_* field here -- see
        # Projectile._apply_direct_damage()'s own comment for why this one
        # is read at a genuinely new site instead.
        self.relic_siphon_gold_fraction_bonus_multiplier = 1.0
        # Amplified Coils-style relic -- SiphonTower-exclusive damage bonus,
        # same _relic_family_damage_bonus() hook shape as relic_lightning_
        # damage_bonus_multiplier/relic_cannon_knockback_damage_bonus_
        # multiplier above, read via SiphonTower's own override.
        self.relic_siphon_damage_bonus_multiplier = 1.0
        # SiphonTower's own accumulator -- battle gold earned from a
        # fraction of damage dealt, credited per hit in Projectile._apply_
        # direct_damage() and drained into real Economy.gold whole-gold-at-
        # a-time by Game.update() (the same drain-a-per-frame-accumulated-
        # value idiom fired_this_frame/impact_events/damage_events already
        # establish -- see CLAUDE.md's "Visual effects" section). Harmless
        # on every non-Siphon tower, which never accumulates anything here
        # since siphon_gold_fraction is 0.0 for them. Deliberately never
        # reset to 0 by the drain -- only the whole-gold portion is removed
        # each time, so a sub-1-gold remainder always carries forward
        # rather than being silently lost. Not serialized by save_state.py:
        # a save only ever happens between waves, with no live combat state
        # captured at all, and this remainder is worth less than 1 gold
        # regardless.
        self.pending_siphon_gold = 0.0
        # Overcharged Capacitors-style relic -- Overload-Cannon-exclusive,
        # same plain-multiply create_projectile()-read shape as relic_beam_
        # ramp_bonus_multiplier/relic_frost_slow_bonus_multiplier above:
        # burst_multiplier is an input to OverloadCannonTower's own burst
        # formula (damage = effective_damage() * burst_multiplier), not one
        # of effective_damage()'s own additive sources, so it skips the
        # family_damage_bonus() hook the same way every plain-multiply
        # relic here does.
        self.relic_overload_burst_bonus_multiplier = 1.0
        # Fusion Core-style relic -- Overload-Cannon-exclusive damage bonus,
        # same family_damage_bonus() hook shape as relic_lightning_damage_
        # bonus_multiplier/relic_cannon_knockback_damage_bonus_multiplier
        # above, read via OverloadCannonTower's own _relic_family_damage_
        # bonus() override.
        self.relic_overload_damage_bonus_multiplier = 1.0
        # Containment Charges-style relic is deliberately NOT one of these
        # relic_* fields -- it's a flat per-floor value with no per-tower
        # variation, so Game.update()'s own dead-enemy drain loop reads
        # self.relic_modifiers.splitter_child_damage directly instead of
        # this being threaded through Tower/Projectile like every relic
        # above (which all genuinely can vary per shot/per tower).
        # Always one tile's worth of area (settings.SUBTILES_PER_TILE)
        # unless a Compact Framework-style relic shrinks it -- see
        # tile_rect()/upgrade_badge_center()/draw() below and
        # Game._current_footprint_subtiles().
        self.footprint_subtiles = settings.SUBTILES_PER_TILE

    @property
    def is_max_level(self):
        return self.level >= self.MAX_LEVEL

    def upgrade_cost(self):
        """Gold cost to reach the next level, or None if already maxed.
        Folds in relic_upgrade_cost_multiplier (a Quartermaster's Favor-
        style relic's own discount, set once at construction like every
        other relic_* field -- see Game._construct_tower) the same way
        specialization_cost() below does."""
        if self.is_max_level:
            return None
        return round(self.cost * self.UPGRADE_COST_MULTIPLIERS[self.level + 1] * self.relic_upgrade_cost_multiplier)

    def _multiplier_table_for(self, name):
        """The level->multiplier table that applies to stat `name` -- its
        own override table if LEVEL_STAT_MULTIPLIER_OVERRIDES has one,
        otherwise the shared default LEVEL_STAT_MULTIPLIERS."""
        return self.LEVEL_STAT_MULTIPLIER_OVERRIDES.get(name, self.LEVEL_STAT_MULTIPLIERS)

    def upgrade(self):
        """Level up by one, rescaling every LEVEL_SCALED_STATS entry from
        its level-1 base. No-op (returns False) once at MAX_LEVEL."""
        if self.is_max_level:
            return False
        self.total_invested += self.upgrade_cost()
        self.level += 1
        for name, base_value in self._base_stats.items():
            multiplier = self._multiplier_table_for(name)[self.level]
            setattr(self, name, base_value * multiplier)
        return True

    def sell_value(self):
        """Gold refunded if this tower is sold right now -- a fraction
        (settings.SELL_REFUND_FRACTION, plus a Liquidation Rights-style
        relic's own additive bonus -- relic_sell_refund_bonus, set once at
        construction) of everything spent on it, base cost plus any
        upgrades, not just the base cost."""
        return round(self.total_invested * (settings.SELL_REFUND_FRACTION + self.relic_sell_refund_bonus))

    @property
    def can_specialize(self):
        return self.is_max_level and self.specialization is None

    def specialization_cost(self):
        """Gold cost to choose a specialization, or None if not eligible
        right now (not maxed yet, or already specialized). Folds in
        relic_upgrade_cost_multiplier the same way upgrade_cost() above
        does -- a Quartermaster's Favor-style relic discounts both."""
        if not self.can_specialize:
            return None
        return round(self.cost * self.SPECIALIZATION_COST_MULTIPLIER * self.relic_upgrade_cost_multiplier)

    def specialize(self, key):
        """Choose specialization `key` -- the one-time branching upgrade
        available once a tower hits MAX_LEVEL, applying that option's
        stat_multipliers on top of the tower's current stats. No-op
        (returns False) if not currently eligible or `key` isn't one of
        this tower's SPECIALIZATIONS."""
        if not self.can_specialize or key not in self.SPECIALIZATIONS:
            return False
        self.total_invested += self.specialization_cost()
        for stat_name, multiplier in self.SPECIALIZATIONS[key]["stat_multipliers"].items():
            setattr(self, stat_name, getattr(self, stat_name) * multiplier)
        self.specialization = key
        return True

    def _stat_after_next_upgrade(self, name):
        """What LEVEL_SCALED_STATS entry `name` would become after one
        more upgrade, without actually upgrading. Equal to its current
        value if already at MAX_LEVEL, or if this tower doesn't scale
        that stat with level at all."""
        if self.is_max_level or name not in self._base_stats:
            return getattr(self, name)
        next_level = self.level + 1
        return self._base_stats[name] * self._multiplier_table_for(name)[next_level]

    def range_after_next_upgrade(self):
        """Preview of `range` one level up -- used while hovering a
        tower's '+' badge, both for the range-ring preview and the stats
        panel (ui.py)."""
        return self._stat_after_next_upgrade("range")

    def damage_after_next_upgrade(self):
        """Preview of `damage` one level up -- see range_after_next_upgrade
        for the same idea applied to damage."""
        return self._stat_after_next_upgrade("damage")

    def reset_aura(self):
        """Called on every tower, every frame, before any tower's own
        update() runs (see Game.update()) -- a buff only lasts the frame a
        SupportTower is actually in range to re-apply it via receive_aura()."""
        self.aura_damage_multiplier = 1.0
        self.aura_range_multiplier = 1.0

    def receive_aura(self, damage_multiplier, range_multiplier):
        """Called by a SupportTower in range, once per frame, for every
        other tower it buffs. max(), not stacking/multiplying: several
        support towers in range at once don't compound into a stronger
        buff, and this is deterministic regardless of what order Game's
        tower loop happens to visit them in."""
        self.aura_damage_multiplier = max(self.aura_damage_multiplier, damage_multiplier)
        self.aura_range_multiplier = max(self.aura_range_multiplier, range_multiplier)

    def update(self, dt, enemies, projectiles, towers=None, enemy_index=None):
        self.cooldown -= dt
        if self.cooldown > 0:
            return

        target = self.acquire_target(enemies, enemy_index)
        if target is None:
            return

        self.shots_fired += 1
        self.fired_this_frame = True
        projectile = self.create_projectile(target)
        # Relic-driven, chance-based hit effects apply uniformly to every
        # tower's shots -- copied onto the projectile here, the one choke
        # point every tower type's fire cycle passes through, rather than
        # each create_projectile() override having to remember to do it
        # itself. See Projectile._apply_hit_effects for where the actual
        # roll happens (once per enemy the projectile hits, not once here
        # per shot).
        #
        # KNOWN DUPLICATE -- read before editing: OverloadCannonTower.
        # update() (below) keeps its own copy of this exact block, verbatim
        # -- its cadence (acquire once, charge, burst, repeat) doesn't fit
        # this method's own cooldown-then-immediately-fire template at all,
        # so it overrides update() entirely instead of just
        # create_projectile() (see that class's own docstring). If you add
        # a new relic_* line to this block, you MUST add the identical line
        # to OverloadCannonTower.update()'s own copy too, or Overload
        # Cannon will silently not support that relic.
        projectile.relic_poison_chance = self.relic_poison_chance
        projectile.relic_poison_effect = self.relic_poison_effect
        projectile.relic_crit_chance = self.relic_crit_chance
        projectile.relic_crit_damage_multiplier = self.relic_crit_damage_multiplier
        projectile.relic_chain_chance = self.relic_chain_chance
        projectile.relic_chain_effect = self.relic_chain_effect
        projectile.relic_damage_vs_slowed_multiplier = self.relic_damage_vs_slowed_multiplier
        projectile.relic_slow_chance = self.relic_slow_chance
        projectile.relic_slow_effect = self.relic_slow_effect
        projectile.relic_poison_ignores_shield = self.relic_poison_ignores_shield
        projectile.relic_damage_vs_early_route_multiplier = self.relic_damage_vs_early_route_multiplier
        projectile.relic_damage_vs_high_hp_multiplier = self.relic_damage_vs_high_hp_multiplier
        projectile.relic_overkill_carry_fraction = self.relic_overkill_carry_fraction
        projectile.relic_knockback_chance = self.relic_knockback_chance
        projectile.relic_knockback_effect = self.relic_knockback_effect
        projectile.relic_mark_chance = self.relic_mark_chance
        projectile.relic_mark_effect = self.relic_mark_effect
        projectile.relic_damage_vs_flying_multiplier = self.relic_damage_vs_flying_multiplier
        projectile.relic_damage_vs_shielded_multiplier = self.relic_damage_vs_shielded_multiplier
        projectile.relic_damage_vs_healer_multiplier = self.relic_damage_vs_healer_multiplier
        projectile.relic_damage_vs_fast_multiplier = self.relic_damage_vs_fast_multiplier
        projectile.relic_damage_vs_boss_multiplier = self.relic_damage_vs_boss_multiplier
        projectile.relic_damage_vs_marked_and_slowed_multiplier = self.relic_damage_vs_marked_and_slowed_multiplier
        projectile.relic_damage_vs_marked_and_poisoned_multiplier = self.relic_damage_vs_marked_and_poisoned_multiplier
        projectile.relic_damage_vs_slowed_and_poisoned_multiplier = self.relic_damage_vs_slowed_and_poisoned_multiplier
        projectile.relic_damage_vs_marked_and_slowed_and_poisoned_multiplier = (
            self.relic_damage_vs_marked_and_slowed_and_poisoned_multiplier
        )
        projectiles.append(projectile)
        self.cooldown = 1.0 / self.effective_fire_rate()

    def acquire_target(self, enemies, enemy_index=None):
        """In-range, still-on-the-path enemy selected by targeting_mode --
        "first" (furthest along the path) is the default and, before
        targeting_mode existed, this method's only-ever behavior; see
        _target_first. More robust than raw proximity on a path with
        switchbacks, and works unchanged regardless of which enemy species
        are involved. Must exclude enemies that already reached the goal,
        not just dead ones: Game.update() runs every tower's update()
        before it filters reached-goal enemies out of the live list for
        this frame, so without this check a tower could fire a brand-new
        shot at an enemy that's already effectively gone -- and since
        "furthest along the path" is the whole ranking for the default
        mode, a just-arrived enemy would usually *win* that ranking over
        every real threat still on the path. Also excludes a flying enemy
        (see enemy.py) from a tower whose can_target_flying is False --
        checked via getattr rather than a bare attribute access, since not
        every enemy stand-in (tests, mainly) defines is_flying.

        `enemy_index` (an `EnemySpatialIndex`, see spatial_index.py) is an
        optional broad-phase narrowing of `enemies` down to whatever's near
        enough to plausibly be in range -- Game.update() builds one fresh
        each frame and passes it through; every existing caller that omits
        it (every test in this codebase, chiefly) falls back to scanning
        the raw `enemies` list exactly as before, with identical results
        either way, since the index is only ever a candidate pool the exact
        in_range() check below still filters."""
        effective_range = self.effective_range()
        pool = enemy_index.near(self.pos, effective_range) if enemy_index is not None else enemies
        candidates = [
            e for e in pool
            if not e.is_dead and not e.reached_goal and self.in_range(e, effective_range)
            and (self.can_target_flying or not getattr(e, "is_flying", False))
        ]
        if not candidates:
            return None
        return self._TARGETING_STRATEGIES[self.targeting_mode](self, candidates)

    def _target_first(self, candidates):
        return max(candidates, key=lambda e: e.distance_traveled)

    def _target_last(self, candidates):
        return min(candidates, key=lambda e: e.distance_traveled)

    def _target_strongest(self, candidates):
        return max(candidates, key=lambda e: e.hp)

    def _target_weakest(self, candidates):
        return min(candidates, key=lambda e: e.hp)

    def _target_closest(self, candidates):
        return min(candidates, key=lambda e: self.pos.distance_to(e.pos))

    def cycle_targeting_mode(self):
        """Advance to the next TARGETING_MODES entry, wrapping around --
        the stats panel's "Targeting: ..." row calls this on click."""
        index = self.TARGETING_MODES.index(self.targeting_mode)
        self.targeting_mode = self.TARGETING_MODES[(index + 1) % len(self.TARGETING_MODES)]

    # Keyed by TARGETING_MODES; acquire_target() looks itself up here rather
    # than an if/elif chain. Defined after the strategy methods themselves
    # so it can reference them directly.
    _TARGETING_STRATEGIES = {
        "first": _target_first,
        "last": _target_last,
        "strongest": _target_strongest,
        "closest": _target_closest,
        "weakest": _target_weakest,
    }

    def in_range(self, enemy, effective_range=None):
        """`effective_range` lets a caller that already computed it once
        (e.g. acquire_target(), scanning every enemy in the wave) pass it
        straight through instead of this method re-deriving the same
        tower-constant value per call; omit it and this just resolves its
        own effective_range()."""
        if effective_range is None:
            effective_range = self.effective_range()
        return self.pos.distance_to(enemy.pos) <= effective_range

    def effective_range(self):
        """self.range scaled by three independent bonus sources, stacked
        ADDITIVELY (1.0 + aura_bonus + relic_bonus + last_stand_bonus): the
        transient per-frame aura buff (aura_range_multiplier, reset every
        frame -- see reset_aura()/receive_aura()), this tower's own
        persistent, relic-driven bonus (relic_range_bonus_multiplier, set
        once at construction from whatever Spyglass Array-style relic the
        run holds -- see Game._construct_tower), and a Desperate Reach-
        style relic's own live, per-frame-recomputed bonus (relic_last_
        stand_range_multiplier -- see set_last_stand_multiplier()). None of
        the three multiply or take max() against each other -- a tower
        buffed by a nearby Support tower, a held Range relic, and a last-
        stand relic all at once gets more range than any one alone, unlike
        receive_aura()'s own max()-not-stacking rule for multiple
        SupportTowers."""
        return self.range * (
            1.0
            + (self.aura_range_multiplier - 1.0)
            + (self.relic_range_bonus_multiplier - 1.0)
            + (self.relic_last_stand_range_multiplier - 1.0)
        )

    def relic_adjusted_range(self):
        """self.range scaled by only this tower's own persistent,
        relic-driven range bonus -- effective_range() minus its transient
        aura_range_multiplier term. SupportTower.update() uses this for
        its own broadcast reach instead of effective_range(): folding in
        aura_range_multiplier there would let one Support tower's buff on
        another feed into that other tower's own broadcast decision
        within the same frame (Game.update()'s two-pass loop runs every
        tower's own update() in list order, all sharing one frame), an
        order-dependent chain reaction with no equivalent before relics
        existed -- a Support tower's own reach was always immune to
        aura buffs, only ever widened by a relic held all run."""
        return self.range * (1.0 + (self.relic_range_bonus_multiplier - 1.0))

    def effective_damage(self):
        """self.damage scaled by five independent bonus sources, stacked
        ADDITIVELY (1.0 + aura_bonus + relic_bonus + last_stand_bonus +
        density_bonus + family_bonus) -- the same "sources don't multiply
        or max()" rule effective_range() already establishes for its own
        two sources, generalized here: the transient per-frame aura buff
        (aura_damage_multiplier, reset every frame -- see reset_aura()/
        receive_aura()), this tower's persistent relic-driven bonus
        (relic_damage_bonus_multiplier, set once at construction -- see
        Game._construct_tower), a Last Stand Charm-style relic's live,
        per-frame-recomputed bonus (relic_last_stand_multiplier -- see
        set_last_stand_multiplier()), an Overcrowded Circuits-style
        relic's own live density bonus, recomputed whenever the board's
        tower set changes rather than every frame (relic_tower_density_
        bonus_multiplier -- see set_nearby_tower_bonus()), and a Storm
        Core/Heavy Ordnance-style relic's own tower-family-exclusive bonus
        (_relic_family_damage_bonus() -- 0.0 on this base class, overridden
        by whichever concrete tower class(es) that relic targets; see that
        method's own docstring for why it has to be a hook rather than a
        plain field read here directly). Every create_projectile() below
        reads this instead of self.damage directly, so a buffed tower's
        shots reflect it without each subclass repeating the
        multiplication."""
        return self.damage * (
            1.0
            + (self.aura_damage_multiplier - 1.0)
            + (self.relic_damage_bonus_multiplier - 1.0)
            + (self.relic_last_stand_multiplier - 1.0)
            + (self.relic_tower_density_bonus_multiplier - 1.0)
            + self._relic_family_damage_bonus()
        )

    def _relic_family_damage_bonus(self):
        """Hook for a relic that only bonuses a specific tower family's
        damage (Storm Core for Lightning, Heavy Ordnance for Cannon/
        Knockback) -- 0.0 (no bonus) on this base class, overridden by
        whichever concrete tower class(es) that relic targets, each
        returning `self.relic_<x>_bonus_multiplier - 1.0` the same way
        effective_damage()'s other four sources already do. This has to be
        a per-class hook rather than one more plain field read directly in
        effective_damage() itself: relic_lightning_damage_bonus_multiplier/
        relic_cannon_knockback_damage_bonus_multiplier are set on *every*
        tower harmlessly at construction (see Game._construct_tower, same
        "harmless everywhere, read only where it matters" shape arc_
        conductor/shockwave_rounds already established), so folding either
        straight into the base class's own formula unconditionally would
        silently apply a Lightning-exclusive or Cannon/Knockback-exclusive
        relic's bonus to every tower type instead of just the one(s) it
        names -- exactly the class-exclusivity a plain shared field can't
        express on its own. Earlier versions of Storm Core/Heavy Ordnance
        instead multiplied their bonus into an already-resolved
        effective_damage() result at each create_projectile() call site --
        that kept the exclusivity but broke additive stacking with every
        other source above (compounding multiplicatively against them
        instead); this hook is what fixes both at once."""
        return 0.0

    def set_last_stand_multiplier(self, active):
        """Called every frame by Game.update() (alongside reset_aura(), in
        the same first pass) with `active` = whether Economy.lives is down
        to the last one -- the one relic-driven value on this class that
        reacts to live, changing game state rather than resolving once at
        floor-load/construction time. relic_last_stand_bonus_multiplier/
        relic_last_stand_fire_rate_bonus_multiplier/relic_last_stand_range_
        bonus_multiplier are the relics' own configured strengths (constant,
        from Game._construct_tower); this just switches whether effective_
        damage()/effective_fire_rate()/effective_range() currently apply
        them, all three in the same call since all three relics key off the
        exact same "down to your last life" condition."""
        self.relic_last_stand_multiplier = (
            self.relic_last_stand_bonus_multiplier if active else 1.0
        )
        self.relic_last_stand_fire_rate_multiplier = (
            self.relic_last_stand_fire_rate_bonus_multiplier if active else 1.0
        )
        self.relic_last_stand_range_multiplier = (
            self.relic_last_stand_range_bonus_multiplier if active else 1.0
        )

    def set_nearby_tower_bonus(self, towers):
        """Called with the board's full current towers list (`self`
        included) whenever that set actually changes -- a placement, a
        sale, or restoring a whole save (see Game._recompute_tower_
        density_bonuses) -- mirroring how SupportTower.update() already
        receives and scans this same list for its own aura broadcast,
        rather than a caller reducing it to a bare count first. Computes
        and stores the live Overcrowded Circuits-style density bonus read
        by effective_damage(), capped at relic_tower_density_damage_bonus_
        cap, AND the live Overclocked Circuits-style density bonus read by
        effective_fire_rate(), capped at relic_tower_density_fire_rate_
        bonus_cap -- both derived from the exact same nearby_count this
        method already computes once, not a second scan. No such relic
        held (relic_tower_density_radius left at 0) or no other tower
        actually within it leaves both multipliers at 1.0, a no-op in
        effective_damage()'s additive stack and effective_fire_rate()'s
        multiplicative one -- and skips the scan itself entirely in the
        no-relic case, the common one. 'Every other tower' counts
        SupportTower instances too -- the relics' own text says 'tower,'
        not 'attacking tower.' This is deliberately NOT re-resolved every
        frame the way aura_damage_multiplier is: unlike an aura buff
        (broadcast fresh each frame by whichever SupportTower is currently
        in range), a tower's own .pos never moves once placed, so nothing
        about this count can change between one of the events above and
        the next."""
        nearby_count = 0
        if self.relic_tower_density_radius > 0:
            radius_sq = self.relic_tower_density_radius ** 2
            nearby_count = sum(
                1 for other in towers
                if other is not self and self.pos.distance_squared_to(other.pos) <= radius_sq
            )
        damage_bonus = min(
            nearby_count * self.relic_tower_density_damage_bonus_per_neighbor,
            self.relic_tower_density_damage_bonus_cap,
        )
        self.relic_tower_density_bonus_multiplier = 1.0 + damage_bonus
        fire_rate_bonus = min(
            nearby_count * self.relic_tower_density_fire_rate_bonus_per_neighbor,
            self.relic_tower_density_fire_rate_bonus_cap,
        )
        self.relic_tower_density_fire_rate_bonus_multiplier = 1.0 + fire_rate_bonus

    def effective_fire_rate(self):
        """self.fire_rate scaled by three independent multiplicative
        sources: this tower's own persistent, relic-driven bonus
        (relic_fire_rate_bonus_multiplier -- see Game._construct_tower),
        an Adrenaline Rush-style relic's live, per-frame-recomputed bonus
        (relic_last_stand_fire_rate_multiplier -- see set_last_stand_
        multiplier()), and an Overclocked Circuits-style relic's own live
        density bonus, recomputed whenever the board's tower set changes
        rather than every frame (relic_tower_density_fire_rate_bonus_
        multiplier -- see set_nearby_tower_bonus()). Unlike effective_
        range()/effective_damage(), there's no aura equivalent for fire
        rate to also fold in, so all three sources just multiply straight
        in rather than stacking additively."""
        return (
            self.fire_rate
            * self.relic_fire_rate_bonus_multiplier
            * self.relic_last_stand_fire_rate_multiplier
            * self.relic_tower_density_fire_rate_bonus_multiplier
        )

    def create_projectile(self, target):
        raise NotImplementedError

    def tile_rect(self):
        """pygame.Rect for this tower's footprint -- self.footprint_subtiles
        subtiles square (a full tile, settings.SUBTILES_PER_TILE, unless a
        relic shrank it -- see Game._construct_tower), positioned at its
        subtile anchor rather than a tile boundary."""
        size = self.footprint_subtiles * settings.SUBTILE_SIZE
        return pygame.Rect(self.anchor_col * settings.SUBTILE_SIZE, self.anchor_row * settings.SUBTILE_SIZE,
                            size, size)

    def contains_point(self, pos):
        """True if pixel position `pos` is anywhere on this tower's tile --
        used to show its stats/range on hover. Broader than
        contains_upgrade_badge() below, which is just the small clickable
        '+' circle that actually triggers an upgrade."""
        return self.tile_rect().collidepoint(pos)

    # --- Upgrade badge: the clickable "+cost" shown at a placed tower's
    # top-right corner. Geometry lives here (not in game.py/ui.py) so hit-
    # testing and drawing always agree on where it is. ---

    BADGE_RADIUS = 9

    def upgrade_badge_center(self):
        rect = self.tile_rect()
        inset = self.BADGE_RADIUS + 2
        return (rect.left + rect.width - inset, rect.top + inset)

    def contains_upgrade_badge(self, pos):
        """True if pixel position `pos` is within this tower's upgrade
        badge -- there is no badge (and this is always False) once the
        tower is at MAX_LEVEL, since there's nothing left to upgrade to."""
        if self.is_max_level:
            return False
        cx, cy = self.upgrade_badge_center()
        dx, dy = pos[0] - cx, pos[1] - cy
        return dx * dx + dy * dy <= self.BADGE_RADIUS ** 2

    def draw(self, surface, assets, font=None):
        # Sized almost edge-to-edge with the footprint (self.footprint_
        # subtiles subtiles square -- a full tile unless a relic shrank
        # it, see tile_rect()) rather than with a big margin, so the
        # sprite's own edges make it obvious which subtiles the tower's
        # anchor actually covers -- the margin is just the same subtile
        # gap the map's own mosaic uses, not an arbitrary inset.
        margin = 2 * settings.SUBTILE_GAP
        footprint_size = self.footprint_subtiles * settings.SUBTILE_SIZE
        size = (footprint_size - margin, footprint_size - margin)
        sprite = assets.get(self.sprite_name, size)
        rect = sprite.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        surface.blit(sprite, rect)
        self._draw_level_pips(surface, rect)
        if font is not None:
            self._draw_upgrade_badge(surface, font)

    def _draw_upgrade_badge(self, surface, font):
        cost = self.upgrade_cost()
        if cost is None:
            return  # already at max level -- nothing to upgrade to

        center = self.upgrade_badge_center()
        pygame.draw.circle(surface, settings.COLOR_BUTTON_SELECTED, center, self.BADGE_RADIUS)
        pygame.draw.circle(surface, (0, 0, 0), center, self.BADGE_RADIUS, width=1)

        plus_text = font.render("+", True, settings.COLOR_TEXT)
        surface.blit(plus_text, plus_text.get_rect(center=center))

        cost_text = font.render(str(cost), True, settings.COLOR_GOLD)
        surface.blit(cost_text, cost_text.get_rect(midtop=(center[0], center[1] + self.BADGE_RADIUS + 2)))

    def _draw_level_pips(self, surface, sprite_rect):
        # One pip per level above 1 -- a level-1 (just-placed) tower shows
        # none, so upgraded towers are the ones that visibly stand out.
        pip_count = self.level - 1
        if pip_count <= 0:
            return
        pip_radius, spacing = 3, 9
        start_x = sprite_rect.centerx - spacing * (pip_count - 1) / 2
        y = sprite_rect.bottom - 2
        for i in range(pip_count):
            x = int(start_x + i * spacing)
            pygame.draw.circle(surface, settings.COLOR_GOLD, (x, y), pip_radius)
            pygame.draw.circle(surface, (0, 0, 0), (x, y), pip_radius, width=1)


class BasicTower(Tower):
    cost = 50
    range = 120
    damage = 10
    fire_rate = 1.2
    projectile_speed = 360.0
    sprite_name = "tower_basic"
    display_name = "Basic"
    # Cheap and unremarkable at level 1, but scales on damage much more
    # steeply than the generic curve so it stays a satisfying investment
    # late-game instead of being outclassed by pricier towers -- fair
    # numbers don't always make for a fun upgrade path. Range still uses
    # the generic LEVEL_STAT_MULTIPLIERS.
    LEVEL_STAT_MULTIPLIER_OVERRIDES = {"damage": {1: 1.0, 2: 1.7, 3: 2.6}}
    # A native crit mechanic -- flat across levels (not in LEVEL_SCALED_
    # STATS), only ever moved by specialization below, same "level ->
    # generic curve, specialization -> the tower's own mechanic" split
    # every other tower's signature stat already follows.
    crit_chance = 0.15
    crit_damage_multiplier = 1.6
    EXTRA_STATS = (
        ("Crit chance", "crit_chance", _format_chance_percent),
        ("Crit multiplier", "crit_damage_multiplier", _format_buff_percent),
    )
    # Keys are kept as the literal "power"/"precision" (not renamed to
    # match the new crit flavor) since several tests in test_tower_
    # leveling.py/test_game.py exercise the generic specialize() mechanism
    # via a default-constructed BasicTower and hardcode those two key
    # strings -- only the values/flavor text below are new.
    SPECIALIZATIONS = {
        "power": {
            "display_name": "Piercing Strikes",
            "description": "Crits hit much harder.",
            "stat_multipliers": {"crit_damage_multiplier": 1.375},  # 1.6 -> 2.2
        },
        "precision": {
            "display_name": "Keen Eye",
            "description": "Crits much more often.",
            "stat_multipliers": {"crit_chance": 1.333},  # 0.15 -> ~0.20
        },
    }

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(), sprite_name="projectile_basic", source=self,
            crit_chance=self.crit_chance * self.relic_basic_crit_chance_bonus_multiplier,
            crit_damage_multiplier=self.crit_damage_multiplier * self.relic_basic_crit_damage_bonus_multiplier,
        )


class CannonTower(Tower):
    cost = 100
    range = 100
    damage = 18
    fire_rate = 0.6
    projectile_speed = 260.0
    splash_radius = 55
    sprite_name = "tower_cannon"
    display_name = "Cannon"
    FIRE_SOUND = "tower_fire_heavy"
    EXTRA_STATS = (("Splash radius", "splash_radius", _format_px),)
    # A lobbed, ground-impact blast has nothing to detonate against in
    # midair -- see enemy.py's FlyingEnemy -- UNLESS an Aerial Targeting
    # Array-style relic is held (relic_cannon_targets_flying, set at
    # construction time -- see Game._construct_tower). A property, not a
    # plain class attribute like every other tower's can_target_flying
    # (including KnockbackTower's own, untouched, immediately below):
    # Tower.acquire_target() always reads self.can_target_flying off a
    # real instance, so this resolves per-tower from that instance's own
    # relic field with no other call site needing to change.
    @property
    def can_target_flying(self):
        return self.relic_cannon_targets_flying

    # Overrides the generic Power/Precision placeholders with options that
    # play off Cannon's own splash mechanic instead.
    SPECIALIZATIONS = {
        "bigger_blast": {
            "display_name": "Bigger Blast",
            "description": "Wider splash radius.",
            "stat_multipliers": {"splash_radius": 1.4},
        },
        "heavier_payload": {
            "display_name": "Heavier Payload",
            "description": "Harder-hitting shells.",
            "stat_multipliers": {"damage": 1.35},
        },
    }

    def _relic_family_damage_bonus(self):
        # Heavy Ordnance-style relic -- see Tower._relic_family_damage_
        # bonus's own docstring for why this has to be a per-class
        # override rather than a plain field effective_damage() reads
        # directly. KnockbackTower below overrides this identically -- the
        # same Cannon/Knockback pairing relic_splash_radius_bonus_
        # multiplier's own read sites already share.
        return self.relic_cannon_knockback_damage_bonus_multiplier - 1.0

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target,
            # High-Velocity Shells-style relic -- see relic_cannon_
            # projectile_speed_bonus_multiplier's own comment on Tower.
            # __init__.
            speed=self.projectile_speed * self.relic_cannon_projectile_speed_bonus_multiplier,
            damage=self.effective_damage(),
            splash_radius=self.splash_radius * self.relic_splash_radius_bonus_multiplier,
            sprite_name="projectile_cannon", source=self,
        )


class FrostTower(Tower):
    cost = 75
    range = 110
    damage = 4
    fire_rate = 1.0
    projectile_speed = 320.0
    slow_factor = 0.5
    slow_duration = 2.0
    sprite_name = "tower_frost"
    display_name = "Frost"
    EXTRA_STATS = (
        ("Slow", "slow_factor", _format_slow_percent),
        ("Slow duration", "slow_duration", _format_seconds),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off Frost's own slow mechanic instead. Deep Freeze's multiplier
    # is deliberately *less* than 1.0 -- slow_factor is the one stat in this
    # whole registry where "better" means smaller (see _format_slow_percent:
    # a lower slow_factor is a stronger slow), the opposite direction of
    # every other tower's >1.0 buff convention here.
    SPECIALIZATIONS = {
        "deep_freeze": {
            "display_name": "Deep Freeze",
            "description": "Slows even more.",
            "stat_multipliers": {"slow_factor": 0.7},
        },
        "lingering_frost": {
            "display_name": "Lingering Frost",
            "description": "Slow lasts much longer.",
            "stat_multipliers": {"slow_duration": 1.6},
        },
    }

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(),
            slow_effect=(
                self.slow_factor * self.relic_frost_slow_bonus_multiplier,
                self.slow_duration * self.relic_frost_duration_bonus_multiplier,
            ),
            sprite_name="projectile_frost", source=self,
        )


class KnockbackTower(Tower):
    cost = 90
    range = 90
    damage = 8
    fire_rate = 0.9
    projectile_speed = 300.0
    splash_radius = 70  # hits every enemy in this radius of the impact, not just the target
    # Seconds of each hit enemy's own forward progress to undo -- not a
    # fixed pixel distance, so faster enemies get shoved back further.
    # Kept small now that it's AoE: a big per-enemy shove across a whole
    # cluster would be far too strong.
    knockback_duration = 0.35
    sprite_name = "tower_knockback"
    display_name = "Knockback"
    EXTRA_STATS = (
        ("Splash radius", "splash_radius", _format_px),
        ("Knockback", "knockback_duration", _format_seconds),
    )
    # A physical shove along the ground path doesn't reach something
    # airborne -- see enemy.py's FlyingEnemy.
    can_target_flying = False
    # Overrides the generic Power/Precision placeholders with options that
    # play off Knockback's own splash/shove mechanic instead.
    SPECIALIZATIONS = {
        "wrecking_ball": {
            "display_name": "Wrecking Ball",
            "description": "Wider splash radius.",
            "stat_multipliers": {"splash_radius": 1.4},
        },
        "concussive_force": {
            "display_name": "Concussive Force",
            "description": "Bigger backward shove.",
            "stat_multipliers": {"knockback_duration": 1.5},
        },
    }

    def _relic_family_damage_bonus(self):
        # Heavy Ordnance-style relic -- mirrors CannonTower's own override
        # of this hook exactly (see its docstring reference on Tower for
        # why a per-class hook, not a plain field, is required here).
        return self.relic_cannon_knockback_damage_bonus_multiplier - 1.0

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(),
            splash_radius=self.splash_radius * self.relic_splash_radius_bonus_multiplier,
            knockback_duration=self.knockback_duration * self.relic_knockback_duration_bonus_multiplier,
            sprite_name="projectile_knockback", source=self,
        )


class LightningTower(Tower):
    cost = 110
    range = 100
    damage = 8
    fire_rate = 1.0
    projectile_speed = 400.0
    # Max distance from one hit enemy to the next it can arc to -- kept
    # short since, unlike max_chain_targets, nothing else bounds how many
    # enemies a bolt can reach through a tightly packed cluster.
    chain_range = 50
    max_chain_targets = float("inf")  # arcs to every unvisited enemy it can reach, no cap
    sprite_name = "tower_lightning"
    display_name = "Lightning"
    FIRE_SOUND = "tower_fire_zap"
    EXTRA_STATS = (
        ("Chain range", "chain_range", _format_px),
        ("Max targets", "max_chain_targets", _format_count),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off Lightning's own mechanic instead: a longer reach between
    # chain links, or more damage on every link a bolt hits (not just the
    # first target) -- create_projectile() below reads both straight off
    # self, so a chosen specialization applies to every shot fired after.
    SPECIALIZATIONS = {
        "arc_reach": {
            "display_name": "Arc Reach",
            "description": "Chains reach further.",
            "stat_multipliers": {"chain_range": 1.6},
        },
        "overcharge": {
            "display_name": "Overcharge",
            "description": "Harder-hitting chains.",
            "stat_multipliers": {"damage": 1.5},
        },
    }

    def _relic_family_damage_bonus(self):
        # Storm Core-style relic -- see Tower._relic_family_damage_bonus's
        # own docstring for why this has to be a per-class override rather
        # than a plain field effective_damage() reads directly.
        return self.relic_lightning_damage_bonus_multiplier - 1.0

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(),
            chain_range=self.chain_range * self.relic_lightning_chain_range_bonus_multiplier,
            max_chain_targets=self.max_chain_targets,
            sprite_name="projectile_lightning", source=self,
        )


class SniperTower(Tower):
    """Very high damage, very long range, slow fire rate -- a glass-cannon
    single-target pick with a native "Execute" mechanic: bonus damage
    against a target already at or below execute_hp_threshold of its own
    max_hp (a genuinely new condition, distinct from every other max-HP/
    route/slow-based check in this codebase -- see projectile.py's own
    docstring)."""
    cost = 130
    range = 220
    damage = 45
    fire_rate = 0.35
    projectile_speed = 500.0
    sprite_name = "tower_sniper"
    display_name = "Sniper"
    # Flat across levels (not in LEVEL_SCALED_STATS), only ever moved by
    # specialization below, same shape as Basic's own crit_chance/
    # crit_damage_multiplier.
    execute_hp_threshold = 0.30
    execute_damage_multiplier = 1.75
    EXTRA_STATS = (
        ("Execute threshold", "execute_hp_threshold", _format_chance_percent),
        ("Execute multiplier", "execute_damage_multiplier", _format_buff_percent),
    )
    # Unlike Basic, no test hardcodes Sniper's specific key strings, but
    # they're kept as-is anyway (only the values/flavor text are new) to
    # minimize churn.
    SPECIALIZATIONS = {
        "armor_piercing": {
            "display_name": "Executioner's Round",
            "description": "Finishing blows hit harder.",
            "stat_multipliers": {"execute_damage_multiplier": 1.4},  # 1.75 -> 2.45
        },
        "extended_scope": {
            "display_name": "Precision Marking",
            "description": "Executes enemies sooner.",
            "stat_multipliers": {"execute_hp_threshold": 1.5},  # 0.30 -> 0.45
        },
    }

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(), sprite_name="projectile_sniper", source=self,
            execute_hp_threshold=self.execute_hp_threshold * self.relic_execute_threshold_bonus_multiplier,
            execute_damage_multiplier=self.execute_damage_multiplier * self.relic_execute_damage_bonus_multiplier,
        )


class PoisonTower(Tower):
    """Low direct hit, but leaves a damage-over-time effect behind -- see
    Projectile.poison_effect / Enemy.apply_poison, deliberately built as
    close a parallel to FrostTower's slow_effect as possible."""
    cost = 85
    range = 100
    damage = 3
    fire_rate = 1.0
    projectile_speed = 300.0
    poison_damage_per_tick = 4
    poison_tick_interval = 0.5
    poison_duration = 3.0
    sprite_name = "tower_poison"
    display_name = "Poison"
    EXTRA_STATS = (
        ("Poison", "poison_damage_per_tick", _format_poison_tick),
        ("Poison duration", "poison_duration", _format_seconds),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off Poison's own damage-over-time mechanic instead.
    SPECIALIZATIONS = {
        "virulent_strain": {
            "display_name": "Virulent Strain",
            "description": "Stronger poison ticks.",
            "stat_multipliers": {"poison_damage_per_tick": 1.5},
        },
        "lingering_toxin": {
            "display_name": "Lingering Toxin",
            "description": "Poison lasts much longer.",
            "stat_multipliers": {"poison_duration": 1.6},
        },
    }

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(),
            poison_effect=(
                self.poison_damage_per_tick * self.relic_poison_tower_tick_bonus_multiplier,
                self.poison_tick_interval,
                self.poison_duration * self.relic_poison_tower_duration_bonus_multiplier,
            ),
            sprite_name="projectile_poison", source=self,
        )


class SiphonTower(Tower):
    """Low direct hit, but converts a fraction of damage DEALT into battle
    gold -- the first tower in this roster whose own mechanic generates
    economy from damage rather than from kills (contrast with the
    bounty_hunters_ledger relic, which is a kill-gold-only relic, not a
    tower mechanic). siphon_gold_fraction is flat across levels (not in
    LEVEL_SCALED_STATS), only ever moved by specialization/relics, the same
    shape as PoisonTower's own poison_damage_per_tick above.

    Deliberately introduces NO new Tower<->Economy/Game coupling: neither
    Tower nor Projectile has ever held a live Economy/Game reference, and
    this tower doesn't start now. Instead it reuses the exact drain-a-per-
    frame-accumulated-value idiom fired_this_frame/impact_events/
    damage_events already establish (see CLAUDE.md's "Visual effects"
    section) -- see pending_siphon_gold's own comment in __init__ above,
    Projectile._apply_direct_damage() for where it's credited, and
    Game.update() for where it's actually drained into real gold.
    create_projectile() below needs zero siphon-specific kwargs at all --
    the whole mechanic lives on the Tower side and is read directly off
    self.source (this tower) at credit time."""
    cost = 70
    range = 105
    damage = 3
    fire_rate = 1.0
    projectile_speed = 300.0
    siphon_gold_fraction = 0.6
    sprite_name = "tower_siphon"
    display_name = "Siphon"
    EXTRA_STATS = (
        ("Gold conversion", "siphon_gold_fraction", _format_chance_percent),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off Siphon's own gold-conversion mechanic instead.
    SPECIALIZATIONS = {
        "refined_conduit": {
            "display_name": "Refined Conduit",
            "description": "Siphons more gold per hit.",
            "stat_multipliers": {"siphon_gold_fraction": 1.35},
        },
        "overcharged_coils": {
            "display_name": "Overcharged Coils",
            "description": "Harder hits, longer reach.",
            "stat_multipliers": {"damage": 1.5, "range": 1.15},
        },
    }

    def _relic_family_damage_bonus(self):
        # Amplified Coils-style relic -- see Tower._relic_family_damage_
        # bonus's own docstring for why this has to be a per-class override
        # rather than a plain field effective_damage() reads directly.
        return self.relic_siphon_damage_bonus_multiplier - 1.0

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(),
            sprite_name="projectile_siphon", source=self,
        )


class BeamTower(Tower):
    """Fires rapidly at a single target and rewards staying locked onto it:
    each consecutive hit landed on the same, uninterrupted target ramps its
    damage by ramp_per_hit, capped at max_ramp_multiplier -- switching
    targets (a different enemy wandering into range, or targeting_mode
    itself picking someone new) resets the ramp back to 1.0x on the very
    next shot. Reuses the entire existing Projectile/cooldown pipeline
    unchanged -- create_projectile() is still the only override Tower.
    update() needs -- so the "beam" reads as a fast, sustained stream of
    hits (high fire_rate, near-instant projectile_speed) rather than a
    literal continuous-damage line, with no changes needed anywhere else
    (Tower.update(), Economy, rendering).

    damage/fire_rate/max_ramp_multiplier were retuned down from their
    original launch values (8 / 5.0 / 2.5) after a real playtest's results
    table showed this tower dramatically outdamaging every other tower --
    its raw DPS/gold was already the roster's highest *before* the ramp
    stacked, then peaked at roughly 2.5-9x every other tower's sustained
    figure once fully ramped. The new numbers put unramped DPS/gold (0.16)
    below BasicTower's (0.24) -- weaker until a target is committed to --
    while the fully-ramped ceiling (0.32) stays the roster's best sustained
    single-target option without dwarfing it, still rewarding the same
    stay-locked-on-one-target playstyle the mechanic is built around."""
    cost = 150
    range = 130
    damage = 6
    fire_rate = 4.0
    projectile_speed = 900.0
    sprite_name = "tower_beam"
    display_name = "Beam"

    ramp_per_hit = 0.15
    max_ramp_multiplier = 2.0
    EXTRA_STATS = (
        ("Ramp per hit", "ramp_per_hit", _format_ramp_per_hit),
        ("Max ramp", "max_ramp_multiplier", _format_buff_percent),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off this tower's own ramp mechanic instead, same spirit as every
    # other concrete tower's SPECIALIZATIONS.
    SPECIALIZATIONS = {
        "overcharge": {
            "display_name": "Overcharge",
            "description": "Ramps damage faster.",
            "stat_multipliers": {"ramp_per_hit": 1.6, "max_ramp_multiplier": 1.3},
        },
        "discharge": {
            "display_name": "Rapid Discharge",
            "description": "Fires faster and hits harder.",
            "stat_multipliers": {"damage": 1.35, "fire_rate": 1.25},
        },
    }

    def __init__(self, anchor_col, anchor_row, pixel_pos):
        super().__init__(anchor_col, anchor_row, pixel_pos)
        # Which enemy the ramp is currently built up against, and how many
        # consecutive shots have landed on it uninterrupted -- reset the
        # instant create_projectile() is asked to fire at anyone else.
        self._locked_target = None
        self._consecutive_hits = 0

    def create_projectile(self, target):
        if target is self._locked_target:
            self._consecutive_hits += 1
        else:
            self._locked_target = target
            self._consecutive_hits = 0
        # relic_beam_ramp_bonus_multiplier/relic_beam_max_ramp_bonus (a
        # Focused Optics/Sustained Barrage-style relic) scale on top of
        # whatever ramp_per_hit/max_ramp_multiplier currently are --
        # composing correctly whether or not this tower already chose the
        # "overcharge" specialization above, which permanently mutates
        # those same two instance attributes the same way leveling up
        # mutates self.damage. Inlined (not bound to locals) to match
        # BeaconTower.create_projectile()'s own inline-scaling style, and
        # to avoid shadowing self.ramp_per_hit/self.max_ramp_multiplier
        # with same-named locals.
        ramp = min(
            1.0 + self._consecutive_hits * self.ramp_per_hit * self.relic_beam_ramp_bonus_multiplier,
            self.max_ramp_multiplier + self.relic_beam_max_ramp_bonus,
        )
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage() * ramp,
            sprite_name="projectile_beam", source=self,
        )


class BeaconTower(Tower):
    """Near-zero direct damage -- its real job is marking whatever its
    always-on AoE flash touches: every enemy caught in mark_splash_radius
    takes mark_damage_multiplier more damage from every source (not just
    this tower's own hits) for mark_duration seconds (see Enemy.apply_mark/
    take_damage). Reuses the existing Projectile class verbatim -- one new
    mark_effect constructor field, exactly how FrostTower added slow_effect
    -- which also means Beacon's own tiny hits go through the full existing
    relic pipeline for free, same as every other tower. can_target_flying
    stays the class default True: a beacon flash is light-based, not a
    ground-impact blast, so it has no reason to exclude flying targets the
    way Cannon/Knockback do."""
    cost = 80
    range = 110
    damage = 1
    fire_rate = 1.0
    projectile_speed = 340.0
    mark_splash_radius = 50
    mark_damage_multiplier = 1.20
    mark_duration = 3.0
    sprite_name = "tower_beacon"
    display_name = "Beacon"
    EXTRA_STATS = (
        ("Splash radius", "mark_splash_radius", _format_px),
        ("Mark bonus", "mark_damage_multiplier", _format_buff_percent),
        ("Mark duration", "mark_duration", _format_seconds),
    )
    # Overrides the generic Power/Precision placeholders with options that
    # play off Beacon's own marking mechanic instead.
    SPECIALIZATIONS = {
        "wide_beacon": {
            "display_name": "Wide Beacon",
            "description": "Marks a much larger area.",
            "stat_multipliers": {"mark_splash_radius": 1.8},
        },
        "searing_brand": {
            "display_name": "Searing Brand",
            "description": "Hits harder, lasts longer.",
            "stat_multipliers": {"mark_damage_multiplier": 1.5, "mark_duration": 1.4},
        },
    }

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage(),
            splash_radius=self.mark_splash_radius * self.relic_beacon_splash_radius_bonus_multiplier,
            mark_effect=(
                self.mark_damage_multiplier * self.relic_beacon_mark_bonus_multiplier, self.mark_duration,
            ),
            sprite_name="projectile_beacon", source=self,
        )


class SupportTower(Tower):
    """Never attacks -- buffs every other tower within range instead (see
    Tower.reset_aura()/receive_aura(), and Game.update()'s two-pass tower
    loop that calls reset_aura() on every tower before any tower's own
    update() runs, so buff application order can't matter). damage/
    fire_rate are 0 and never scale -- LEVEL_SCALED_STATS names
    buff_damage_multiplier instead of damage, so upgrade()'s generic
    rescale-from-base loop scales the actual buff strength, not a
    permanently-zero attack stat."""
    cost = 120
    range = 90
    damage = 0
    fire_rate = 0.0
    sprite_name = "tower_support"
    display_name = "Support"
    IS_SUPPORT = True
    FIRE_SOUND = None  # never fires -- see the class docstring above

    buff_damage_multiplier = 1.25
    buff_range_multiplier = 1.15
    LEVEL_SCALED_STATS = ("buff_damage_multiplier", "range")
    EXTRA_STATS = (
        ("Damage buff", "buff_damage_multiplier", _format_buff_percent),
        ("Range buff", "buff_range_multiplier", _format_buff_percent),
    )
    # Overrides the generic Power/Precision placeholders (which multiply
    # "damage", permanently 0 here) with options that play off this
    # tower's own mechanic instead.
    SPECIALIZATIONS = {
        "amplify": {
            "display_name": "Amplify",
            "description": "Stronger damage buff.",
            "stat_multipliers": {"buff_damage_multiplier": 1.2},
        },
        "reach": {
            "display_name": "Reach",
            "description": "Buffs a wider radius.",
            "stat_multipliers": {"buff_range_multiplier": 1.15, "range": 1.2},
        },
    }

    def update(self, dt, enemies, projectiles, towers=None, enemy_index=None):
        # enemy_index accepted, unused: Game.update() calls every tower's
        # update() with the same signature regardless of type, but a
        # SupportTower never attacks, so it never calls acquire_target()
        # and has no use for the broad-phase index (see spatial_index.py).
        # relic_adjusted_range(), not effective_range() -- a Spyglass
        # Array-style relic still widens a Support tower's own reach too,
        # same as every other tower's range, since no relic in this
        # codebase singles out one tower type, but effective_range() would
        # also fold in aura_range_multiplier -- see relic_adjusted_range()'s
        # own docstring for why that specifically causes a same-frame,
        # order-dependent buff chain between Support towers.
        # relic_aura_range_bonus_multiplier/relic_aura_strength_bonus_
        # multiplier (a Resonant Field-style relic) multiply straight onto
        # the already-resolved values below -- combining two SAME-kind
        # multipliers, unlike relic_adjusted_range()'s own additive
        # combination of DIFFERENT-origin bonuses (see that method's own
        # docstring). Deliberately separate fields from tower_range_
        # multiplier/relic_range_bonus_multiplier above -- a general Range
        # relic already widens this tower's own broadcast reach via
        # relic_adjusted_range(); Resonant Field scales specifically the
        # aura math on top of that, not instead of it.
        broadcast_range = self.relic_adjusted_range() * self.relic_aura_range_bonus_multiplier
        buffed_damage_multiplier = self.buff_damage_multiplier * self.relic_aura_strength_bonus_multiplier
        buffed_range_multiplier = self.buff_range_multiplier * self.relic_aura_strength_bonus_multiplier
        for other in (towers or ()):
            if other is self:
                continue
            if self.pos.distance_to(other.pos) <= broadcast_range:
                other.receive_aura(buffed_damage_multiplier, buffed_range_multiplier)

    def create_projectile(self, target):
        raise NotImplementedError("SupportTower never fires -- see update()")


class OverloadCannonTower(Tower):
    """Charges for several seconds locked onto one target, then fires one
    massive burst hit, then goes idle and repeats -- a genuinely different
    cadence from every other tower's steady rhythm ("acquire a target,
    fire, cool down, repeat"). Tower.update()'s own template doesn't fit
    this shape at all (a fresh target is (re-)acquired every time the
    cooldown allows a shot, and the "cooldown" there is the gap AFTER a
    shot, not a charge-up BEFORE one), so this class overrides update()
    entirely rather than just create_projectile() -- the only other tower
    that does this is SupportTower, for the same reason (its own cadence
    doesn't fit the base template either).

    The charge is genuinely at risk while building, which is the whole
    point: acquire_target() is called only ONCE, the instant a fresh
    charge begins (self._charge_target locks onto that one enemy object by
    identity) -- never re-acquired on later frames while charging, unlike
    every other tower's per-shot acquire_target() call. If the locked
    target dies, reaches the goal, or leaves range at ANY point before the
    charge completes, the whole charge is lost immediately: reset to zero,
    no partial burst, no refund, no carrying the partial charge over onto
    a newly acquired target. The tower goes idle and only tries to acquire
    a brand-new target (restarting the charge from empty) on a LATER
    frame. This is deliberate, not a missing feature -- it's what actually
    creates the tower's own risk/reward identity; a tower that silently
    resumed an interrupted charge against a different target would have
    none of the risk its burst damage is priced around.

    Charge duration is 1.0 / effective_fire_rate(), resolved fresh the
    instant a new charge begins -- exactly how every other tower resolves
    its own cooldown at the moment it fires (see Tower.update()'s own
    `self.cooldown = 1.0 / self.effective_fire_rate()`). That means every
    existing fire-rate-affecting relic (quickfire_rounds, overdrive_coils,
    snipers_discipline, a Support tower's own aura, adrenaline_rush, ...)
    already makes this tower charge faster or slower for free -- no new
    plumbing needed for that interaction. burst_multiplier is flat across
    levels (not in LEVEL_SCALED_STATS) and only ever moved by
    specialization/relics, the same shape as BasicTower's own crit_chance.

    Deliberately no EXTRA_STATS row for "charge time": ui.py's stats panel
    (_draw_panel_stats) reads EXTRA_STATS off the bare tower CLASS, not an
    instance, for the unplaced build-menu preview -- a computed @property
    here would break that read. The existing generic "Fire rate" row
    already communicates cadence just fine: 1/fire_rate literally IS the
    charge time here too, just under a different display name."""
    cost = 140
    range = 140
    damage = 70
    fire_rate = 0.2  # 1/fire_rate = 5.0s charge time at level 1, before relics/specialization
    projectile_speed = 260.0
    # Flat across levels (not in LEVEL_SCALED_STATS) -- only ever moved by
    # specialization ("overcharged_payload" below) or a relic
    # (relic_overload_burst_bonus_multiplier), same shape as BasicTower's
    # own crit_chance/crit_damage_multiplier.
    burst_multiplier = 1.8
    sprite_name = "tower_overload_cannon"
    display_name = "Overload Cannon"
    FIRE_SOUND = "tower_fire_heavy"  # reuses Cannon's own heavy thump cue -- no new SOUND_MANIFEST entry needed
    EXTRA_STATS = (("Burst multiplier", "burst_multiplier", _format_buff_percent),)
    # Overrides the generic Power/Precision placeholders with options that
    # play off this tower's own charge/burst mechanic instead.
    SPECIALIZATIONS = {
        "capacitor_bank": {
            "display_name": "Capacitor Bank",
            "description": "Charges much faster.",
            "stat_multipliers": {"fire_rate": 1.5},
        },
        "overcharged_payload": {
            "display_name": "Overcharged Payload",
            "description": "Burst hits much harder.",
            "stat_multipliers": {"burst_multiplier": 1.35},
        },
    }

    def __init__(self, anchor_col, anchor_row, pixel_pos):
        super().__init__(anchor_col, anchor_row, pixel_pos)
        # None while idle (no charge underway); the locked target Enemy
        # object once a charge begins -- checked by identity, never
        # re-derived by "closest"/"first"/etc. while charging. See the
        # class docstring's own "target lock, not re-acquisition" note.
        self._charge_target = None
        # Seconds of charge accumulated so far against self._charge_target,
        # compared against self._charge_duration (resolved once, the
        # instant the current charge began) to decide when the burst fires.
        self._charge_elapsed = 0.0
        self._charge_duration = 0.0

    def _relic_family_damage_bonus(self):
        # Fusion Core-style relic -- see Tower._relic_family_damage_bonus's
        # own docstring for why this has to be a per-class override rather
        # than a plain field effective_damage() reads directly.
        return self.relic_overload_damage_bonus_multiplier - 1.0

    def create_projectile(self, target):
        return Projectile(
            pos=self.pos, target=target, speed=self.projectile_speed,
            damage=self.effective_damage() * self.burst_multiplier * self.relic_overload_burst_bonus_multiplier,
            sprite_name="projectile_overload_cannon", source=self,
        )

    def update(self, dt, enemies, projectiles, towers=None, enemy_index=None):
        """Overrides Tower.update() entirely -- see the class docstring for
        why this tower's charge/burst cadence can't reuse that method's own
        cooldown-then-fire template. Mirrors its overall shape (advance a
        timer, fire once ready, tag the resulting projectile with every
        relic_* field) but replaces "cooldown counts down to a shot" with
        "charge counts up to a burst," and adds the interrupted-charge
        check the base template has no equivalent of at all."""
        if self._charge_target is None:
            # Idle: try to acquire a fresh target and begin a new charge.
            # acquire_target() is called here EXACTLY ONCE per charge --
            # never again below while that same charge is building.
            target = self.acquire_target(enemies, enemy_index)
            if target is None:
                return
            self._charge_target = target
            self._charge_elapsed = 0.0
            # Resolved fresh, right now -- mirrors Tower.update()'s own
            # `self.cooldown = 1.0 / self.effective_fire_rate()`, resolved
            # at the moment a shot actually fires. See the class docstring.
            self._charge_duration = 1.0 / self.effective_fire_rate()
            return

        target = self._charge_target
        # Interrupted charge = fully lost -- no partial burst, no refund,
        # no carrying the partial charge onto a different target. Goes
        # idle this frame; a brand-new charge (even against this same
        # enemy, if it's still around and in range) only begins on a LATER
        # frame, via the branch above -- never later in this same call.
        if target.is_dead or target.reached_goal or not self.in_range(target):
            self._charge_target = None
            self._charge_elapsed = 0.0
            self._charge_duration = 0.0
            return

        self._charge_elapsed += dt
        if self._charge_elapsed < self._charge_duration:
            return  # still charging

        # Charge complete -- fire the burst, then go idle (a fresh charge,
        # even against this same target, only begins on a later frame).
        self.shots_fired += 1
        self.fired_this_frame = True
        projectile = self.create_projectile(target)
        # KNOWN DUPLICATE -- read before editing: this is a deliberate,
        # verbatim copy of the identical relic-tagging block in the base
        # Tower.update() (see that method's own matching comment). This
        # tower can't share it via a common helper without also reworking
        # every other update() override (SupportTower's included) to fit a
        # shared shape, out of scope for this change. If you add a new
        # relic_* line to that block, you MUST add the identical line here
        # too, or Overload Cannon will silently not support that relic.
        projectile.relic_poison_chance = self.relic_poison_chance
        projectile.relic_poison_effect = self.relic_poison_effect
        projectile.relic_crit_chance = self.relic_crit_chance
        projectile.relic_crit_damage_multiplier = self.relic_crit_damage_multiplier
        projectile.relic_chain_chance = self.relic_chain_chance
        projectile.relic_chain_effect = self.relic_chain_effect
        projectile.relic_damage_vs_slowed_multiplier = self.relic_damage_vs_slowed_multiplier
        projectile.relic_slow_chance = self.relic_slow_chance
        projectile.relic_slow_effect = self.relic_slow_effect
        projectile.relic_poison_ignores_shield = self.relic_poison_ignores_shield
        projectile.relic_damage_vs_early_route_multiplier = self.relic_damage_vs_early_route_multiplier
        projectile.relic_damage_vs_high_hp_multiplier = self.relic_damage_vs_high_hp_multiplier
        projectile.relic_overkill_carry_fraction = self.relic_overkill_carry_fraction
        projectile.relic_knockback_chance = self.relic_knockback_chance
        projectile.relic_knockback_effect = self.relic_knockback_effect
        projectile.relic_mark_chance = self.relic_mark_chance
        projectile.relic_mark_effect = self.relic_mark_effect
        projectile.relic_damage_vs_flying_multiplier = self.relic_damage_vs_flying_multiplier
        projectile.relic_damage_vs_shielded_multiplier = self.relic_damage_vs_shielded_multiplier
        projectile.relic_damage_vs_healer_multiplier = self.relic_damage_vs_healer_multiplier
        projectile.relic_damage_vs_fast_multiplier = self.relic_damage_vs_fast_multiplier
        projectile.relic_damage_vs_boss_multiplier = self.relic_damage_vs_boss_multiplier
        projectile.relic_damage_vs_marked_and_slowed_multiplier = self.relic_damage_vs_marked_and_slowed_multiplier
        projectile.relic_damage_vs_marked_and_poisoned_multiplier = self.relic_damage_vs_marked_and_poisoned_multiplier
        projectile.relic_damage_vs_slowed_and_poisoned_multiplier = self.relic_damage_vs_slowed_and_poisoned_multiplier
        projectile.relic_damage_vs_marked_and_slowed_and_poisoned_multiplier = (
            self.relic_damage_vs_marked_and_slowed_and_poisoned_multiplier
        )
        projectiles.append(projectile)
        self._charge_target = None
        self._charge_elapsed = 0.0
        self._charge_duration = 0.0


TOWER_TYPES = {
    "basic": BasicTower,
    "cannon": CannonTower,
    "frost": FrostTower,
    "knockback": KnockbackTower,
    "lightning": LightningTower,
    "sniper": SniperTower,
    "poison": PoisonTower,
    "siphon": SiphonTower,
    "support": SupportTower,
    "beam": BeamTower,
    "beacon": BeaconTower,
    "overload_cannon": OverloadCannonTower,
}
