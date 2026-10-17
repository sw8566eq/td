"""Proving Grounds -- an optional challenge fight on the run's map.

A `"challenge"` map node is an ordinary fight with one constraint drawn
from CHALLENGES, in exchange for a better reward if the player wins it
without breaking the constraint: a pick-one-of-RELIC_CHOICE_COUNT relic
choice on the reward screen plus bonus shop currency (bonus_shop_currency).

Registry shape as usual: each Challenge is plain data, and each field is
read generically by the one place that enforces it -- the placement gate
(max_towers, allowed_tower_count), the upgrade gate (allows_upgrades), the
floor's FloorEscalation (enemy_speed_multiplier/enemy_gold_multiplier, via
apply_to_escalation), the life-loss choke point (leak_limit) and the
renderer (hides_intel). Game never branches on which challenge it is.

The roll is re-derived on demand from the node's own id (Game._node_
challenge, via _run_rng), never stored -- the same "no RNG state
serialized" rule Elite affixes follow -- so the map tooltip, the floor
load and a resumed save always agree. See docs/agents/run-map.md
"Proving Grounds".
"""

import dataclasses
import random
from collections.abc import Sequence
from dataclasses import dataclass

from run.run_escalation import FloorEscalation

# How many relics the win's pick-one row offers.
RELIC_CHOICE_COUNT = 2
# The win's bonus shop currency: flat + per point of run depth, the same
# "flat + growth" shape as a Treasure node's own payout.
BONUS_SHOP_CURRENCY_BASE, BONUS_SHOP_CURRENCY_PER_DEPTH = 20, 2


@dataclass(frozen=True)
class Challenge:
    key: str
    display_name: str
    description: str
    # Placement gate: at most this many towers on the board at once.
    max_towers: int | None = None
    # Placement gate: only this many of the run's damaging tower types may
    # be built, chosen by the node's own rng (roll_for_node).
    allowed_tower_count: int | None = None
    # Upgrade gate: False blocks both upgrades and specializations.
    allows_upgrades: bool = True
    # Folded into the floor's FloorEscalation (apply_to_escalation).
    enemy_speed_multiplier: float = 1.0
    enemy_gold_multiplier: float = 1.0
    # Life-loss gate: leaks past this many cost no lives but fail the
    # challenge (the run loses at most this many lives on the floor).
    leak_limit: int | None = None
    # Renderer: no next-wave preview and no range rings.
    hides_intel: bool = False


CHALLENGES = {
    "skeleton_crew": Challenge(
        "skeleton_crew", "Skeleton Crew", "At most 4 towers on the board at once.", max_towers=4,
    ),
    "no_upgrades": Challenge(
        "no_upgrades", "No Upgrades", "Towers can't be upgraded or specialized this floor.", allows_upgrades=False,
    ),
    "narrow_front": Challenge(
        "narrow_front", "Narrow Front", "Only two of your tower types may be built.", allowed_tower_count=2,
    ),
    "double_time": Challenge(
        "double_time", "Double Time", "Enemies move 35% faster but drop 50% more gold.",
        enemy_speed_multiplier=1.35, enemy_gold_multiplier=1.5,
    ),
    "glass_gate": Challenge(
        "glass_gate", "Glass Gate", "Only 3 lives at stake: a 4th leak costs nothing but fails the challenge.",
        leak_limit=3,
    ),
    "fog_of_war": Challenge(
        "fog_of_war", "Fog of War", "No wave preview and no range rings.", hides_intel=True,
    ),
}
CHALLENGE_ORDER = list(CHALLENGES)


@dataclass(frozen=True)
class ChallengeRoll:
    """One node's rolled challenge plus whatever it drew for itself --
    `allowed_towers` is the Narrow Front-style build list (None = no
    restriction)."""
    challenge: Challenge
    allowed_towers: frozenset[str] | None = None

    def summary(self, display_names: dict[str, str]) -> str:
        """"Name: description" plus the allowed tower names, if any -- the
        one line the map tooltip, the sidebar and the refusal toasts share."""
        text = f"{self.challenge.display_name}: {self.challenge.description}"
        if self.allowed_towers is not None:
            names = ", ".join(sorted(display_names.get(name, name) for name in self.allowed_towers))
            text += f" Allowed: {names}."
        return text


def roll_for_node(rng: random.Random, candidate_towers: Sequence[str]) -> ChallengeRoll:
    """A node's challenge, then (drawn after it, on the same rng) its
    allowed tower types out of `candidate_towers` -- the run's held
    damaging types, in a stable order. Fewer candidates than the limit
    leaves the build list unrestricted."""
    challenge = CHALLENGES[CHALLENGE_ORDER[rng.randrange(len(CHALLENGE_ORDER))]]
    allowed = None
    count = challenge.allowed_tower_count
    if count is not None and len(candidate_towers) > count:
        allowed = frozenset(rng.sample(list(candidate_towers), count))
    return ChallengeRoll(challenge, allowed)


def apply_to_escalation(escalation: FloorEscalation, challenge: Challenge) -> FloorEscalation:
    return dataclasses.replace(
        escalation,
        enemy_speed_multiplier=escalation.enemy_speed_multiplier * challenge.enemy_speed_multiplier,
        enemy_gold_multiplier=escalation.enemy_gold_multiplier * challenge.enemy_gold_multiplier,
    )


def placement_refusal(
    roll: ChallengeRoll, tower_name: str, towers_on_board: int, display_names: dict[str, str],
) -> str | None:
    """Why placing a `tower_name` is refused under `roll`, or None if it's allowed."""
    challenge = roll.challenge
    if challenge.max_towers is not None and towers_on_board >= challenge.max_towers:
        return f"{challenge.display_name}: at most {challenge.max_towers} towers on the board"
    if roll.allowed_towers is not None and tower_name not in roll.allowed_towers:
        names = " and ".join(sorted(display_names.get(name, name) for name in roll.allowed_towers))
        return f"{challenge.display_name}: only {names} can be built"
    return None


def upgrade_refusal(roll: ChallengeRoll) -> str | None:
    """Why upgrading/specializing is refused under `roll`, or None."""
    if not roll.challenge.allows_upgrades:
        return f"{roll.challenge.display_name}: no upgrades this floor"
    return None


def status_line(roll: ChallengeRoll, towers_on_board: int, leaks: int, failed: bool) -> str:
    """The fight's short sidebar readout -- the challenge's name plus
    whichever live count it gates (towers, leaks), or FAILED once broken.
    Short on purpose: the full rule is on the map tooltip and in every
    refusal toast."""
    challenge = roll.challenge
    if failed:
        return f"{challenge.display_name}: FAILED"
    if challenge.leak_limit is not None:
        return f"{challenge.display_name}: {leaks}/{challenge.leak_limit} leaks"
    if challenge.max_towers is not None:
        return f"{challenge.display_name}: {towers_on_board}/{challenge.max_towers} towers"
    if roll.allowed_towers is not None:
        return f"{challenge.display_name}: {len(roll.allowed_towers)} types"
    return challenge.display_name


def bonus_shop_currency(depth: int) -> int:
    """The win's bonus shop currency at this run depth."""
    return BONUS_SHOP_CURRENCY_BASE + BONUS_SHOP_CURRENCY_PER_DEPTH * depth
