"""The out-of-battle Shop -- what a floor clear now opens onto, replacing
the old take-it-or-leave-it draft of exactly one free card. See CLAUDE.md's
"Two currencies" section for the whole redesign this belongs to, and
game.py's own note (on GameState.DRAFT) for why the *code* still says
"draft" throughout even though the *screen* is now a shop.

A shop visit offers a handful of tower cards (card_pool.draft_offer) and
relic cards (relics.relic_offer) together, each priced in RunState.
shop_currency -- a second, cross-floor currency, deliberately separate
from Economy.gold (battle gold, which resets fresh every floor -- see
economy.py/game.py's _load_floor). The player can buy zero, some, or all
of what's offered before continuing to the next floor (see Game._handle_
draft_click); every purchase within one visit costs more than the last
(PRICE_ESCALATION), so a fat currency balance still can't just buy out the
whole shop in one stop.
"""

from dataclasses import dataclass

import card_pool
import relics

# Fewer of each than the old single-type draft offered (3) -- a shop visit
# already shows both types together, so keeping each type's own count down
# is what keeps the screen from turning into a wall of cards.
TOWER_OFFER_COUNT = 2
RELIC_OFFER_COUNT = 2

# Relics priced higher than towers -- a relic is a run-long passive, a
# tower card is a one-time unlock into the build menu; placeholder numbers,
# tunable once there's real playtesting to tune against (see the loose
# draft this shipped from, please-look-at-the-jiggly-cake.md).
TOWER_PRICE = 8
RELIC_PRICE = 10

# Each purchase within the same shop visit costs 50% more than the last --
# price_for() applies this against however many items this visit has
# already bought, so pricing stays a pure function of that count rather
# than mutable per-item state living on the item itself.
PRICE_ESCALATION = 1.5

# Two independent sources feed shop currency at every floor clear (see
# Game._advance_run_floor): a small, flat income that escalates with floor_
# index (mirrors run_escalation.py's own per-floor growth, though on a much
# smaller scale -- this is a second currency, not another gold multiplier)
# plus a cut of whatever battle gold went unspent that floor, so hoarding
# gold in a fight that's already won pays off instead of it just vanishing
# when the floor resets.
BASE_INCOME_PER_FLOOR = 3
INCOME_GROWTH_PER_FLOOR = 1
LEFTOVER_GOLD_CONVERSION_RATE = 0.10


@dataclass(frozen=True)
class ShopItem:
    kind: str  # "tower" (a TOWER_TYPES name) or "relic" (a RELICS key)
    key: str
    base_price: int


def build_offer(rng, run, meta_progression_path=None):
    """This shop visit's items -- every tower slot first, then every relic
    slot, both sampled from the same `rng` in that fixed order, so a given
    (seed, floor) always offers the identical shop. Either half can come
    back shorter than its own *_OFFER_COUNT once that pool is exhausted
    (see card_pool.draft_offer/relics.relic_offer), so the returned list's
    length isn't guaranteed either -- callers already handle an empty
    result the same way the old draft did (see Game._enter_draft)."""
    tower_choices = card_pool.draft_offer(
        rng, run, count=TOWER_OFFER_COUNT, meta_progression_path=meta_progression_path,
    )
    relic_choices = relics.relic_offer(rng, run, count=RELIC_OFFER_COUNT)
    return (
        [ShopItem("tower", name, TOWER_PRICE) for name in tower_choices]
        + [ShopItem("relic", key, RELIC_PRICE) for key in relic_choices]
    )


def price_for(item, purchases_this_visit):
    """`item`'s actual cost, escalated by how many other items this same
    shop visit has already bought (0 for the first purchase, so the first
    item bought each visit always costs exactly its own base_price)."""
    return round(item.base_price * PRICE_ESCALATION ** purchases_this_visit)


def income_for_floor(floor_index, leftover_gold):
    """Shop currency earned when floor_index's floor clears, given
    `leftover_gold` battle gold still unspent at that moment -- the flat,
    escalating half plus a fraction of the leftover (see this module's own
    docstring for why leftover gold converts here instead of vanishing)."""
    flat_income = BASE_INCOME_PER_FLOOR + INCOME_GROWTH_PER_FLOOR * floor_index
    return flat_income + round(leftover_gold * LEFTOVER_GOLD_CONVERSION_RATE)
