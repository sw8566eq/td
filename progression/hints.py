"""Field Notes: one-time contextual hints, shown the first time a player
meets each system (a node type, a reward screen, a new enemy, low lives...).

`HINTS` is the registry: one `Hint` per key, each naming the *trigger* it
belongs to -- a plain string Game passes to `HintTracker.notify()` at a
moment it already goes through (`"node_shop"` from `_enter_node`,
`"enemy_burrower"` when a wave spawns one, `"low_lives"` from
`_lose_a_life`...). Adding a hint is one registry line; a trigger nobody has
registered a hint for is a harmless no-op, so a call site can notify freely.

Which hints this account has already seen is local player data in its own
small JSON file (`hints.json`), loaded defensively through
`json_io.load_json_with_fallback` like every other player file, its path
injectable (`Game(hints_path=...)`). Whether hints show at all is a player
setting (`player_settings.json`'s `hints_enabled`), not part of this file,
so Settings' "Reset hints" never flips the toggle.

Pure and pygame-free (strict mypy): the presentation side -- the panel that
draws `HintTracker.current` -- lives in `presentation/ui.py`. See
docs/agents/core-game.md "Field Notes (first-time hints)".
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from persistence.json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
HINTS_PATH = module_relative_path(__file__, "hints.json")

# How long a hint stays up before the next queued one replaces it, unless
# the player clicks it away first. Ages only while a hint can be seen (see
# Game.HINT_STATES), so one left up as the player pauses isn't missed.
HINT_DISPLAY_SECONDS = 10.0


@dataclass(frozen=True)
class Hint:
    trigger: str
    title: str
    text: str


HINTS: dict[str, Hint] = {
    # --- Fighting ---
    "first_fight": Hint(
        "fight_start", "Defend the path",
        "Enemies walk the path to your base, and each one that gets through costs a life. "
        "Build towers, then press Start (Space) to send the first wave.",
    ),
    "early_call": Hint(
        "wave_cleared", "Call waves early",
        "Between waves, Skip (Space) sends the next wave now and pays bonus battle gold "
        "for every second of countdown you cut.",
    ),
    "move_towers": Hint(
        "wave_cleared", "Moving towers",
        "Between waves, click a tower and press Move (beside Sell) to relocate it. Free before "
        "the first wave, a small gold fee after.",
    ),
    "coverage": Hint(
        "tower_built", "Coverage overlay",
        "Press V to toggle the coverage overlay and see which stretches of path your towers reach.",
    ),
    "specialize": Hint(
        "specialize_ready", "Specialize",
        "That tower is at max level. Pick one of its two specializations in the side panel "
        "to push it further.",
    ),
    "resonance": Hint(
        "resonance", "Resonance",
        "Some tower pairs boost each other when built close together. While placing, the "
        "preview draws a line to any partner in reach.",
    ),
    "barricade": Hint(
        "built_barricade", "Barricades",
        "A Barricade sits on the path and holds ground enemies until they break it. "
        "Sappers and bosses batter it much faster.",
    ),
    "high_ground": Hint(
        "high_ground", "High ground",
        "Raised tiles give a tower standing mostly on them +20% range. Path traps can't use them.",
    ),
    "harpoon": Hint(
        "built_harpoon", "Harpoon",
        "Each Harpoon hit Grounds a flyer for a few seconds. While grounded, ground-only "
        "towers and Barricades can reach it too.",
    ),
    "potion": Hint(
        "holding_potion", "Bandolier",
        "Your Bandolier holds potions. Click a slot under the side panel, or press Q/W/E, "
        "to drink one mid-fight. Each is single-use.",
    ),
    "module": Hint(
        "module_fitted", "Modules",
        "A module is fitted: every tower of that type you build this run gets its extra "
        "effect, listed in the side panel.",
    ),
    "low_lives": Hint(
        "low_lives", "Lives running low",
        "Lives carry from floor to floor. An Outpost on the map lets you rest to recover "
        "some before the next fight.",
    ),
    # --- Enemies ---
    "enemy_flying": Hint(
        "enemy_flying", "Flyers",
        "Flyers travel in the air. Cannon, Knockback, Mortar and path traps can't hit them "
        "unless a Harpoon drags them down first.",
    ),
    "enemy_shielded": Hint(
        "enemy_shielded", "Shields",
        "Shielded enemies carry a blue bar that soaks up damage before their health "
        "starts to drop.",
    ),
    "enemy_burrower": Hint(
        "enemy_burrower", "Burrowers",
        "Burrowers tunnel under the path: traps can't hit them and Barricades can't hold "
        "them. A Beacon's mark brings them to the surface.",
    ),
    "enemy_sapper": Hint(
        "enemy_sapper", "Sappers",
        "Sappers batter Barricades five times harder than other enemies. Kill them before "
        "they reach your wall.",
    ),
    # --- The run's map ---
    "node_elite": Hint(
        "node_elite", "Elite fight",
        "Elites are tougher and carry an affix (shown in the side panel), but their reward "
        "adds a relic and a module or potion.",
    ),
    "node_boss": Hint(
        "node_boss", "Boss",
        "The boss closes the act. Beat it to claim a trophy relic: strong, but each one "
        "comes with a drawback.",
    ),
    "node_shop": Hint(
        "node_shop", "Shop",
        "The Shop takes shop currency, earned from leftover battle gold after each floor. "
        "Battle gold itself never carries over.",
    ),
    "node_event": Hint(
        "node_event", "Event",
        "Events offer a choice. Some options cost lives, shop currency or a relic; ones you "
        "can't afford are greyed out.",
    ),
    "node_rest": Hint(
        "node_rest", "Outpost",
        "At an Outpost, Rest to recover lives, use the Forge so a tower is always placed at "
        "level 2, or Drill a crew for veterancy.",
    ),
    "node_treasure": Hint(
        "node_treasure", "Treasure",
        "A Treasure cache always holds a relic. Press R in a fight or on the map to review "
        "the relics you carry.",
    ),
    "node_armory": Hint(
        "node_armory", "Armory",
        "The Armory fits a module to one tower type for the rest of the run. Take one, or "
        "skip if none fit your plan.",
    ),
    "reward": Hint(
        "reward", "Rewards",
        "Pick one tower card to add it to your build menu for the rest of the run. Relic and "
        "potion cards can be claimed as well.",
    ),
    "veterancy": Hint(
        "veterancy", "Veterancy",
        "Tower types earn experience from kills. A promoted type builds new towers stronger "
        "for the rest of the run.",
    ),
    "act_cleared": Hint(
        "act_cleared", "Act cleared",
        "The next act is a new map with tougher enemies. Your towers, relics, potions and "
        "lives come with you.",
    ),
    "curse": Hint(
        "curse", "Curses",
        "Curses are relics that work against you. A Shop can remove one for a price.",
    ),
    "relic": Hint(
        "relic", "Relics",
        "Relics last the whole run. Press R to see yours; the Field Manual (K on the main "
        "menu) lists every relic, potion and enemy.",
    ),
    # --- Around the run ---
    "blessing": Hint(
        "blessing", "Orders from Command",
        "Each run opens with Orders from Command: pick one boon to start with, then choose "
        "your path on the map.",
    ),
    "gauntlet": Hint(
        "gauntlet_unlocked", "Gauntlet",
        "A new Gauntlet level is unlocked. The main menu now starts runs at it (Left/Right "
        "there to choose); each level adds a harder rule.",
    ),
    "run_lost": Hint(
        "run_lost", "The run is over",
        "Runs end when lives run out, but your account keeps growing: new towers, relics and "
        "levels unlock as you play.",
    ),
}

# trigger -> the hint keys it fires, in registry order.
_BY_TRIGGER: dict[str, tuple[str, ...]] = {}
for _key, _hint in HINTS.items():
    _BY_TRIGGER[_hint.trigger] = (*_BY_TRIGGER.get(_hint.trigger, ()), _key)


def hints_for(trigger: str) -> tuple[str, ...]:
    """Every HINTS key registered for `trigger` (empty for an unknown one)."""
    return _BY_TRIGGER.get(trigger, ())


def _parse_seen(data: Any) -> set[str]:
    return {key for key in data.get("seen", []) if isinstance(key, str)}


def load_seen(path: str = HINTS_PATH) -> set[str]:
    """The hint keys this account has already seen, or an empty set for a
    missing/corrupt file -- the worst a bad file can do is show hints
    again."""
    return load_json_with_fallback(path, _parse_seen, set)


def save_seen(seen: Iterable[str], path: str = HINTS_PATH) -> None:
    with open(path, "w") as f:
        json.dump({"schema_version": SCHEMA_VERSION, "seen": sorted(seen)}, f, indent=2)


@dataclass
class HintTracker:
    """Seen-set plus a one-at-a-time display queue. `notify()` queues any
    unseen hint for a trigger; a hint is marked seen (and written through to
    disk) only when it actually becomes `current`, so one still queued when
    the game closes shows next time instead of being lost."""

    path: str = HINTS_PATH
    enabled: bool = True
    seen: set[str] = field(default_factory=set)
    current: str | None = None
    elapsed: float = 0.0
    pending: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: str = HINTS_PATH, enabled: bool = True) -> "HintTracker":
        return cls(path=path, enabled=enabled, seen=load_seen(path))

    def notify(self, *triggers: str) -> None:
        """Queue every not-yet-seen hint registered for any of `triggers`."""
        if not self.enabled:
            return
        for trigger in triggers:
            for key in hints_for(trigger):
                if key not in self.seen and key != self.current and key not in self.pending:
                    self.pending.append(key)
        if self.current is None:
            self._advance()

    def update(self, dt: float) -> None:
        """Age the shown hint by `dt` seconds; past HINT_DISPLAY_SECONDS the
        next queued one (if any) takes its place."""
        if self.current is None:
            return
        self.elapsed += dt
        if self.elapsed >= HINT_DISPLAY_SECONDS:
            self.dismiss()

    def dismiss(self) -> None:
        """Close the shown hint (a click on it, or its timeout)."""
        self.current = None
        self._advance()

    def set_enabled(self, value: bool) -> None:
        """Turning hints off also drops whatever was showing or queued --
        unseen ones stay unseen, so turning them back on still shows them."""
        self.enabled = value
        if not value:
            self.current = None
            self.pending.clear()

    def reset(self) -> None:
        """Forget every seen hint (Settings' "Reset hints")."""
        self.seen.clear()
        self.current = None
        self.pending.clear()
        save_seen(self.seen, self.path)

    def _advance(self) -> None:
        self.elapsed = 0.0
        if not self.pending:
            return
        self.current = self.pending.pop(0)
        self.seen.add(self.current)
        save_seen(self.seen, self.path)
