"""Floor-by-floor difficulty escalation for a roguelike run.

Composed as an *additional* factor alongside difficulty.DIFFICULTY_MODES'
own multipliers -- never replacing them, per difficulty.py's own "extra
factor" rule -- so a run on Hard is still harder than the same run on Easy
at every floor, just also escalating further the deeper it goes.

Not a fixed-key registry like DIFFICULTY_MODES: floor_index is unbounded
once the final floor's own endless tail is running (see waves.py's
_default_endless_wave, which already provides the escalation *within* one
floor once its authored waves run out). This is the *between-floors*
escalation layered on top of that, growing once per floor rather than once
per wave -- floor 0 is always exactly 1.0x every multiplier, so a run's
first floor plays identically to that same level played standalone.
"""

from dataclasses import dataclass

# Tuned so hp grows fastest -- that's what a deck of newly-drafted towers
# most needs to keep pace with as a run goes on -- while gold grows a
# little too, so a longer run's economy doesn't fall behind its own
# escalating threat, and speed grows slowest since a faster-moving enemy
# is harder to compensate for with towers alone than a tankier one.
_HP_GROWTH_PER_FLOOR = 0.12
_SPEED_GROWTH_PER_FLOOR = 0.02
_GOLD_GROWTH_PER_FLOOR = 0.05

# An Elite map node's own extra bump on top of whatever its row already
# escalates to (see apply_elite_multiplier below) -- placeholder numbers,
# tunable once there's real playtesting to tune against, same spirit as
# shop.py's own TOWER_PRICE/RELIC_PRICE comment. Gold scales with hp (a
# tougher fight should pay out more in the fight itself too, on top of
# shop.ELITE_INCOME_MULTIPLIER's own bonus at the *floor-clear* level) --
# speed barely moves, since a faster-*and* tankier enemy compounds harder
# than either alone.
ELITE_HP_MULTIPLIER = 1.5
ELITE_SPEED_MULTIPLIER = 1.1
ELITE_GOLD_MULTIPLIER = 1.5


@dataclass(frozen=True)
class FloorEscalation:
    enemy_hp_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    enemy_gold_multiplier: float = 1.0


def escalation_for_floor(floor_index):
    """FloorEscalation for the floor_index-th floor of a run (0-based) --
    for a branching run this is the current node's *row*, not a linear
    floor count (see RunState.current_row), but the formula itself doesn't
    care which int it's handed."""
    return FloorEscalation(
        enemy_hp_multiplier=1.0 + _HP_GROWTH_PER_FLOOR * floor_index,
        enemy_speed_multiplier=1.0 + _SPEED_GROWTH_PER_FLOOR * floor_index,
        enemy_gold_multiplier=1.0 + _GOLD_GROWTH_PER_FLOOR * floor_index,
    )


def apply_elite_multiplier(escalation):
    """Layers an Elite map node's own extra bump on top of an already-
    computed FloorEscalation -- multiplicative, the same "extra factor,
    never replacing" rule this module's own docstring states for
    difficulty.py/relics.py, so an Elite node at row 3 is harder than a
    plain Combat node at that same row, not just harder than row 0."""
    return FloorEscalation(
        enemy_hp_multiplier=escalation.enemy_hp_multiplier * ELITE_HP_MULTIPLIER,
        enemy_speed_multiplier=escalation.enemy_speed_multiplier * ELITE_SPEED_MULTIPLIER,
        enemy_gold_multiplier=escalation.enemy_gold_multiplier * ELITE_GOLD_MULTIPLIER,
    )
