"""Run-wide passive modifier cards ("relics") -- a second, genuinely
optional card type alongside tower cards (see card_pool.py), offered via
the exact same draft screen (see Game._enter_draft/_is_relic_floor). A
per-floor relic's modifiers (gold_per_floor_bonus/enemy_gold_multiplier,
see RelicModifiers) are composed into a run's floor-load the same way
difficulty.DIFFICULTY_MODES/run_escalation.FloorEscalation already are: an
extra factor on top of what's already there, never replacing it. A
one-time relic's (war_chest/sturdy_gate) bonus applies once instead,
directly, the instant the card is drafted (Game._apply_one_time_relic_bonus)
-- see RelicModifiers' own docstring for why a one-time bonus can't be
folded into that same per-floor composition.

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
        "war_chest", "War Chest", "+25% extra starting gold for this run.",
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

    - gold_per_floor_bonus: Game._load_floor adds it to self.economy.gold
      on every floor load, explicitly, since a floor's economy is either
      freshly constructed (floor 0) or carried forward from the previous
      floor (floor 1+) either way.
    - enemy_gold_multiplier: threaded into WaveManager's own constructor
      kwargs in _load_level_object, and WaveManager itself is always
      rebuilt fresh every floor, so this needs no special per-floor
      handling to keep applying.

    A Relic's own starting_gold_multiplier/starting_lives_bonus (a
    genuinely one-time bonus, not a per-floor one -- see RELICS' own
    comment on war_chest/sturdy_gate) is deliberately NOT one of these
    fields: this type only ever gets composed once, from whatever relics a
    run holds *at floor-load time*, and reused across every floor of that
    load -- but a one-time bonus has to fire exactly once, the instant the
    card is drafted (Game._apply_one_time_relic_bonus), never re-applied on
    a later floor's own load. Folding it in here would either double-apply
    it on every subsequent floor or require this type to start tracking
    which relics it's already "spent," neither of which this simple
    aggregate-and-reuse shape is built for."""
    gold_per_floor_bonus: int = 0
    enemy_gold_multiplier: float = 1.0


def compose_relic_modifiers(relic_keys):
    """Aggregate every relic in `relic_keys` into one RelicModifiers bundle
    -- flat bonuses add, multipliers multiply, so composing several relics
    is order-independent regardless of which was drafted first."""
    gold_per_floor_bonus = 0
    enemy_gold_multiplier = 1.0
    for key in relic_keys:
        relic = RELICS[key]
        gold_per_floor_bonus += relic.gold_per_floor_bonus
        enemy_gold_multiplier *= relic.enemy_gold_multiplier
    return RelicModifiers(gold_per_floor_bonus, enemy_gold_multiplier)
