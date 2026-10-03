"""Potions -- single-use, mid-fight consumables a run carries between
floors. A run holds at most POTION_SLOTS of them
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

from run.relics import RELICS
from run.run_state import RunState
from support.rng_sampling import sample_up_to

# The base belt size -- a Potion Belt-style relic adds more (slot_count).
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
SMOKE_BOMB_KNOCKBACK = 120.0
VENOM_VIAL_HP_FRACTION_PER_TICK = 0.04
VENOM_VIAL_BOSS_HP_FRACTION_PER_TICK = 0.01
VENOM_VIAL_DURATION = 6.0


@dataclass(frozen=True)
class Potion:
    key: str
    display_name: str
    description: str
    use: Callable[[Any], None]
    # Only affects enemies on the field -- Game.use_potion refuses it (and
    # keeps the potion) while there are none, rather than wasting it.
    needs_enemies: bool = True


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
    """Battle gold a Liquid Gold grants at run depth `row` (RunState.depth) -- grows
    the same way every floor's own gold economy does (run_escalation.py),
    so it stays worth a slot late in a run."""
    return LIQUID_GOLD_BASE + LIQUID_GOLD_PER_ROW * row


def _liquid_gold(game: Any) -> None:
    depth = game.active_run.depth if game.active_run is not None else 0
    game.economy.add_gold(liquid_gold_amount(depth))


def _mending_salve(game: Any) -> None:
    game.economy.lives += MENDING_SALVE_LIVES


def _smoke_bomb(game: Any) -> None:
    for enemy in game.enemies:
        enemy.apply_knockback(SMOKE_BOMB_KNOCKBACK)


def _venom_vial(game: Any) -> None:
    for enemy in game.enemies:
        fraction = VENOM_VIAL_BOSS_HP_FRACTION_PER_TICK if enemy.IS_BOSS else VENOM_VIAL_HP_FRACTION_PER_TICK
        enemy.apply_poison(enemy.max_hp * fraction, 1.0, VENOM_VIAL_DURATION)


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
        _liquid_gold, needs_enemies=False,
    ),
    "mending_salve": Potion(
        "mending_salve", "Mending Salve",
        f"Restore {MENDING_SALVE_LIVES} lives.",
        _mending_salve, needs_enemies=False,
    ),
    "overclock_elixir": Potion(
        "overclock_elixir", "Overclock Elixir",
        f"Every tower fires {round((OVERCLOCK_FIRE_RATE_MULTIPLIER - 1) * 100)}% faster "
        f"for {OVERCLOCK_DURATION:g}s.",
        _overclock, needs_enemies=False,
    ),
    "smoke_bomb": Potion(
        "smoke_bomb", "Smoke Screen",
        f"Shove every enemy on the field {SMOKE_BOMB_KNOCKBACK:g}px back along its route.",
        _smoke_bomb,
    ),
    "venom_vial": Potion(
        "venom_vial", "Venom Vial",
        f"Poison every enemy for {round(VENOM_VIAL_HP_FRACTION_PER_TICK * 100)}% of its max HP per second "
        f"for {VENOM_VIAL_DURATION:g}s ({round(VENOM_VIAL_BOSS_HP_FRACTION_PER_TICK * 100)}% vs bosses).",
        _venom_vial,
    ),
}

POTION_ORDER = list(POTIONS)


def random_potion(rng: random.Random) -> str:
    """One potion key, uniformly from the whole registry -- unlike relics/
    towers, potions are consumed, so a run can hold duplicates and nothing
    is ever excluded."""
    return sample_up_to(rng, POTION_ORDER, 1)[0]


def slot_count(run: RunState) -> int:
    """POTION_SLOTS plus every held relic's potion_slot_bonus (Potion
    Belt)."""
    return POTION_SLOTS + sum(RELICS[key].potion_slot_bonus for key in run.relics)


def potions_blocked(run: RunState) -> bool:
    """Whether a Sealed Cask-style boss relic (Relic.blocks_potions)
    forbids taking any new potion."""
    return any(RELICS[key].blocks_potions for key in run.relics)


def has_free_slot(run: RunState) -> bool:
    """Room for one more potion -- never, while potions_blocked."""
    if potions_blocked(run):
        return False
    return len(run.potions) < slot_count(run)
