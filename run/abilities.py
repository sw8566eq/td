"""Commander abilities -- each Commander's one signature, activated move.

Every Commander (commanders.py) names one `ABILITIES` entry. Mid-fight the
player fires it from the sidebar's ability button or its fixed hotkey
(Game.activate_ability); once used it is spent until `cooldown_waves`
waves have been cleared (RunState.ability_cooldown, ticked down by Game at
every wave clear and carried across floors). There is no resource to
spend and nothing to draw: a Commander has exactly one ability, always the
same one, and the only decision is *when*.

Same registry shape as potions.py: each entry carries its own `use`
function, so adding an ability is one function plus one registry line --
Game never branches on which ability it is. A `use` function receives the
live Game (typed Any here, since this module stays pygame-free and
strictly typed) plus the aimed point for a `targeted` ability, touches
only board-level state (enemies, towers, run, timers), and returns whether
it took effect: False refuses the activation (Game toasts
`unusable_message` and keeps the charge), so a `use` must check before it
changes anything.

A timed ability (`duration` > 0) also leaves Game.ability_timer running;
while it does, Game calls `tower_buff(tower, type_key)` on every tower
each frame, right after resetting that tower's ability multipliers --
the same per-frame reset-then-apply shape the Overclock Elixir uses, so a
tower placed mid-effect is buffed too.

Damage abilities follow the potions' boss precedent: a boss (IS_BOSS)
takes a much smaller fraction, so an ability softens a boss fight but
never trivializes it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Point = tuple[float, float]

# --- Warden: Hold the Gate ---
HOLD_THE_GATE_CHARGES = 3
HOLD_THE_GATE_COOLDOWN = 3
# --- Alchemist: Toxic Downpour ---
TOXIC_DOWNPOUR_RADIUS = 110.0
TOXIC_DOWNPOUR_HP_FRACTION_PER_TICK = 0.06
TOXIC_DOWNPOUR_BOSS_HP_FRACTION_PER_TICK = 0.01
TOXIC_DOWNPOUR_DURATION = 6.0
TOXIC_DOWNPOUR_COOLDOWN = 2
# --- Marksman: Called Shot ---
CALLED_SHOT_DAMAGE_MULTIPLIER = 2.0
CALLED_SHOT_DURATION = 6.0
CALLED_SHOT_TOWERS = ("basic", "sniper")
CALLED_SHOT_COOLDOWN = 2
# --- Engineer: Rapid Repairs ---
RAPID_REPAIRS_FIRE_RATE_MULTIPLIER = 1.4
RAPID_REPAIRS_DURATION = 8.0
RAPID_REPAIRS_COOLDOWN = 3
# --- Stormcaller: Thunderhead ---
THUNDERHEAD_TARGETS = 8
THUNDERHEAD_HP_FRACTION = 0.35
THUNDERHEAD_BOSS_HP_FRACTION = 0.06
THUNDERHEAD_COOLDOWN = 2
# --- Trapmaster: Caltrops ---
CALTROPS_SLOW_FACTOR = 0.45
CALTROPS_DURATION = 6.0
CALTROPS_COOLDOWN = 2
# --- Skywatch: Downdraft ---
DOWNDRAFT_DURATION = 6.0
DOWNDRAFT_SLOW_FACTOR = 0.7
DOWNDRAFT_COOLDOWN = 2


@dataclass(frozen=True)
class Ability:
    key: str
    display_name: str
    description: str
    cooldown_waves: int
    use: Callable[[Any, Point | None], bool]
    unusable_message: str = ""
    # Aimed: activating enters a targeting mode (click the field to fire,
    # right-click/Esc to cancel), and `use` receives the clicked point.
    targeted: bool = False
    # The aimed area's radius -- what the targeting preview ring draws.
    radius: float = 0.0
    # Seconds Game.ability_timer runs after a successful use (0 = instant).
    duration: float = 0.0
    tower_buff: Callable[[Any, str], None] | None = None
    # What RunState.ability_charges counts, for the button's status line
    # ("2 leaks blocked left"); empty for an ability that never sets it.
    charge_label: str = ""


def _live(enemy: Any) -> bool:
    return not enemy.is_dead and not enemy.reached_goal


def _airborne(enemy: Any) -> bool:
    """entities.enemy.is_airborne, duck-typed so this module stays pygame-free."""
    return bool(getattr(enemy, "is_flying", False)) and getattr(enemy, "ground_timer", 0.0) <= 0


def _hold_the_gate(game: Any, target: Point | None) -> bool:
    run = game.active_run
    if run.ability_charges >= HOLD_THE_GATE_CHARGES:
        return False
    run.ability_charges = HOLD_THE_GATE_CHARGES
    return True


def _toxic_downpour(game: Any, target: Point | None) -> bool:
    assert target is not None
    x, y = target
    victims = [enemy for enemy in game.enemies if _live(enemy)
               and (enemy.pos.x - x) ** 2 + (enemy.pos.y - y) ** 2 <= TOXIC_DOWNPOUR_RADIUS ** 2]
    if not victims:
        return False
    for enemy in victims:
        fraction = TOXIC_DOWNPOUR_BOSS_HP_FRACTION_PER_TICK if enemy.IS_BOSS else TOXIC_DOWNPOUR_HP_FRACTION_PER_TICK
        enemy.apply_poison(enemy.max_hp * fraction, 1.0, TOXIC_DOWNPOUR_DURATION)
    game.ability_flash(target, TOXIC_DOWNPOUR_RADIUS)
    return True


def _any_enemies(game: Any, target: Point | None) -> bool:
    """A timed tower buff only worth starting with something to shoot at --
    Game starts the timer."""
    return any(_live(enemy) for enemy in game.enemies)


def _called_shot_buff(tower: Any, type_key: str) -> None:
    if type_key in CALLED_SHOT_TOWERS:
        tower.ability_damage_multiplier = CALLED_SHOT_DAMAGE_MULTIPLIER


def _rapid_repairs(game: Any, target: Point | None) -> bool:
    for tower in game.towers:
        if getattr(tower, "max_hp", None) is not None:
            tower.hp = tower.max_hp
    return True


def _rapid_repairs_buff(tower: Any, type_key: str) -> None:
    tower.ability_fire_rate_multiplier = RAPID_REPAIRS_FIRE_RATE_MULTIPLIER


def thunderhead_targets(enemies: list[Any]) -> list[Any]:
    """The THUNDERHEAD_TARGETS live enemies with the most current HP --
    ties broken by whoever is furthest along the path, so the pick is
    deterministic."""
    live = [enemy for enemy in enemies if _live(enemy)]
    live.sort(key=lambda enemy: (enemy.hp, enemy.distance_traveled), reverse=True)
    return live[:THUNDERHEAD_TARGETS]


def _thunderhead(game: Any, target: Point | None) -> bool:
    struck = thunderhead_targets(game.enemies)
    if not struck:
        return False
    for enemy in struck:
        fraction = THUNDERHEAD_BOSS_HP_FRACTION if enemy.IS_BOSS else THUNDERHEAD_HP_FRACTION
        enemy.take_damage(enemy.max_hp * fraction)
        game.ability_flash((enemy.pos.x, enemy.pos.y), 26.0)
    return True


def _caltrops(game: Any, target: Point | None) -> bool:
    """Ground enemies only: a flyer passes over, a burrower passes under."""
    victims = [enemy for enemy in game.enemies
               if _live(enemy) and not _airborne(enemy) and not getattr(enemy, "is_burrowed", False)]
    if not victims:
        return False
    for enemy in victims:
        enemy.apply_slow(CALTROPS_SLOW_FACTOR, CALTROPS_DURATION)
    return True


def _downdraft(game: Any, target: Point | None) -> bool:
    flyers = [enemy for enemy in game.enemies if _live(enemy) and getattr(enemy, "is_flying", False)]
    if not flyers:
        return False
    for enemy in flyers:
        enemy.apply_ground(DOWNDRAFT_DURATION)
        enemy.apply_slow(DOWNDRAFT_SLOW_FACTOR, DOWNDRAFT_DURATION)
        game.ability_flash((enemy.pos.x, enemy.pos.y), 22.0)
    return True


def _pct(fraction: float) -> int:
    return round(fraction * 100)


ABILITIES = {
    "hold_the_gate": Ability(
        "hold_the_gate", "Hold the Gate",
        f"The next {HOLD_THE_GATE_CHARGES} enemies to leak this floor cost no lives.",
        HOLD_THE_GATE_COOLDOWN, _hold_the_gate, unusable_message="The gate is already held",
        charge_label="leaks blocked",
    ),
    "toxic_downpour": Ability(
        "toxic_downpour", "Toxic Downpour",
        f"Aim a downpour: every enemy within {TOXIC_DOWNPOUR_RADIUS:g}px is poisoned for "
        f"{_pct(TOXIC_DOWNPOUR_HP_FRACTION_PER_TICK)}% of its max HP per second for {TOXIC_DOWNPOUR_DURATION:g}s "
        f"({_pct(TOXIC_DOWNPOUR_BOSS_HP_FRACTION_PER_TICK)}% vs bosses).",
        TOXIC_DOWNPOUR_COOLDOWN, _toxic_downpour, unusable_message="No enemies there",
        targeted=True, radius=TOXIC_DOWNPOUR_RADIUS,
    ),
    "called_shot": Ability(
        "called_shot", "Called Shot",
        f"For {CALLED_SHOT_DURATION:g}s every Basic and Sniper shot is a called crit: "
        f"x{CALLED_SHOT_DAMAGE_MULTIPLIER:g} damage.",
        CALLED_SHOT_COOLDOWN, _any_enemies, unusable_message="No enemies to shoot at",
        duration=CALLED_SHOT_DURATION, tower_buff=_called_shot_buff,
    ),
    "rapid_repairs": Ability(
        "rapid_repairs", "Rapid Repairs",
        f"Every tower fires {_pct(RAPID_REPAIRS_FIRE_RATE_MULTIPLIER - 1)}% faster for "
        f"{RAPID_REPAIRS_DURATION:g}s, and every Barricade is repaired to full.",
        RAPID_REPAIRS_COOLDOWN, _rapid_repairs, duration=RAPID_REPAIRS_DURATION, tower_buff=_rapid_repairs_buff,
    ),
    "thunderhead": Ability(
        "thunderhead", "Thunderhead",
        f"Lightning strikes the {THUNDERHEAD_TARGETS} toughest enemies on the field for "
        f"{_pct(THUNDERHEAD_HP_FRACTION)}% of their max HP ({_pct(THUNDERHEAD_BOSS_HP_FRACTION)}% vs bosses).",
        THUNDERHEAD_COOLDOWN, _thunderhead, unusable_message="No enemies to strike",
    ),
    "caltrops": Ability(
        "caltrops", "Caltrops",
        f"Scatter caltrops: every ground enemy is slowed to {_pct(CALTROPS_SLOW_FACTOR)}% speed "
        f"for {CALTROPS_DURATION:g}s.",
        CALTROPS_COOLDOWN, _caltrops, unusable_message="No ground enemies to slow",
    ),
    "downdraft": Ability(
        "downdraft", "Downdraft",
        f"Ground every flyer for {DOWNDRAFT_DURATION:g}s -- ground towers can hit it -- and slow it "
        f"to {_pct(DOWNDRAFT_SLOW_FACTOR)}% speed.",
        DOWNDRAFT_COOLDOWN, _downdraft, unusable_message="No flyers to ground",
    ),
}
