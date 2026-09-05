"""Sampling which built-in levels make up one roguelike run's floor
sequence.

Deliberately not a shuffle: LEVELS' own ids already read as an authored
difficulty/complexity ramp (single-lane corridors 1-5/10 before multi-lane
merge/branch levels 6-9/11 -- see levels.py), so sampling *without*
reordering is what makes a run's floor sequence actually escalate, rather
than a random shuffle occasionally front-loading a hard level onto floor 1.
"""

from levels import LEVELS
from rng_sampling import sample_up_to

DEFAULT_FLOOR_COUNT = 6


def sample_floor_sequence(rng, count=DEFAULT_FLOOR_COUNT, level_pool=LEVELS):
    """An ascending tuple of `count` level ids sampled without replacement
    from `level_pool` (default: every built-in LEVELS id). `count` is
    clamped to the pool size (see rng_sampling.sample_up_to) so a run
    never asks for more floors than exist -- callers that want a
    full-campaign run can just pass a large count. Sorted after sampling,
    unlike card_pool.draft_offer/relics.relic_offer's own unsorted
    choices -- a floor sequence's whole point is ascending order (see this
    module's own docstring), while a draft's choices are presented in
    whatever order rng.sample() itself returned them."""
    pool = sorted(level_pool.keys())
    return tuple(sorted(sample_up_to(rng, pool, count)))
