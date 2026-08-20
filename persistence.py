"""Save/load custom (editor-authored) levels to/from disk as JSON.

The only file I/O of game data anywhere in this codebase -- Level's shape
(frozenset/tuple of (col, row) pairs, a wave_specs list of plain dicts, a
few scalars) is otherwise trivially JSON-serializable, so this module is
just the (de)serialization glue plus a small amount of filesystem
bookkeeping (slugging a level's name into a stable filename/id, listing
what's on disk).

A corrupt or hand-edited-wrong file is expected to happen eventually --
list_custom_levels() skips one rather than crashing the whole level list,
same spirit as AssetManager falling back to a placeholder instead of
crashing when a sprite file is missing/broken.
"""

import json
import os
import re

from levels import Level

# Bumped from 1 -> 2 when wave_specs' per-wave dicts gained a spawn-cell
# level of nesting (see levels.py) -- no migration path for old files, since
# custom_levels/ is local, gitignored player data with no released version
# to stay compatible with yet.
SCHEMA_VERSION = 2
LEVELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_levels")


def level_to_dict(level):
    return {
        "schema_version": SCHEMA_VERSION,
        "id": level.id,
        "name": level.name,
        "path_cells": sorted(list(cell) for cell in level.path_cells),
        "spawn_cells": [list(cell) for cell in level.spawn_cells],
        "goal_cells": [list(cell) for cell in level.goal_cells],
        "blocked_cells": sorted(list(cell) for cell in level.blocked_cells),
        "branch_weights": [
            [list(from_cell), list(to_cell), weight]
            for (from_cell, to_cell), weight in level.branch_weights.items()
        ],
        # Each wave is [[spawn_cell, {enemy_name: count}], ...] rather than
        # a JSON object keyed by spawn_cell -- JSON object keys must be
        # strings, and a spawn_cell is a (col, row) pair -- same list-of-
        # pairs approach branch_weights above already uses for its own
        # tuple-keyed dict.
        "wave_specs": [
            [[list(spawn_cell), composition] for spawn_cell, composition in wave.items()]
            for wave in level.wave_specs
        ],
        "starting_gold": level.starting_gold,
        "starting_lives": level.starting_lives,
    }


def level_from_dict(data):
    return Level(
        id=data["id"],
        name=data["name"],
        path_cells=frozenset(tuple(cell) for cell in data["path_cells"]),
        spawn_cells=tuple(tuple(cell) for cell in data["spawn_cells"]),
        goal_cells=tuple(tuple(cell) for cell in data["goal_cells"]),
        blocked_cells=frozenset(tuple(cell) for cell in data.get("blocked_cells", [])),
        branch_weights={
            (tuple(from_cell), tuple(to_cell)): weight
            for from_cell, to_cell, weight in data.get("branch_weights", [])
        },
        wave_specs=[
            {tuple(spawn_cell): composition for spawn_cell, composition in wave}
            for wave in data["wave_specs"]
        ],
        starting_gold=data.get("starting_gold", 150),
        starting_lives=data.get("starting_lives", 20),
    )


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "level"


def save_level(level, directory=LEVELS_DIR):
    """Write `level` as {slug}.json in `directory` and return the path
    written. The slug is derived from the level's name, with a numeric
    suffix appended on collision -- it becomes the level's id in the
    saved file (and so, once reloaded via list_custom_levels(), the id
    Game.load_custom_level sees), regardless of whatever id `level`
    itself carried in memory (an editor-fresh level's is just a generic
    placeholder)."""
    os.makedirs(directory, exist_ok=True)
    base_slug = _slugify(level.name)
    slug = base_slug
    suffix = 1
    while os.path.exists(os.path.join(directory, f"{slug}.json")):
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    data = level_to_dict(level)
    data["id"] = slug
    path = os.path.join(directory, f"{slug}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def load_level_file(path):
    with open(path) as f:
        data = json.load(f)
    return level_from_dict(data)


def list_custom_levels(directory=LEVELS_DIR):
    """Every valid saved level in `directory`, in filename order. A file
    that's missing, corrupt, or fails Level's own validation (e.g. hand-
    edited into an invalid path) is skipped rather than raised -- one bad
    file shouldn't take the whole level-select screen down with it."""
    if not os.path.isdir(directory):
        return []
    levels = []
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        try:
            levels.append(load_level_file(os.path.join(directory, filename)))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return levels
