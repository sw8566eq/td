"""Persisted player preferences (fullscreen, difficulty) across sessions.

Mirrors progress.py's own conventions closely: a single JSON file, defensive
handling of a missing/corrupt file (falls back to the defaults rather than
crashing, same spirit as progress.load_progress()/persistence.list_custom_
levels() skipping bad data). Named player_settings.py rather than
settings.py, since that name is already taken by this repo's global-
constants module (imported everywhere as `import settings`).
"""

import json

from json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
SETTINGS_PATH = module_relative_path(__file__, "player_settings.json")

DEFAULTS = {"fullscreen": False, "difficulty": "normal"}


def _merge_with_defaults(data):
    merged = dict(DEFAULTS)
    merged["fullscreen"] = bool(data.get("fullscreen", DEFAULTS["fullscreen"]))
    merged["difficulty"] = str(data.get("difficulty", DEFAULTS["difficulty"]))
    return merged


def load_settings(path=SETTINGS_PATH):
    """The saved settings dict, or a fresh copy of DEFAULTS if the file
    doesn't exist yet or fails to parse -- a corrupt/hand-edited file
    shouldn't take the whole game down, same spirit as progress.py."""
    return load_json_with_fallback(path, _merge_with_defaults, lambda: dict(DEFAULTS))


def save_settings(settings_dict, path=SETTINGS_PATH):
    data = {"schema_version": SCHEMA_VERSION, **settings_dict}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
