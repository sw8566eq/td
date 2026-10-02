# The run's branching map

## The run's branching map

A run's map (`run/run_map.py`) is a Slay-the-Spire-style row-based DAG, generated once, up front (`Game.
start_new_run`), and shown to the player in full from the start -- not fog-of-war, not revealed
fork-by-fork. `ROW_COUNT` rows (6, unchanged from the old flat sequence's own floor count, which
keeps `run/run_escalation.py`'s tuned growth constants meaning the same thing they always did); edges
only ever run from one row to the next, never skip a row or point backward, which is what keeps
"every node reachable, every node can reach the boss" provable by simple induction (see
`_generate_edges`' own docstring) rather than needing a general graph-reachability pass after the
fact (tests still verify it via BFS over many seeds anyway). Row 0 is a fixed-width, all-Combat
choice (which of `START_ROW_WIDTH` same-difficulty layouts to open the run on, not a difficulty
choice at all) -- the run's very first resolved node is always guaranteed to be a real level load,
keeping the lives-capture special case above simple. The final row is always exactly one node of its
own dedicated `"boss"` type (`RunMap.boss_node_id`) -- fixing its width at 1 is what keeps
`is_final_floor`/`endless=True` trivial, no "did every path converge" check needed.

Every other row is a weighted-random mix of the six ordinary `NODE_TYPES` (`NODE_TYPE_WEIGHTS`) --
`"boss"` is a seventh registered type with no entry in that weight table at all, since it's never
drawn by the mix, only forced onto the final row exactly like `"combat"` is forced onto row 0 -- capped
at half the row per type (`MAX_SAME_TYPE_PER_ROW_FRACTION`) so a wide row can't degenerate into one
repeated type. `MIN_ELITE_ROW` keeps Elite off the run's opening rows; `GUARANTEED_REST_ROW` forces
at least one Rest node onto that one row if the weighted draw didn't already produce one, and
`GUARANTEED_TREASURE_ROW` (a distinct row, same injection shape) does the same for Treasure -- whose
own 4/100 weight and lack of any guarantee otherwise meant a run could plausibly see zero of them.
Both are deliberately **not** mirrored for Shop, which stays pure chance (a run's Shop cadence is
meant to vary, unlike Rest's "never go the whole back half with no way to recover lives" guarantee,
or Treasure's "always at least one guaranteed relic-shopping stop"). A Combat/Elite node's own
level id is drawn from whichever tier its row falls in (`_level_pool_for_row`, partitioned by
structure -- single-spawn "corridor" levels for earlier rows, multi-spawn "multi-lane" ones for later
rows -- not a hardcoded id list, so it stays self-maintaining as levels are added) rather than sampled
freely across all of `LEVELS`, preserving the same corridor-then-multi-lane authored ramp the old
flat, ascending `floor_sequence` used to give for free. The final row's own boss node is a further
special case on top of that tiering, not just "whichever multi-lane level a late row would otherwise
draw" -- see the Boss bullet below.

The seven node types:
- **Combat**: a normal floor, exactly what a run's only node type used to be.
- **Elite**: a harder floor (`run_escalation.apply_elite_multiplier`, layered on top of the row's own
  escalation) that pays out more shop currency on clear (`shop.income_for_floor`'s own
  `ELITE_INCOME_MULTIPLIER`) -- risk/reward, not "harder for its own sake."
- **Shop**: `GameState.DRAFT` (see its own naming note just below) -- reuses `run/shop.py` verbatim, only
  reached via a map node now rather than automatically after every floor clear (see "Two currencies"
  below for what this replaced).
- **Event**: `GameState.EVENT` -- a short prompt and 2-3 options (`run/events.py`), each a fixed,
  honestly-described delta (shop currency, lives, a relic grant, a tower unlock, or -- since the
  gaps-and-synergies batch -- giving up a relic already held, `EventOption.relic_cost`) rather than
  a hidden-odds gamble, same "say exactly what it does" precedent `run/relics.py`'s own registry sets.
  `Game.event_options` (`events.available_options(event, run)`) is the actual rendered/clickable
  subset -- may be shorter than the event's own full `options` tuple if a `relic_cost` option got
  dropped for holding no relics; a `relic_cost` option must always be the last in its tuple, since
  filtering only ever truncates the tail, keeping every other option's index stable regardless.
  Two-phase (`Game.event_phase`, "choose" then "resolved") -- `_handle_event_click`/
  `_resolve_event_choice` apply the chosen option's effect (indexing into `event_options`, never the
  raw `current_event.options`) and show what happened; any further click/key then returns to the
  map.
- **Rest**: `GameState.REST` -- Slay the Spire's campfire choice, three phases (`Game.rest_phase`):
  "choose" Rest (heal `run.lives` by `run_map.heal_amount_for_row(node.row)`) or Smith; "smith" picks a
  held, not-yet-forged tower (`Game._forgeable_towers`, a grid via `ui.build_smith_choice_rects`, plus
  Back); "resolved" then any key/click continues via `_finish_node`. Forging appends to
  `RunState.forged_towers`; `try_place_tower` then calls `Game._apply_forge` on every placement of that
  type -- one free `upgrade()`, `total_invested` reset to the base cost so a sale doesn't refund gold
  never spent, and `tower.forged = True`, which `save_state` serializes so `_tower_from_save_data`
  replays the free level the same way before replaying any paid ones.
- **Treasure**: `GameState.TREASURE` -- also auto-resolves on entry (`Game._enter_treasure_node`): a
  guaranteed shop-currency payout (`run_map.treasure_shop_currency_for_row`) plus one guaranteed relic
  pick, degrading gracefully to currency-only once every relic is already held (`relics.relic_offer`'s
  own empty-once-exhausted precedent).
- **Boss**: the run's climactic final-row node -- dispatched through `Game._load_combat_node` exactly
  like Combat/Elite (`Game._enter_node`'s `("combat", "elite", "boss")` check), escalated further still
  by `run_escalation.apply_boss_multiplier` (tuned higher than Elite's own bump), and drawn from its
  own dedicated `run_map.BOSS_LEVEL_IDS` pool (two levels, ids 16/17) rather than the ordinary
  multi-lane tier -- `_level_pool_for_row` excludes `BOSS_LEVEL_IDS` from that ordinary complex pool
  entirely, so an ordinary mid-run Elite/Combat node can never draw one early. Each ends its final
  wave in `{"final_boss": N}` (`enemy.FinalBossEnemy`, an `ENEMY_TYPES` entry reserved for these two
  levels) rather than the ordinary `{"boss": N}` every other level's own final wave still uses.
  `FinalBossEnemy` inherits `BossEnemy`'s Enrage/Armor mechanics unmodified and adds a one-time-per-run
  live mechanic of its own: while still alive, it periodically summons `SUMMON_COUNT` `ScoutEnemy`
  reinforcements at its own current position along the route, via `Enemy.pending_spawns` -- the same
  channel `SplitterEnemy` already uses, just populated repeatedly while alive rather than once at
  death, which is what required generalizing `Game.update()`'s own drain of that list: every enemy's
  own `pending_spawns` is now drained into `still_alive` and cleared *before* the dead/goal/alive split
  runs, not only inside the `if enemy.is_dead:` branch the way it worked before `FinalBossEnemy`
  existed. That same drain also runs every child/summon through `WaveManager.apply_spawn_multipliers()`
  (the post-construction difficulty/escalation/relic scaling `_spawn_enemy` applies to every wave
  spawn) before Fracture Rounds/Containment Charges touch it -- these enemies are constructed by their
  parent, never by `_spawn_enemy`, and used to enter play at baseline stats on every floor. Since the boss node is always loaded `endless=True` (see below), there is no "you defeated
  the boss, run over" screen -- `WaveManager.authored_waves_cleared` (a new flag, distinct from
  `all_waves_complete`, which never fires under `endless=True`) is what `Game.update()`'s own
  before/after check reads to detect the boss node's authored waves running out for the first time,
  firing `Game._handle_boss_defeated()`: a one-shot-per-run toast, a `bosses_defeated` bump on both
  `progression/meta_progression.py` and `progression/achievements.py` (the `"boss_slayer"` achievement), and a persistent
  `RunState.boss_defeated` flag that appends "-- Boss defeated!" onto the HUD's existing Wave line for
  the rest of the (still-ongoing, still-endless) fight -- piggybacked onto that line rather than a new
  one, same headroom reasoning `shop_currency`'s own comment in `ui.draw_hud` already gives.
  `RunState.boss_defeated` (guarded the same one-shot way `used_guardians_reprieve` is) is what stops
  a mid-boss-fight Restart -- which rebuilds a fresh `WaveManager` whose own `authored_waves_cleared`
  starts `False` again -- from double-counting `bosses_defeated` a second time.

`Game._enter_map()` (re-)shows the map screen, rebuilding `self.map_node_rects` fresh every time
(`ui.build_map_node_rects`) -- the same "computed fresh, not a persistent cache" spirit
`draft_choices` already follows, though unlike a Shop visit's own offer this never needs a
scroll-aware rebuild (the map never scrolls at `ROW_COUNT=6`). `Game._available_node_ids()` (`run.
map.start_node_ids` if nothing's been picked yet, else the current node's own edges) is the single
source of truth both `_handle_map_click`'s legality check and `ui.draw_map_screen`'s "available"
visual state read from. `Game._enter_node(node_id)` sets `run.current_node_id` and dispatches to
whichever `_enter_*_node`/`_load_combat_node` method that node type needs; `Game._finish_node
(node_id)` is the shared terminal step every non-combat resolution (a Shop's Continue, an Event's
chosen option, Rest/Treasure's auto-resolve) routes through -- mark the node visited, return to the
map. A Combat/Elite node's own clear already appends its own id in `_advance_run_floor`, so it never
goes through `_finish_node` -- there's no separate "leave the results screen" step distinct from
pressing any key on `FLOOR_CLEARED`, which goes straight to `_enter_map()`.

`GameState.MAP`/`DRAFT`/`EVENT`/`REST`/`TREASURE` are all full-screen states (like `LEVEL_SELECT`/
`EDITOR` -- see `render()`'s early-return block), not overlays drawn atop a frozen board the way
`PAUSED`/`GAME_OVER`/`VICTORY`/`FLOOR_CLEARED` are: `MAP` can be shown before any floor of the run has
ever loaded (right after `start_new_run()`, before `self.grid`/`self.economy` exist at all), so
there's structurally no board to freeze behind it -- the other four are reached from `MAP` and follow
the same full-screen convention for consistency, even on a node sequence where a board technically
still exists from an earlier floor.

## Post-combat rewards

`run/rewards.py` -- after a Combat/Elite floor's FLOOR_CLEARED results screen, any key goes to
`GameState.REWARD` (`Game._enter_reward_screen`), not straight to the map: up to
`TOWER_REWARD_COUNT` free tower cards (pick at most one, `Game._take_reward_card`; the rest are
forfeited) plus, on an Elite node only, one free relic (claimable independently, through
`_grant_relic` like every other relic source). Drawn from the same `card_pool.draft_offer`/
`relics.relic_offer` helpers the Shop uses, via `_run_rng(run, "reward", node.id)`, so the same seed
always offers the same reward. An empty reward (every tower held, no Elite relic) skips the screen
straight to the map. The node is already marked visited by `_advance_run_floor`, so leaving the
reward screen (`Continue`/`Skip`, or Enter) calls `_enter_map()` directly, never `_finish_node`. The
boss node never reaches this screen (it's endless, so it never fires FLOOR_CLEARED). Quitting on this
screen forfeits the reward, same as quitting mid-Shop forfeits the shop.

## Potions

`run/potions.py` -- `POTIONS` registry of single-use consumables, each entry carrying its own `use(game)`
function (so `Game.use_potion(slot)` never branches on which potion it is). Held on
`RunState.potions` (max `POTION_SLOTS`, duplicates allowed, serialized by `save_state` and validated
against `POTIONS` on load). Earned from post-combat rewards (always on Elite, `COMBAT_POTION_DROP_CHANCE`
otherwise, rolled *after* the tower/relic draws so existing seeds' cards don't change); a potion card
on the reward screen is unclaimable while the belt is full. Used by clicking a slot in the sidebar's
bottom-edge belt (`ui.build_potion_slot_rects`/`draw_potion_belt`, below the Sell button) -- only
during `PLAYING`. Overclock Elixir is the one timed effect: `Game.overclock_timer` (reset per floor by
`_load_level_object`) is re-applied to every tower's `potion_fire_rate_multiplier` each frame in
`update()`'s first tower pass, so towers placed mid-effect are overclocked too.

## Elite affixes

`run/elite_affixes.py` -- `AFFIXES` registry of plain multipliers (hp/speed/gold, plus
`count_multiplier`). `Game._elite_affix(run, node)` rolls one per Elite node from
`_run_rng(run, "affix", node.id)` -- never stored, so the map tooltip (`Game.map_node_affixes`, built
in `_enter_map`), the floor load and a resumed save always agree. `_floor_load_context` folds it into
the escalation (after Elite's own bump and Ascension); `_level_for_node` swaps in a private Level copy
with scaled non-boss counts for Swarming (the copy is what `save_state` stores, so resume keeps it
without re-deriving). Shown in the sidebar above the potion belt (`Renderer._run_modifiers_text`,
together with the run's Ascension) rather than on the HUD's Wave line, which has no width left with a
12-tower build menu (`test_hud_gold_lives_wave_text_fits_before_the_play_area_edge`).

Potions can also be drunk with the fixed (non-remappable) `Q`/`W`/`E` hotkeys
(`input_handler.POTION_HOTKEYS`, checked after every remappable PLAYING action so a rebinding onto
those keys still wins), and bought at the Shop's potion stand: `Game.shop_potion`, rolled in
`_enter_shop_node` from the same rng *after* `shop.build_offer` (existing seeds' card offers
unchanged), one per visit at `shop.POTION_PRICE` times the run's shop price multiplier
(`_can_buy_shop_potion` is shared by the click and the renderer).

## Starting blessing

`events.BLESSING` -- an `Event` kept out of `EVENTS`/`_EVENT_ORDER` so `pick_event` never draws it.
`Game._enter_blessing` shows it on the ordinary Event screen right after `_choose_commander`/
`_start_daily_challenge` (not inside `start_new_run`, which tests and the save path call directly),
setting `event_is_blessing`; the item rng key is `"blessing:<option>"`. Every Event-leaving path goes
through `Game._leave_event`, which returns to the map for the blessing (no node to mark visited) and
calls `_finish_node` otherwise. `EventOption.extra_relic` gives the dark bargain its second relic.
`ui.build_event_option_rects` compresses its column for 4+ options.
