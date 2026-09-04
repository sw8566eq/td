import random

from relics import RELICS, RelicModifiers, compose_relic_modifiers, relic_offer
from run_state import RunState


def _run(relics=()):
    return RunState(
        seed=1, floor_sequence=(1,), difficulty="normal",
        unlocked_towers=["basic", "cannon", "frost"], relics=list(relics),
    )


def test_relic_offer_excludes_already_held_relics():
    run = _run(relics=["prospectors_charm"])
    offer = relic_offer(random.Random(1), run, count=len(RELICS))
    assert "prospectors_charm" not in offer


def test_relic_offer_returns_requested_count_when_pool_has_enough():
    run = _run()
    offer = relic_offer(random.Random(1), run, count=2)
    assert len(offer) == 2
    assert len(set(offer)) == 2


def test_relic_offer_returns_fewer_once_the_pool_is_exhausted():
    run = _run(relics=list(RELICS.keys()))  # every relic already held
    assert relic_offer(random.Random(1), run, count=3) == []


def test_relic_offer_is_deterministic_for_a_fixed_rng_seed():
    run = _run()
    first = relic_offer(random.Random(7), run, count=2)
    second = relic_offer(random.Random(7), run, count=2)
    assert first == second


def test_compose_relic_modifiers_with_no_relics_is_a_no_op():
    assert compose_relic_modifiers([]) == RelicModifiers()


def test_compose_relic_modifiers_flat_bonuses_add():
    modifiers = compose_relic_modifiers(["prospectors_charm", "sturdy_gate"])
    assert modifiers.gold_per_floor_bonus == RELICS["prospectors_charm"].gold_per_floor_bonus
    assert modifiers.starting_lives_bonus == RELICS["sturdy_gate"].starting_lives_bonus


def test_compose_relic_modifiers_multipliers_multiply():
    modifiers = compose_relic_modifiers(["war_chest", "bounty_hunters_ledger"])
    assert modifiers.starting_gold_multiplier == RELICS["war_chest"].starting_gold_multiplier
    assert modifiers.enemy_gold_multiplier == RELICS["bounty_hunters_ledger"].enemy_gold_multiplier


def test_compose_relic_modifiers_is_order_independent():
    forward = compose_relic_modifiers(["prospectors_charm", "war_chest", "sturdy_gate"])
    backward = compose_relic_modifiers(["sturdy_gate", "war_chest", "prospectors_charm"])
    assert forward == backward
