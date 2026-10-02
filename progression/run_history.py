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
from typing import Any

from persistence.json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
RUN_HISTORY_PATH = module_relative_path(__file__, "run_history.json")
# How many individual runs' details (the "runs" list -- see
# record_run_result) the file keeps, newest first; best_floors_cleared
# itself is never trimmed.
MAX_RUN_RECORDS = 100

# One run's details: seed, floors_cleared, plus commander/ascension/act/
# daily. Additive key in the same file and schema version -- an older
# file simply has no "runs" list yet.
RunRecord = dict[str, Any]


def load_run_history(path: str = RUN_HISTORY_PATH) -> dict[int, int]:
    """{seed: best_floors_cleared} for every seed played so far, or {} if
    the file doesn't exist yet or fails to parse -- same defensive
    fallback spirit as progress.load_progress()."""
    return load_json_with_fallback(
        path,
        lambda data: {int(seed): floors for seed, floors in data.get("best_floors_cleared", {}).items()},
        dict,
    )


def load_run_records(path: str = RUN_HISTORY_PATH) -> list[RunRecord]:
    """Every recorded run's details (see record_run_result's `details`),
    most recent first -- [] for a file written before this existed, or a
    missing/corrupt one."""
    return load_json_with_fallback(path, lambda data: list(data.get("runs", [])), list)


def save_run_history(
    best_floors_cleared: dict[int, int], path: str = RUN_HISTORY_PATH, records: list[RunRecord] | None = None,
) -> None:
    """`records` None keeps whatever runs list the file already has, so a
    caller that only knows about best_floors_cleared never wipes it."""
    if records is None:
        records = load_run_records(path)
    # JSON object keys must be strings -- seeds are ints everywhere else
    # (see load_run_history's own conversion back).
    data = {
        "schema_version": SCHEMA_VERSION,
        "best_floors_cleared": {str(k): v for k, v in best_floors_cleared.items()},
        "runs": records[:MAX_RUN_RECORDS],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def record_run_result(
    seed: int, floors_cleared: int, path: str = RUN_HISTORY_PATH, details: RunRecord | None = None,
) -> dict[int, int]:
    """Record a run's outcome for `seed`, keeping the best (highest)
    floors_cleared seen across repeat attempts on that seed rather than
    overwriting with a worse result. `details` (commander/ascension/act/
    daily -- see Game._record_run_permadeath), if given, is also pushed
    onto the front of the per-run records list, capped at
    MAX_RUN_RECORDS. Returns the updated {seed: best_floors_cleared}
    mapping, the same shape load_run_history() returns."""
    best_floors_cleared = load_run_history(path)
    best_floors_cleared[seed] = max(floors_cleared, best_floors_cleared.get(seed, 0))
    records = load_run_records(path)
    if details is not None:
        records.insert(0, {"seed": seed, "floors_cleared": floors_cleared, **details})
    save_run_history(best_floors_cleared, path, records)
    return best_floors_cleared
