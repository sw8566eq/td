"""Run-wide passive modifier cards ("relics") -- a second, genuinely
optional card type alongside tower cards (see card_pool.py), offered via
the exact same draft screen (see Game._enter_draft/_is_relic_floor) but
composed into a run's floor-load the same way difficulty.DIFFICULTY_MODES/
run_escalation.FloorEscalation already are: an extra factor on top of
what's already there, never replacing it.

Unlike a tower card, a relic isn't gated by meta_progression.py -- every
registered relic is always eligible to be offered in any run. There are
few enough relics, and few enough relic-draft floors per run, that
account-wide unlock-gating would add a second progression system for a
card type explicitly framed as secondary/optional (see the plan's design
resolution), not a proportional amount of extra depth.
"""

from dataclasses import dataclass


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
    # war_chest/sturdy_gate are deliberately one-time, run-start bonuses,
    # not per-floor ones -- starting_gold_multiplier/starting_lives_bonus
    # only ever affect floor 0's Economy construction (see game.py's
    # _load_level_object); every later floor carries its own gold/lives
    # forward instead of reconstructing them from level.starting_gold/
    # starting_lives, so there's no "starting" value left for a percentage/
    # flat bonus to apply to again. Their description text says so
    # honestly, rather than promising a recurring effect a carried-forward
    # economy has no natural way to keep granting.
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
    than `count` once the pool is exhausted rather than raising."""
    candidates = [key for key in RELICS if key not in run.relics]
    return rng.sample(candidates, min(count, len(candidates)))


@dataclass(frozen=True)
class RelicModifiers:
    """Two of these fields recur every floor; two apply once, at floor 0,
    and never again -- not a distinction this type enforces on its own, so
    a future field needs to be added with the same care taken here:

    - gold_per_floor_bonus recurs: Game._load_floor adds it to
      self.economy.gold on every floor load, explicitly, since a floor's
      economy is either freshly constructed (floor 0) or carried forward
      from the previous floor (floor 1+) either way.
    - enemy_gold_multiplier recurs implicitly: it's threaded into
      WaveManager's own constructor kwargs in _load_level_object, and
      WaveManager itself is always rebuilt fresh every floor, so this
      needs no special per-floor handling to keep applying.
    - starting_gold_multiplier/starting_lives_bonus do NOT recur: both are
      folded into _load_level_object's Economy(...) construction, which
      only actually determines a floor's starting gold/lives at floor 0 --
      every later floor's Economy gets overwritten with the run's own
      carried-forward gold/lives instead (see _load_floor), so a
      percentage/flat bonus applied only at construction time has nothing
      left to act on past floor 0. Their own RELICS description text says
      "for this run," not "on every floor," for exactly this reason."""
    gold_per_floor_bonus: int = 0
    starting_gold_multiplier: float = 1.0
    starting_lives_bonus: int = 0
    enemy_gold_multiplier: float = 1.0


def compose_relic_modifiers(relic_keys):
    """Aggregate every relic in `relic_keys` into one RelicModifiers bundle
    -- flat bonuses add, multipliers multiply, so composing several relics
    is order-independent regardless of which was drafted first."""
    gold_per_floor_bonus = 0
    starting_gold_multiplier = 1.0
    starting_lives_bonus = 0
    enemy_gold_multiplier = 1.0
    for key in relic_keys:
        relic = RELICS[key]
        gold_per_floor_bonus += relic.gold_per_floor_bonus
        starting_gold_multiplier *= relic.starting_gold_multiplier
        starting_lives_bonus += relic.starting_lives_bonus
        enemy_gold_multiplier *= relic.enemy_gold_multiplier
    return RelicModifiers(gold_per_floor_bonus, starting_gold_multiplier, starting_lives_bonus, enemy_gold_multiplier)
