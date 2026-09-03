"""Sampling which built-in levels make up one roguelike run's floor
sequence.

Deliberately not a shuffle: LEVELS' own ids already read as an authored
difficulty/complexity ramp (single-lane corridors 1-5/10 before multi-lane
merge/branch levels 6-9/11 -- see levels.py), so sampling *without*
reordering is what makes a run's floor sequence actually escalate, rather
than a random shuffle occasionally front-loading a hard level onto floor 1.
"""

from levels import LEVELS

DEFAULT_FLOOR_COUNT = 6


def sample_floor_sequence(rng, count=DEFAULT_FLOOR_COUNT, level_pool=LEVELS):
    """An ascending tuple of `count` level ids sampled without replacement
    from `level_pool` (default: every built-in LEVELS id). `count` is
    clamped to the pool size so a run never asks for more floors than exist
    -- callers that want a full-campaign run can just pass a large count."""
    pool = sorted(level_pool.keys())
    count = min(count, len(pool))
    return tuple(sorted(rng.sample(pool, count)))
