"""Run-wide passive modifier cards ("relics") -- a second, genuinely
optional card type alongside tower cards (see card_pool.py), offered via
the exact same draft screen (see Game._enter_draft/_is_relic_floor). Every
relic's numeric effect is one of three shapes:

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

Unlike a tower card, a relic isn't gated by meta_progression.py -- every
registered relic is always eligible to be offered in any run. There are
few enough relics, and few enough relic-draft floors per run, that
account-wide unlock-gating would add a second progression system for a
card type explicitly framed as secondary/optional (see the plan's design
resolution), not a proportional amount of extra depth.
"""

from dataclasses import dataclass

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


RELICS = {
    "prospectors_charm": Relic(
        "prospectors_charm", "Prospector's Charm", "+20 gold at the start of every floor.",
        gold_per_floor_bonus=20,
    ),
    # war_chest/sturdy_gate are deliberately one-time bonuses, not per-floor
    # ones -- their description text says so honestly, rather than
    # promising a recurring effect a carried-forward economy has no natural
    # way to keep granting. Applied directly onto the run's carried gold/
    # lives the instant the card is drafted (Game._apply_one_time_relic_
    # bonus), not folded into Economy construction the way every other
    # relic modifier is -- no relic can ever be drafted before floor 2 (see
    # Game._is_relic_floor), by which point floor 0's Economy construction
    # (the only place a starting_gold_multiplier/starting_lives_bonus could
    # otherwise act) is long gone, so that route would make these two
    # permanently inert regardless of when they're picked.
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
}

DEFAULT_RELIC_OFFER_COUNT = 3

# Every RELIC_FLOOR_INTERVAL-th floor transition offers relics instead of a
# tower (see Game._is_relic_floor) -- named here, next to RELICS/DEFAULT_
# RELIC_OFFER_COUNT, rather than left as a bare literal at its one call
# site, matching how every other balance number in this milestone
# (run_escalation.py's growth rates, meta_progression.py's thresholds) gets
# named and commented.
RELIC_FLOOR_INTERVAL = 2


def relic_offer(rng, run, count=DEFAULT_RELIC_OFFER_COUNT):
    """`count` relic keys offered as a relic draft's choices, drawn from
    RELICS minus whatever `run.relics` already has -- same shape as
    card_pool.draft_offer, just for the other card type. Returns fewer
    than `count` once the pool is exhausted rather than raising (see
    rng_sampling.sample_up_to)."""
    candidates = [key for key in RELICS if key not in run.relics]
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

    Two more fields don't fit the "recurs every floor, for as long as
    it's held" framing above either, and are resolved elsewhere entirely:
    misers_coffer's gold_per_floor_bonus_while_unspent folds into
    gold_per_floor_bonus above, but only conditionally (see compose_relic_
    modifiers' has_spent_gold parameter and Game._spend_gold) --
    once revoked, it stays revoked for the rest of the run, unlike every
    other field here which stays constant for as long as the relic is
    held. guardians_reprieve has no field here at all (see RELICS' own
    comment on it) -- checked directly against run.relics in
    Game._lose_a_life instead."""
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


def compose_relic_modifiers(relic_keys, floor_index=0, has_spent_gold=False):
    """Aggregate every relic in `relic_keys` into one RelicModifiers bundle
    -- flat bonuses add, multipliers multiply, so composing several relics
    is order-independent regardless of which was drafted first.

    `floor_index` and `has_spent_gold` both default so every pre-existing
    call site (and every existing test) is unaffected -- they only matter
    to veterans_momentum's escalating bonus and misers_coffer's
    conditionally-revoked one, respectively; see relics.py's own module
    docstring for both.

    poison_effect and crit_damage_multiplier are the two fields that aren't
    a plain sum/multiply, and both are gated on the relic actually
    granting the chance that uses them (poison_chance > 0 / crit_chance >
    0 respectively) -- a relic with a nonzero damage/multiplier field but
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
    )
