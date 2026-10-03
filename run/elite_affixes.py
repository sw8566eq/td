"""Elite affixes -- every Elite map node rolls one named modifier, so an
Elite is a distinct threat to plan around rather than just "the same
fight, harder" (Slay the Spire's Gremlin Nob vs. Lagavulin, in spirit).

The roll is re-derived on demand from the node's own id (Game._elite_
affix, via _run_rng), never stored on the map -- the same "no RNG state
serialized" rule every other per-node pick follows -- and it's shown on
the map tooltip before the player commits, matching this game's "nothing
hidden" map (see ui._draw_map_node_tooltip).

Registry shape as usual: AFFIXES is a {key: EliteAffix} dict of plain
multipliers, folded into the floor's FloorEscalation (apply_to_escalation)
and, for count_multiplier, into a private copy of the level's own
wave_specs (scale_wave_counts) -- Game never branches on which affix it is.
"""

import dataclasses
import math
import random
from dataclasses import dataclass

from run.run_escalation import FloorEscalation


@dataclass(frozen=True)
class EliteAffix:
    key: str
    display_name: str
    description: str
    hp_multiplier: float = 1.0
    speed_multiplier: float = 1.0
    gold_multiplier: float = 1.0
    # Every non-boss enemy count in every wave, rounded up.
    count_multiplier: float = 1.0
    # Enemy-side traits, copied onto every spawned enemy via WaveManager
    # (Game._apply_affix_traits): heal this fraction of max HP per second,
    # and scale every hit taken.
    regen_fraction_per_second: float = 0.0
    damage_taken_multiplier: float = 1.0
    # Every ground enemy burrows under path traps and Barricades, and/or
    # batters Barricades this many times harder (WaveManager.enemy_burrows/
    # enemy_breach_multiplier).
    burrows: bool = False
    breach_multiplier: float = 1.0


AFFIXES = {
    "swift": EliteAffix("swift", "Swift", "Enemies move 25% faster.", speed_multiplier=1.25),
    "hulking": EliteAffix(
        "hulking", "Hulking", "Enemies have 35% more HP but move 10% slower.",
        hp_multiplier=1.35, speed_multiplier=0.9,
    ),
    "swarming": EliteAffix(
        "swarming", "Swarming", "50% more enemies per wave, each with 20% less HP.",
        hp_multiplier=0.8, count_multiplier=1.5,
    ),
    "gilded": EliteAffix(
        "gilded", "Gilded", "Enemies have 25% more HP but drop 60% more gold.",
        hp_multiplier=1.25, gold_multiplier=1.6,
    ),
    "regenerating": EliteAffix(
        "regenerating", "Regenerating", "Enemies heal 4% of their max HP every second.",
        regen_fraction_per_second=0.04,
    ),
    "armored": EliteAffix(
        "armored", "Armored", "Enemies take 25% less damage from every hit.",
        damage_taken_multiplier=0.75,
    ),
    "tunneling": EliteAffix(
        "tunneling", "Tunneling", "Every ground enemy burrows: Spike Traps, Tar Pits and Barricades can't touch them.",
        burrows=True,
    ),
    "siegebreakers": EliteAffix(
        "siegebreakers", "Siegebreakers", "Enemies batter Barricades 3x as hard and have 10% more HP.",
        breach_multiplier=3.0, hp_multiplier=1.1,
    ),
}
AFFIX_ORDER = list(AFFIXES)

# Boss nodes roll one of these instead -- the same EliteAffix shape (so
# every consumer handles both), each a named boss with its own flavor, like
# Slay the Spire's several bosses per act.
BOSS_AFFIXES = {
    "juggernaut": EliteAffix(
        "juggernaut", "The Juggernaut", "Enemies have 15% more HP and take 10% less damage.",
        hp_multiplier=1.15, damage_taken_multiplier=0.9,
    ),
    "broodmother": EliteAffix(
        "broodmother", "The Broodmother", "40% more enemies per wave, each with 10% less HP.",
        hp_multiplier=0.9, count_multiplier=1.4,
    ),
    "warlord": EliteAffix("warlord", "The Warlord", "Enemies move 15% faster.", speed_multiplier=1.15),
    "lich": EliteAffix(
        "lich", "The Lich", "Enemies heal 3% of their max HP every second and move 5% faster.",
        regen_fraction_per_second=0.03, speed_multiplier=1.05,
    ),
    "golden_tyrant": EliteAffix(
        "golden_tyrant", "The Golden Tyrant", "Enemies have 20% more HP but drop double gold.",
        hp_multiplier=1.2, gold_multiplier=2.0,
    ),
}
BOSS_AFFIX_ORDER = list(BOSS_AFFIXES)


def roll_affix(rng: random.Random) -> str:
    return AFFIX_ORDER[rng.randrange(len(AFFIX_ORDER))]


def roll_boss_affix(rng: random.Random) -> str:
    return BOSS_AFFIX_ORDER[rng.randrange(len(BOSS_AFFIX_ORDER))]


def apply_to_escalation(escalation: FloorEscalation, affix: EliteAffix) -> FloorEscalation:
    return dataclasses.replace(
        escalation,
        enemy_hp_multiplier=escalation.enemy_hp_multiplier * affix.hp_multiplier,
        enemy_speed_multiplier=escalation.enemy_speed_multiplier * affix.speed_multiplier,
        enemy_gold_multiplier=escalation.enemy_gold_multiplier * affix.gold_multiplier,
    )


def scale_wave_counts(
    wave_specs: list[dict[object, dict[str, int]]], multiplier: float, unscaled_species: frozenset[str],
) -> list[dict[object, dict[str, int]]]:
    """A new wave_specs list with every count multiplied (rounded up) --
    except `unscaled_species` (the boss tiers: a Swarming elite still has
    one boss, not two)."""
    return [
        {
            cell: {
                name: count if name in unscaled_species else math.ceil(count * multiplier)
                for name, count in composition.items()
            }
            for cell, composition in wave.items()
        }
        for wave in wave_specs
    ]
