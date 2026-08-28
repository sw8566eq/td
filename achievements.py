"""Persistent, cross-session achievement tracking.

A registry of unlockable achievements (same {key: ...} shape as
TOWER_TYPES/ENEMY_TYPES/LEVELS/DIFFICULTY_MODES), each keyed off crossing a
threshold on one of a handful of cumulative lifetime counters (kills,
towers built/maxed/specialized, levels cleared, waves survived). Mirrors
progress.py's own conventions closely: a single JSON file, defensive
handling of a missing/corrupt file (falls back to "nothing tracked yet"
rather than crashing, same spirit as progress.load_progress()).

bump() mirrors progress.mark_level_cleared()'s exact shape too -- load the
persisted state fresh, mutate, save, return what changed -- so it's always
safe to call from wherever the relevant Game-level event actually happens,
with no in-memory counters of its own that could go stale between calls or
across multiple Game instances sharing one file.
"""

import json
import os

import levels

SCHEMA_VERSION = 1
ACHIEVEMENTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "achievements.json")


class Achievement:
    """One registry entry -- unlocked once `counter` (a key into the
    persisted counters dict) reaches `goal`."""

    def __init__(self, key, display_name, description, counter, goal):
        self.key = key
        self.display_name = display_name
        self.description = description
        self.counter = counter
        self.goal = goal


ACHIEVEMENTS = {
    "first_blood": Achievement(
        "first_blood", "First Blood", "Land your first kill.", "kills", 1,
    ),
    "centurion": Achievement(
        "centurion", "Centurion", "Rack up 100 kills.", "kills", 100,
    ),
    "exterminator": Achievement(
        "exterminator", "Exterminator", "Rack up 1000 kills.", "kills", 1000,
    ),
    "groundbreaker": Achievement(
        "groundbreaker", "Groundbreaker", "Place your first tower.", "towers_built", 1,
    ),
    "fully_loaded": Achievement(
        "fully_loaded", "Fully Loaded", "Max out a tower's level.", "towers_maxed", 1,
    ),
    "specialist": Achievement(
        "specialist", "Specialist", "Choose a tower's first specialization.", "towers_specialized", 1,
    ),
    "first_victory": Achievement(
        "first_victory", "First Victory", "Clear your first level.", "levels_cleared", 1,
    ),
    # Goal is computed off the live LEVELS registry rather than a hardcoded
    # number, so adding more built-in levels later doesn't silently make
    # this permanently unreachable (too high) or already-satisfied (too low).
    "campaign_complete": Achievement(
        "campaign_complete", "Campaign Complete", "Clear every built-in level.",
        "levels_cleared", len(levels.LEVELS),
    ),
    "wave_finisher": Achievement(
        "wave_finisher", "Wave Finisher", "Clear 10 waves total.", "waves_survived", 10,
    ),
    "century_of_waves": Achievement(
        "century_of_waves", "Century of Waves", "Clear 100 waves total.", "waves_survived", 100,
    ),
}
ACHIEVEMENT_ORDER = list(ACHIEVEMENTS.keys())  # stable UI order = registry insertion order


def _empty_state():
    return {"counters": {}, "unlocked": set()}


def load_achievements(path=ACHIEVEMENTS_PATH):
    """{"counters": {name: int}, "unlocked": {key, ...}} -- falls back to
    empty state if the file doesn't exist yet or fails to parse, same
    spirit as progress.load_progress()."""
    if not os.path.isfile(path):
        return _empty_state()
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "counters": {str(name): int(value) for name, value in data.get("counters", {}).items()},
            "unlocked": set(data.get("unlocked", [])),
        }
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return _empty_state()


def save_achievements(state, path=ACHIEVEMENTS_PATH):
    data = {
        "schema_version": SCHEMA_VERSION,
        "counters": state["counters"],
        "unlocked": sorted(state["unlocked"]),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def bump(counter_name, amount=1, path=ACHIEVEMENTS_PATH):
    """Bump `counter_name` by `amount` and return the list of achievement
    keys newly unlocked by this bump (in ACHIEVEMENT_ORDER)."""
    state = load_achievements(path)
    state["counters"][counter_name] = state["counters"].get(counter_name, 0) + amount

    newly_unlocked = []
    for key, achievement in ACHIEVEMENTS.items():
        if key in state["unlocked"]:
            continue
        if achievement.counter == counter_name and state["counters"][counter_name] >= achievement.goal:
            state["unlocked"].add(key)
            newly_unlocked.append(key)

    save_achievements(state, path)
    return newly_unlocked
