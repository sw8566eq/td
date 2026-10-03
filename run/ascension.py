"""The Gauntlet (internally "ascension") -- a stacked, opt-in difficulty ladder.

Defeating the run's boss at Ascension N unlocks Ascension N+1 account-wide
(progression/meta_progression.py's own "highest_ascension" counter), up to
MAX_ASCENSION. A run snapshots its chosen level once, at start
(RunState.ascension), and every level includes all the ones below it:
ASCENSION_LEVELS[i] is the one new rule level i+1 adds on top.

Same "bundle of multipliers composed on top, never replacing anything"
shape as difficulty.py/run_escalation.py: modifiers_for(level) folds every
active rule into one AscensionModifiers, which Game reads at the handful of
points each field applies (see each field's own comment). Ascension 0 is
every field at its no-op default, so a run that never opts in is
byte-for-byte unaffected. Independent of difficulty modes (easy/normal/
hard) -- the two compose like any other pair of multipliers.
"""

import dataclasses
from dataclasses import dataclass

from run.run_escalation import FloorEscalation

MAX_ASCENSION = 10


@dataclass(frozen=True)
class AscensionModifiers:
    # Folded into the floor's FloorEscalation (apply_to_escalation below).
    enemy_hp_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    elite_hp_multiplier: float = 1.0
    boss_hp_multiplier: float = 1.0
    starting_gold_multiplier: float = 1.0
    # The run's starting lives, captured on its first node (Game._load_combat_node).
    starting_lives_multiplier: float = 1.0
    # A Rest node's heal (Game._enter_rest_node).
    rest_heal_multiplier: float = 1.0
    # Every Shop price (Game._shop_price_multiplier).
    shop_price_multiplier: float = 1.0
    # Added to rewards.TOWER_REWARD_COUNT (Game._enter_reward_screen).
    reward_tower_count_delta: int = 0


@dataclass(frozen=True)
class AscensionLevel:
    description: str
    changes: dict[str, float]


# ASCENSION_LEVELS[i] is what Ascension i+1 adds. Multiplicative fields
# multiply into whatever lower levels already set; reward_tower_count_delta
# adds instead (see modifiers_for).
ASCENSION_LEVELS = (
    AscensionLevel("Elites have 20% more HP.", {"elite_hp_multiplier": 1.2}),
    AscensionLevel("Enemies have 10% more HP.", {"enemy_hp_multiplier": 1.1}),
    AscensionLevel("Start every floor with 10% less gold.", {"starting_gold_multiplier": 0.9}),
    AscensionLevel("Bosses have 25% more HP.", {"boss_hp_multiplier": 1.25}),
    AscensionLevel("Rest sites heal 40% less.", {"rest_heal_multiplier": 0.6}),
    AscensionLevel("Start the run with 25% fewer lives.", {"starting_lives_multiplier": 0.75}),
    AscensionLevel("Enemies move 8% faster.", {"enemy_speed_multiplier": 1.08}),
    AscensionLevel("Shop prices are 25% higher.", {"shop_price_multiplier": 1.25}),
    AscensionLevel("Post-combat rewards offer one fewer tower.", {"reward_tower_count_delta": -1}),
    AscensionLevel("Enemies have another 10% more HP.", {"enemy_hp_multiplier": 1.1}),
)
assert len(ASCENSION_LEVELS) == MAX_ASCENSION

_ADDITIVE_FIELDS = frozenset({"reward_tower_count_delta"})


def modifiers_for(level: int) -> AscensionModifiers:
    """Every rule from Ascension 1 up to `level`, folded together."""
    values: dict[str, float] = {}
    defaults = AscensionModifiers()
    for ascension_level in ASCENSION_LEVELS[:level]:
        for name, change in ascension_level.changes.items():
            current = values.get(name, getattr(defaults, name))
            values[name] = current + change if name in _ADDITIVE_FIELDS else current * change
    for name in _ADDITIVE_FIELDS & values.keys():
        values[name] = int(values[name])
    return AscensionModifiers(**values)  # type: ignore[arg-type]


def apply_to_escalation(escalation: FloorEscalation, level: int, node_type: str) -> FloorEscalation:
    """`escalation` with this ascension's enemy/starting-gold rules
    multiplied in -- elite_hp/boss_hp only for that node type."""
    mods = modifiers_for(level)
    hp = mods.enemy_hp_multiplier
    if node_type == "elite":
        hp *= mods.elite_hp_multiplier
    elif node_type == "boss":
        hp *= mods.boss_hp_multiplier
    return dataclasses.replace(
        escalation,
        enemy_hp_multiplier=escalation.enemy_hp_multiplier * hp,
        enemy_speed_multiplier=escalation.enemy_speed_multiplier * mods.enemy_speed_multiplier,
        starting_gold_multiplier=escalation.starting_gold_multiplier * mods.starting_gold_multiplier,
    )


def clamp(level: int) -> int:
    return max(0, min(MAX_ASCENSION, level))
