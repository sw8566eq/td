"""Tracks which built-in levels the player has cleared, across sessions.

Mirrors persistence.py's own conventions: a single JSON file, defensive
handling of a missing/corrupt file (falls back to "nothing cleared" rather
than crashing, same spirit as persistence.list_custom_levels() skipping a
bad file).

This is a *record*, not a gate. It used to also decide which levels were
playable (a sequential is_unlocked(): the lowest id always open, every
other one needing its immediate predecessor cleared), but the roguelike
run loop retired that idea outright -- a run's floor sequence picks its own
levels (see run_floors.py), meta_progression.py gates what the draft can
offer, and Practice mode plays any level immediately. What survives is the
{level_id: best_lives_remaining} tally itself, written by
Game._record_level_cleared() on every non-sandbox floor/level clear and
read back for the "Campaign Complete" achievement's distinct-levels count.
Custom (editor-authored) levels are never recorded here -- they have no
registry id to key on.
"""

import json

from json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
PROGRESS_PATH = module_relative_path(__file__, "progress.json")


def load_progress(path=PROGRESS_PATH):
    """{level_id: best_lives_remaining} for every built-in level cleared so
    far, or {} if the file doesn't exist yet or fails to parse -- a
    corrupt/hand-edited file shouldn't take the whole game down, same
    spirit as list_custom_levels()."""
    return load_json_with_fallback(
        path,
        lambda data: {int(level_id): lives for level_id, lives in data.get("cleared", {}).items()},
        dict,
    )


def save_progress(cleared, path=PROGRESS_PATH):
    # JSON object keys must be strings -- level ids are ints everywhere
    # else (see load_progress's own conversion back).
    data = {"schema_version": SCHEMA_VERSION, "cleared": {str(k): v for k, v in cleared.items()}}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def mark_level_cleared(level_id, lives_remaining, path=PROGRESS_PATH):
    """Record `level_id` as cleared, keeping the best (highest)
    lives_remaining seen across repeat clears rather than overwriting with
    a worse result. Returns the updated {level_id: best_lives_remaining}
    mapping, the same shape load_progress() returns."""
    cleared = load_progress(path)
    cleared[level_id] = max(lives_remaining, cleared.get(level_id, 0))
    save_progress(cleared, path)
    return cleared
