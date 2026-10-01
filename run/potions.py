"""Potions -- single-use, mid-fight consumables a run carries between
floors, Slay the Spire style. A run holds at most POTION_SLOTS of them
(RunState.potions); they drop from post-combat rewards (see rewards.py)
and are used by clicking a slot in the sidebar while a floor is being
played (Game.use_potion).

Same registry shape as relics.py/events.py: `POTIONS` is a `{key:
Potion}` dict, and each entry carries its own `use` function, so adding a
potion is one function plus one registry line -- Game.use_potion never
branches on which potion it is. A `use` function receives the live Game
(typed Any here, since this module stays pygame-free and strictly typed)
and only ever touches its board-level state: enemies, towers, economy,
and the overclock timer.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from support.rng_sampling import sample_up_to

POTION_SLOTS = 3

# Chance an ordinary Combat floor's reward includes a potion; an Elite
# floor always drops one (see rewards.build_combat_reward).
COMBAT_POTION_DROP_CHANCE = 0.4

FIRE_BOMB_HP_FRACTION = 0.30
# A boss (IS_BOSS) takes a much smaller bite, so one potion can't trivialize
# the fight a whole floor is built around.
FIRE_BOMB_BOSS_HP_FRACTION = 0.10
FROST_FLASK_SLOW_FACTOR = 0.4
FROST_FLASK_DURATION = 6.0
MARKING_DUST_MULTIPLIER = 1.5
MARKING_DUST_DURATION = 8.0
LIQUID_GOLD_BASE = 60
LIQUID_GOLD_PER_ROW = 20
MENDING_SALVE_LIVES = 3
OVERCLOCK_FIRE_RATE_MULTIPLIER = 1.5
OVERCLOCK_DURATION = 10.0


@dataclass(frozen=True)
class Potion:
    key: str
    display_name: str
    description: str
    use: Callable[[Any], None]


def _fire_bomb(game: Any) -> None:
    for enemy in game.enemies:
        fraction = FIRE_BOMB_BOSS_HP_FRACTION if enemy.IS_BOSS else FIRE_BOMB_HP_FRACTION
        enemy.take_damage(enemy.max_hp * fraction)


def _frost_flask(game: Any) -> None:
    for enemy in game.enemies:
        enemy.apply_slow(FROST_FLASK_SLOW_FACTOR, FROST_FLASK_DURATION)


def _marking_dust(game: Any) -> None:
    for enemy in game.enemies:
        enemy.apply_mark(MARKING_DUST_MULTIPLIER, MARKING_DUST_DURATION)


def liquid_gold_amount(row: int) -> int:
    """Battle gold a Liquid Gold grants on map row `row` -- grows with depth
    the same way every floor's own gold economy does (run_escalation.py),
    so it stays worth a slot late in a run."""
    return LIQUID_GOLD_BASE + LIQUID_GOLD_PER_ROW * row


def _liquid_gold(game: Any) -> None:
    row = game.active_run.current_row if game.active_run is not None else 0
    game.economy.add_gold(liquid_gold_amount(row))


def _mending_salve(game: Any) -> None:
    game.economy.lives += MENDING_SALVE_LIVES


def _overclock(game: Any) -> None:
    game.overclock_timer = max(game.overclock_timer, OVERCLOCK_DURATION)


POTIONS = {
    "fire_bomb": Potion(
        "fire_bomb", "Fire Bomb",
        f"Blast every enemy on the field for {round(FIRE_BOMB_HP_FRACTION * 100)}% of its max HP "
        f"({round(FIRE_BOMB_BOSS_HP_FRACTION * 100)}% vs bosses).",
        _fire_bomb,
    ),
    "frost_flask": Potion(
        "frost_flask", "Frost Flask",
        f"Slow every enemy on the field to {round(FROST_FLASK_SLOW_FACTOR * 100)}% speed "
        f"for {FROST_FLASK_DURATION:g}s.",
        _frost_flask,
    ),
    "marking_dust": Potion(
        "marking_dust", "Marking Dust",
        f"Mark every enemy on the field: +{round((MARKING_DUST_MULTIPLIER - 1) * 100)}% damage taken "
        f"for {MARKING_DUST_DURATION:g}s.",
        _marking_dust,
    ),
    "liquid_gold": Potion(
        "liquid_gold", "Liquid Gold",
        f"Gain {LIQUID_GOLD_BASE} battle gold, +{LIQUID_GOLD_PER_ROW} per floor deep.",
        _liquid_gold,
    ),
    "mending_salve": Potion(
        "mending_salve", "Mending Salve",
        f"Restore {MENDING_SALVE_LIVES} lives.",
        _mending_salve,
    ),
    "overclock_elixir": Potion(
        "overclock_elixir", "Overclock Elixir",
        f"Every tower fires {round((OVERCLOCK_FIRE_RATE_MULTIPLIER - 1) * 100)}% faster "
        f"for {OVERCLOCK_DURATION:g}s.",
        _overclock,
    ),
}

POTION_ORDER = list(POTIONS)


def random_potion(rng: random.Random) -> str:
    """One potion key, uniformly from the whole registry -- unlike relics/
    towers, potions are consumed, so a run can hold duplicates and nothing
    is ever excluded."""
    return sample_up_to(rng, POTION_ORDER, 1)[0]


def has_free_slot(held: list[str]) -> bool:
    return len(held) < POTION_SLOTS
