"""Shared rng-sampling mechanics behind every "offer up to N choices from
a pool, excluding what's already held" draft in this codebase --
card_pool.draft_offer() (tower cards), relics.relic_offer() (relic cards),
and run_map.generate_run_map() (a combat/elite node's own level id, drawn
from whichever row-appropriate tier -- see that module's own
_level_pool_for_row) all need "sample up to `count` items without
replacement, fewer once the pool doesn't have that many, never raise" --
exactly random.Random.sample()'s own contract once `count` is clamped to
the pool size first, but each of the three independently wrote
`rng.sample(candidates, min(count, len(candidates)))` before this.

Fully typed (via a TypeVar, not just annotated with bare `list`) even
though this module isn't itself one of relics.py/run_map.py/events.py/
shop.py's strict mypy overrides (see pyproject.toml) -- every one of
those calls straight into this function, so leaving it untyped would
otherwise make each of their own calls resolve to `Any` regardless of how
carefully the caller itself is annotated.
"""

import random


def sample_up_to[T](rng: random.Random, candidates: list[T], count: int) -> list[T]:
    """`count` items sampled without replacement from `candidates` (order
    as `rng.sample()` itself returns -- callers that need a specific
    order still sort the result themselves), or every item in `candidates`
    if there are fewer than `count` of them -- never raises the ValueError
    random.Random.sample() itself would for count > len(candidates)."""
    return rng.sample(candidates, min(count, len(candidates)))
