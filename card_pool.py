"""Which TOWER_TYPES entries can be drafted into a run's unlocked tower
pool ("cards").

Milestone 3 narrows draft_offer's default `unlocked_pool` from "every
TOWER_TYPES entry" to whatever meta_progression.py says this player has
unlocked account-wide.
"""

from tower import TOWER_TYPES

# What every run starts with, before any drafting. Chosen from the towers
# with no unique mechanic to learn (basic/sniper) or the simplest ones to
# learn (cannon's splash, frost's slow) -- sniper is left out since its
# glass-cannon playstyle rewards already knowing the game.
STARTER_TOWERS = ("basic", "cannon", "frost")

DEFAULT_DRAFT_COUNT = 3


def draft_offer(rng, run, count=DEFAULT_DRAFT_COUNT, unlocked_pool=None):
    """`count` tower names offered as this draft's choices, drawn from
    `unlocked_pool` (default: every TOWER_TYPES name) minus whatever
    `run.unlocked_towers` already has. Returns fewer than `count` once the
    pool is exhausted rather than raising -- a run that's drafted every
    available tower just stops seeing new choices."""
    pool = unlocked_pool if unlocked_pool is not None else TOWER_TYPES.keys()
    candidates = [name for name in pool if name not in run.unlocked_towers]
    return rng.sample(candidates, min(count, len(candidates)))
