"""Endless mutators -- the final boss floor's score chase gets stranger the
longer it lasts.

Every MUTATOR_CADENCE endless waves cleared in one fight, one more mutator
from MUTATORS is drawn and stacks on top of the ones already active for the
rest of that fight. Draw `index` (0-based) uses its own rng, keyed by the
node id and the index (Game._run_rng(run, "mutator", f"{node.id}:{index}")),
so the active list is a pure function of (seed, node, endless waves cleared)
and is re-derived on every load and resume rather than stored -- the same
"no RNG state serialized" rule every other per-node pick follows, and a
Daily Run gets the same mutators for everyone.

Draws come from the mutators not yet active, so every one shows up once
before any repeats; after that only the `repeatable` ones (plain
multipliers, which stack meaningfully) are drawn again.

Registry shape as usual: each EndlessMutator is plain data -- multipliers
WaveManager applies to every spawned enemy, plus count/escort/species-swap
rules it applies to every wave's spawn queue (MutatorEffects.
transform_composition). Game never branches on which mutator it is.
"""

import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

# A new mutator every this many endless waves cleared.
MUTATOR_CADENCE = 5
# The bounty for facing each new mutator, paid by Game when it's drawn.
BOUNTY_LIVES = 1
BOUNTY_GOLD = 60


@dataclass(frozen=True)
class SpeciesSwap:
    """Every `every`-th eligible enemy in a spawn's queue becomes `to` --
    eligible meaning not a boss, not already `to`, and (if `ground_only`)
    not a flyer."""
    every: int
    to: str
    ground_only: bool = True


@dataclass(frozen=True)
class EndlessMutator:
    key: str
    display_name: str
    description: str
    # Every non-boss count in a wave, rounded to the nearest whole enemy.
    count_multiplier: float = 1.0
    hp_multiplier: float = 1.0
    speed_multiplier: float = 1.0
    # Heal this fraction of max HP per second (on top of a boss affix's).
    regen_fraction_per_second: float = 0.0
    # Every ground enemy burrows (Enemy.BURROWS).
    burrows: bool = False
    # Barricade breach strength (Enemy.BREACH_MULTIPLIER) scaled.
    breach_multiplier: float = 1.0
    swap: SpeciesSwap | None = None
    # Extra enemies of `escort_species` added to every spawn of every wave.
    escort_species: str = ""
    escort_per_spawn: int = 0
    # Whether a second copy may be drawn once every mutator is active.
    repeatable: bool = False


MUTATORS = {
    "swarm": EndlessMutator(
        "swarm", "Swarm", "30% more enemies per wave.", count_multiplier=1.3, repeatable=True,
    ),
    "ironclad": EndlessMutator(
        "ironclad", "Ironclad", "Enemies have 25% more HP.", hp_multiplier=1.25, repeatable=True,
    ),
    "gale": EndlessMutator(
        "gale", "Gale", "Enemies move 15% faster.", speed_multiplier=1.15, repeatable=True,
    ),
    "skyborne": EndlessMutator(
        "skyborne", "Skyborne", "Every 4th ground enemy takes wing as a Flyer.",
        swap=SpeciesSwap(every=4, to="flying"),
    ),
    "tunnelers": EndlessMutator(
        "tunnelers", "Tunnelers", "Every ground enemy burrows under traps and Barricades.", burrows=True,
    ),
    "siege": EndlessMutator(
        "siege", "Siege", "Enemies batter Barricades twice as hard.", breach_multiplier=2.0, repeatable=True,
    ),
    "regrowth": EndlessMutator(
        "regrowth", "Regrowth", "Enemies heal 1% of their max HP every second.",
        regen_fraction_per_second=0.01, repeatable=True,
    ),
    "shielded_ranks": EndlessMutator(
        "shielded_ranks", "Shielded Ranks", "Every 4th ground enemy marches in shielded.",
        swap=SpeciesSwap(every=4, to="shielded"),
    ),
    "escort": EndlessMutator(
        "escort", "Escort", "Every spawn sends a Tank with each wave.",
        escort_species="tank", escort_per_spawn=1, repeatable=True,
    ),
}
MUTATOR_ORDER = list(MUTATORS)


def mutator_count(endless_waves_cleared: int) -> int:
    """How many mutators are active after this many endless waves cleared."""
    return max(0, endless_waves_cleared) // MUTATOR_CADENCE


def roll_mutator(rng: random.Random, active: Iterable[str]) -> str:
    """One more mutator: an inactive one while any are left, then any
    repeatable one."""
    taken = set(active)
    pool = [key for key in MUTATOR_ORDER if key not in taken]
    if not pool:
        pool = [key for key in MUTATOR_ORDER if MUTATORS[key].repeatable]
    return pool[rng.randrange(len(pool))]


def draw_mutators(rng_for_index: Callable[[int], random.Random], count: int) -> list[str]:
    """The first `count` mutators of a fight, in draw order -- draw `index`
    uses rng_for_index(index) (a fresh, keyed rng per draw)."""
    keys: list[str] = []
    for index in range(count):
        keys.append(roll_mutator(rng_for_index(index), keys))
    return keys


@dataclass(frozen=True)
class MutatorEffects:
    """Every active mutator folded into one bundle: multipliers multiply,
    regen and escorts add, burrowing ORs, swaps apply in draw order."""
    hp_multiplier: float = 1.0
    speed_multiplier: float = 1.0
    count_multiplier: float = 1.0
    regen_fraction_per_second: float = 0.0
    burrows: bool = False
    breach_multiplier: float = 1.0
    swaps: tuple[SpeciesSwap, ...] = ()
    escorts: tuple[tuple[str, int], ...] = field(default=())

    def transform_composition(
        self, composition: Mapping[str, int], flying_species: frozenset[str], boss_species: frozenset[str],
    ) -> list[str]:
        """One spawn's enemy queue (species names, in spawn order) for a
        wave whose authored/generated composition is `composition`."""
        counts = {
            name: count if name in boss_species else int(count * self.count_multiplier + 0.5)
            for name, count in composition.items()
        }
        for species, extra in self.escorts:
            counts[species] = counts.get(species, 0) + extra
        queue = [name for name, count in counts.items() for _ in range(count)]
        for swap in self.swaps:
            seen = 0
            for position, name in enumerate(queue):
                if name in boss_species or name == swap.to or (swap.ground_only and name in flying_species):
                    continue
                seen += 1
                if seen % swap.every == 0:
                    queue[position] = swap.to
        return queue

    def merged(self, other: "MutatorEffects | None") -> "MutatorEffects":
        """This bundle with `other` folded on top, by the same rules as
        compose -- `other`'s swaps run after this one's. How an Elite
        affix's or named boss's queue rules (elite_affixes.spawn_rules) and
        the endless final floor's mutators share one spawn queue
        (WaveManager._queue_effects)."""
        if other is None:
            return self
        escorts = dict(self.escorts)
        for species, extra in other.escorts:
            escorts[species] = escorts.get(species, 0) + extra
        return MutatorEffects(
            hp_multiplier=self.hp_multiplier * other.hp_multiplier,
            speed_multiplier=self.speed_multiplier * other.speed_multiplier,
            count_multiplier=self.count_multiplier * other.count_multiplier,
            regen_fraction_per_second=self.regen_fraction_per_second + other.regen_fraction_per_second,
            burrows=self.burrows or other.burrows,
            breach_multiplier=self.breach_multiplier * other.breach_multiplier,
            swaps=self.swaps + other.swaps,
            escorts=tuple(escorts.items()),
        )


def compose(keys: Iterable[str]) -> MutatorEffects:
    hp = speed = count = breach = 1.0
    regen = 0.0
    burrows = False
    swaps: list[SpeciesSwap] = []
    escorts: dict[str, int] = {}
    for key in keys:
        mutator = MUTATORS[key]
        hp *= mutator.hp_multiplier
        speed *= mutator.speed_multiplier
        count *= mutator.count_multiplier
        breach *= mutator.breach_multiplier
        regen += mutator.regen_fraction_per_second
        burrows = burrows or mutator.burrows
        if mutator.swap is not None:
            swaps.append(mutator.swap)
        if mutator.escort_per_spawn:
            escorts[mutator.escort_species] = escorts.get(mutator.escort_species, 0) + mutator.escort_per_spawn
    return MutatorEffects(
        hp_multiplier=hp, speed_multiplier=speed, count_multiplier=count, regen_fraction_per_second=regen,
        burrows=burrows, breach_multiplier=breach, swaps=tuple(swaps), escorts=tuple(escorts.items()),
    )


def summary_names(keys: Iterable[str]) -> list[str]:
    """Display names in first-draw order, a repeat shown as "Swarm x2"."""
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return [
        MUTATORS[key].display_name + (f" x{count}" if count > 1 else "") for key, count in counts.items()
    ]
