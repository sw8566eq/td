# Economy and the Shop

## Two currencies: battle gold and the Shop

A run tracks two independent currencies, deliberately never convertible into each other: **battle
gold** (`Economy.gold`, unchanged as a concept -- what places/upgrades/specializes/sells towers
mid-floor) resets fresh every floor rather than carrying forward, and **shop currency**
(`RunState.shop_currency`) persists across the whole run and is what actually buys cards at the Shop
(`GameState.DRAFT` -- see its own naming note in `core/game.py` for why the code still says "draft"
throughout even though the screen is a shop now, only reached via a map node -- see "The run's
branching map" above -- rather than automatically after every floor clear). A Treasure node and a
Random Event's own `grant_relic`/`unlock_random_tower` options also grant cards/currency directly
(see above), independent of the Shop entirely. Before this split, `RunState.gold` carried battle
gold forward the same unconditional way `lives` still does; there is no such field any more --
`_load_combat_node` never restores or captures battle gold, it's simply rebuilt fresh by every
floor's own `_load_level_object()` call (relic-adjustable via `RelicModifiers.starting_gold_
multiplier`/`gold_per_floor_bonus`, both applied every floor now with no first-node special case
left).

`run/shop.py` is where the Shop's own logic lives, mirroring `run/card_pool.py`/`run/relics.py`'s own
registry-and-bare-function shape:

- `build_offer(rng, run, meta_progression_path=None)` -- this shop visit's items, mixing both card
  types together in one offer (`TOWER_OFFER_COUNT` towers via `card_pool.draft_offer`, then
  `RELIC_OFFER_COUNT` relics via `relics.relic_offer`, same exclude-what's-already-held rules as
  before). Either half can come back shorter once its own pool is exhausted; `Game._enter_shop_node()`
  still skips the screen entirely only if the *combined* offer is empty. The relic half offers one
  extra slot (`RELIC_OFFER_COUNT + 1`) once `meta_progression.has_unlocked_third_relic_slot()` is
  crossed (`SHOP_META_UNLOCKS`' own single entry, `total_floors_cleared=100` -- deliberately the
  longest chase in the whole meta-progression system, since a permanent account-wide Shop upgrade
  outranks any single relic/level) -- read here, directly, the same way `relic_offer()`/
  `draft_offer()` already resolve their own default pools internally from `meta_progression_path`
  rather than pushing the decision up to a caller. `ui.build_draft_choice_rects()` switches to a
  narrower `DRAFT_CARD_WIDTH_COMPACT` once `count >= 5` (5 cards at the normal `DRAFT_CARD_WIDTH`
  would overflow `SCREEN_WIDTH`), and `_draw_relic_card()`'s own text-wrap width is derived from the
  actual rendered rect rather than a fixed constant, so relic description text can't overflow the
  narrower card.
- `price_for(item, purchases_this_visit, discount_multiplier=1.0)` -- an item's actual cost,
  escalated by `PRICE_ESCALATION` for every other item this same shop visit has already bought (0
  for the first purchase), then discounted by a Haggling Permit-style relic's own
  `RelicModifiers.shop_price_multiplier` (default 1.0, a no-op -- `quartermasters_favor` already
  covers the battle-gold half of the economy, this is the shop-currency half). Kept as a pure
  function of a purchase *count* (and this one relic-driven multiplier), not mutable per-item state,
  so `ui.draw_draft_screen` (showing what the *next* purchase would cost) and `Game._try_buy_shop_item`
  (actually charging it) can't drift apart on what "the current price" means. Both read the
  multiplier via `Game._shop_price_multiplier()`, composed fresh from `run.relics` -- never from
  `Game.relic_modifiers`, which is only recomposed at combat-floor load and so is stale for a Permit
  gained or given up between floors (Treasure, Event, or earlier in the same Shop visit).
- `income_for_floor(floor_index, leftover_gold, is_elite=False)` -- shop currency earned at a floor
  clear (`Game._advance_run_floor`): a small flat amount that escalates with `floor_index` (the
  cleared node's own row, mirroring `run/run_escalation.py`'s own per-floor growth on a much smaller
  scale) plus `LEFTOVER_GOLD_CONVERSION_RATE` of whatever battle gold was still unspent at that
  moment -- since battle gold itself never carries forward (see above), this is what makes hoarding
  it in an already-won fight pay off instead of the surplus just vanishing when the floor resets.
  `is_elite` scales the whole result up by `ELITE_INCOME_MULTIPLIER` -- an Elite node's own reward for
  its extra risk (see "The run's branching map" above).

Buying is `Game._try_buy_shop_item(index)`: a silent no-op if unaffordable (same "click does nothing"
precedent `try_place_tower`'s own unbuildable-spot case sets), otherwise it deducts the escalated
price, records the index in `self.shop_purchased_indices` (drawn as SOLD and no longer clickable --
see `ui.draw_draft_screen`), and applies the card: a tower name onto `run.unlocked_towers`, or a relic
key via `Game._grant_relic()` (appends to `run.relics` and applies `_apply_one_time_relic_bonus()` --
the one choke point every relic-granting path, a Shop purchase or a Treasure node's guaranteed pick
alike, routes through). Buying never leaves the shop by itself -- the player can buy several items (or
none) in one visit, then explicitly clicks Continue (`ui.build_shop_continue_button_rect()`) to call
`Game._finish_node()` and return to the map, the same terminal step every other non-combat node
resolution uses. `self.economy.unlimited_gold` (already exactly `self.unlimited_gold or sandbox`, see
"Economy debug flag" below) makes every shop item free the same way it already makes battle gold
spending free -- there's no separate sandbox flag for shop currency.

Battle gold has a third source besides placing-a-tower's own starting pool and a floor's per-kill
rewards: `SiphonTower` generates it mid-floor from a fraction of damage dealt (see that tower's own
section below) -- still just `Economy.gold`, still reset fresh every floor like every other battle
gold, not a new currency of its own.

## Economy debug flag

`Economy.unlimited_gold` (set via `Game(unlimited_gold=...)`, which `main.py --unlimited-gold`
threads through) makes `can_afford()` always `True` and `spend()` a no-op that leaves `gold`
untouched -- every purchase path (place/upgrade/specialize a tower) needed no changes to support
it. `presentation/ui.py`'s HUD shows `"Gold: unlimited"` while it's set. Sandbox mode (see "Difficulty modes,
Sandbox mode, and player settings" above) reuses this exact flag for its own unlimited-gold behavior
(`unlimited_gold=self.unlimited_gold or sandbox`) rather than introducing a second, parallel
concept -- `Economy.invulnerable` is the one genuinely new flag Sandbox needed. The Shop (see "Two
currencies" above) reuses this same flag for shop currency too, rather than a third parallel concept.
