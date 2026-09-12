"""Random Events: the run map's narrative-flavored choice nodes -- a short
prompt and 2-3 options, each a fixed, honestly-described delta rather than
a hidden-odds gamble, same "say exactly what it does" precedent relics.py's
own RELICS registry already sets. Mirrors card_pool.py/relics.py/shop.py's
own registry-and-bare-function shape.

Every option's effect is expressed purely in terms of currency/lives/relics/
tower unlocks that already exist and already persist appropriately on
RunState -- never battle gold (Economy.gold), which doesn't exist yet before
a floor loads and resets fresh every floor regardless (see CLAUDE.md's "Two
currencies" section).
"""

from dataclasses import dataclass

import card_pool
import relics

_EVENT_ORDER = (
    "wandering_merchant", "ancient_shrine", "abandoned_camp", "friendly_duel",
    "traveling_healer", "cursed_idol", "old_battlefield", "collapsed_vault",
    "traveling_smith", "omen_of_ruin", "quartermasters_cache", "unclaimed_cache",
    "crumbling_shrine",
)


@dataclass(frozen=True)
class EventOption:
    key: str
    label: str
    description: str
    shop_currency_delta: int = 0  # can be negative -- a cost
    lives_delta: int = 0  # can be negative -- resolve_event_option clamps at >=1, never kills via an event
    grant_relic: bool = False
    unlock_random_tower: bool = False


@dataclass(frozen=True)
class Event:
    key: str
    display_name: str
    prompt: str
    options: tuple  # tuple[EventOption, ...], 2-3 per event


EVENTS = {
    "wandering_merchant": Event(
        "wandering_merchant", "Wandering Merchant",
        "A merchant offers to trade a relic for some of your shop currency.",
        options=(
            EventOption(
                # Priced at shop.RELIC_PRICE (10), not above it -- an
                # earlier draft charged 15, pricier than just buying a
                # relic at the Shop itself (base price 10, only escalating
                # with *other* purchases the same visit), which made this
                # option strictly worse value than waiting for a Shop node.
                # Playtesting-driven pricing review caught the mismatch;
                # par with the Shop's own base price is what makes taking
                # the guaranteed, off-cycle deal here a genuine option
                # rather than a trap.
                "trade", "Trade 10 shop currency for a relic",
                "You hand over the currency; the merchant hands over a relic.",
                shop_currency_delta=-10, grant_relic=True,
            ),
            EventOption("walk_away", "Walk away", "You keep your currency and move on."),
        ),
    ),
    "ancient_shrine": Event(
        "ancient_shrine", "Ancient Shrine",
        "A weathered shrine seems to want an offering of life, not gold.",
        options=(
            EventOption(
                "offer", "Offer 2 lives for a relic",
                "The shrine accepts your offering and grants a relic.",
                lives_delta=-2, grant_relic=True,
            ),
            EventOption("leave", "Leave it undisturbed", "You leave the shrine as you found it."),
        ),
    ),
    "abandoned_camp": Event(
        "abandoned_camp", "Abandoned Camp",
        "A hastily-abandoned camp, still worth searching.",
        options=(
            EventOption(
                "search_thoroughly", "Search thoroughly (+15 shop currency)",
                "You take your time and find everything of value.",
                shop_currency_delta=15,
            ),
            EventOption(
                "grab_and_go", "Grab what's visible and go (+6 shop currency)",
                "You take only what's in plain sight.",
                shop_currency_delta=6,
            ),
        ),
    ),
    "friendly_duel": Event(
        "friendly_duel", "Friendly Duel",
        "A traveling engineer challenges you to a duel, wagering a tower design.",
        options=(
            EventOption(
                "accept", "Accept (risk 1 life, win a tower)",
                "You accept the challenge and win a new tower design.",
                lives_delta=-1, unlock_random_tower=True,
            ),
            EventOption("decline", "Decline", "You decline -- no risk, no reward."),
        ),
    ),
    "traveling_healer": Event(
        "traveling_healer", "Traveling Healer",
        "A healer offers to mend your losses, for a price.",
        options=(
            EventOption(
                "pay", "Pay 8 shop currency for 3 lives",
                "The healer tends to your losses.",
                shop_currency_delta=-8, lives_delta=3,
            ),
            EventOption("refuse", "Refuse", "You keep your currency and move on unhealed."),
        ),
    ),
    "cursed_idol": Event(
        "cursed_idol", "Cursed Idol",
        "A small idol radiates a faint, uneasy power.",
        options=(
            EventOption(
                "take", "Take it (lose 1 life, gain a relic)",
                "The idol's curse costs you a life as it grants its power.",
                lives_delta=-1, grant_relic=True,
            ),
            EventOption("leave", "Leave it", "You decide it isn't worth the risk."),
        ),
    ),
    "old_battlefield": Event(
        "old_battlefield", "Old Battlefield",
        "The site of some earlier battle, littered with salvage.",
        options=(
            EventOption(
                "scavenge_carefully", "Scavenge carefully (gain a relic)",
                "A careful search turns up a genuine relic.",
                grant_relic=True,
            ),
            EventOption(
                "scavenge_quickly", "Scavenge quickly (+10 shop currency)",
                "A quick pass turns up only loose currency.",
                shop_currency_delta=10,
            ),
        ),
    ),
    "collapsed_vault": Event(
        "collapsed_vault", "Collapsed Vault",
        "A sealed vault, likely damaged by whatever came through here first.",
        options=(
            EventOption(
                "force_open", "Force it open (risk 1 life, +25 shop currency)",
                "The vault gives way all at once, and not gently.",
                lives_delta=-1, shop_currency_delta=25,
            ),
            EventOption(
                "pick_lock", "Pick the lock carefully (+10 shop currency)",
                "It takes time, but the vault opens without incident.",
                shop_currency_delta=10,
            ),
            EventOption("leave_sealed", "Leave it sealed", "You decide it isn't worth the risk."),
        ),
    ),
    "traveling_smith": Event(
        "traveling_smith", "Traveling Smith",
        "A traveling smith offers a tower blueprint, for a price.",
        options=(
            EventOption(
                "buy", "Buy it (-12 shop currency, unlock a tower)",
                "The smith hands over the blueprint in exchange for your currency.",
                shop_currency_delta=-12, unlock_random_tower=True,
            ),
            EventOption("decline", "Decline", "You keep your currency and move on."),
        ),
    ),
    "omen_of_ruin": Event(
        "omen_of_ruin", "Omen of Ruin",
        "A grim omen -- turning back costs time, pressing on costs something else.",
        options=(
            EventOption(
                "press_on", "Press on (risk 2 lives, +18 shop currency)",
                "You push past the omen and find your way regardless.",
                lives_delta=-2, shop_currency_delta=18,
            ),
            EventOption("turn_back", "Turn back", "You heed the omen and lose nothing."),
        ),
    ),
    "quartermasters_cache": Event(
        "quartermasters_cache", "Quartermaster's Cache",
        "An abandoned quartermaster's cache.",
        options=(
            EventOption(
                "take_currency", "Take the currency (+14 shop currency)",
                "You take the currency and leave the rest behind.",
                shop_currency_delta=14,
            ),
            EventOption(
                "take_spare_part", "Take the spare part (-5 shop currency, gain a relic)",
                "You spend a little to salvage a usable relic.",
                shop_currency_delta=-5, grant_relic=True,
            ),
            EventOption("leave", "Leave it", "You decide it isn't worth the trouble."),
        ),
    ),
    "unclaimed_cache": Event(
        "unclaimed_cache", "Unclaimed Cache",
        "An unclaimed supply cache -- take one thing before you go.",
        options=(
            EventOption(
                "take_schematic", "Take the tower schematic (unlock a tower)",
                "You take the schematic and leave the rest untouched.",
                unlock_random_tower=True,
            ),
            EventOption(
                "take_device", "Take the strange device (gain a relic)",
                "You take the device and leave the rest untouched.",
                grant_relic=True,
            ),
        ),
    ),
    "crumbling_shrine": Event(
        "crumbling_shrine", "Crumbling Shrine",
        "A crumbling shrine -- give something, take something, or walk on.",
        options=(
            EventOption(
                "offer", "Leave an offering (-10 shop currency, +3 lives)",
                "The shrine accepts your offering and mends your wounds.",
                shop_currency_delta=-10, lives_delta=3,
            ),
            EventOption(
                "take", "Take what's left (risk 2 lives, +15 shop currency)",
                "You take what you can, and it takes something back.",
                lives_delta=-2, shop_currency_delta=15,
            ),
            EventOption("walk_on", "Walk on", "You leave the shrine undisturbed."),
        ),
    ),
}

# Registry insertion order isn't guaranteed stable input for rng.choice the
# way it is for rng.sample (see card_pool._default_unlocked_pool's own
# comment on the identical risk) -- _EVENT_ORDER above is the fixed order
# pick_event samples from, independent of however EVENTS itself is written.
assert set(_EVENT_ORDER) == set(EVENTS.keys())


def pick_event(rng):
    """One Event, deterministically, from `rng` -- the whole registry is
    always eligible (no meta_progression-style unlock gate, same reasoning
    relics.py's own module docstring gives for relics: too few events, and
    too few Event nodes per run, for a second progression system to be
    worth the complexity)."""
    return EVENTS[rng.choice(_EVENT_ORDER)]


def resolve_event_option(run, option, item_rng, meta_progression_path=None):
    """Apply `option`'s effects directly onto `run`, returning a small
    {"relic": key} / {"tower": name} / {} dict describing what (if
    anything) was granted, for the resolved screen to describe. `item_rng`
    is a fresh, stateless random.Random (see Game._resolve_event_choice) --
    keyed on the option actually chosen, not the event itself, so only the
    branch actually taken needs to be reproducible."""
    run.shop_currency = max(0, run.shop_currency + option.shop_currency_delta)
    run.lives = max(1, run.lives + option.lives_delta)

    granted = {}
    if option.grant_relic:
        picks = relics.relic_offer(item_rng, run, count=1)
        if picks:
            key = picks[0]
            run.relics.append(key)
            # Same one-time-bonus formula Game._apply_one_time_relic_bonus
            # applies for a shop-bought or Treasure-granted relic (see that
            # method's own docstring for why a one-time bonus can't be
            # folded into the normal per-floor RelicModifiers composition)
            # -- duplicated here, rather than shared, since it's a single
            # line and importing Game into this module would be circular.
            run.lives += relics.RELICS[key].starting_lives_bonus
            granted["relic"] = key
    if option.unlock_random_tower:
        picks = card_pool.draft_offer(item_rng, run, count=1, meta_progression_path=meta_progression_path)
        if picks:
            run.unlocked_towers.append(picks[0])
            granted["tower"] = picks[0]
    return granted
