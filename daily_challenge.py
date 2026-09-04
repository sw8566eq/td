"""Daily Run's own seed: a UTC-date-derived int, so every player gets the
exact same roguelike run (floor_sequence, draft offers -- see run_floors.py/
card_pool.py) on a given day, and their own skill/picks are the only
variable. Everything else Daily Run needs is general run machinery, not
anything specific to "daily" -- see Game.start_new_run's own docstring for
why a Daily Run needs nothing beyond this one seed.
"""

from datetime import datetime, timezone


def todays_seed(today=None):
    """An int seed derived from a UTC calendar date -- the same day always
    yields the same seed for every player regardless of timezone. `today`
    is overridable (a `datetime.date`) so tests/an explicit "play a specific
    day's challenge" flow don't depend on the real wall-clock date."""
    today = today or datetime.now(timezone.utc).date()
    return int(today.strftime("%Y%m%d"))
