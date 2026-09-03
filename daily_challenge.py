"""Daily Challenge: a seeded, deterministic Endless run everyone can compare
scores on.

Reuses WaveManager's existing injectable `rng` (waves.py) -- pathing.
sample_route()'s branch choice at a fork is the *only* source of
non-determinism in a run (enemy stat/gold scaling and Endless mode's own
wave-growth formula are both pure deterministic arithmetic) -- rather than
building a new challenge-specific game mode: seeding that rng with today's
date makes every enemy's routing choice at a fork identical for every player
on the same day, and Endless already makes the wave composition identical
regardless of rng. Routing is the one variable a shared seed needs to pin
down, which is also why this rotates among the three *multi-lane* levels
(the only ones with a fork to route at -- a single-spawn corridor would make
the seed meaningless) rather than always using the same level.

Mirrors progress.py's own conventions closely: a single JSON file, defensive
handling of a missing/corrupt file (falls back to "nothing recorded yet"
rather than crashing), and a record_result() that loads the persisted state
fresh, mutates, saves, and returns what changed -- same load-mutate-save-
return shape as progress.mark_level_cleared()/achievements.bump(), so it's
always safe to call from wherever the relevant event actually happens.
"""

import json
from datetime import datetime, timezone

from json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
DAILY_CHALLENGE_PATH = module_relative_path(__file__, "daily_challenge.json")

# The only levels with a branch point for a seed's routing choice to
# actually affect -- see module docstring.
MULTI_LANE_LEVEL_IDS = (7, 8, 9, 11)


def todays_seed(today=None):
    """An int seed derived from a UTC calendar date -- the same day always
    yields the same seed for every player regardless of timezone. `today`
    is overridable (a `datetime.date`) so tests/an explicit "play a specific
    day's challenge" flow don't depend on the real wall-clock date."""
    today = today or datetime.now(timezone.utc).date()
    return int(today.strftime("%Y%m%d"))


def level_id_for_seed(seed):
    """Which of MULTI_LANE_LEVEL_IDS today's challenge uses -- deterministic
    from the seed itself, so "today's level" needs no separate storage."""
    return MULTI_LANE_LEVEL_IDS[seed % len(MULTI_LANE_LEVEL_IDS)]


def load_daily_challenge(path=DAILY_CHALLENGE_PATH):
    """{seed: best_waves_survived} for every seed played so far, or {} if
    the file doesn't exist yet or fails to parse -- same defensive fallback
    spirit as progress.load_progress()."""
    return load_json_with_fallback(
        path,
        lambda data: {int(seed): waves for seed, waves in data.get("best_waves", {}).items()},
        dict,
    )


def save_daily_challenge(best_waves, path=DAILY_CHALLENGE_PATH):
    # JSON object keys must be strings -- seeds are ints everywhere else
    # (see load_daily_challenge's own conversion back).
    data = {"schema_version": SCHEMA_VERSION, "best_waves": {str(k): v for k, v in best_waves.items()}}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def record_result(seed, waves_survived, path=DAILY_CHALLENGE_PATH):
    """Record a Daily Challenge run's outcome for `seed`, keeping the best
    (highest) waves_survived seen across repeat attempts rather than
    overwriting with a worse result. Returns the updated {seed:
    best_waves_survived} mapping, the same shape load_daily_challenge()
    returns."""
    best_waves = load_daily_challenge(path)
    best_waves[seed] = max(waves_survived, best_waves.get(seed, 0))
    save_daily_challenge(best_waves, path)
    return best_waves
