"""Tower modules -- attachments fitted to a tower *type* for the rest of a
run. Each type has one module slot (RunState.tower_modules, {tower type:
module key}); fitting a new module to a type replaces the old one.

A module offer always comes pre-paired with one of the run's own tower
types (module_offer), so taking it is a single decision on the reward
screen: "Long Barrel, for your Cannons". Every tower of that type built
afterwards gets it, applied by Game._construct_tower through apply_module
-- plain stat multipliers, plus an optional on-hit slow or poison that
rides the tower's existing relic on-hit fields.

Registry shape as everywhere else: MODULES is a {key: Module} dict, and
nothing outside this module branches on which module it is.
"""

import random
from dataclasses import dataclass
from typing import Any

from run.run_state import RunState
from support.rng_sampling import sample_up_to


@dataclass(frozen=True)
class Module:
    key: str
    display_name: str
    description: str
    damage_bonus: float = 0.0  # additive, like every other effective_damage() source
    range_multiplier: float = 1.0
    fire_rate_multiplier: float = 1.0
    # (factor, seconds) applied on every hit, or None.
    slow_on_hit: tuple[float, float] | None = None
    # (damage per tick, tick seconds, duration) -- the same shape as a relic's
    # poison_effect -- or None.
    poison_on_hit: tuple[float, float, float] | None = None
    crit_chance_bonus: float = 0.0
    # Damage-free towers (Support) gain nothing from a damage module, so
    # offers skip them for modules that only add damage.
    needs_damage: bool = True


MODULES = {
    "long_barrel": Module(
        "long_barrel", "Long Barrel", "+20% range.", range_multiplier=1.2, needs_damage=False,
    ),
    "rapid_loader": Module(
        "rapid_loader", "Rapid Loader", "+20% fire rate.", fire_rate_multiplier=1.2,
    ),
    "heavy_payload": Module(
        "heavy_payload", "Heavy Payload", "+35% damage, but -15% fire rate.",
        damage_bonus=0.35, fire_rate_multiplier=0.85,
    ),
    "cryo_coil": Module(
        "cryo_coil", "Cryo Coil", "Every hit slows its target to 80% speed for 1s.", slow_on_hit=(0.8, 1.0),
    ),
    "venom_injector": Module(
        "venom_injector", "Venom Injector", "Every hit poisons its target: 2 damage every 0.5s for 2s.",
        poison_on_hit=(2.0, 0.5, 2.0),
    ),
    "targeting_chip": Module(
        "targeting_chip", "Targeting Chip", "+12% chance to crit.", crit_chance_bonus=0.12,
    ),
    "overclocked_core": Module(
        "overclocked_core", "Overclocked Core", "+12% damage and +10% fire rate, but -10% range.",
        damage_bonus=0.12, fire_rate_multiplier=1.1, range_multiplier=0.9,
    ),
}
MODULE_ORDER = list(MODULES)


def module_offer(rng: random.Random, run: RunState, damaging_types: frozenset[str]) -> tuple[str, str] | None:
    """One (module key, tower type) pair for a reward: a tower type the run
    holds -- preferring one with no module yet -- and a module it doesn't
    already carry. `damaging_types` are the types that deal damage (a
    damage-only module is never paired with one that doesn't). None if the
    run holds no towers."""
    if not run.unlocked_towers:
        return None
    bare = [name for name in run.unlocked_towers if name not in run.tower_modules]
    tower_type = sample_up_to(rng, bare or list(run.unlocked_towers), 1)[0]
    candidates = [
        key for key in MODULE_ORDER
        if key != run.tower_modules.get(tower_type)
        and (tower_type in damaging_types or not MODULES[key].needs_damage)
    ]
    return sample_up_to(rng, candidates, 1)[0], tower_type


def apply_module(tower: Any, module: Module) -> None:
    """Fit `module` onto a freshly constructed tower -- after its relic
    fields are set, so a module's on-hit effect only ever adds to them."""
    tower.module_damage_bonus = module.damage_bonus
    tower.relic_range_bonus_multiplier *= module.range_multiplier
    tower.relic_fire_rate_bonus_multiplier *= module.fire_rate_multiplier
    tower.relic_crit_chance += module.crit_chance_bonus
    if module.slow_on_hit is not None:
        tower.relic_slow_chance = 1.0
        tower.relic_slow_effect = module.slow_on_hit
    if module.poison_on_hit is not None:
        tower.relic_poison_chance = 1.0
        tower.relic_poison_effect = module.poison_on_hit
