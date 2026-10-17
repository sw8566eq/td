"""The Service Record: lifetime statistics across every run.

One JSON file, same defensive-load/injectable-path shape as the other
progression files (see docs/agents/persistence.md "Small on-disk JSON state
files"). Pure Python -- no pygame -- so the screen's rows are unit-testable.

The state is four sections of plain numeric stats:

- ``overall``    -- ``{stat: number}`` (OVERALL_STATS lists them in display order)
- ``towers``     -- ``{tower type: {stat: number}}`` (TOWER_STATS)
- ``enemies``    -- ``{enemy type: {stat: number}}`` (ENEMY_STATS)
- ``commanders`` -- ``{commander key: {stat: number}}`` (COMMANDER_STATS)

Every write is either an *add* (a running total) or a *raise* (a "best ever"
value only ever goes up), expressed as ``Entry`` tuples and applied in one
load-mutate-save by ``record()``. Nothing here decides *when* a stat is
recorded -- ``Game`` does, and only outside sandbox (see
docs/agents/persistence.md "`progression/service_record.py`" for why per-tower
damage is folded in once per floor rather than live).
"""

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from persistence.json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
SERVICE_RECORD_PATH = module_relative_path(__file__, "service_record.json")

Number = int | float
Stats = dict[str, Number]

OVERALL = "overall"
TOWERS = "towers"
ENEMIES = "enemies"
COMMANDERS = "commanders"
SUBJECT_SECTIONS = (TOWERS, ENEMIES, COMMANDERS)

# (section, subject, stat, amount) -- subject is "" for OVERALL.
Entry = tuple[str, str, str, Number]

# {stat: label}, in the order the screen lists them. "Best" stats are raised,
# never added (see Game's recording hooks).
OVERALL_STATS: dict[str, str] = {
    "runs_started": "Runs started",
    "runs_ended": "Runs ended",
    "floors_cleared": "Floors cleared",
    "acts_cleared": "Acts cleared",
    "deepest_depth": "Deepest floor reached",
    "best_endless_score": "Best endless score (waves)",
    "enemies_killed": "Enemies killed",
    "gold_earned": "Battle gold earned",
    "lives_lost": "Lives lost",
    "towers_built": "Towers built",
    "relics_collected": "Relics collected",
    "potions_used": "Potions used",
    "abilities_used": "Abilities used",
}
TOWER_STATS = ("built", "damage", "kills", "best_rank")
ENEMY_STATS = ("kills",)
COMMANDER_STATS = ("runs", "best_depth")


@dataclass
class ServiceRecord:
    overall: Stats = field(default_factory=dict)
    towers: dict[str, Stats] = field(default_factory=dict)
    enemies: dict[str, Stats] = field(default_factory=dict)
    commanders: dict[str, Stats] = field(default_factory=dict)

    def stats_for(self, section: str, subject: str) -> Stats:
        """The mutable stats dict an Entry targets, created on first use."""
        if section == OVERALL:
            return self.overall
        if section not in SUBJECT_SECTIONS:
            raise ValueError(f"unknown service record section {section!r}")
        table: dict[str, Stats] = getattr(self, section)
        return table.setdefault(subject, {})

    def get(self, section: str, subject: str, stat: str) -> Number:
        """A stat's value, 0 if never recorded -- read-only (never creates)."""
        if section == OVERALL:
            return self.overall.get(stat, 0)
        table: dict[str, Stats] = getattr(self, section)
        return table.get(subject, {}).get(stat, 0)


# --- Entry builders ---

def overall(stat: str, amount: Number) -> Entry:
    return (OVERALL, "", stat, amount)


def tower(name: str, stat: str, amount: Number) -> Entry:
    return (TOWERS, name, stat, amount)


def enemy(name: str, stat: str, amount: Number) -> Entry:
    return (ENEMIES, name, stat, amount)


def commander(key: str, stat: str, amount: Number) -> Entry:
    return (COMMANDERS, key, stat, amount)


# --- Pure state updates ---

def apply(record: ServiceRecord, adds: Iterable[Entry] = (), raises: Iterable[Entry] = ()) -> ServiceRecord:
    """Add each `adds` amount onto its stat; raise each `raises` stat to at
    least its amount. Mutates and returns `record`. A zero add is skipped so
    an idle floor doesn't create empty subject rows."""
    for section, subject, stat, amount in adds:
        if amount:
            stats = record.stats_for(section, subject)
            stats[stat] = stats.get(stat, 0) + amount
    for section, subject, stat, amount in raises:
        if amount > record.get(section, subject, stat):
            record.stats_for(section, subject)[stat] = amount
    return record


def tower_floor_entries(results: Iterable[tuple[str, float, int]]) -> list[Entry]:
    """One floor's (tower type, damage dealt, kills) per tower -- placed and
    sold alike -- summed per type into "damage"/"kills" add entries."""
    damage: dict[str, float] = {}
    kills: dict[str, int] = {}
    for name, dealt, killed in results:
        damage[name] = damage.get(name, 0.0) + dealt
        kills[name] = kills.get(name, 0) + killed
    entries: list[Entry] = []
    for name, dealt in damage.items():
        entries.append(tower(name, "damage", dealt))
        entries.append(tower(name, "kills", kills[name]))
    return entries


@dataclass
class FloorTally:
    """Per-floor counts Game accumulates live (kills by enemy type, lives
    lost) and flushes into the record in one write -- at a floor's end or
    when the floor is saved (see Game._flush_service_tally)."""
    enemy_kills: dict[str, int] = field(default_factory=dict)
    kills: int = 0
    lives_lost: int = 0

    def add_kill(self, enemy_type: str | None) -> None:
        self.kills += 1
        if enemy_type is not None:
            self.enemy_kills[enemy_type] = self.enemy_kills.get(enemy_type, 0) + 1

    def entries(self, gold_earned: Number = 0) -> list[Entry]:
        result = [
            overall("enemies_killed", self.kills),
            overall("lives_lost", self.lives_lost),
            overall("gold_earned", gold_earned),
        ]
        result += [enemy(name, "kills", count) for name, count in self.enemy_kills.items()]
        return result


# --- Display rows ---

def _sorted_subjects(table: dict[str, Stats], stat: str) -> list[tuple[str, Stats]]:
    return sorted(table.items(), key=lambda item: (-item[1].get(stat, 0), item[0]))


def tower_rows(record: ServiceRecord) -> list[tuple[str, Stats]]:
    """Every tower type ever recorded, most total damage first."""
    return _sorted_subjects(record.towers, "damage")


def enemy_rows(record: ServiceRecord) -> list[tuple[str, Stats]]:
    """Every enemy type ever killed, most kills first."""
    return _sorted_subjects(record.enemies, "kills")


def commander_rows(record: ServiceRecord) -> list[tuple[str, Stats]]:
    """Every commander ever led, most runs first."""
    return _sorted_subjects(record.commanders, "runs")


# --- On disk ---

def _valid_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value >= 0
    )


def _parse_stats(raw: Any) -> Stats:
    if not isinstance(raw, dict):
        return {}
    return {str(stat): value for stat, value in raw.items() if _valid_number(value)}


def _parse_table(raw: Any) -> dict[str, Stats]:
    if not isinstance(raw, dict):
        return {}
    return {str(subject): _parse_stats(stats) for subject, stats in raw.items() if isinstance(stats, dict)}


def _parse(data: Any) -> ServiceRecord:
    """Keep every well-formed stat; a damaged section or value drops out
    rather than discarding the whole record."""
    if not isinstance(data, dict):
        raise TypeError("service record must be a JSON object")
    return ServiceRecord(
        overall=_parse_stats(data.get(OVERALL)),
        towers=_parse_table(data.get(TOWERS)),
        enemies=_parse_table(data.get(ENEMIES)),
        commanders=_parse_table(data.get(COMMANDERS)),
    )


def load_service_record(path: str = SERVICE_RECORD_PATH) -> ServiceRecord:
    """The saved record, or an empty one for a missing/corrupt file."""
    return load_json_with_fallback(path, _parse, ServiceRecord)


def save_service_record(record: ServiceRecord, path: str = SERVICE_RECORD_PATH) -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        OVERALL: record.overall,
        TOWERS: record.towers,
        ENEMIES: record.enemies,
        COMMANDERS: record.commanders,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def record(path: str = SERVICE_RECORD_PATH, adds: Iterable[Entry] = (), raises: Iterable[Entry] = ()) -> ServiceRecord:
    """Load, apply, save -- same load-mutate-save-return shape as
    achievements.bump(), so it's safe to call from anywhere with no
    in-memory copy to go stale."""
    updated = apply(load_service_record(path), adds, raises)
    save_service_record(updated, path)
    return updated
