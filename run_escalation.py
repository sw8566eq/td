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


@dataclass(frozen=True)
class FloorEscalation:
    enemy_hp_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    enemy_gold_multiplier: float = 1.0


def escalation_for_floor(floor_index):
    """FloorEscalation for the floor_index-th floor of a run (0-based)."""
    return FloorEscalation(
        enemy_hp_multiplier=1.0 + _HP_GROWTH_PER_FLOOR * floor_index,
        enemy_speed_multiplier=1.0 + _SPEED_GROWTH_PER_FLOOR * floor_index,
        enemy_gold_multiplier=1.0 + _GOLD_GROWTH_PER_FLOOR * floor_index,
    )
