"""Persistent, cross-session achievement tracking.

A registry of unlockable achievements (same {key: ...} shape as
TOWER_TYPES/ENEMY_TYPES/LEVELS/DIFFICULTY_MODES), each keyed off crossing a
threshold on one of a handful of cumulative lifetime counters (kills,
towers built/maxed/specialized, levels cleared, waves survived). Mirrors
progress.py's own conventions closely: a single JSON file, defensive
handling of a missing/corrupt file (falls back to "nothing tracked yet"
rather than crashing, same spirit as progress.load_progress()).

bump()/set_counter() mirror progress.mark_level_cleared()'s exact shape too
-- load the persisted state fresh, mutate, save, return what changed -- so
they're always safe to call from wherever the relevant Game-level event
actually happens, with no in-memory counters of its own that could go
stale between calls or across multiple Game instances sharing one file.
That load-mutate-save-return mechanics is shared with meta_progression.py
via threshold_unlocks.py (see that module's own docstring) -- this module
just supplies its own registry/path/schema version to it.
"""

import levels
import threshold_unlocks
from json_io import module_relative_path
from threshold_unlocks import CountersState

SCHEMA_VERSION = 1
ACHIEVEMENTS_PATH = module_relative_path(__file__, "achievements.json")


class Achievement:
    """One registry entry -- unlocked once `counter` (a key into the
    persisted counters dict) reaches `goal`."""

    def __init__(self, key: str, display_name: str, description: str, counter: str, goal: int) -> None:
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
    # Keyed off distinct_levels_cleared (set via set_counter(), below), not
    # levels_cleared -- that one is a naive +1-per-victory counter, which
    # would let replaying one already-cleared level over and over reach
    # this goal without ever touching most of the campaign.
    "campaign_complete": Achievement(
        "campaign_complete", "Campaign Complete", "Clear every built-in level.",
        "distinct_levels_cleared", len(levels.LEVELS),
    ),
    "wave_finisher": Achievement(
        "wave_finisher", "Wave Finisher", "Clear 10 waves total.", "waves_survived", 10,
    ),
    "century_of_waves": Achievement(
        "century_of_waves", "Century of Waves", "Clear 100 waves total.", "waves_survived", 100,
    ),
    "boss_slayer": Achievement(
        "boss_slayer", "Boss Slayer", "Defeat the run's final boss.", "bosses_defeated", 1,
    ),
    # A v1.0 batch of 8, closing the biggest count-disparity in the
    # content registries (11 achievements against 74 relics before this)
    # -- none tied to relics collected, Daily Runs, or specific towers.
    # Thresholds pattern-matched against the existing registry's own
    # escalation style (kills' 1/100/1000, waves_survived's 10/100 --
    # roughly x5-10 per tier). relics_collected/daily_runs_played/
    # events_resolved are new counters, bumped from Game (see
    # Game._grant_relic/_resolve_event_choice/_record_run_permadeath) --
    # never from inside Tower/Enemy/Economy, same rule every other counter
    # here already follows, so resume_saved_run() can never double-count
    # one. siphon_built/overload_cannon_built reuse the same per-tower-
    # type pattern try_place_tower() already bumps every tower's own name
    # under (f"{tower_name}_built"), so any future tower gets one for
    # free with zero new plumbing -- these two are just the first
    # achievements to actually key off it.
    "relic_collector": Achievement(
        "relic_collector", "Collector", "Collect 10 relics across your runs.", "relics_collected", 10,
    ),
    "relic_hoarder": Achievement(
        "relic_hoarder", "Hoarder", "Collect 50 relics across your runs.", "relics_collected", 50,
    ),
    "daily_habit": Achievement(
        "daily_habit", "Creature of Habit", "Play 7 Daily Runs.", "daily_runs_played", 7,
    ),
    "daily_devotee": Achievement(
        "daily_devotee", "Daily Devotee", "Play 30 Daily Runs.", "daily_runs_played", 30,
    ),
    "crossroads": Achievement(
        "crossroads", "Crossroads", "Resolve 5 Random Events.", "events_resolved", 5,
    ),
    "well_traveled": Achievement(
        "well_traveled", "Well-Traveled", "Resolve 30 Random Events.", "events_resolved", 30,
    ),
    "power_tap": Achievement(
        "power_tap", "Power Tap", "Place a Siphon Tower.", "siphon_built", 1,
    ),
    "overcharged": Achievement(
        "overcharged", "Overcharged", "Place an Overload Cannon.", "overload_cannon_built", 1,
    ),
}
ACHIEVEMENT_ORDER = list(ACHIEVEMENTS.keys())  # stable UI order = registry insertion order


def load_achievements(path: str = ACHIEVEMENTS_PATH) -> CountersState:
    """{"counters": {name: int}, "unlocked": {key, ...}} -- falls back to
    empty state if the file doesn't exist yet or fails to parse, same
    spirit as progress.load_progress()."""
    return threshold_unlocks.load_counters_state(path)


def save_achievements(state: CountersState, path: str = ACHIEVEMENTS_PATH) -> None:
    threshold_unlocks.save_counters_state(state, path, SCHEMA_VERSION)


def bump(counter_name: str, amount: int = 1, path: str = ACHIEVEMENTS_PATH) -> list[str]:
    """Bump `counter_name` by `amount` and return the list of achievement
    keys newly unlocked by this bump (in ACHIEVEMENT_ORDER). For a
    counter that's a simple +1-(or more)-per-event tally -- kills, towers
    built, waves survived, and so on."""
    return threshold_unlocks.bump_counter(ACHIEVEMENTS, counter_name, amount, path, SCHEMA_VERSION)


def set_counter(counter_name: str, value: int, path: str = ACHIEVEMENTS_PATH) -> list[str]:
    """Set `counter_name` to max(current value, `value`) and return the
    list of achievement keys newly unlocked (same contract as bump()).
    For a counter driven by an already-deduplicated external count --
    e.g. distinct built-in levels cleared, from progress.py's own
    {level_id: ...} tracking -- rather than a naive increment-per-event
    tally, where replaying the same event repeatedly must never look like
    additional progress. The max() keeps it monotonic (a lifetime
    counter, like every other one here) even if called with a smaller
    value than what's already recorded."""
    return threshold_unlocks.set_counter(ACHIEVEMENTS, counter_name, value, path, SCHEMA_VERSION)
