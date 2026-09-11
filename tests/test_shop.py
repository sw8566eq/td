import random

from relics import RELICS
from run_map import generate_run_map
from run_state import RunState
from shop import (
    ELITE_INCOME_MULTIPLIER,
    RELIC_OFFER_COUNT,
    RELIC_PRICE,
    TOWER_OFFER_COUNT,
    TOWER_PRICE,
    ShopItem,
    build_offer,
    income_for_floor,
    price_for,
)
from tower import TOWER_TYPES


def _run(unlocked_towers=(), relics=()):
    # build_offer only ever reads run.unlocked_towers/run.relics -- the map
    # itself is irrelevant here, just a real one RunState now requires.
    game_map = generate_run_map(random.Random(1))
    return RunState(
        seed=1, map=game_map, difficulty="normal",
        unlocked_towers=list(unlocked_towers), relics=list(relics),
        current_node_id=game_map.start_node_ids[0],
    )


# --- build_offer ---


def test_build_offer_mixes_towers_and_relics_together(tmp_path):
    run = _run()
    offer = build_offer(random.Random(1), run, meta_progression_path=tmp_path / "meta_progression.json")
    kinds = {item.kind for item in offer}
    assert kinds == {"tower", "relic"}


def test_build_offer_towers_exclude_already_unlocked_ones(tmp_path):
    run = _run(unlocked_towers=TOWER_TYPES.keys())  # every tower already unlocked
    offer = build_offer(random.Random(1), run, meta_progression_path=tmp_path / "meta_progression.json")
    assert all(item.kind != "tower" for item in offer)
    assert any(item.kind == "relic" for item in offer)  # relics aren't gated the same way


def test_build_offer_relics_exclude_already_held_ones(tmp_path):
    run = _run(relics=RELICS.keys())  # every relic already held
    offer = build_offer(random.Random(1), run, meta_progression_path=tmp_path / "meta_progression.json")
    assert all(item.kind != "relic" for item in offer)


def test_build_offer_is_empty_once_both_pools_are_exhausted(tmp_path):
    run = _run(unlocked_towers=TOWER_TYPES.keys(), relics=RELICS.keys())
    offer = build_offer(random.Random(1), run, meta_progression_path=tmp_path / "meta_progression.json")
    assert offer == []


def test_build_offer_prices_towers_and_relics_at_their_own_module_constants(tmp_path):
    run = _run()
    offer = build_offer(random.Random(1), run, meta_progression_path=tmp_path / "meta_progression.json")
    for item in offer:
        assert item.base_price == (TOWER_PRICE if item.kind == "tower" else RELIC_PRICE)


def test_build_offer_is_deterministic_for_a_fixed_rng_seed(tmp_path):
    run = _run()
    path = tmp_path / "meta_progression.json"
    first = build_offer(random.Random(7), run, meta_progression_path=path)
    second = build_offer(random.Random(7), run, meta_progression_path=path)
    assert first == second


def test_build_offer_respects_its_own_offer_counts(tmp_path):
    # A pool wide open (no exhaustion on either side) offers exactly
    # TOWER_OFFER_COUNT + RELIC_OFFER_COUNT items -- STARTER_TOWERS alone
    # already has more towers than TOWER_OFFER_COUNT, and RELICS has far
    # more relics than RELIC_OFFER_COUNT, so neither side is starved here.
    run = _run()
    offer = build_offer(random.Random(1), run, meta_progression_path=tmp_path / "meta_progression.json")
    assert len(offer) == TOWER_OFFER_COUNT + RELIC_OFFER_COUNT


# --- price_for ---


def test_price_for_the_first_purchase_is_the_base_price():
    item = ShopItem("tower", "basic", 8)
    assert price_for(item, purchases_this_visit=0) == 8


def test_price_for_escalates_with_purchases_this_visit():
    item = ShopItem("relic", "war_chest", 10)
    first = price_for(item, purchases_this_visit=0)
    second = price_for(item, purchases_this_visit=1)
    third = price_for(item, purchases_this_visit=2)
    assert first < second < third


# --- income_for_floor ---


def test_income_for_floor_grows_with_floor_index_alone():
    previous = income_for_floor(0, leftover_gold=0)
    for floor_index in range(1, 10):
        current = income_for_floor(floor_index, leftover_gold=0)
        assert current > previous
        previous = current


def test_income_for_floor_grows_with_leftover_gold_alone():
    assert income_for_floor(0, leftover_gold=500) > income_for_floor(0, leftover_gold=0)


def test_income_for_floor_is_deterministic():
    assert income_for_floor(3, leftover_gold=120) == income_for_floor(3, leftover_gold=120)


def test_income_for_floor_elite_bonus_pays_out_more_than_normal():
    normal = income_for_floor(2, leftover_gold=50, is_elite=False)
    elite = income_for_floor(2, leftover_gold=50, is_elite=True)
    assert elite == round(normal * ELITE_INCOME_MULTIPLIER)
    assert elite > normal
