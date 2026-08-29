"""Tracks which built-in levels the player has cleared, across sessions.

Mirrors persistence.py's own conventions: a single JSON file, defensive
handling of a missing/corrupt file (falls back to "nothing cleared" rather
than crashing, same spirit as persistence.list_custom_levels() skipping a
bad file). Unlocking is sequential, not "any earlier level" -- the lowest
id in a level registry is always unlocked, and every other level needs its
immediate predecessor (by sorted id) already cleared. Custom (editor-
authored) levels have no fixed order among themselves and are never gated
by this at all -- is_unlocked() is only ever consulted for a LEVELS entry.
"""

import json
import os

SCHEMA_VERSION = 1
PROGRESS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress.json")


def load_progress(path=PROGRESS_PATH):
    """{level_id: best_lives_remaining} for every built-in level cleared so
    far, or {} if the file doesn't exist yet or fails to parse -- a
    corrupt/hand-edited file shouldn't take the whole game down, same
    spirit as list_custom_levels()."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return {int(level_id): lives for level_id, lives in data.get("cleared", {}).items()}
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return {}


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


def is_unlocked(level_id, levels_dict, cleared):
    """True if `level_id` (a key of `levels_dict`) is playable given
    `cleared` (a load_progress()-shaped mapping) -- the lowest id in
    `levels_dict` is always unlocked; every other id needs its immediate
    sequential predecessor already cleared."""
    ordered_ids = sorted(levels_dict)
    if not ordered_ids or level_id == ordered_ids[0]:
        return True
    previous_id = ordered_ids[ordered_ids.index(level_id) - 1]
    return previous_id in cleared
