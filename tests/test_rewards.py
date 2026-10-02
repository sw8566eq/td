"""Tests for run/rewards.py -- the post-combat reward offer itself. The
REWARD screen's Game-level flow is covered in test_run.py."""

import random

from conftest import make_linear_run_map

from entities.tower import TOWER_TYPES
from run import card_pool, potions, rewards
from run.card_pool import STARTER_TOWERS
from run.potions import POTIONS
from run.relics import RELICS
from run.run_state import RunState


def _run(**overrides):
    kwargs = {
        "seed": 1, "map": make_linear_run_map(["combat"]), "difficulty": "normal",
        "unlocked_towers": list(STARTER_TOWERS),
    }
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_combat_reward_offers_unheld_towers_and_no_relic(tmp_path, monkeypatch):
    monkeypatch.setattr(card_pool, "_default_unlocked_pool", lambda _path: list(TOWER_TYPES))
    run = _run()
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=False, meta_progression_path=str(tmp_path / "meta.json"),
    )
    assert len(reward.tower_choices) == rewards.TOWER_REWARD_COUNT
    assert not set(reward.tower_choices) & set(STARTER_TOWERS)
    assert reward.relic is None
    assert not reward.is_empty


def test_elite_reward_adds_an_unheld_relic(tmp_path):
    run = _run(relics=["lucky_strikes"])
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=True, meta_progression_path=str(tmp_path / "meta.json"),
    )
    assert reward.relic in RELICS
    assert reward.relic != "lucky_strikes"


def test_reward_is_empty_once_every_pool_is_exhausted(tmp_path):
    run = _run(unlocked_towers=list(TOWER_TYPES), relics=list(RELICS))
    reward = rewards.build_combat_reward(
        random.Random(1), run, is_elite=True, meta_progression_path=str(tmp_path / "meta.json"),
    )
    assert reward.tower_choices == ()
    assert reward.relic is None
    # Potions are never exhausted, and an Elite always drops one.
    assert reward.potion in POTIONS
    assert not reward.is_empty
    assert rewards.CombatReward(()).is_empty


def test_combat_potion_drop_follows_the_drop_chance(tmp_path, monkeypatch):
    path = str(tmp_path / "meta.json")
    run = _run(unlocked_towers=list(TOWER_TYPES))
    monkeypatch.setattr(potions, "COMBAT_POTION_DROP_CHANCE", 1.0)
    assert rewards.build_combat_reward(random.Random(1), run, is_elite=False, meta_progression_path=path).potion in POTIONS
    monkeypatch.setattr(potions, "COMBAT_POTION_DROP_CHANCE", 0.0)
    assert rewards.build_combat_reward(random.Random(1), run, is_elite=False, meta_progression_path=path).potion is None


def test_same_rng_seed_gives_the_same_reward(tmp_path):
    path = str(tmp_path / "meta.json")
    first = rewards.build_combat_reward(random.Random(7), _run(), is_elite=True, meta_progression_path=path)
    second = rewards.build_combat_reward(random.Random(7), _run(), is_elite=True, meta_progression_path=path)
    assert first == second


def test_forge_cards_fill_the_tower_row_once_new_towers_run_out(tmp_path):
    run = _run(unlocked_towers=list(TOWER_TYPES), forged_towers=["basic"])
    reward = rewards.build_combat_reward(random.Random(1), run, is_elite=False,
                                         meta_progression_path=str(tmp_path / "m.json"))
    assert reward.tower_choices == ()
    assert len(reward.forge_choices) == rewards.TOWER_REWARD_COUNT
    assert "basic" not in reward.forge_choices
    assert set(reward.forge_choices) <= set(TOWER_TYPES)


def test_no_forge_cards_while_new_towers_fill_the_row(tmp_path, monkeypatch):
    monkeypatch.setattr(card_pool, "_default_unlocked_pool", lambda _path: list(TOWER_TYPES))
    reward = rewards.build_combat_reward(random.Random(1), _run(), is_elite=False,
                                         meta_progression_path=str(tmp_path / "m.json"))
    assert reward.forge_choices == ()


def test_deeper_rewards_offer_pre_forged_towers(tmp_path, monkeypatch):
    from conftest import make_linear_run_map

    monkeypatch.setattr(card_pool, "_default_unlocked_pool", lambda _path: list(TOWER_TYPES))
    path = str(tmp_path / "m.json")
    shallow = _run(current_node_id="0-0")
    assert all(not rewards.build_combat_reward(random.Random(s), shallow, False, path).forged_tower_choices
               for s in range(20))
    deep = _run(map=make_linear_run_map(["combat"] * 6), current_node_id="5-0", act=2)
    offered = [rewards.build_combat_reward(random.Random(s), deep, False, path).forged_tower_choices
               for s in range(20)]
    assert any(offered)
    for seed, forged in enumerate(offered):
        reward = rewards.build_combat_reward(random.Random(seed), deep, False, path)
        assert set(forged) <= set(reward.tower_choices)
