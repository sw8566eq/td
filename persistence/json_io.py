"""Two small shared helpers behind every module that reads/writes its own
local player data as a file next to the project root: progress.py,
player_settings.py, achievements.py, save_state.py, persistence.py,
meta_progression.py, run_history.py, keybindings.py, and assets.py.

`load_json_with_fallback` is the "one JSON file, defensive load" shape --
progress/player_settings/achievements/save_state each persist their own kind
of local player data as a single JSON file with its own schema and its own
fallback value, but every one of their load_*() functions was the exact same
shape: missing/corrupt/semantically-invalid file -> a caller-supplied
fallback, never a crash -- same spirit as persistence.list_custom_levels()
skipping a bad file. This factors that shape out once instead of four
hand-copies of it.

`module_relative_path` factors out the other shape all of those modules
share: a path anchored to the project root, not the process's current
working directory, which is only ever guaranteed to be the repo root for
`python main.py` run from there -- a packaged --onedir build (see
CLAUDE.md's "Release binary" section) launched from anywhere else needs
this to keep finding its own bundled data/assets. Every caller lives one
level under the project root now (persistence/progress.py,
presentation/assets.py, ...), inside one of the repo's top-level package
folders -- see CLAUDE.md's "Organized into folders" section -- so
`module_relative_path` walks up two levels from the calling module's own
`__file__` (package dir, then project root), not one. This is safe and
uniform *only* because every caller sits at that same, single level of
nesting; a module moved any deeper would need this helper's own logic
extended, not just another call site fixed up.
"""

import json
import os
from collections.abc import Callable
from typing import Any

# The union of every exception any of the four modules' own load_*()
# functions used to catch individually -- broader than any one of them
# needed on its own, but catching a superset here is safe (still just
# "fall back to default"), and keeps this the one place that decides what
# counts as "bad data" for all four.
_FALLBACK_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError)


def module_relative_path(module_file: str, *parts: str) -> str:
    """Join `parts` onto the project root -- two directories up from
    `module_file` (pass a module's own `__file__`): the calling module's
    own package folder, then that package folder's parent, the actual repo
    root where `assets/`/`custom_levels/`/every `*.json` state file lives.
    Not the process's current working directory. Callers use this the same
    way every time: `module_relative_path(__file__, "progress.json")`."""
    package_dir = os.path.dirname(os.path.abspath(module_file))
    project_root = os.path.dirname(package_dir)
    return os.path.join(project_root, *parts)


def load_json_with_fallback[T](path: str, transform: Callable[[Any], T], default: Callable[[], T]) -> T:
    """Read and json.parse `path`, pass the raw parsed value through
    `transform` (returning whatever shape the caller actually wants --
    also the place to raise if the data is well-formed JSON but
    semantically invalid, e.g. save_state.load_run()'s wave_state/
    wave_index/tower-type checks), or return `default()` if the file
    doesn't exist or anything above raises. `default` is a zero-arg
    callable, not a plain value, so a mutable fallback (like `dict` or
    `list`) is never accidentally shared/aliased across calls. `transform`'s
    own parameter is `Any`, not a narrower type, since `json.load()`'s
    return is inherently untyped -- every caller's own `transform` narrows
    it down to whatever shape `T` actually is (see callers like
    run_history.load_run_history()'s own inline `transform` lambda for the
    pattern)."""
    if not os.path.isfile(path):
        return default()
    try:
        with open(path) as f:
            data = json.load(f)
        return transform(data)
    except _FALLBACK_ERRORS:
        return default()
