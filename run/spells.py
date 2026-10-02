"""Spells -- the run's deck of cards, Slay the Spire style.

A run carries a deck of spell cards (RunState.deck, duplicates allowed). At
the start of every fight the deck is shuffled into a CombatDeck: a draw
pile, a hand, a discard pile and an exhaust pile, plus energy. A "turn" is
one wave -- the opening hand is dealt the moment the floor loads, and every
time a wave is cleared (Game.update) the hand is discarded, energy refills
and a fresh hand is drawn. Cards are played by clicking them in the
sidebar or with the A/S/D/F/G hotkeys (Game.play_card).

Same registry shape as potions.py: `SPELLS` is a `{key: Spell}` dict and
each entry carries its own `cast` function, so adding a spell is one
function plus one registry line -- Game.play_card never branches on which
spell it is. A `cast` function receives the live Game (typed Any here,
since this module stays pygame-free and strictly typed) and the card's
level, and only touches board-level state: enemies, towers, economy, the
combat deck and the fight-scoped spell state Game owns (spell_fire_rate_
timer/multiplier, spell_damage_timer/bonus, bounty_timer,
free_tower_charges).

Upgrades (Slay the Spire's "+" cards): a deck card is a SPELLS key, or that
key plus UPGRADE_SUFFIX ("zap+"). Every spell number is a (base, upgraded)
pair, so a card's level just indexes it -- see card_level/card_cost/
card_description. A Rest site's Study upgrades one card.

Nothing about a CombatDeck is ever saved: Continue always restarts a fight
from its beginning, and the shuffle is re-derived from Game._run_rng keyed
by the node id, so the same fight always deals the same hands.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from support.rng_sampling import sample_up_to

HAND_SIZE = 4
# A hand never grows past this (Insight-style draw stops there) -- it's
# also how many card slots the sidebar has room for.
HAND_LIMIT = 5
MAX_ENERGY = 3

STARTER_DECK = ("zap", "zap", "zap", "rally", "rally", "prospect", "shove")

# How many spell cards a post-combat reward offers to pick from.
REWARD_SPELL_COUNT = 3

# Every spell number is a (base, upgraded) pair, indexed by a card's level
# (0, or 1 for an upgraded "+" card -- see card_level).
ZAP_TARGETS = 3
ZAP_HP_FRACTION = (0.22, 0.30)
ZAP_BOSS_HP_FRACTION = (0.06, 0.08)
RALLY_FIRE_RATE_MULTIPLIER = (1.3, 1.4)
RALLY_DURATION = (8.0, 10.0)
PROSPECT_BASE_GOLD = (25, 40)
PROSPECT_GOLD_PER_DEPTH = (6, 8)
SHOVE_DISTANCE = (70.0, 110.0)
CHAIN_LIGHTNING_HP_FRACTION = (0.15, 0.22)
CHAIN_LIGHTNING_BOSS_HP_FRACTION = (0.04, 0.06)
BLIZZARD_SLOW_FACTOR = (0.5, 0.4)
BLIZZARD_DURATION = (5.0, 7.0)
EXPOSE_MULTIPLIER = (1.3, 1.45)
EXPOSE_DURATION = (6.0, 8.0)
PLAGUE_HP_FRACTION_PER_TICK = (0.03, 0.04)
PLAGUE_BOSS_HP_FRACTION_PER_TICK = (0.008, 0.011)
PLAGUE_DURATION = (5.0, 6.0)
BOUNTY_GOLD_MULTIPLIER = 2
BOUNTY_DURATION = (10.0, 15.0)
INSIGHT_DRAW = (2, 3)
SURGE_ENERGY = (2, 3)
PATCH_GATE_LIVES = (1, 2)
EXECUTE_HP_FRACTION = (0.25, 0.35)
EMPOWER_DAMAGE_BONUS = (0.4, 0.6)
EMPOWER_DURATION = (6.0, 8.0)
FOCUS_FIRE_HP_FRACTION = (0.35, 0.50)
FOCUS_FIRE_BOSS_HP_FRACTION = (0.10, 0.14)

# An upgraded card's key is its base key plus this suffix ("zap+").
UPGRADE_SUFFIX = "+"


@dataclass(frozen=True)
class Spell:
    key: str
    display_name: str
    # Energy cost per level -- (base, upgraded); most upgrades keep the cost.
    costs: tuple[int, int]
    # The card text for a level -- the same numbers its cast reads.
    describe: Callable[[int], str]
    # cast(game, level) -- see this module's docstring.
    cast: Callable[[Any, int], None]
    # Only affects enemies on the field -- Game.play_card refuses it (and
    # keeps the card in hand) while there are none, rather than wasting it.
    needs_enemies: bool = True
    # Removed from the fight once played (Slay the Spire's Exhaust) instead
    # of going to the discard pile -- back in the deck next fight.
    exhaust: bool = False
    # "common"/"uncommon"/"rare" -- weights reward offers (REWARD_RARITY_WEIGHTS).
    rarity: str = "common"
    # Never offered by rewards or the Shop (the starter cards still are --
    # only a flag for a future card that should stay starter-only).
    offerable: bool = True

    @property
    def cost(self) -> int:
        return self.costs[0]

    @property
    def description(self) -> str:
        return self.describe(0)


def _boss_scaled(enemy: Any, fraction: tuple[float, float], boss_fraction: tuple[float, float],
                 level: int) -> float:
    return float(enemy.max_hp * (boss_fraction[level] if enemy.IS_BOSS else fraction[level]))


def _zap(game: Any, level: int) -> None:
    leaders = sorted(game.enemies, key=lambda enemy: enemy.distance_traveled, reverse=True)
    for enemy in leaders[:ZAP_TARGETS]:
        enemy.take_damage(_boss_scaled(enemy, ZAP_HP_FRACTION, ZAP_BOSS_HP_FRACTION, level))


def _rally(game: Any, level: int) -> None:
    game.spell_fire_rate_timer = max(game.spell_fire_rate_timer, RALLY_DURATION[level])
    game.spell_fire_rate_multiplier = max(game.spell_fire_rate_multiplier, RALLY_FIRE_RATE_MULTIPLIER[level])


def prospect_gold(depth: int, level: int = 0) -> int:
    """Battle gold a Prospect grants at run depth `depth` -- grows with the
    run the same way every floor's own gold economy does."""
    return PROSPECT_BASE_GOLD[level] + PROSPECT_GOLD_PER_DEPTH[level] * depth


def _prospect(game: Any, level: int) -> None:
    depth = game.active_run.depth if game.active_run is not None else 0
    game.economy.add_gold(prospect_gold(depth, level))


def _shove(game: Any, level: int) -> None:
    for enemy in game.enemies:
        enemy.apply_knockback(SHOVE_DISTANCE[level])


def _chain_lightning(game: Any, level: int) -> None:
    for enemy in game.enemies:
        enemy.take_damage(_boss_scaled(enemy, CHAIN_LIGHTNING_HP_FRACTION, CHAIN_LIGHTNING_BOSS_HP_FRACTION, level))


def _blizzard(game: Any, level: int) -> None:
    for enemy in game.enemies:
        enemy.apply_slow(BLIZZARD_SLOW_FACTOR[level], BLIZZARD_DURATION[level])


def _expose(game: Any, level: int) -> None:
    for enemy in game.enemies:
        enemy.apply_mark(EXPOSE_MULTIPLIER[level], EXPOSE_DURATION[level])


def _plague(game: Any, level: int) -> None:
    for enemy in game.enemies:
        tick = _boss_scaled(enemy, PLAGUE_HP_FRACTION_PER_TICK, PLAGUE_BOSS_HP_FRACTION_PER_TICK, level)
        enemy.apply_poison(tick, 1.0, PLAGUE_DURATION[level])


def _bounty(game: Any, level: int) -> None:
    game.bounty_timer = max(game.bounty_timer, BOUNTY_DURATION[level])


def _insight(game: Any, level: int) -> None:
    game.combat_deck.draw(INSIGHT_DRAW[level])


def _surge(game: Any, level: int) -> None:
    game.combat_deck.energy += SURGE_ENERGY[level]


def _patch_gate(game: Any, level: int) -> None:
    game.economy.lives += PATCH_GATE_LIVES[level]


def _execute(game: Any, level: int) -> None:
    for enemy in game.enemies:
        if not enemy.IS_BOSS and enemy.hp <= enemy.max_hp * EXECUTE_HP_FRACTION[level]:
            enemy.take_damage(enemy.hp)


def _empower(game: Any, level: int) -> None:
    game.spell_damage_timer = max(game.spell_damage_timer, EMPOWER_DURATION[level])
    game.spell_damage_bonus = max(game.spell_damage_bonus, EMPOWER_DAMAGE_BONUS[level])


def _requisition(game: Any, level: int) -> None:
    game.free_tower_charges += 1


def _focus_fire(game: Any, level: int) -> None:
    target = max(game.enemies, key=lambda enemy: enemy.hp)
    target.take_damage(_boss_scaled(target, FOCUS_FIRE_HP_FRACTION, FOCUS_FIRE_BOSS_HP_FRACTION, level))


def _pct(fraction: float) -> int:
    return round(fraction * 100)


SPELLS = {
    "zap": Spell(
        "zap", "Zap", (1, 1),
        lambda lv: f"Hit the {ZAP_TARGETS} enemies furthest along for {_pct(ZAP_HP_FRACTION[lv])}% of their "
                   f"max HP ({_pct(ZAP_BOSS_HP_FRACTION[lv])}% vs bosses).",
        _zap,
    ),
    "rally": Spell(
        "rally", "Rally", (1, 1),
        lambda lv: f"Every tower fires {_pct(RALLY_FIRE_RATE_MULTIPLIER[lv] - 1)}% faster for "
                   f"{RALLY_DURATION[lv]:g}s.",
        _rally, needs_enemies=False,
    ),
    "prospect": Spell(
        "prospect", "Prospect", (1, 1),
        lambda lv: f"Gain {PROSPECT_BASE_GOLD[lv]} battle gold, +{PROSPECT_GOLD_PER_DEPTH[lv]} per floor deep.",
        _prospect, needs_enemies=False,
    ),
    "shove": Spell(
        "shove", "Shove", (1, 1),
        lambda lv: f"Push every enemy {SHOVE_DISTANCE[lv]:g}px back along its route.",
        _shove,
    ),
    "chain_lightning": Spell(
        "chain_lightning", "Chain Lightning", (2, 2),
        lambda lv: f"Hit every enemy for {_pct(CHAIN_LIGHTNING_HP_FRACTION[lv])}% of its max HP "
                   f"({_pct(CHAIN_LIGHTNING_BOSS_HP_FRACTION[lv])}% vs bosses).",
        _chain_lightning, rarity="uncommon",
    ),
    "blizzard": Spell(
        "blizzard", "Blizzard", (2, 2),
        lambda lv: f"Slow every enemy to {_pct(BLIZZARD_SLOW_FACTOR[lv])}% speed for {BLIZZARD_DURATION[lv]:g}s.",
        _blizzard,
    ),
    "expose": Spell(
        "expose", "Expose", (1, 1),
        lambda lv: f"Mark every enemy: +{_pct(EXPOSE_MULTIPLIER[lv] - 1)}% damage taken for "
                   f"{EXPOSE_DURATION[lv]:g}s.",
        _expose,
    ),
    "plague": Spell(
        "plague", "Plague", (1, 1),
        lambda lv: f"Poison every enemy for {_pct(PLAGUE_HP_FRACTION_PER_TICK[lv])}% of its max HP per second "
                   f"for {PLAGUE_DURATION[lv]:g}s.",
        _plague,
    ),
    "bounty": Spell(
        "bounty", "Bounty", (1, 1),
        lambda lv: f"Enemies killed in the next {BOUNTY_DURATION[lv]:g}s drop {BOUNTY_GOLD_MULTIPLIER}x gold.",
        _bounty, needs_enemies=False, rarity="uncommon",
    ),
    "insight": Spell(
        "insight", "Insight", (0, 0),
        lambda lv: f"Draw {INSIGHT_DRAW[lv]} cards. Exhaust.",
        _insight, needs_enemies=False, exhaust=True, rarity="uncommon",
    ),
    "surge": Spell(
        "surge", "Surge", (0, 0),
        lambda lv: f"Gain {SURGE_ENERGY[lv]} energy. Exhaust.",
        _surge, needs_enemies=False, exhaust=True, rarity="rare",
    ),
    "patch_gate": Spell(
        "patch_gate", "Patch the Gate", (2, 2),
        lambda lv: f"Restore {PATCH_GATE_LIVES[lv]} {'life' if PATCH_GATE_LIVES[lv] == 1 else 'lives'}. Exhaust.",
        _patch_gate, needs_enemies=False, exhaust=True, rarity="uncommon",
    ),
    "execute": Spell(
        "execute", "Execute", (2, 1),
        lambda lv: f"Finish off every non-boss enemy below {_pct(EXECUTE_HP_FRACTION[lv])}% HP.",
        _execute, rarity="uncommon",
    ),
    "empower": Spell(
        "empower", "Empower", (2, 2),
        lambda lv: f"Every tower deals +{_pct(EMPOWER_DAMAGE_BONUS[lv])}% damage for {EMPOWER_DURATION[lv]:g}s.",
        _empower, needs_enemies=False, rarity="rare",
    ),
    "requisition": Spell(
        "requisition", "Requisition", (1, 0),
        lambda lv: "Your next tower placed this fight is free. Exhaust.",
        _requisition, needs_enemies=False, exhaust=True, rarity="rare",
    ),
    "focus_fire": Spell(
        "focus_fire", "Focus Fire", (1, 1),
        lambda lv: f"Hit the toughest enemy for {_pct(FOCUS_FIRE_HP_FRACTION[lv])}% of its max HP "
                   f"({_pct(FOCUS_FIRE_BOSS_HP_FRACTION[lv])}% vs bosses).",
        _focus_fire,
    ),
}

SPELL_ORDER = list(SPELLS)

REWARD_RARITY_WEIGHTS = {"common": 6, "uncommon": 3, "rare": 1}


def base_key(card: str) -> str:
    """The SPELLS key behind a deck card ("zap+" -> "zap")."""
    return card.removesuffix(UPGRADE_SUFFIX)


def card_level(card: str) -> int:
    """0 for a base card, 1 for an upgraded one."""
    return 1 if card.endswith(UPGRADE_SUFFIX) else 0


def upgraded(card: str) -> str:
    """The upgraded version of `card` (already-upgraded cards stay as they are)."""
    return base_key(card) + UPGRADE_SUFFIX


def is_valid_card(card: str) -> bool:
    """Whether `card` is a registered spell, upgraded or not -- what a save's
    deck is validated against."""
    return base_key(card) in SPELLS and card in (base_key(card), upgraded(card))


def spell_of(card: str) -> Spell:
    return SPELLS[base_key(card)]


def card_cost(card: str) -> int:
    return spell_of(card).costs[card_level(card)]


def card_name(card: str) -> str:
    """"Zap", or "Zap+" for an upgraded card."""
    return spell_of(card).display_name + (UPGRADE_SUFFIX if card_level(card) else "")


def card_description(card: str) -> str:
    return spell_of(card).describe(card_level(card))


def initials(card: str) -> str:
    """A card's short label -- the first letter of each word, plus "+" when upgraded."""
    letters = "".join(word[0] for word in spell_of(card).display_name.split())
    return letters + (UPGRADE_SUFFIX if card_level(card) else "")


def upgradeable_cards(deck: list[str]) -> list[str]:
    """Each distinct not-yet-upgraded card in `deck`, in registry order --
    what a Rest site's Study can pick from."""
    return [key for key in SPELL_ORDER if key in deck]


def spell_offer(rng: random.Random, count: int = REWARD_SPELL_COUNT) -> list[str]:
    """`count` distinct spell keys for a reward/Shop, weighted by rarity
    (rarer cards show up less often). Unlike towers/relics a deck may hold
    duplicates, so nothing the run already holds is excluded."""
    pool = [key for key in SPELL_ORDER if SPELLS[key].offerable]
    picks: list[str] = []
    while pool and len(picks) < count:
        weights = [REWARD_RARITY_WEIGHTS[SPELLS[key].rarity] for key in pool]
        choice = rng.choices(pool, weights=weights)[0]
        picks.append(choice)
        pool.remove(choice)
    return picks


def random_spell(rng: random.Random) -> str:
    """One offerable spell key, uniformly -- for Events."""
    return sample_up_to(rng, [key for key in SPELL_ORDER if SPELLS[key].offerable], 1)[0]


@dataclass
class CombatDeck:
    """One fight's live deck: draw pile (drawn from the end), hand, discard
    and exhaust piles, and energy. Built fresh on every floor load from
    RunState.deck (Game._load_combat_node)."""

    rng: random.Random
    draw_pile: list[str]
    hand: list[str] = field(default_factory=list)
    discard_pile: list[str] = field(default_factory=list)
    exhaust_pile: list[str] = field(default_factory=list)
    energy: int = 0
    max_energy: int = MAX_ENERGY
    hand_size: int = HAND_SIZE
    # Cards played since the last new_turn -- what an Echo Chamber-style
    # relic checks for "the first spell this wave".
    played_this_turn: int = 0

    @classmethod
    def from_deck(cls, deck: list[str], rng: random.Random, max_energy: int = MAX_ENERGY,
                  hand_size: int = HAND_SIZE) -> "CombatDeck":
        pile = list(deck)
        rng.shuffle(pile)
        return cls(rng=rng, draw_pile=pile, max_energy=max_energy, hand_size=hand_size)

    def draw(self, count: int) -> int:
        """Draw up to `count` cards, reshuffling the discard pile into the
        draw pile when it runs dry; stops at HAND_LIMIT or when both piles
        are empty. Returns how many were actually drawn."""
        drawn = 0
        while drawn < count and len(self.hand) < HAND_LIMIT:
            if not self.draw_pile:
                if not self.discard_pile:
                    break
                self.draw_pile = self.discard_pile
                self.discard_pile = []
                self.rng.shuffle(self.draw_pile)
            self.hand.append(self.draw_pile.pop())
            drawn += 1
        return drawn

    def new_turn(self) -> None:
        """Discard the hand, refill energy, draw a fresh hand."""
        self.discard_pile.extend(self.hand)
        self.hand = []
        self.energy = self.max_energy
        self.played_this_turn = 0
        self.draw(self.hand_size)

    def can_play(self, index: int) -> bool:
        return 0 <= index < len(self.hand) and card_cost(self.hand[index]) <= self.energy

    def play(self, index: int) -> str:
        """Remove the card at `index` from the hand, pay its energy and
        move it to the discard (or exhaust) pile. The caller casts it --
        after this, so a draw effect never re-draws the card just played."""
        card = self.hand.pop(index)
        self.energy -= card_cost(card)
        self.played_this_turn += 1
        (self.exhaust_pile if spell_of(card).exhaust else self.discard_pile).append(card)
        return card
