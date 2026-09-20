"""Which TOWER_TYPES entries can be drafted into a run's unlocked tower
pool ("cards").
"""

import random

import meta_progression
from rng_sampling import sample_up_to
from run_state import RunState
from tower import TOWER_TYPES

# What every run starts with, before any drafting. Chosen from the towers
# with no unique mechanic to learn (basic/sniper) or the simplest ones to
# learn (cannon's splash, frost's slow) -- sniper is left out since its
# glass-cannon playstyle rewards already knowing the game.
STARTER_TOWERS = ("basic", "cannon", "frost")

DEFAULT_DRAFT_COUNT = 3


def _default_unlocked_pool(meta_progression_path: str) -> list[str]:
    """STARTER_TOWERS plus whatever meta_progression.py says this player
    has unlocked account-wide, in TOWER_TYPES' own stable registry order
    (not meta_progression.unlocked_tower_pool()'s raw set, whose iteration
    order isn't guaranteed stable across process launches) -- draft_offer
    below feeds this straight into rng.sample(), and sample's own result
    depends on the order of what it's sampling from, so an unstable input
    order would silently break "the same seed offers the same cards"
    across two separate game launches, not just within one."""
    unlocked = set(STARTER_TOWERS) | meta_progression.unlocked_tower_pool(meta_progression_path)
    return [name for name in TOWER_TYPES if name in unlocked]


def draft_offer(
    rng: random.Random, run: RunState, count: int = DEFAULT_DRAFT_COUNT,
    unlocked_pool: list[str] | None = None, meta_progression_path: str | None = None,
) -> list[str]:
    """`count` tower names offered as this draft's choices, drawn from
    `unlocked_pool` (default: _default_unlocked_pool(), above, reading
    `meta_progression_path` -- same injectable-path convention every
    on-disk-state module in this codebase uses, so a test never has to
    touch the real repo-root meta_progression.json) minus whatever
    `run.unlocked_towers` already has. Returns fewer than `count` once the
    pool is exhausted rather than raising -- a run that's drafted every
    available tower just stops seeing new choices (see
    rng_sampling.sample_up_to)."""
    if unlocked_pool is None:
        unlocked_pool = _default_unlocked_pool(meta_progression_path or meta_progression.META_PROGRESSION_PATH)
    candidates = [name for name in unlocked_pool if name not in run.unlocked_towers]
    return sample_up_to(rng, candidates, count)
