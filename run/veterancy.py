"""Tower veterancy -- every tower *type* in a run earns battle experience
and ranks up, getting stronger for the rest of the run.

Experience is kills: when a floor is cleared (Game._advance_run_floor) each
tower type gains the kills of every tower of that type that fought there,
sold ones included. Clears only -- a restarted or lost floor earns nothing,
so experience can't be farmed. Towers that buff rather than kill (a class
with a nonzero VETERANCY_ASSIST_FRACTION, e.g. Support and Beacon) earn
that fraction of the floor's total kills as "assists" instead.

RunState.tower_xp holds the totals; rank_for() turns one into a rank
(0..len(RANKS)), and Tower.apply_veterancy(rank) is the one place a rank
becomes a stat bonus, so each tower class decides what its experience
improves without Game ever branching on tower type.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VeterancyRank:
    name: str
    xp_required: int


RANKS = (
    VeterancyRank("Blooded", 25),
    VeterancyRank("Seasoned", 75),
    VeterancyRank("Veteran", 175),
    VeterancyRank("Legendary", 350),
)
MAX_RANK = len(RANKS)

# What one rank is worth -- read by Tower.apply_veterancy and its overrides.
DAMAGE_BONUS_PER_RANK = 0.06
AURA_BONUS_PER_RANK = 0.06
MARK_BONUS_PER_RANK = 0.03
# The rank an Old Guard-style relic (Relic.veteran_fire_rate_bonus) needs.
VETERAN_RANK = 3


def rank_for(xp: float) -> int:
    """How many ranks `xp` experience has earned."""
    return sum(1 for rank in RANKS if xp >= rank.xp_required)


def rank_name(rank: int) -> str:
    return RANKS[rank - 1].name if rank else "Recruit"


def next_rank_xp(xp: float) -> int | None:
    """Experience needed for the next rank, or None at MAX_RANK."""
    rank = rank_for(xp)
    return None if rank >= MAX_RANK else RANKS[rank].xp_required


def floor_xp(kills_by_type: dict[str, int], assist_fractions: dict[str, float], multiplier: float = 1.0) -> dict[str, float]:
    """Experience each tower type present on a just-cleared floor earns:
    its own kills, plus its assist fraction of every kill on the floor,
    all scaled by `multiplier` (a Drill Sergeant-style relic)."""
    total_kills = sum(kills_by_type.values())
    return {
        tower_type: (kills + assist_fractions.get(tower_type, 0.0) * total_kills) * multiplier
        for tower_type, kills in kills_by_type.items()
    }
