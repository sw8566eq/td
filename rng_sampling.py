"""Shared rng-sampling mechanics behind every "offer up to N choices from
a pool, excluding what's already held" draft in this codebase --
card_pool.draft_offer() (tower cards), relics.relic_offer() (relic cards),
and run_floors.sample_floor_sequence() (a run's own floor sequence) all
need "sample up to `count` items without replacement, fewer once the pool
doesn't have that many, never raise" -- exactly random.Random.sample()'s
own contract once `count` is clamped to the pool size first, but each of
the three independently wrote `rng.sample(candidates, min(count,
len(candidates)))` before this.
"""


def sample_up_to(rng, candidates, count):
    """`count` items sampled without replacement from `candidates` (order
    as `rng.sample()` itself returns -- callers that need a specific
    order, e.g. run_floors.sample_floor_sequence()'s ascending floors,
    still sort the result themselves), or every item in `candidates` if
    there are fewer than `count` of them -- never raises the ValueError
    random.Random.sample() itself would for count > len(candidates)."""
    return rng.sample(candidates, min(count, len(candidates)))
