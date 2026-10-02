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
since this module stays pygame-free and strictly typed) and only touches
board-level state: enemies, towers, economy, the combat deck and the
fight-scoped spell timers Game owns (spell_fire_rate_timer,
spell_damage_timer, bounty_timer, free_tower_charges).

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

ZAP_TARGETS = 3
ZAP_HP_FRACTION = 0.22
ZAP_BOSS_HP_FRACTION = 0.06
RALLY_FIRE_RATE_MULTIPLIER = 1.3
RALLY_DURATION = 8.0
PROSPECT_BASE_GOLD = 25
PROSPECT_GOLD_PER_DEPTH = 6
SHOVE_DISTANCE = 70.0
CHAIN_LIGHTNING_HP_FRACTION = 0.15
CHAIN_LIGHTNING_BOSS_HP_FRACTION = 0.04
BLIZZARD_SLOW_FACTOR = 0.5
BLIZZARD_DURATION = 5.0
EXPOSE_MULTIPLIER = 1.3
EXPOSE_DURATION = 6.0
PLAGUE_HP_FRACTION_PER_TICK = 0.03
PLAGUE_BOSS_HP_FRACTION_PER_TICK = 0.008
PLAGUE_DURATION = 5.0
BOUNTY_GOLD_MULTIPLIER = 2
BOUNTY_DURATION = 10.0
INSIGHT_DRAW = 2
SURGE_ENERGY = 2
PATCH_GATE_LIVES = 1
EXECUTE_HP_FRACTION = 0.25
EMPOWER_DAMAGE_BONUS = 0.4
EMPOWER_DURATION = 6.0
FOCUS_FIRE_HP_FRACTION = 0.35
FOCUS_FIRE_BOSS_HP_FRACTION = 0.10


@dataclass(frozen=True)
class Spell:
    key: str
    display_name: str
    cost: int
    description: str
    cast: Callable[[Any], None]
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


def _boss_scaled(enemy: Any, fraction: float, boss_fraction: float) -> float:
    return float(enemy.max_hp * (boss_fraction if enemy.IS_BOSS else fraction))


def _zap(game: Any) -> None:
    leaders = sorted(game.enemies, key=lambda enemy: enemy.distance_traveled, reverse=True)
    for enemy in leaders[:ZAP_TARGETS]:
        enemy.take_damage(_boss_scaled(enemy, ZAP_HP_FRACTION, ZAP_BOSS_HP_FRACTION))


def _rally(game: Any) -> None:
    game.spell_fire_rate_timer = max(game.spell_fire_rate_timer, RALLY_DURATION)


def prospect_gold(depth: int) -> int:
    """Battle gold a Prospect grants at run depth `depth` -- grows with the
    run the same way every floor's own gold economy does."""
    return PROSPECT_BASE_GOLD + PROSPECT_GOLD_PER_DEPTH * depth


def _prospect(game: Any) -> None:
    depth = game.active_run.depth if game.active_run is not None else 0
    game.economy.add_gold(prospect_gold(depth))


def _shove(game: Any) -> None:
    for enemy in game.enemies:
        enemy.apply_knockback(SHOVE_DISTANCE)


def _chain_lightning(game: Any) -> None:
    for enemy in game.enemies:
        enemy.take_damage(_boss_scaled(enemy, CHAIN_LIGHTNING_HP_FRACTION, CHAIN_LIGHTNING_BOSS_HP_FRACTION))


def _blizzard(game: Any) -> None:
    for enemy in game.enemies:
        enemy.apply_slow(BLIZZARD_SLOW_FACTOR, BLIZZARD_DURATION)


def _expose(game: Any) -> None:
    for enemy in game.enemies:
        enemy.apply_mark(EXPOSE_MULTIPLIER, EXPOSE_DURATION)


def _plague(game: Any) -> None:
    for enemy in game.enemies:
        tick = _boss_scaled(enemy, PLAGUE_HP_FRACTION_PER_TICK, PLAGUE_BOSS_HP_FRACTION_PER_TICK)
        enemy.apply_poison(tick, 1.0, PLAGUE_DURATION)


def _bounty(game: Any) -> None:
    game.bounty_timer = max(game.bounty_timer, BOUNTY_DURATION)


def _insight(game: Any) -> None:
    game.combat_deck.draw(INSIGHT_DRAW)


def _surge(game: Any) -> None:
    game.combat_deck.energy += SURGE_ENERGY


def _patch_gate(game: Any) -> None:
    game.economy.lives += PATCH_GATE_LIVES


def _execute(game: Any) -> None:
    for enemy in game.enemies:
        if not enemy.IS_BOSS and enemy.hp <= enemy.max_hp * EXECUTE_HP_FRACTION:
            enemy.take_damage(enemy.hp)


def _empower(game: Any) -> None:
    game.spell_damage_timer = max(game.spell_damage_timer, EMPOWER_DURATION)


def _requisition(game: Any) -> None:
    game.free_tower_charges += 1


def _focus_fire(game: Any) -> None:
    target = max(game.enemies, key=lambda enemy: enemy.hp)
    target.take_damage(_boss_scaled(target, FOCUS_FIRE_HP_FRACTION, FOCUS_FIRE_BOSS_HP_FRACTION))


def _pct(fraction: float) -> int:
    return round(fraction * 100)


SPELLS = {
    "zap": Spell(
        "zap", "Zap", 1,
        f"Hit the {ZAP_TARGETS} enemies furthest along for {_pct(ZAP_HP_FRACTION)}% of their max HP "
        f"({_pct(ZAP_BOSS_HP_FRACTION)}% vs bosses).",
        _zap,
    ),
    "rally": Spell(
        "rally", "Rally", 1,
        f"Every tower fires {_pct(RALLY_FIRE_RATE_MULTIPLIER - 1)}% faster for {RALLY_DURATION:g}s.",
        _rally, needs_enemies=False,
    ),
    "prospect": Spell(
        "prospect", "Prospect", 1,
        f"Gain {PROSPECT_BASE_GOLD} battle gold, +{PROSPECT_GOLD_PER_DEPTH} per floor deep.",
        _prospect, needs_enemies=False,
    ),
    "shove": Spell(
        "shove", "Shove", 1,
        f"Push every enemy {SHOVE_DISTANCE:g}px back along its route.",
        _shove,
    ),
    "chain_lightning": Spell(
        "chain_lightning", "Chain Lightning", 2,
        f"Hit every enemy for {_pct(CHAIN_LIGHTNING_HP_FRACTION)}% of its max HP "
        f"({_pct(CHAIN_LIGHTNING_BOSS_HP_FRACTION)}% vs bosses).",
        _chain_lightning, rarity="uncommon",
    ),
    "blizzard": Spell(
        "blizzard", "Blizzard", 2,
        f"Slow every enemy to {_pct(BLIZZARD_SLOW_FACTOR)}% speed for {BLIZZARD_DURATION:g}s.",
        _blizzard,
    ),
    "expose": Spell(
        "expose", "Expose", 1,
        f"Mark every enemy: +{_pct(EXPOSE_MULTIPLIER - 1)}% damage taken for {EXPOSE_DURATION:g}s.",
        _expose,
    ),
    "plague": Spell(
        "plague", "Plague", 1,
        f"Poison every enemy for {_pct(PLAGUE_HP_FRACTION_PER_TICK)}% of its max HP per second "
        f"for {PLAGUE_DURATION:g}s.",
        _plague,
    ),
    "bounty": Spell(
        "bounty", "Bounty", 1,
        f"Enemies killed in the next {BOUNTY_DURATION:g}s drop {BOUNTY_GOLD_MULTIPLIER}x gold.",
        _bounty, needs_enemies=False, rarity="uncommon",
    ),
    "insight": Spell(
        "insight", "Insight", 0,
        f"Draw {INSIGHT_DRAW} cards. Exhaust.",
        _insight, needs_enemies=False, exhaust=True, rarity="uncommon",
    ),
    "surge": Spell(
        "surge", "Surge", 0,
        f"Gain {SURGE_ENERGY} energy. Exhaust.",
        _surge, needs_enemies=False, exhaust=True, rarity="rare",
    ),
    "patch_gate": Spell(
        "patch_gate", "Patch the Gate", 2,
        f"Restore {PATCH_GATE_LIVES} life. Exhaust.",
        _patch_gate, needs_enemies=False, exhaust=True, rarity="uncommon",
    ),
    "execute": Spell(
        "execute", "Execute", 2,
        f"Finish off every non-boss enemy below {_pct(EXECUTE_HP_FRACTION)}% HP.",
        _execute, rarity="uncommon",
    ),
    "empower": Spell(
        "empower", "Empower", 2,
        f"Every tower deals +{_pct(EMPOWER_DAMAGE_BONUS)}% damage for {EMPOWER_DURATION:g}s.",
        _empower, needs_enemies=False, rarity="rare",
    ),
    "requisition": Spell(
        "requisition", "Requisition", 1,
        "Your next tower placed this fight is free. Exhaust.",
        _requisition, needs_enemies=False, exhaust=True, rarity="rare",
    ),
    "focus_fire": Spell(
        "focus_fire", "Focus Fire", 1,
        f"Hit the toughest enemy for {_pct(FOCUS_FIRE_HP_FRACTION)}% of its max HP "
        f"({_pct(FOCUS_FIRE_BOSS_HP_FRACTION)}% vs bosses).",
        _focus_fire,
    ),
}

SPELL_ORDER = list(SPELLS)

REWARD_RARITY_WEIGHTS = {"common": 6, "uncommon": 3, "rare": 1}


def initials(key: str) -> str:
    """A spell's short card label -- the first letter of each word."""
    return "".join(word[0] for word in SPELLS[key].display_name.split())


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
        self.draw(self.hand_size)

    def can_play(self, index: int) -> bool:
        return 0 <= index < len(self.hand) and SPELLS[self.hand[index]].cost <= self.energy

    def play(self, index: int) -> str:
        """Remove the card at `index` from the hand, pay its energy and
        move it to the discard (or exhaust) pile. The caller casts it --
        after this, so a draw effect never re-draws the card just played."""
        key = self.hand.pop(index)
        spell = SPELLS[key]
        self.energy -= spell.cost
        (self.exhaust_pile if spell.exhaust else self.discard_pile).append(key)
        return key
