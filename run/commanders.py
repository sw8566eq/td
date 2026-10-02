"""Commanders -- Slay the Spire's characters, for a tower defense run.

Picked on the Commander select screen right before a run starts (Game.
_enter_commander_select), a Commander decides what the run begins with:
its own starter towers (replacing card_pool.STARTER_TOWERS), a signature
starting relic, and, for some, starting potions or towers already forged.
Same registry shape as every other content kind -- COMMANDERS is a {key:
Commander} dict, and Game.start_new_run reads a Commander's fields without
ever branching on which one it is.

DEFAULT_COMMANDER is always available (and is what a Daily Run always
uses, so scores stay comparable); every other one is gated behind a
meta_progression.COMMANDER_META_UNLOCKS entry.
"""

from dataclasses import dataclass, field

DEFAULT_COMMANDER = "warden"


@dataclass(frozen=True)
class Commander:
    key: str
    display_name: str
    description: str
    starter_towers: tuple[str, ...]
    starting_relics: tuple[str, ...] = ()
    starting_potions: tuple[str, ...] = ()
    forged_towers: tuple[str, ...] = field(default_factory=tuple)


COMMANDERS = {
    "warden": Commander(
        "warden", "The Warden",
        "A steady defender. Basic, Cannon and Frost; once per run, survives a killing blow.",
        ("basic", "cannon", "frost"), starting_relics=("guardians_reprieve",),
    ),
    "alchemist": Commander(
        "alchemist", "The Alchemist",
        "Poisons everything. Basic, Poison and Frost; venom-coated shots and two potions to start.",
        ("basic", "poison", "frost"), starting_relics=("venomous_coating",),
        starting_potions=("fire_bomb", "mending_salve"),
    ),
    "marksman": Commander(
        "marksman", "The Marksman",
        "Precision over volume. Basic, Sniper and Frost; every tower crits more often.",
        ("basic", "sniper", "frost"), starting_relics=("focused_fire",),
    ),
    "engineer": Commander(
        "engineer", "The Engineer",
        "Builds it better. Basic, Cannon and Support; Basic starts forged, upgrades cost less.",
        ("basic", "cannon", "support"), starting_relics=("quartermasters_favor",),
        forged_towers=("basic",),
    ),
    "stormcaller": Commander(
        "stormcaller", "The Stormcaller",
        "Chains lightning through crowds. Basic, Lightning and Frost; Lightning starts forged and hits harder.",
        ("basic", "lightning", "frost"), starting_relics=("storm_core",), forged_towers=("lightning",),
    ),
}
COMMANDER_ORDER = list(COMMANDERS)
