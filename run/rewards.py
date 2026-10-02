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

from run import card_pool, modules, potions, relics
from run.run_state import RunState
from support.rng_sampling import sample_up_to

TOWER_REWARD_COUNT = 3
# An act boss's reward (every act but the last -- see run_map.ACT_COUNT):
# pick one of this many relics instead of the usual tower cards, Slay the
# Spire's boss-relic choice.
BOSS_RELIC_CHOICES = 3
# Slay the Spire's upgraded card rewards: each new tower card has this
# chance per point of run depth (RunState.depth) to come pre-forged, capped
# at FORGED_CARD_MAX_CHANCE -- so deeper fights offer better cards.
FORGED_CARD_CHANCE_PER_DEPTH = 0.03
FORGED_CARD_MAX_CHANCE = 0.5


@dataclass(frozen=True)
class CombatReward:
    tower_choices: tuple[str, ...]
    # A guaranteed relic -- Elite floors only, None otherwise (or once
    # every relic is already held, relic_offer's own exhausted case).
    relic: str | None = None
    potion: str | None = None
    # An act boss's pick-one relic choice -- empty for every other node.
    boss_relic_choices: tuple[str, ...] = ()
    # Which of tower_choices come pre-forged (taking one adds it already
    # forged -- see Game._take_reward_card).
    forged_tower_choices: tuple[str, ...] = ()
    # Forge cards for towers the run already holds, filling the tower row
    # once there aren't enough new towers left to offer. Part of the same
    # pick-one row as tower_choices.
    forge_choices: tuple[str, ...] = ()
    # An Elite's module offer (run/modules.py): (module key, tower type), or None.
    module: tuple[str, str] | None = None

    @property
    def is_empty(self) -> bool:
        return (not self.tower_choices and self.relic is None and self.potion is None
                and not self.boss_relic_choices and not self.forge_choices and self.module is None)


def build_combat_reward(
    rng: random.Random, run: RunState, is_elite: bool, meta_progression_path: str | None = None,
    tower_count: int = TOWER_REWARD_COUNT, is_boss: bool = False, damaging_types: frozenset[str] = frozenset(),
) -> CombatReward:
    """This floor clear's reward -- tower choices first, then the Elite
    relic, both drawn from the same `rng` in that fixed order so a given
    (seed, node) always rewards the identical cards."""
    if is_boss:
        # A boss reward is its relic choice plus a guaranteed potion -- no
        # tower cards, keeping the screen to one decision that matters.
        boss_relics = relics.boss_relic_offer(rng, run, BOSS_RELIC_CHOICES, meta_progression_path=meta_progression_path)
        return CombatReward((), potion=potions.random_potion(rng), boss_relic_choices=tuple(boss_relics))
    tower_choices = card_pool.draft_offer(
        rng, run, count=tower_count, meta_progression_path=meta_progression_path,
    )
    relic = None
    if is_elite:
        picks = relics.relic_offer(rng, run, count=1, meta_progression_path=meta_progression_path)
        relic = picks[0] if picks else None
    potion = None
    guaranteed = any(relics.RELICS[key].guaranteed_potion_drop for key in run.relics)
    # rng.random() is still drawn when guaranteed, so holding the relic
    # never shifts which potion the same seed rolls.
    if is_elite or rng.random() < potions.COMBAT_POTION_DROP_CHANCE or guaranteed:
        potion = potions.random_potion(rng)
    # Drawn last, so every card/relic/potion above stays what the same seed
    # always offered.
    depth = run.depth if run.current_node_id is not None else 0
    forged_chance = min(FORGED_CARD_MAX_CHANCE, FORGED_CARD_CHANCE_PER_DEPTH * depth)
    forged_tower_choices = tuple(name for name in tower_choices if rng.random() < forged_chance)
    forgeable = [name for name in run.unlocked_towers if name not in run.forged_towers]
    forge_choices = sample_up_to(rng, forgeable, tower_count - len(tower_choices)) if tower_count > 0 else []
    # Drawn last, so every older pick above stays what the same seed offered.
    module = modules.module_offer(rng, run, damaging_types) if is_elite else None
    if module is not None and not guaranteed:
        # An Elite's module takes the place of its potion, keeping the
        # screen to five cards (only a Brewmaster's Kit-style guarantee
        # makes it six -- ui.build_draft_choice_rects' narrow layout).
        potion = None
    return CombatReward(
        tuple(tower_choices), relic, potion,
        forged_tower_choices=forged_tower_choices, forge_choices=tuple(forge_choices), module=module,
    )
