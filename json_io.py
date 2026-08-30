"""Shared "one JSON file, defensive load" helper behind progress.py,
player_settings.py, achievements.py, and save_state.py.

Each of those four modules persists its own kind of local player data as a
single JSON file with its own schema and its own fallback value, but every
one of their load_*() functions was the exact same shape: missing/corrupt/
semantically-invalid file -> a caller-supplied fallback, never a crash --
same spirit as persistence.list_custom_levels() skipping a bad file. This
factors that shape out once instead of four hand-copies of it.
"""

import json
import os

# The union of every exception any of the four modules' own load_*()
# functions used to catch individually -- broader than any one of them
# needed on its own, but catching a superset here is safe (still just
# "fall back to default"), and keeps this the one place that decides what
# counts as "bad data" for all four.
_FALLBACK_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError)


def load_json_with_fallback(path, transform, default):
    """Read and json.parse `path`, pass the raw parsed value through
    `transform` (returning whatever shape the caller actually wants --
    also the place to raise if the data is well-formed JSON but
    semantically invalid, e.g. save_state.load_run()'s wave_state/
    wave_index/tower-type checks), or return `default()` if the file
    doesn't exist or anything above raises. `default` is a zero-arg
    callable, not a plain value, so a mutable fallback (like `dict` or
    `list`) is never accidentally shared/aliased across calls."""
    if not os.path.isfile(path):
        return default()
    try:
        with open(path) as f:
            data = json.load(f)
        return transform(data)
    except _FALLBACK_ERRORS:
        return default()
