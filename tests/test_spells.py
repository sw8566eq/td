"""Tests for the spell deck -- run/spells.py's registry, CombatDeck's
draw/discard/exhaust/energy rules, each spell's own effect, and Game's
wiring: dealing a hand on every floor load and wave clear, play_card,
the sidebar hand, A/S/D/F/G hotkeys, the reward screen's spell row, and
the deck surviving a save/resume."""

import itertools
import json
import random

import pygame
import pytest
from conftest import (
    clear_mouse_mock,
    find_buildable_anchor,
    mock_mouse_pos,
    spy_on_audio,
    start_first_floor,
)

from core.game import GameState
from entities.enemy import BossEnemy, GruntEnemy
from persistence import save_state
from presentation import ui
from progression import achievements
from run import spells
from run.spells import (
    HAND_LIMIT,
    HAND_SIZE,
    MAX_ENERGY,
    SPELLS,
    STARTER_DECK,
    CombatDeck,
)


def _enemy(cls=GruntEnemy, x=0):
    enemy = cls([pygame.Vector2(0, 0), pygame.Vector2(900, 0)], wave_number=1)
    enemy.distance_traveled = x
    return enemy


def _floor_with_hand(game, hand, energy=MAX_ENERGY):
    """A run's first floor with the fight's hand forced to `hand`."""
    start_first_floor(game, seed=1)
    game.combat_deck.hand = list(hand)
    game.combat_deck.energy = energy
    return game.combat_deck


# --- Registry ---


def test_every_spell_is_well_formed():
    for key, spell in SPELLS.items():
        assert spell.key == key
        assert spell.display_name and spell.description
        assert 0 <= spell.cost <= MAX_ENERGY
        assert spell.rarity in spells.REWARD_RARITY_WEIGHTS
        assert spells.initials(key)
        if spell.exhaust:
            assert "Exhaust" in spell.description


def test_starter_deck_only_uses_registered_spells():
    assert all(key in SPELLS for key in STARTER_DECK)
    assert len(STARTER_DECK) > HAND_SIZE


def test_spell_offer_is_deterministic_distinct_and_weighted():
    assert spells.spell_offer(random.Random(4)) == spells.spell_offer(random.Random(4))
    for seed in range(30):
        offer = spells.spell_offer(random.Random(seed))
        assert len(offer) == spells.REWARD_SPELL_COUNT
        assert len(set(offer)) == len(offer)
    assert len(spells.spell_offer(random.Random(1), count=len(SPELLS) + 5)) == len(SPELLS)
    counts = {"common": 0, "rare": 0}
    for seed in range(300):
        for key in spells.spell_offer(random.Random(seed), count=1):
            if SPELLS[key].rarity in counts:
                counts[SPELLS[key].rarity] += 1
    assert counts["common"] > counts["rare"]


def test_random_spell_is_a_real_key():
    for seed in range(10):
        assert spells.random_spell(random.Random(seed)) in SPELLS


# --- CombatDeck ---


def test_new_turn_draws_a_hand_and_refills_energy():
    deck = CombatDeck.from_deck(list(STARTER_DECK), random.Random(1))
    deck.new_turn()
    assert len(deck.hand) == HAND_SIZE
    assert deck.energy == MAX_ENERGY
    assert sorted(deck.hand + deck.draw_pile) == sorted(STARTER_DECK)


def test_same_rng_seed_deals_the_same_hand():
    first = CombatDeck.from_deck(list(STARTER_DECK), random.Random("x"))
    second = CombatDeck.from_deck(list(STARTER_DECK), random.Random("x"))
    first.new_turn()
    second.new_turn()
    assert first.hand == second.hand


def test_draw_reshuffles_the_discard_pile_when_the_draw_pile_runs_dry():
    deck = CombatDeck(rng=random.Random(1), draw_pile=["zap"], discard_pile=["rally", "shove"])
    assert deck.draw(3) == 3
    assert sorted(deck.hand) == ["rally", "shove", "zap"]
    assert deck.discard_pile == [] and deck.draw_pile == []


def test_draw_stops_when_both_piles_are_empty_or_the_hand_is_full():
    deck = CombatDeck(rng=random.Random(1), draw_pile=["zap"])
    assert deck.draw(4) == 1
    full = CombatDeck(rng=random.Random(1), draw_pile=["zap"] * 10, hand=["zap"] * HAND_LIMIT)
    assert full.draw(2) == 0


def test_play_pays_energy_and_discards_or_exhausts():
    deck = CombatDeck(rng=random.Random(1), draw_pile=[], hand=["zap", "insight"], energy=1)
    assert deck.can_play(0) and deck.can_play(1)
    assert deck.play(0) == "zap"
    assert deck.energy == 0 and deck.discard_pile == ["zap"]
    assert deck.play(0) == "insight"
    assert deck.exhaust_pile == ["insight"]


def test_can_play_needs_enough_energy_and_a_real_index():
    deck = CombatDeck(rng=random.Random(1), draw_pile=[], hand=["blizzard"], energy=1)
    assert not deck.can_play(0)
    assert not deck.can_play(1)
    assert not deck.can_play(-1)


def test_new_turn_discards_the_unplayed_hand():
    deck = CombatDeck(rng=random.Random(1), draw_pile=[], hand=["zap", "rally"], energy=0)
    deck.new_turn()
    assert deck.energy == MAX_ENERGY
    assert sorted(deck.hand) == ["rally", "zap"]  # reshuffled straight back in


# --- Game wiring ---


def test_a_run_starts_with_the_starter_deck_and_its_first_fight_deals_a_hand(game):
    run = start_first_floor(game, seed=1)
    assert run.deck == list(STARTER_DECK)
    assert len(game.combat_deck.hand) == HAND_SIZE
    assert game.combat_deck.energy == MAX_ENERGY


def test_restarting_a_floor_deals_the_same_opening_hand(game):
    start_first_floor(game, seed=3)
    hand = list(game.combat_deck.hand)
    game.combat_deck.play(0)
    game.state = GameState.PAUSED  # the pause menu's Restart Level
    game.reset()
    assert game.combat_deck.hand == hand
    assert game.combat_deck.energy == MAX_ENERGY


def test_practice_floors_have_no_spell_deck(game):
    game.start_new_run(seed=1)
    game._load_level_object(game.level, sandbox=True)
    assert game.combat_deck is None
    assert not game.play_card(0)


def test_clearing_a_wave_starts_a_new_turn(game):
    deck = _floor_with_hand(game, [], energy=0)
    deck.draw_pile = list(STARTER_DECK)
    game.wave_manager.skip_delay()
    for _ in range(4000):
        if game.wave_manager.current_wave_number > 1 or game.state != GameState.PLAYING:
            break
        game.enemies = []
        game.update(dt=0.05)
    assert game.wave_manager.current_wave_number > 1
    assert deck.energy == MAX_ENERGY
    assert len(deck.hand) == HAND_SIZE


def test_play_card_casts_spends_energy_plays_a_sound_and_counts(game):
    deck = _floor_with_hand(game, ["prospect"])
    gold = game.economy.gold
    played = spy_on_audio(game)

    assert game.play_card(0)

    assert game.economy.gold == gold + spells.prospect_gold(game.active_run.depth)
    assert deck.energy == MAX_ENERGY - 1
    assert deck.hand == [] and deck.discard_pile[-1] == "prospect"
    assert "potion_used" in played
    assert achievements.load_achievements(game.achievements_path)["counters"]["spells_cast"] == 1


def test_play_card_refuses_without_energy_or_outside_play(game):
    deck = _floor_with_hand(game, ["blizzard"], energy=1)
    game.enemies = [_enemy()]
    assert not game.play_card(0)
    assert deck.hand == ["blizzard"]
    deck.energy = MAX_ENERGY
    game.state = GameState.PAUSED
    assert not game.play_card(0)
    game.state = GameState.PLAYING
    assert not game.play_card(5)
    assert game.play_card(0)


def test_enemy_spells_are_kept_while_the_field_is_empty(game):
    deck = _floor_with_hand(game, ["zap"])
    game.enemies = []
    assert not game.play_card(0)
    assert deck.hand == ["zap"] and deck.energy == MAX_ENERGY


@pytest.mark.parametrize("key, index", [(pygame.K_a, 0), (pygame.K_s, 1), (pygame.K_d, 2), (pygame.K_f, 3)])
def test_a_s_d_f_play_hand_cards(game, key, index):
    hand = ["prospect", "rally", "bounty", "requisition"]
    deck = _floor_with_hand(game, hand)
    game._handle_keydown(key)
    assert deck.hand == [card for i, card in enumerate(hand) if i != index]


def test_clicking_a_card_plays_it(game):
    deck = _floor_with_hand(game, ["rally", "prospect"])
    game._handle_click(game.card_rects()[1].center)
    assert deck.hand == ["rally"]


def test_render_with_a_hovered_card_and_running_effects_does_not_crash(game):
    _floor_with_hand(game, ["rally", "empower", "chain_lightning", "zap", "surge"])
    game.spell_fire_rate_timer = game.spell_damage_timer = game.bounty_timer = 3.0
    game.free_tower_charges = 1
    try:
        mock_mouse_pos(game.card_rects()[2].center)
        game.render()
        game.combat_deck.hand = []
        game.render()
    finally:
        clear_mouse_mock()


def test_card_rects_fit_the_sidebar_and_sit_between_sell_and_the_potion_belt():
    rects = ui.build_card_rects(HAND_LIMIT)
    for rect in rects:
        assert rect.left >= ui.settings.PLAY_WIDTH and rect.right <= ui.settings.SCREEN_WIDTH
        assert rect.top > ui.SELL_BUTTON_TOP + ui.ACTION_BUTTON_HEIGHT
        assert rect.bottom < ui.RUN_MODIFIERS_Y
    for a, b in itertools.pairwise(rects):
        assert not a.colliderect(b)


# --- Each spell's effect ---


def test_zap_hits_the_leaders_and_bosses_less(game):
    _floor_with_hand(game, ["zap"])
    trailer, mid, leader, boss = _enemy(x=10), _enemy(x=50), _enemy(x=90), _enemy(BossEnemy, x=70)
    game.enemies = [trailer, mid, leader, boss]
    game.play_card(0)
    assert trailer.hp == trailer.max_hp
    assert leader.hp == pytest.approx(leader.max_hp * (1 - spells.ZAP_HP_FRACTION))
    assert mid.hp < mid.max_hp
    assert boss.max_hp - boss.hp <= boss.max_hp * spells.ZAP_BOSS_HP_FRACTION + 1e-6


def test_chain_lightning_hits_everything(game):
    _floor_with_hand(game, ["chain_lightning"])
    enemies = [_enemy(x=i) for i in range(5)]
    game.enemies = list(enemies)
    game.play_card(0)
    assert all(e.hp == pytest.approx(e.max_hp * (1 - spells.CHAIN_LIGHTNING_HP_FRACTION)) for e in enemies)


def test_focus_fire_hits_the_toughest_enemy(game):
    _floor_with_hand(game, ["focus_fire"])
    weak, tough = _enemy(), _enemy()
    tough.max_hp = tough.hp = weak.max_hp * 3
    game.enemies = [weak, tough]
    game.play_card(0)
    assert weak.hp == weak.max_hp
    assert tough.hp == pytest.approx(tough.max_hp * (1 - spells.FOCUS_FIRE_HP_FRACTION))


def test_blizzard_expose_plague_and_shove_apply_their_status(game):
    _floor_with_hand(game, ["blizzard", "expose"])
    enemy = _enemy(x=200)
    enemy.update(0.0, [enemy])
    game.enemies = [enemy]
    game.play_card(0)
    game.play_card(0)
    assert enemy.slow_multiplier == spells.BLIZZARD_SLOW_FACTOR
    assert enemy.mark_damage_multiplier == spells.EXPOSE_MULTIPLIER
    game.combat_deck.hand = ["plague", "shove"]
    game.combat_deck.energy = MAX_ENERGY
    game.play_card(0)
    assert enemy.poison_time_remaining == spells.PLAGUE_DURATION
    game.play_card(0)  # shove -- knockback queued without crashing


def test_execute_finishes_weak_non_bosses_only(game):
    _floor_with_hand(game, ["execute"])
    weak, healthy, boss = _enemy(), _enemy(), _enemy(BossEnemy)
    weak.hp = weak.max_hp * 0.2
    boss.hp = boss.max_hp * 0.1
    game.enemies = [weak, healthy, boss]
    game.play_card(0)
    assert weak.is_dead
    assert healthy.hp == healthy.max_hp
    assert not boss.is_dead


def test_rally_and_empower_buff_towers_until_they_expire(game):
    _floor_with_hand(game, ["rally", "empower"])
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    tower = game.towers[0]
    rate, damage = tower.effective_fire_rate(), tower.effective_damage()

    game.play_card(0)
    game.play_card(0)
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == pytest.approx(rate * spells.RALLY_FIRE_RATE_MULTIPLIER)
    assert tower.effective_damage() == pytest.approx(damage * (1 + spells.EMPOWER_DAMAGE_BONUS))

    game.update(dt=spells.RALLY_DURATION)
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == pytest.approx(rate)
    assert tower.effective_damage() == pytest.approx(damage)


def test_bounty_doubles_kill_gold(game):
    _floor_with_hand(game, ["bounty"])
    game.play_card(0)
    enemy = _enemy()
    enemy.take_damage(enemy.max_hp * 10)
    game.enemies = [enemy]
    gold = game.economy.gold
    game.update(dt=0.01)
    assert game.economy.gold == pytest.approx(gold + enemy.gold_reward * spells.BOUNTY_GOLD_MULTIPLIER)


def test_insight_draws_and_surge_adds_energy(game):
    deck = _floor_with_hand(game, ["insight", "surge"], energy=0)
    deck.draw_pile = ["zap", "zap"]
    game.play_card(0)
    assert sorted(deck.hand) == ["surge", "zap", "zap"]
    game.play_card(deck.hand.index("surge"))
    assert deck.energy == spells.SURGE_ENERGY
    assert sorted(deck.exhaust_pile) == ["insight", "surge"]


def test_patch_the_gate_restores_a_life(game):
    _floor_with_hand(game, ["patch_gate"])
    lives = game.economy.lives
    game.play_card(0)
    assert game.economy.lives == lives + spells.PATCH_GATE_LIVES


def test_requisition_makes_the_next_tower_free_and_unrefundable(game):
    _floor_with_hand(game, ["requisition"])
    game.play_card(0)
    gold = game.economy.gold
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    assert game.economy.gold == gold
    assert game.towers[0].total_invested == 0
    assert game.free_tower_charges == 0
    game.economy.gold = 0
    assert not game.try_place_tower(*find_buildable_anchor(game))


def test_spell_timers_reset_on_a_fresh_floor_load(game):
    _floor_with_hand(game, ["rally", "bounty", "requisition"])
    for _ in range(3):
        game.play_card(0)
    game.state = GameState.PAUSED
    game.reset()
    assert game.spell_fire_rate_timer == game.bounty_timer == 0.0
    assert game.free_tower_charges == 0


def test_needs_enemies_flags_match_what_each_spell_touches(game):
    for key, spell in SPELLS.items():
        if spell.needs_enemies:
            continue
        _floor_with_hand(game, [key])
        game.enemies = []
        assert game.play_card(0), key


# --- Rewards and persistence ---


def _clear_into_reward(game):
    from test_run import _clear_into_reward as clear

    clear(game)


def test_combat_rewards_offer_a_pick_one_spell_row(game):
    _clear_into_reward(game)
    cards = game._reward_cards()
    spell_indices = [i for i, (kind, _key) in enumerate(cards) if kind == "spell"]
    assert len(spell_indices) == spells.REWARD_SPELL_COUNT
    first, second = spell_indices[:2]

    game._handle_reward_click(game.reward_rects[first].center)
    game._handle_reward_click(game.reward_rects[second].center)

    assert game.active_run.deck == list(STARTER_DECK) + [cards[first][1]]
    assert not game._reward_card_available(second)


def test_reward_spell_row_sits_between_the_cards_and_continue(game):
    _clear_into_reward(game)
    spell_rects = game.reward_rects[-spells.REWARD_SPELL_COUNT:]
    assert all(rect.top > game.reward_rects[0].bottom for rect in spell_rects)
    assert all(rect.bottom < game.reward_continue_rect.top for rect in spell_rects)
    assert game.reward_continue_rect.bottom <= ui.settings.SCREEN_HEIGHT
    game.render()


def test_boss_rewards_offer_no_spells(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["boss", "combat"])
    from run import rewards

    reward = rewards.build_combat_reward(random.Random(1), game.active_run, is_elite=False, is_boss=True)
    assert reward.spell_choices == ()


def test_the_deck_survives_a_save_and_resume(game):
    start_first_floor(game, seed=1)
    game.active_run.deck.append("chain_lightning")
    game.save_run()

    game.resume_saved_run(save_state.load_run(game.save_path))

    assert game.active_run.deck == list(STARTER_DECK) + ["chain_lightning"]


def test_an_old_save_without_a_deck_gets_the_starter_deck(game):
    start_first_floor(game, seed=1)
    game.save_run()
    with open(game.save_path) as file:
        raw = json.load(file)
    del raw["run"]["deck"]
    with open(game.save_path, "w") as file:
        json.dump(raw, file)
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_run.deck == list(STARTER_DECK)


def test_a_save_with_an_unknown_spell_is_not_resumable(game):
    start_first_floor(game, seed=1)
    game.active_run.deck.append("not_a_spell")
    game.save_run()
    assert save_state.load_run(game.save_path) is None
