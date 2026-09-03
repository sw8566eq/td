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
independently wrote the same threshold-crossing one.
"""


def empty_counters_state():
    """{"counters": {}, "unlocked": set()} -- the shared empty/fallback
    state shape, passed as the `default` callable to
    json_io.load_json_with_fallback."""
    return {"counters": {}, "unlocked": set()}


def parse_counters_state(data):
    """Parse a persisted counters-state JSON blob back into
    {"counters": {name: int}, "unlocked": {key, ...}} -- the shared load
    transform, passed to json_io.load_json_with_fallback."""
    return {
        "counters": {str(name): int(value) for name, value in data.get("counters", {}).items()},
        "unlocked": set(data.get("unlocked", [])),
    }


def unlock_crossed_thresholds(registry, state, counter_name):
    """Mutate state["unlocked"] with every not-yet-unlocked `registry`
    entry (each needing its own .counter/.goal attributes) keyed off
    `counter_name` whose goal state["counters"][counter_name] now meets or
    exceeds, and return the list of keys newly added (in registry
    insertion order) -- shared by achievements.py/meta_progression.py's
    own bump()/set_counter(), which differ only in how they arrive at the
    counter's new value."""
    newly_unlocked = []
    for key, entry in registry.items():
        if key in state["unlocked"]:
            continue
        if entry.counter == counter_name and state["counters"][counter_name] >= entry.goal:
            state["unlocked"].add(key)
            newly_unlocked.append(key)
    return newly_unlocked
