"""Shared mechanics behind every "lifetime counters unlock registry
entries" tracker in this codebase -- achievements.py and
meta_progression.py both persist the exact same {"counters": {name: int},
"unlocked": {key, ...}} state shape and the same threshold-crossing rule
(a registry entry unlocks once its own counter reaches its own goal),
differing only in what their own registry actually contains (Achievement
vs MetaUnlock) and what triggers a bump. Achievements are cosmetic/
trophy-flavored and meta-progression unlocks are gameplay-flavored (they
change what a roguelike run's draft can offer) -- two genuinely separate
concerns, kept in two separate files/JSON files/registries on purpose
-- but the bookkeeping *mechanics* underneath them are identical, and
duplicating those a second time is exactly the shape json_io.py's own
load_json_with_fallback/module_relative_path were factored out to avoid:
before that, several modules independently wrote the same file-I/O
expression; before this module, achievements.py and meta_progression.py
independently wrote the same threshold-crossing one, and (until
load_counters_state/save_counters_state/bump_counter/set_counter below)
the same load-mutate-save-return one too.

achievements.py/meta_progression.py's own load_*/save_*/bump()/
set_counter() functions are kept as the public API each module has always
exposed (both to the rest of the codebase and to their own extensive test
suites) -- they just delegate their bodies here now, rather than each
independently repeating the exact same four function bodies a second
time. `path` and `schema_version` stay plain parameters rather than
config this module owns itself, since each caller's own module still owns
its own JSON file's schema version and default path.
"""

import json
from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from json_io import load_json_with_fallback


class CountersState(TypedDict):
    counters: dict[str, int]
    unlocked: set[str]


class ThresholdUnlockEntry(Protocol):
    """The shape unlock_crossed_thresholds()/bump_counter()/set_counter()
    actually need from a registry entry -- achievements.Achievement and
    meta_progression.py's MetaUnlock/RelicMetaUnlock/LevelMetaUnlock all
    satisfy this structurally without importing (or being imported by)
    this module, which is exactly why this is a Protocol rather than a
    shared base class: achievements.py already imports this module, so a
    real import the other way would be a cycle."""
    counter: str
    goal: int


def empty_counters_state() -> CountersState:
    """{"counters": {}, "unlocked": set()} -- the shared empty/fallback
    state shape, passed as the `default` callable to
    json_io.load_json_with_fallback."""
    return {"counters": {}, "unlocked": set()}


def parse_counters_state(data: Any) -> CountersState:
    """Parse a persisted counters-state JSON blob back into
    {"counters": {name: int}, "unlocked": {key, ...}} -- the shared load
    transform, passed to json_io.load_json_with_fallback."""
    return {
        "counters": {str(name): int(value) for name, value in data.get("counters", {}).items()},
        "unlocked": set(data.get("unlocked", [])),
    }


def unlock_crossed_thresholds(
    registry: Mapping[str, ThresholdUnlockEntry], state: CountersState, counter_name: str,
) -> list[str]:
    """Mutate state["unlocked"] with every not-yet-unlocked `registry`
    entry (each needing its own .counter/.goal attributes) keyed off
    `counter_name` whose goal state["counters"][counter_name] now meets or
    exceeds, and return the list of keys newly added (in registry
    insertion order) -- shared by bump_counter()/set_counter() below,
    which differ only in how they arrive at the counter's new value.
    `registry` is typed as `Mapping`, not `dict` -- dict's invariance
    would reject a caller's own `dict[str, MetaUnlock | RelicMetaUnlock |
    LevelMetaUnlock]` here, since none of those three is `dict[str,
    ThresholdUnlockEntry]` itself even though each one structurally
    satisfies the Protocol."""
    newly_unlocked = []
    for key, entry in registry.items():
        if key in state["unlocked"]:
            continue
        if entry.counter == counter_name and state["counters"][counter_name] >= entry.goal:
            state["unlocked"].add(key)
            newly_unlocked.append(key)
    return newly_unlocked


def load_counters_state(path: str) -> CountersState:
    """{"counters": {name: int}, "unlocked": {key, ...}} -- falls back to
    empty state if the file doesn't exist yet or fails to parse, same
    spirit as progress.load_progress()."""
    return load_json_with_fallback(path, parse_counters_state, empty_counters_state)


def save_counters_state(state: CountersState, path: str, schema_version: int) -> None:
    data = {
        "schema_version": schema_version,
        "counters": state["counters"],
        "unlocked": sorted(state["unlocked"]),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def bump_counter(
    registry: Mapping[str, ThresholdUnlockEntry], counter_name: str, amount: int, path: str, schema_version: int,
) -> list[str]:
    """Bump `counter_name` by `amount` and return the list of `registry`
    keys newly unlocked by this bump (in registry insertion order). For a
    counter that's a simple +1-(or more)-per-event tally -- load the
    persisted state fresh, mutate, save, return what changed, so this is
    always safe to call from wherever the relevant event actually
    happens, with no in-memory counters of its own that could go stale
    between calls or across multiple Game instances sharing one file."""
    state = load_counters_state(path)
    state["counters"][counter_name] = state["counters"].get(counter_name, 0) + amount
    newly_unlocked = unlock_crossed_thresholds(registry, state, counter_name)
    save_counters_state(state, path, schema_version)
    return newly_unlocked


def set_counter(
    registry: Mapping[str, ThresholdUnlockEntry], counter_name: str, value: int, path: str, schema_version: int,
) -> list[str]:
    """Set `counter_name` to max(current value, `value`) and return the
    list of `registry` keys newly unlocked (same contract as
    bump_counter()). For a counter driven by an already-deduplicated
    external count -- e.g. achievements.py's own distinct_levels_cleared,
    from progress.py's {level_id: ...} tracking -- rather than a naive
    increment-per-event tally, where replaying the same event repeatedly
    must never look like additional progress. The max() keeps it
    monotonic (a lifetime counter, like every other one here) even if
    called with a smaller value than what's already recorded."""
    state = load_counters_state(path)
    state["counters"][counter_name] = max(state["counters"].get(counter_name, 0), value)
    newly_unlocked = unlock_crossed_thresholds(registry, state, counter_name)
    save_counters_state(state, path, schema_version)
    return newly_unlocked
