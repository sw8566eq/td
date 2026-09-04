"""A record of every roguelike run's outcome, kept per seed so a replayed
seed (Daily Run's own repeatable date-seed -- see daily_challenge.
todays_seed/Game._start_daily_challenge) keeps its best result rather than
being overwritten by a worse retry. A regular run's seed is random
(Game.start_new_run(seed=None)), so in practice this just grows one entry
per run played; the per-seed max is what makes it also correct for a
seed that gets replayed on purpose -- Daily Run needs no special handling
here at all, it's just another seed.
"""

import json

from json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
RUN_HISTORY_PATH = module_relative_path(__file__, "run_history.json")


def load_run_history(path=RUN_HISTORY_PATH):
    """{seed: best_floors_cleared} for every seed played so far, or {} if
    the file doesn't exist yet or fails to parse -- same defensive
    fallback spirit as progress.load_progress()."""
    return load_json_with_fallback(
        path,
        lambda data: {int(seed): floors for seed, floors in data.get("best_floors_cleared", {}).items()},
        dict,
    )


def save_run_history(best_floors_cleared, path=RUN_HISTORY_PATH):
    # JSON object keys must be strings -- seeds are ints everywhere else
    # (see load_run_history's own conversion back).
    data = {
        "schema_version": SCHEMA_VERSION,
        "best_floors_cleared": {str(k): v for k, v in best_floors_cleared.items()},
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def record_run_result(seed, floors_cleared, path=RUN_HISTORY_PATH):
    """Record a run's outcome for `seed`, keeping the best (highest)
    floors_cleared seen across repeat attempts on that seed rather than
    overwriting with a worse result. Returns the updated {seed:
    best_floors_cleared} mapping, the same shape load_run_history()
    returns."""
    best_floors_cleared = load_run_history(path)
    best_floors_cleared[seed] = max(floors_cleared, best_floors_cleared.get(seed, 0))
    save_run_history(best_floors_cleared, path)
    return best_floors_cleared
