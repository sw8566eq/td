import random

import meta_progression
from card_pool import STARTER_TOWERS, draft_offer
from run_state import RunState
from tower import TOWER_TYPES


def _run(unlocked_towers):
    return RunState(
        seed=1, floor_sequence=(1,), difficulty="normal",
        unlocked_towers=list(unlocked_towers),
    )


def test_starter_towers_are_registered_tower_types():
    assert set(STARTER_TOWERS).issubset(TOWER_TYPES.keys())


# --- draft_offer's own candidate-selection mechanics (an explicit
# unlocked_pool, so these are independent of meta_progression.py's actual
# unlock state -- see the "default unlocked_pool" section below for that
# integration). ---

def test_draft_offer_excludes_already_unlocked_towers():
    run = _run(STARTER_TOWERS)
    offer = draft_offer(random.Random(1), run, count=len(TOWER_TYPES), unlocked_pool=TOWER_TYPES.keys())
    assert not set(offer) & set(STARTER_TOWERS)


def test_draft_offer_returns_requested_count_when_pool_has_enough():
    run = _run(STARTER_TOWERS)
    offer = draft_offer(random.Random(1), run, count=3, unlocked_pool=TOWER_TYPES.keys())
    assert len(offer) == 3
    assert len(set(offer)) == 3  # no duplicate candidates offered at once


def test_draft_offer_returns_fewer_once_the_pool_is_exhausted():
    run = _run(TOWER_TYPES.keys())  # every tower already drafted
    offer = draft_offer(random.Random(1), run, count=3, unlocked_pool=TOWER_TYPES.keys())
    assert offer == []


def test_draft_offer_is_deterministic_for_a_fixed_rng_seed():
    run = _run(STARTER_TOWERS)
    first = draft_offer(random.Random(7), run, count=3, unlocked_pool=TOWER_TYPES.keys())
    second = draft_offer(random.Random(7), run, count=3, unlocked_pool=TOWER_TYPES.keys())
    assert first == second


def test_draft_offer_respects_a_custom_unlocked_pool():
    run = _run([])
    offer = draft_offer(random.Random(1), run, count=5, unlocked_pool=("basic", "cannon"))
    assert set(offer) == {"basic", "cannon"}


# --- draft_offer's default unlocked_pool (no unlocked_pool passed) ---

def test_default_pool_is_just_the_starters_with_nothing_unlocked_yet(tmp_path):
    run = _run([])
    offer = draft_offer(
        random.Random(1), run, count=len(TOWER_TYPES), meta_progression_path=tmp_path / "meta_progression.json",
    )
    assert set(offer) == set(STARTER_TOWERS)


def test_default_pool_includes_a_meta_unlocked_tower(tmp_path):
    path = tmp_path / "meta_progression.json"
    unlock = next(iter(meta_progression.META_UNLOCKS.values()))
    meta_progression.bump(unlock.counter, unlock.goal, path)

    run = _run([])
    offer = draft_offer(random.Random(1), run, count=len(TOWER_TYPES), meta_progression_path=path)

    assert unlock.tower_name in offer
