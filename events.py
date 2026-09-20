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

Relics/tower unlocks otherwise only ever flow one direction (granted, never
spent) -- EventOption.relic_cost is the one exception, letting an option
also require giving up a relic the run already holds; see its own comment
and available_options()/resolve_event_option() below for the full shape,
including why the given-up relic must be drawn before it's removed.
"""

import random
from dataclasses import dataclass

import card_pool
import relics
from run_state import RunState

_EVENT_ORDER = (
    "wandering_merchant", "ancient_shrine", "abandoned_camp", "friendly_duel",
    "traveling_healer", "cursed_idol", "old_battlefield", "collapsed_vault",
    "traveling_smith", "omen_of_ruin", "quartermasters_cache", "unclaimed_cache",
    "crumbling_shrine", "traveling_collector", "stranded_caravan", "restless_veteran",
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
    # A genuinely new resource direction -- every option above only ever
    # grants relics/towers, never spends one. True means this option also
    # requires giving up a relic the run already holds (see
    # available_options/resolve_event_option below); available_options
    # drops the option entirely once run.relics is empty, mirroring
    # relics.relic_offer's own "return fewer, don't crash" precedent for a
    # relic pool that's run dry. An option with relic_cost=True must be
    # the LAST option in its Event's own tuple -- available_options only
    # ever truncates the tail, so every earlier index's identity stays
    # stable regardless of whether this option gets filtered out (several
    # existing tests click "the first rendered option" without forcing
    # which event gets picked, and would silently break if an early-index
    # option could vanish). Enforced below EVENTS itself, not just here in
    # prose -- a module-level assert, the same load-bearing-invariant shape
    # _EVENT_ORDER's own already uses, so a future event violating this
    # rule fails at import time instead of only under the narrow runtime
    # conditions that would actually surface the desync.
    relic_cost: bool = False


@dataclass(frozen=True)
class Event:
    key: str
    display_name: str
    prompt: str
    options: tuple[EventOption, ...]  # 2-3 per event


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
    "traveling_collector": Event(
        "traveling_collector", "Traveling Collector",
        "A collector is fascinated by whatever you're carrying.",
        options=(
            EventOption(
                "sell_trinkets", "Sell her some trinkets instead (+6 shop currency)",
                "You part with a few odds and ends.",
                shop_currency_delta=6,
            ),
            EventOption("decline", "Decline and move on", "You keep everything and walk away."),
            # Deliberately last -- see EventOption.relic_cost's own comment
            # on why an option with relic_cost=True can never be placed
            # earlier in an event's own tuple.
            EventOption(
                "trade_relic", "Trade a relic for a different one (+10 shop currency)",
                "You hand over one of your relics; the collector hands back a "
                "different one, plus some currency for your trouble.",
                shop_currency_delta=10, grant_relic=True, relic_cost=True,
            ),
        ),
    ),
    "stranded_caravan": Event(
        "stranded_caravan", "Stranded Caravan",
        "A caravan lost a wheel and can't go on -- they're liquidating before scavengers find them.",
        options=(
            EventOption(
                "buy_the_schematics", "Buy the schematics (-9 shop currency, unlock a tower)",
                "You buy the blueprint outright.",
                shop_currency_delta=-9, unlock_random_tower=True,
            ),
            EventOption(
                "take_the_supplies", "Take the unguarded supplies (+12 shop currency)",
                "You take what's easy to carry.",
                shop_currency_delta=12,
            ),
            EventOption("leave_them_be", "Leave them to their luck", "You decide it isn't your business."),
        ),
    ),
    "restless_veteran": Event(
        "restless_veteran", "Restless War Veteran",
        "A war veteran, done with fighting, wants to pass on what she's carrying before she goes.",
        options=(
            EventOption(
                "accept_her_gift", "Accept her gift (unlock a tower, +5 shop currency)",
                "She hands over both without asking anything in return.",
                unlock_random_tower=True, shop_currency_delta=5,
            ),
            EventOption("wish_her_well", "Wish her well and let her go", "You let her continue on her way."),
        ),
    ),
}

# Registry insertion order isn't guaranteed stable input for rng.choice the
# way it is for rng.sample (see card_pool._default_unlocked_pool's own
# comment on the identical risk) -- _EVENT_ORDER above is the fixed order
# pick_event samples from, independent of however EVENTS itself is written.
assert set(_EVENT_ORDER) == set(EVENTS.keys())
# A machine-checked version of EventOption.relic_cost's own "must be last"
# comment, rather than trusting every future event author to remember and
# honor a rule stated only in prose -- catches a violation at import time
# (the same moment the _EVENT_ORDER check above does) instead of only
# under the narrow conditions (a relics-empty run, a test that doesn't
# force which event it lands on) that would actually surface a desync.
assert all(
    not any(option.relic_cost for option in event.options[:-1])
    for event in EVENTS.values()
), "an EventOption with relic_cost=True must be the last option in its Event"


def pick_event(rng: random.Random) -> Event:
    """One Event, deterministically, from `rng` -- the whole registry is
    always eligible (no meta_progression-style unlock gate, same reasoning
    relics.py's own module docstring gives for relics: too few events, and
    too few Event nodes per run, for a second progression system to be
    worth the complexity)."""
    return EVENTS[rng.choice(_EVENT_ORDER)]


def available_options(event: Event, run: RunState) -> list[EventOption]:
    """`event.options`, minus any relic_cost option `run` can't actually
    pay (no relics held) -- mirrors relics.relic_offer's own "return
    fewer, don't crash" precedent for a pool that's run dry, applied here
    to a fixed option tuple instead of a sampled list. Only ever truncates
    the tail (see EventOption.relic_cost's own comment on why a relic_cost
    option must be the last one in its tuple), so every remaining option
    keeps its original index -- callers that render/index by position
    (Game._enter_event_node's rect count, _handle_event_click/
    _resolve_event_choice's indexing) can use this list directly without
    it ever desyncing against what's actually on screen."""
    return [option for option in event.options if not option.relic_cost or run.relics]


def resolve_event_option(
    run: RunState, option: EventOption, item_rng: random.Random, meta_progression_path: str | None = None,
) -> dict:
    """Apply `option`'s effects directly onto `run`, returning a small
    {"relic": key} / {"tower": name} / {} dict describing what (if
    anything) was granted, for the resolved screen to describe -- plus
    "relic_given_up" when option.relic_cost fired. `item_rng` is a fresh,
    stateless random.Random (see Game._resolve_event_choice) -- keyed on
    the option actually chosen, not the event itself, so only the branch
    actually taken needs to be reproducible."""
    run.shop_currency = max(0, run.shop_currency + option.shop_currency_delta)
    run.lives = max(1, run.lives + option.lives_delta)

    # Drawn now, while still present in run.relics, so relics.relic_offer's
    # own "already held" exclusion below can't hand the exact same relic
    # right back -- but not actually removed until after that draw
    # completes (see the bottom of this function), the same "compute
    # first, mutate last" ordering that keeps the two independent.
    given_up_relic = None
    if option.relic_cost and run.relics:
        given_up_relic = item_rng.choice(run.relics)

    granted = {}
    if option.grant_relic:
        picks = relics.relic_offer(item_rng, run, count=1, meta_progression_path=meta_progression_path)
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
    if given_up_relic is not None:
        run.relics.remove(given_up_relic)
        granted["relic_given_up"] = given_up_relic
    return granted
