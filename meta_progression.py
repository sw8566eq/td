"""Persistent, cross-session tower unlocks for the roguelike run's draft
pool.

A registry of lockable towers (same {key: ...} shape as ACHIEVEMENTS/
TOWER_TYPES/ENEMY_TYPES/LEVELS), each keyed off crossing a threshold on one
of a handful of cumulative lifetime counters -- built on threshold_unlocks.py's
shared mechanics, the same ones achievements.py itself is built on (see that
module's own docstring for why the *mechanics* are shared while the file/
registry/JSON state stay genuinely separate). Kept as a genuinely separate
module and file from achievements.py on purpose: achievements are cosmetic/
trophy-flavored (there's no gameplay consequence to unlocking one), while
these unlocks are gameplay-flavored -- they change what card_pool.draft_offer()
can actually offer a future run. Conflating the two would make one registry
serve two very different urgencies of "what does this number gate."

Unlike Achievement, a MetaUnlock has no display_name/description of its
own -- it unlocks a specific TOWER_TYPES entry, which already has a
display_name; toasting/describing an unlock reads that off TOWER_TYPES
directly (see Game._queue_meta_unlock_toasts) rather than duplicating it
here where it could drift out of sync.
"""

import json

from json_io import load_json_with_fallback, module_relative_path
from threshold_unlocks import empty_counters_state, parse_counters_state, unlock_crossed_thresholds

SCHEMA_VERSION = 1
META_PROGRESSION_PATH = module_relative_path(__file__, "meta_progression.json")


class MetaUnlock:
    """One registry entry -- `tower_name` becomes draftable account-wide
    once `counter` (a key into the persisted counters dict) reaches
    `goal`."""

    def __init__(self, key, tower_name, counter, goal):
        self.key = key
        self.tower_name = tower_name
        self.counter = counter
        self.goal = goal


# Every TOWER_TYPES entry not in card_pool.STARTER_TOWERS gets exactly one
# entry here -- not imported from card_pool.py to avoid a circular import
# (card_pool.draft_offer's own default pool reads unlocked_tower_pool()
# below), so this list is the one place that pairing has to be kept
# correct by hand. total_floors_cleared/runs_played/runs_reached_endless
# are bumped from game.py (_advance_run_floor and _record_run_permadeath)
# -- see their own comments there for exactly when each fires.
#
# unlock_knockback's goal of 1 is load-bearing, not just the easiest one:
# _advance_run_floor bumps total_floors_cleared *before* the player ever
# sees a draft screen (see its own comment), so a brand new player's very
# first floor clear already crosses this threshold -- their first-ever
# draft screen (Milestone 2's own "every floor clear enters DRAFT"
# assumption) has a real card to offer instead of finding STARTER_TOWERS
# fully exhausted and silently skipping straight to the next floor. Every
# later threshold only has to keep pace with that, not also solve it.
META_UNLOCKS = {
    "unlock_knockback": MetaUnlock("unlock_knockback", "knockback", "total_floors_cleared", 1),
    "unlock_poison": MetaUnlock("unlock_poison", "poison", "total_floors_cleared", 3),
    "unlock_lightning": MetaUnlock("unlock_lightning", "lightning", "total_floors_cleared", 5),
    "unlock_sniper": MetaUnlock("unlock_sniper", "sniper", "runs_played", 1),
    "unlock_support": MetaUnlock("unlock_support", "support", "runs_played", 2),
    "unlock_beam": MetaUnlock("unlock_beam", "beam", "runs_reached_endless", 1),
}


def load_meta_progression(path=META_PROGRESSION_PATH):
    """{"counters": {name: int}, "unlocked": {key, ...}} -- falls back to
    empty state if the file doesn't exist yet or fails to parse, same
    spirit as achievements.load_achievements()."""
    return load_json_with_fallback(path, parse_counters_state, empty_counters_state)


def save_meta_progression(state, path=META_PROGRESSION_PATH):
    data = {
        "schema_version": SCHEMA_VERSION,
        "counters": state["counters"],
        "unlocked": sorted(state["unlocked"]),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def bump(counter_name, amount=1, path=META_PROGRESSION_PATH):
    """Bump `counter_name` by `amount` and return the list of unlock keys
    newly unlocked by this bump (in registry insertion order). For a
    counter that's a simple +1-(or more)-per-event tally -- every counter
    above is one of these; achievements.py's sibling set_counter() (for a
    counter driven by an already-deduplicated external count, like its own
    distinct_levels_cleared) has no equivalent here yet since nothing
    needs it -- add one, mirroring that shape, if a future counter does."""
    state = load_meta_progression(path)
    state["counters"][counter_name] = state["counters"].get(counter_name, 0) + amount
    newly_unlocked = unlock_crossed_thresholds(META_UNLOCKS, state, counter_name)
    save_meta_progression(state, path)
    return newly_unlocked


def unlocked_tower_pool(path=META_PROGRESSION_PATH):
    """Every TOWER_TYPES name unlocked account-wide via META_UNLOCKS so
    far -- card_pool.draft_offer()'s default pool is this plus
    card_pool.STARTER_TOWERS (composed there, not here, for the same
    circular-import reason META_UNLOCKS above isn't built from
    card_pool.STARTER_TOWERS directly)."""
    state = load_meta_progression(path)
    return {unlock.tower_name for key, unlock in META_UNLOCKS.items() if key in state["unlocked"]}
