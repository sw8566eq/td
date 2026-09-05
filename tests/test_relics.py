import random

from relics import RELICS, Relic, RelicModifiers, compose_relic_modifiers, relic_offer
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
    # Only prospectors_charm contributes gold_per_floor_bonus -- composing
    # it twice (an artificial input real play's relic_offer() exclusion
    # never produces, but compose_relic_modifiers() itself doesn't forbid)
    # is what actually distinguishes "sums" from "just copies through" for
    # the one flat-add field RelicModifiers still has.
    modifiers = compose_relic_modifiers(["prospectors_charm", "prospectors_charm"])
    assert modifiers.gold_per_floor_bonus == 2 * RELICS["prospectors_charm"].gold_per_floor_bonus


def test_compose_relic_modifiers_multipliers_multiply():
    modifiers = compose_relic_modifiers(["bounty_hunters_ledger", "bounty_hunters_ledger"])
    assert modifiers.enemy_gold_multiplier == RELICS["bounty_hunters_ledger"].enemy_gold_multiplier ** 2


def test_compose_relic_modifiers_multiplies_enemy_speed_multiplier():
    modifiers = compose_relic_modifiers(["tangled_roots", "tangled_roots"])
    assert modifiers.enemy_speed_multiplier == RELICS["tangled_roots"].enemy_speed_multiplier ** 2


def test_compose_relic_modifiers_multiplies_tower_range_multiplier():
    modifiers = compose_relic_modifiers(["spyglass_array", "spyglass_array"])
    assert modifiers.tower_range_multiplier == RELICS["spyglass_array"].tower_range_multiplier ** 2


def test_compose_relic_modifiers_multiplies_tower_fire_rate_multiplier():
    modifiers = compose_relic_modifiers(["quickfire_rounds", "quickfire_rounds"])
    assert modifiers.tower_fire_rate_multiplier == RELICS["quickfire_rounds"].tower_fire_rate_multiplier ** 2


def test_compose_relic_modifiers_sums_poison_chance():
    modifiers = compose_relic_modifiers(["venomous_coating", "venomous_coating"])
    assert modifiers.poison_chance == RELICS["venomous_coating"].poison_chance * 2


def test_compose_relic_modifiers_builds_poison_effect_from_the_relics_own_fields():
    modifiers = compose_relic_modifiers(["venomous_coating"])
    relic = RELICS["venomous_coating"]
    assert modifiers.poison_effect == (relic.poison_damage_per_tick, relic.poison_tick_interval, relic.poison_duration)


def test_compose_relic_modifiers_combines_two_poison_relics_like_two_poison_hits(monkeypatch):
    # Mirrors Enemy.apply_poison()'s own semantics for combining two hits:
    # keep the harsher tick damage and the longer duration, last-write on
    # tick interval -- an artificial input (no second poison relic exists
    # yet) that still exercises the aggregation logic directly.
    stronger_tick = Relic(
        "test_stronger_tick", "", "", poison_chance=0.1,
        poison_damage_per_tick=99, poison_tick_interval=1.0, poison_duration=1.0,
    )
    longer_duration = Relic(
        "test_longer_duration", "", "", poison_chance=0.1,
        poison_damage_per_tick=1, poison_tick_interval=2.0, poison_duration=99.0,
    )
    monkeypatch.setitem(RELICS, "test_stronger_tick", stronger_tick)
    monkeypatch.setitem(RELICS, "test_longer_duration", longer_duration)
    modifiers = compose_relic_modifiers(["test_stronger_tick", "test_longer_duration"])
    assert modifiers.poison_chance == 0.2
    assert modifiers.poison_effect == (99, 2.0, 99.0)  # max tick damage, last tick interval, max duration


def test_compose_relic_modifiers_sums_crit_chance():
    modifiers = compose_relic_modifiers(["lucky_strikes", "lucky_strikes"])
    assert modifiers.crit_chance == RELICS["lucky_strikes"].crit_chance * 2


def test_compose_relic_modifiers_takes_the_max_crit_damage_multiplier(monkeypatch):
    # Not multiplied -- two crit relics multiplying would compound fast,
    # same conservative choice already made for poison's own tick damage.
    weaker_crit = Relic("test_weaker_crit", "", "", crit_chance=0.1, crit_damage_multiplier=1.5)
    monkeypatch.setitem(RELICS, "test_weaker_crit", weaker_crit)
    modifiers = compose_relic_modifiers(["lucky_strikes", "test_weaker_crit"])
    assert modifiers.crit_damage_multiplier == RELICS["lucky_strikes"].crit_damage_multiplier


def test_compose_relic_modifiers_sums_tower_footprint_shrink():
    modifiers = compose_relic_modifiers(["compact_framework", "compact_framework"])
    assert modifiers.tower_footprint_shrink == RELICS["compact_framework"].tower_footprint_shrink * 2


def test_compose_relic_modifiers_is_order_independent():
    forward = compose_relic_modifiers(["prospectors_charm", "war_chest", "sturdy_gate"])
    backward = compose_relic_modifiers(["sturdy_gate", "war_chest", "prospectors_charm"])
    assert forward == backward


def test_war_chest_and_sturdy_gate_contribute_nothing_to_composed_modifiers():
    # Their bonuses are one-time, applied directly at draft-pick time
    # (Game._apply_one_time_relic_bonus) rather than through this per-floor
    # aggregate -- see RelicModifiers' own docstring for why a one-time
    # bonus can't be folded into per-floor composition.
    assert compose_relic_modifiers(["war_chest", "sturdy_gate"]) == RelicModifiers()
