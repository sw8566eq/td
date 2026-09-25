import random

from entities.tower import TOWER_TYPES
from run.card_pool import STARTER_TOWERS
from run.events import (
    EVENTS,
    available_options,
    can_afford_option,
    pick_event,
    resolve_event_option,
)
from run.relics import RELICS
from run.run_map import MapNode, RunMap
from run.run_state import RunState

_MAP = RunMap(
    rows=((MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),),),
    edges={},
)


def _run(**overrides):
    kwargs = {
        "seed": 1, "map": _MAP, "difficulty": "normal",
        "unlocked_towers": list(STARTER_TOWERS), "current_node_id": "0-0",
    }
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_every_event_has_two_or_three_options():
    for event in EVENTS.values():
        assert 2 <= len(event.options) <= 3


def test_every_events_option_keys_are_unique_within_that_event():
    for event in EVENTS.values():
        keys = [option.key for option in event.options]
        assert len(keys) == len(set(keys))


def test_a_relic_cost_option_is_always_the_last_option_in_its_event():
    # events.py itself already enforces this with a module-level assert at
    # import time (see EventOption.relic_cost's own comment on why it
    # matters) -- this test re-confirms the same rule as an ordinary,
    # individually-reportable pytest failure too, rather than relying
    # solely on collection-time import failing.
    for event in EVENTS.values():
        assert not any(option.relic_cost for option in event.options[:-1]), event.key


def test_every_event_has_at_least_one_option_with_a_real_effect():
    # Not every option needs an effect -- "walk away"/"leave it"/"decline"
    # are deliberately safe, no-op alternatives (a genuine no-risk-no-
    # reward choice) -- but an event where *no* option does anything would
    # be a pointless node to ever land on.
    for event in EVENTS.values():
        assert any(
            option.shop_currency_delta != 0 or option.lives_delta != 0
            or option.grant_relic or option.unlock_random_tower or option.relic_cost
            for option in event.options
        ), f"{event.key} has no option that does anything"


def test_pick_event_is_deterministic_for_a_fixed_seed():
    assert pick_event(random.Random(7)) == pick_event(random.Random(7))


def test_pick_event_returns_a_registered_event():
    for seed in range(20):
        assert pick_event(random.Random(seed)).key in EVENTS


def test_resolve_event_option_applies_currency_delta():
    option = next(o for e in EVENTS.values() for o in e.options if o.shop_currency_delta > 0)
    run = _run(shop_currency=10)
    resolve_event_option(run, option, random.Random(1))
    assert run.shop_currency == 10 + option.shop_currency_delta


def _option(event_key, option_key):
    return next(o for o in EVENTS[event_key].options if o.key == option_key)


def test_a_currency_costing_option_is_unaffordable_without_enough_currency():
    option = _option("stranded_caravan", "buy_the_schematics")  # -9 shop currency
    assert not can_afford_option(option, _run(shop_currency=8, lives=5))
    assert can_afford_option(option, _run(shop_currency=9, lives=5))


def test_unlimited_currency_waives_only_the_currency_cost():
    assert can_afford_option(_option("stranded_caravan", "buy_the_schematics"), _run(shop_currency=0, lives=5),
                             unlimited_currency=True)
    lives_costing = next(o for e in EVENTS.values() for o in e.options if o.lives_delta < 0)
    assert not can_afford_option(lives_costing, _run(lives=1), unlimited_currency=True)


def test_a_lives_costing_option_is_unaffordable_if_it_would_leave_no_lives():
    option = next(o for e in EVENTS.values() for o in e.options if o.lives_delta == -2)
    assert not can_afford_option(option, _run(lives=2))
    assert can_afford_option(option, _run(lives=3))


def test_a_cost_free_option_is_always_affordable():
    option = _option("stranded_caravan", "leave_them_be")
    assert can_afford_option(option, _run(shop_currency=0, lives=1))


def test_every_event_has_an_option_affordable_with_nothing():
    # Otherwise a broke, 1-life run could land on an Event it can't leave.
    broke = _run(shop_currency=0, lives=1)
    for event in EVENTS.values():
        assert any(can_afford_option(o, broke) for o in available_options(event, broke)), event.key


def test_resolve_event_option_clamps_shop_currency_at_zero():
    option = next(o for e in EVENTS.values() for o in e.options if o.shop_currency_delta < 0)
    run = _run(shop_currency=0)
    resolve_event_option(run, option, random.Random(1))
    assert run.shop_currency == 0


def test_resolve_event_option_clamps_lives_at_one():
    option = next(o for e in EVENTS.values() for o in e.options if o.lives_delta < 0)
    run = _run(lives=1)
    resolve_event_option(run, option, random.Random(1))
    assert run.lives == 1


def test_resolve_event_option_applies_lives_delta_when_not_clamped():
    option = next(o for e in EVENTS.values() for o in e.options if o.lives_delta > 0)
    run = _run(lives=5)
    resolve_event_option(run, option, random.Random(1))
    assert run.lives == 5 + option.lives_delta


def test_resolve_event_option_grants_a_relic_and_reports_it():
    option = next(o for e in EVENTS.values() for o in e.options if o.grant_relic)
    run = _run()

    granted = resolve_event_option(run, option, random.Random(1))

    assert granted["relic"] in RELICS
    assert granted["relic"] in run.relics


def test_resolve_event_option_relic_grant_degrades_gracefully_once_exhausted():
    option = next(o for e in EVENTS.values() for o in e.options if o.grant_relic)
    run = _run(relics=list(RELICS.keys()))  # every relic already held

    granted = resolve_event_option(run, option, random.Random(1))

    assert "relic" not in granted
    assert run.relics == list(RELICS.keys())  # unchanged


def test_resolve_event_option_grants_a_relics_one_time_bonus():
    # sturdy_gate's +3 lives is a one-time bonus, applied the instant it's
    # granted (see Game._apply_one_time_relic_bonus's own docstring for why)
    # -- events.py duplicates that one-line formula rather than sharing it
    # with Game (see resolve_event_option's own comment); this proves the
    # duplicate actually applies it. Every relic but sturdy_gate is already
    # held, so relic_offer's own candidate pool is exactly {"sturdy_gate"}
    # regardless of rng draw.
    option = next(o for e in EVENTS.values() for o in e.options if o.grant_relic)
    run = _run(relics=[key for key in RELICS if key != "sturdy_gate"], lives=10)

    granted = resolve_event_option(run, option, random.Random(1))

    assert granted["relic"] == "sturdy_gate"
    assert run.lives == 10 + RELICS["sturdy_gate"].starting_lives_bonus


def test_resolve_event_option_unlocks_a_tower_and_reports_it(tmp_path):
    option = next(o for e in EVENTS.values() for o in e.options if o.unlock_random_tower)
    run = _run(unlocked_towers=[])

    granted = resolve_event_option(run, option, random.Random(1), meta_progression_path=tmp_path / "meta.json")

    assert granted["tower"] in TOWER_TYPES
    assert granted["tower"] in run.unlocked_towers


def test_resolve_event_option_tower_grant_degrades_gracefully_once_exhausted(tmp_path):
    option = next(o for e in EVENTS.values() for o in e.options if o.unlock_random_tower)
    run = _run(unlocked_towers=list(TOWER_TYPES.keys()))  # every tower already unlocked

    granted = resolve_event_option(run, option, random.Random(1), meta_progression_path=tmp_path / "meta.json")

    assert "tower" not in granted


# --- The 6 events added in Chunk D, one test per event covering every one
# of its own options' deltas -- rather than the generic "first option
# anywhere in the registry matching X" shape the original 7 events' tests
# above use, since that shape can't target a *specific* new event/option.


def test_collapsed_vault_options():
    event = EVENTS["collapsed_vault"]
    assert len(event.options) == 3

    force_open, pick_lock, leave_sealed = event.options

    run = _run(shop_currency=0, lives=5)
    resolve_event_option(run, force_open, random.Random(1))
    assert run.shop_currency == 25
    assert run.lives == 4

    run = _run(shop_currency=0)
    resolve_event_option(run, pick_lock, random.Random(1))
    assert run.shop_currency == 10

    run = _run(shop_currency=0, lives=5)
    resolve_event_option(run, leave_sealed, random.Random(1))
    assert run.shop_currency == 0
    assert run.lives == 5


def test_traveling_smith_options(tmp_path):
    event = EVENTS["traveling_smith"]
    assert len(event.options) == 2

    buy, decline = event.options

    run = _run(shop_currency=20, unlocked_towers=[])
    granted = resolve_event_option(run, buy, random.Random(1), meta_progression_path=tmp_path / "meta.json")
    assert run.shop_currency == 8
    assert granted["tower"] in run.unlocked_towers

    run = _run(shop_currency=20)
    resolve_event_option(run, decline, random.Random(1))
    assert run.shop_currency == 20


def test_omen_of_ruin_options():
    event = EVENTS["omen_of_ruin"]
    assert len(event.options) == 2

    press_on, turn_back = event.options

    run = _run(shop_currency=0, lives=5)
    resolve_event_option(run, press_on, random.Random(1))
    assert run.shop_currency == 18
    assert run.lives == 3

    run = _run(shop_currency=0, lives=5)
    resolve_event_option(run, turn_back, random.Random(1))
    assert run.shop_currency == 0
    assert run.lives == 5


def test_quartermasters_cache_options():
    event = EVENTS["quartermasters_cache"]
    assert len(event.options) == 3

    take_currency, take_spare_part, leave = event.options

    run = _run(shop_currency=0)
    resolve_event_option(run, take_currency, random.Random(1))
    assert run.shop_currency == 14

    run = _run(shop_currency=10)
    granted = resolve_event_option(run, take_spare_part, random.Random(1))
    assert run.shop_currency == 5
    assert granted["relic"] in run.relics

    run = _run(shop_currency=0)
    resolve_event_option(run, leave, random.Random(1))
    assert run.shop_currency == 0


def test_unclaimed_cache_options(tmp_path):
    event = EVENTS["unclaimed_cache"]
    assert len(event.options) == 2

    take_schematic, take_device = event.options

    run = _run(unlocked_towers=[])
    granted = resolve_event_option(run, take_schematic, random.Random(1), meta_progression_path=tmp_path / "meta.json")
    assert granted["tower"] in run.unlocked_towers

    run = _run()
    granted = resolve_event_option(run, take_device, random.Random(1))
    assert granted["relic"] in run.relics


def test_crumbling_shrine_options():
    event = EVENTS["crumbling_shrine"]
    assert len(event.options) == 3

    offer, take, walk_on = event.options

    run = _run(shop_currency=10, lives=5)
    resolve_event_option(run, offer, random.Random(1))
    assert run.shop_currency == 0
    assert run.lives == 8

    run = _run(shop_currency=0, lives=5)
    resolve_event_option(run, take, random.Random(1))
    assert run.shop_currency == 15
    assert run.lives == 3

    run = _run(shop_currency=0, lives=5)
    resolve_event_option(run, walk_on, random.Random(1))
    assert run.shop_currency == 0
    assert run.lives == 5


# --- The 3 events added in this batch: Traveling Collector (a genuinely
# new "spend a relic you hold" resource direction), Stranded Caravan and
# Restless Veteran (leaning on unlock_random_tower, previously
# under-represented at only 3/13 events).


def test_traveling_collector_options():
    event = EVENTS["traveling_collector"]
    assert len(event.options) == 3

    sell_trinkets, decline, trade_relic = event.options
    assert trade_relic.relic_cost  # must be last -- see EventOption.relic_cost's own comment

    run = _run(shop_currency=0)
    resolve_event_option(run, sell_trinkets, random.Random(1))
    assert run.shop_currency == 6

    run = _run(shop_currency=0)
    resolve_event_option(run, decline, random.Random(1))
    assert run.shop_currency == 0

    run = _run(shop_currency=0, relics=["war_chest"])
    granted = resolve_event_option(run, trade_relic, random.Random(1))
    assert run.shop_currency == 10
    assert granted["relic_given_up"] == "war_chest"
    assert "war_chest" not in run.relics
    assert granted["relic"] in run.relics
    assert granted["relic"] != "war_chest"


def test_stranded_caravan_options(tmp_path):
    event = EVENTS["stranded_caravan"]
    assert len(event.options) == 3

    buy, take, leave = event.options

    run = _run(shop_currency=20, unlocked_towers=[])
    granted = resolve_event_option(run, buy, random.Random(1), meta_progression_path=tmp_path / "meta.json")
    assert run.shop_currency == 11
    assert granted["tower"] in run.unlocked_towers

    run = _run(shop_currency=0)
    resolve_event_option(run, take, random.Random(1))
    assert run.shop_currency == 12

    run = _run(shop_currency=20)
    resolve_event_option(run, leave, random.Random(1))
    assert run.shop_currency == 20


def test_restless_veteran_options(tmp_path):
    event = EVENTS["restless_veteran"]
    assert len(event.options) == 2

    accept, decline = event.options

    run = _run(shop_currency=0, unlocked_towers=[])
    granted = resolve_event_option(run, accept, random.Random(1), meta_progression_path=tmp_path / "meta.json")
    assert run.shop_currency == 5
    assert granted["tower"] in run.unlocked_towers

    run = _run(shop_currency=0)
    resolve_event_option(run, decline, random.Random(1))
    assert run.shop_currency == 0


# --- available_options (relic_cost filtering) ---


def test_available_options_includes_relic_cost_option_when_a_relic_is_held():
    event = EVENTS["traveling_collector"]
    run = _run(relics=["war_chest"])
    assert available_options(event, run) == list(event.options)


def test_available_options_drops_relic_cost_option_when_no_relic_is_held():
    event = EVENTS["traveling_collector"]
    run = _run(relics=[])
    options = available_options(event, run)
    assert len(options) == len(event.options) - 1
    assert all(not option.relic_cost for option in options)
    # Only the tail was dropped -- every remaining option keeps its
    # original index (see EventOption.relic_cost's own comment on why).
    assert options == list(event.options[:-1])


def test_available_options_never_drops_a_non_relic_cost_option():
    for event in EVENTS.values():
        run = _run(relics=[])
        options = available_options(event, run)
        non_relic_cost_count = sum(1 for option in event.options if not option.relic_cost)
        assert len(options) >= non_relic_cost_count


# --- resolve_event_option's relic-given-up mechanics ---


def test_resolve_event_option_relic_cost_removes_the_given_up_relic():
    option = next(o for e in EVENTS.values() for o in e.options if o.relic_cost)
    run = _run(relics=["war_chest"])

    granted = resolve_event_option(run, option, random.Random(1))

    assert granted["relic_given_up"] == "war_chest"
    assert "war_chest" not in run.relics


def test_resolve_event_option_relic_cost_never_redraws_the_same_relic():
    # war_chest is the only relic held, so a naive "remove first, draw
    # second" ordering could legally hand it right back once relic_offer's
    # own already-held exclusion no longer sees it.
    option = next(o for e in EVENTS.values() for o in e.options if o.relic_cost)
    for seed in range(20):
        run = _run(relics=["war_chest"])
        granted = resolve_event_option(run, option, random.Random(seed))
        assert granted["relic"] != "war_chest"


def test_resolve_event_option_relic_cost_is_a_noop_when_no_relic_is_held():
    # Calling directly, bypassing available_options entirely -- confirms
    # the guard lives in resolve_event_option itself, not only in the
    # filtering layer above it. The option's own grant_relic still fires
    # independently (it isn't gated on relics being held) -- only the
    # relic_cost side is a no-op here.
    option = next(o for e in EVENTS.values() for o in e.options if o.relic_cost)
    run = _run(relics=[])

    granted = resolve_event_option(run, option, random.Random(1))

    assert "relic_given_up" not in granted
