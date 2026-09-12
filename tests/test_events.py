import random

from card_pool import STARTER_TOWERS
from events import EVENTS, pick_event, resolve_event_option
from relics import RELICS
from run_map import MapNode, RunMap
from run_state import RunState
from tower import TOWER_TYPES

_MAP = RunMap(
    rows=((MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),),),
    edges={},
)


def _run(**overrides):
    kwargs = dict(
        seed=1, map=_MAP, difficulty="normal",
        unlocked_towers=list(STARTER_TOWERS), current_node_id="0-0",
    )
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_every_event_has_two_or_three_options():
    for event in EVENTS.values():
        assert 2 <= len(event.options) <= 3


def test_every_events_option_keys_are_unique_within_that_event():
    for event in EVENTS.values():
        keys = [option.key for option in event.options]
        assert len(keys) == len(set(keys))


def test_every_event_has_at_least_one_option_with_a_real_effect():
    # Not every option needs an effect -- "walk away"/"leave it"/"decline"
    # are deliberately safe, no-op alternatives (a genuine no-risk-no-
    # reward choice) -- but an event where *no* option does anything would
    # be a pointless node to ever land on.
    for event in EVENTS.values():
        assert any(
            option.shop_currency_delta != 0 or option.lives_delta != 0
            or option.grant_relic or option.unlock_random_tower
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
