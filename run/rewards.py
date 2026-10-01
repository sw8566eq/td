"""Post-combat rewards -- the Slay-the-Spire "card reward" screen a run
shows after every cleared Combat/Elite floor (GameState.REWARD, entered
from FLOOR_CLEARED; see Game._enter_reward_screen).

Every reward is free and optional: pick at most one of `tower_choices`
(a new tower card for the run's build menu) or skip them all, and -- on
an Elite floor only -- also take one guaranteed relic, the same "elites
drop relics" trade Slay the Spire makes for its own harder fights. The
Shop (shop.py) is still where shop currency buys extra cards; this is
the steady, every-fight trickle of new options a deckbuilder run grows
from.

Built from the same draft helpers the Shop uses (card_pool.draft_offer/
relics.relic_offer), so every "exclude what's already held, fewer once
exhausted, same seed -> same offer" rule they already guarantee carries
over unchanged.

A reward can also carry one potion (potions.py) -- always on an Elite
floor, potions.COMBAT_POTION_DROP_CHANCE of the time otherwise -- rolled
last, after the tower/relic draws, so adding it never changed which cards
an existing seed offers.
"""

import random
from dataclasses import dataclass

from run import card_pool, potions, relics
from run.run_state import RunState

TOWER_REWARD_COUNT = 3


@dataclass(frozen=True)
class CombatReward:
    tower_choices: tuple[str, ...]
    # A guaranteed relic -- Elite floors only, None otherwise (or once
    # every relic is already held, relic_offer's own exhausted case).
    relic: str | None = None
    potion: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.tower_choices and self.relic is None and self.potion is None


def build_combat_reward(
    rng: random.Random, run: RunState, is_elite: bool, meta_progression_path: str | None = None,
) -> CombatReward:
    """This floor clear's reward -- tower choices first, then the Elite
    relic, both drawn from the same `rng` in that fixed order so a given
    (seed, node) always rewards the identical cards."""
    tower_choices = card_pool.draft_offer(
        rng, run, count=TOWER_REWARD_COUNT, meta_progression_path=meta_progression_path,
    )
    relic = None
    if is_elite:
        picks = relics.relic_offer(rng, run, count=1, meta_progression_path=meta_progression_path)
        relic = picks[0] if picks else None
    potion = None
    if is_elite or rng.random() < potions.COMBAT_POTION_DROP_CHANCE:
        potion = potions.random_potion(rng)
    return CombatReward(tuple(tower_choices), relic, potion)
