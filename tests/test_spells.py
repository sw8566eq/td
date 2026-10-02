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
from run import shop, spells
from run.commanders import COMMANDERS, DEFAULT_COMMANDER
from run.relics import RELICS as RELICS_BY_KEY
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


def _warden_deck():
    """What a run started with the default commander holds: the starter
    deck plus The Warden's signature spell."""
    return list(STARTER_DECK) + [COMMANDERS[DEFAULT_COMMANDER].signature_spell]


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
    assert run.deck == _warden_deck()
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
    assert leader.hp == pytest.approx(leader.max_hp * (1 - spells.ZAP_HP_FRACTION[0]))
    assert mid.hp < mid.max_hp
    assert boss.max_hp - boss.hp <= boss.max_hp * spells.ZAP_BOSS_HP_FRACTION[0] + 1e-6


def test_chain_lightning_hits_everything(game):
    _floor_with_hand(game, ["chain_lightning"])
    enemies = [_enemy(x=i) for i in range(5)]
    game.enemies = list(enemies)
    game.play_card(0)
    assert all(e.hp == pytest.approx(e.max_hp * (1 - spells.CHAIN_LIGHTNING_HP_FRACTION[0])) for e in enemies)


def test_focus_fire_hits_the_toughest_enemy(game):
    _floor_with_hand(game, ["focus_fire"])
    weak, tough = _enemy(), _enemy()
    tough.max_hp = tough.hp = weak.max_hp * 3
    game.enemies = [weak, tough]
    game.play_card(0)
    assert weak.hp == weak.max_hp
    assert tough.hp == pytest.approx(tough.max_hp * (1 - spells.FOCUS_FIRE_HP_FRACTION[0]))


def test_blizzard_expose_plague_and_shove_apply_their_status(game):
    _floor_with_hand(game, ["blizzard", "expose"])
    enemy = _enemy(x=200)
    enemy.update(0.0, [enemy])
    game.enemies = [enemy]
    game.play_card(0)
    game.play_card(0)
    assert enemy.slow_multiplier == spells.BLIZZARD_SLOW_FACTOR[0]
    assert enemy.mark_damage_multiplier == spells.EXPOSE_MULTIPLIER[0]
    game.combat_deck.hand = ["plague", "shove"]
    game.combat_deck.energy = MAX_ENERGY
    game.play_card(0)
    assert enemy.poison_time_remaining == spells.PLAGUE_DURATION[0]
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
    assert tower.effective_fire_rate() == pytest.approx(rate * spells.RALLY_FIRE_RATE_MULTIPLIER[0])
    assert tower.effective_damage() == pytest.approx(damage * (1 + spells.EMPOWER_DAMAGE_BONUS[0]))

    game.update(dt=spells.RALLY_DURATION[0])
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
    assert deck.energy == spells.SURGE_ENERGY[0]
    assert sorted(deck.exhaust_pile) == ["insight", "surge"]


def test_patch_the_gate_restores_a_life(game):
    _floor_with_hand(game, ["patch_gate"])
    lives = game.economy.lives
    game.play_card(0)
    assert game.economy.lives == lives + spells.PATCH_GATE_LIVES[0]


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

    assert game.active_run.deck == _warden_deck() + ["chain_lightning"]


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


# --- The Shop's spell row, card removal, and the deck screen ---


def _shop(game, currency=100):
    from test_run import _enter_run_shop

    run = _enter_run_shop(game)
    run.shop_currency = currency
    assert game.state == GameState.DRAFT
    return run


def _spell_indices(game):
    return [i for i, item in enumerate(game.draft_choices) if item.kind == "spell"]


def test_the_shop_sells_spells_into_the_deck(game):
    run = _shop(game)
    indices = _spell_indices(game)
    assert len(indices) == spells.REWARD_SPELL_COUNT
    key = game.draft_choices[indices[0]].key

    game._handle_draft_click(game.draft_choice_rects[indices[0]].center)

    assert run.deck == list(STARTER_DECK) + [key]
    assert run.shop_currency == 100 - shop.SPELL_PRICE


def test_shop_spell_row_and_service_buttons_do_not_overlap(game):
    _shop(game)
    buttons = [game.shop_potion_rect, game.shop_exit_rect, game.shop_remove_card_rect, game.shop_remove_curse_rect]
    for rect in game.draft_choice_rects + buttons:
        assert 0 <= rect.left and rect.right <= ui.settings.SCREEN_WIDTH
        assert rect.bottom <= ui.settings.SCREEN_HEIGHT
    everything = game.draft_choice_rects + buttons
    for i, a in enumerate(everything):
        for b in everything[i + 1:]:
            assert not a.colliderect(b)
    game.render()


def test_remove_a_card_opens_the_picker_and_removes_one_copy(game):
    run = _shop(game)
    price = game._card_removal_price()
    game._handle_draft_click(game.shop_remove_card_rect.center)
    assert game.state == GameState.DECK and game.deck_view_mode == "remove"
    game.render()

    zap_index = [key for key, _count in ui.deck_entries(run.deck)].index("zap")
    game.input_handler._handle_deck_click(game.deck_entry_rects[zap_index].center)

    assert game.state == GameState.DRAFT
    assert run.deck.count("zap") == STARTER_DECK.count("zap") - 1
    assert run.shop_currency == 100 - price
    assert run.cards_removed == 1
    assert not game._can_remove_card()  # once per visit
    game._handle_draft_click(game.shop_remove_card_rect.center)
    assert game.state == GameState.DRAFT
    game.render()


def test_card_removal_gets_pricier_each_time():
    assert shop.card_removal_price(1) > shop.card_removal_price(0)


def test_backing_out_of_the_picker_costs_nothing(game):
    run = _shop(game)
    game._open_card_removal()
    game.input_handler._handle_deck_click(game.deck_back_rect.center)
    assert game.state == GameState.DRAFT
    assert run.shop_currency == 100 and run.deck == list(STARTER_DECK)
    game._open_card_removal()
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.DRAFT


def test_card_removal_needs_currency_and_a_card(game):
    run = _shop(game, currency=0)
    game._open_card_removal()
    assert game.state == GameState.DRAFT
    run.shop_currency = 100
    run.deck = []
    game._open_card_removal()
    assert game.state == GameState.DRAFT
    game._remove_card("zap")
    assert run.cards_removed == 0


def test_view_mode_clicks_never_remove(game):
    run = start_first_floor(game, seed=1)
    game._enter_map()
    game._handle_keydown(pygame.K_d)
    assert game.state == GameState.DECK and game.deck_view_mode == "view"
    game.input_handler._handle_deck_click(game.deck_entry_rects[0].center)
    assert run.deck == _warden_deck()
    try:
        mock_mouse_pos(game.deck_entry_rects[0].center)
        game.render()
    finally:
        clear_mouse_mock()
    game._handle_keydown(pygame.K_SPACE)
    assert game.state == GameState.MAP


def test_an_empty_deck_renders(game):
    run = start_first_floor(game, seed=1)
    run.deck = []
    game.open_deck_view()
    game.render()


def test_cards_removed_survives_a_save_and_resume(game):
    run = start_first_floor(game, seed=1)
    run.cards_removed = 2
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_run.cards_removed == 2


def test_the_compendium_lists_every_spell():
    pygame.font.init()
    rows = ui.compendium_rows(pygame.font.SysFont(None, 22))
    names = {name for kind, name, _detail in rows if kind == "entry" and name}
    for spell in SPELLS.values():
        assert f"{spell.display_name} ({spell.cost})" in names


# --- Upgrades ("+" cards) and the Rest site's Study ---


def test_card_helpers():
    assert spells.base_key("zap+") == "zap" and spells.base_key("zap") == "zap"
    assert spells.card_level("zap+") == 1 and spells.card_level("zap") == 0
    assert spells.upgraded("zap") == spells.upgraded("zap+") == "zap+"
    assert spells.card_name("zap+") == "Zap+"
    assert spells.initials("chain_lightning+") == "CL+"
    assert spells.is_valid_card("zap+") and spells.is_valid_card("zap")
    assert not spells.is_valid_card("zap++") and not spells.is_valid_card("nope+")
    assert spells.card_cost("requisition+") == 0 and spells.card_cost("execute+") == 1


def test_every_upgrade_is_described_differently_or_cheaper():
    for key, spell in SPELLS.items():
        assert spell.describe(1) != spell.describe(0) or spell.costs[1] < spell.costs[0], key
        assert spell.costs[1] <= spell.costs[0]


def test_an_upgraded_zap_hits_harder(game):
    _floor_with_hand(game, ["zap+"])
    enemy = _enemy()
    game.enemies = [enemy]
    game.play_card(0)
    assert enemy.hp == pytest.approx(enemy.max_hp * (1 - spells.ZAP_HP_FRACTION[1]))


def test_upgraded_rally_and_empower_use_their_stronger_values_then_reset(game):
    _floor_with_hand(game, ["rally+", "empower+"])
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    tower = game.towers[0]
    rate, damage = tower.effective_fire_rate(), tower.effective_damage()
    game.play_card(0)
    game.play_card(0)
    game.update(dt=0.01)
    assert tower.effective_fire_rate() == pytest.approx(rate * spells.RALLY_FIRE_RATE_MULTIPLIER[1])
    assert tower.effective_damage() == pytest.approx(damage * (1 + spells.EMPOWER_DAMAGE_BONUS[1]))
    game.update(dt=spells.RALLY_DURATION[1] + 1)
    game.update(dt=0.01)
    assert game.spell_fire_rate_multiplier == 1.0 and game.spell_damage_bonus == 0.0
    assert tower.effective_fire_rate() == pytest.approx(rate)


def test_upgraded_cards_render_in_hand_and_deck(game):
    _floor_with_hand(game, ["zap+", "insight+"])
    try:
        mock_mouse_pos(game.card_rects()[0].center)
        game.render()
    finally:
        clear_mouse_mock()
    game.active_run.deck.append("zap+")
    assert ("zap+", 1) in ui.deck_entries(game.active_run.deck)
    entries = [card for card, _count in ui.deck_entries(game.active_run.deck)]
    assert entries.index("zap+") == entries.index("zap") + 1
    game.open_deck_view()
    game.render()


def test_a_big_deck_switches_to_the_compact_grid(game):
    run = start_first_floor(game, seed=1)
    run.deck = list(SPELLS) + [spells.upgraded(key) for key in SPELLS]
    game.open_deck_view()
    rects = game.deck_entry_rects
    assert len(rects) == 2 * len(SPELLS)
    assert all(rect.bottom < game.deck_back_rect.top for rect in rects)
    game.render()


def _rest(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "rest"], lives=5)
    game._enter_node("1-0")
    assert game.state == GameState.REST
    return run


def test_study_upgrades_one_copy_and_resolves_the_rest_site(game):
    run = _rest(game)
    game._handle_rest_click(game.rest_option_rects[2].center)
    assert game.state == GameState.DECK and game.deck_view_mode == "upgrade"
    game.render()
    cards = [card for card, _count in game.deck_view_entries()]
    game.input_handler._handle_deck_click(game.deck_entry_rects[cards.index("zap")].center)

    assert game.state == GameState.REST and game.rest_phase == "resolved"
    assert run.deck.count("zap+") == 1 and run.deck.count("zap") == STARTER_DECK.count("zap") - 1
    assert run.visited_node_ids == ["1-0"]
    assert achievements.load_achievements(game.achievements_path)["counters"]["spells_upgraded"] == 1
    game.render()


def test_study_only_offers_cards_not_yet_upgraded_and_back_returns_to_the_choice(game):
    run = _rest(game)
    run.deck = ["zap+", "rally"]
    game._choose_rest_option(2)
    assert [card for card, _count in game.deck_view_entries()] == ["rally"]
    game.input_handler._handle_deck_click(game.deck_back_rect.center)
    assert game.state == GameState.REST and game.rest_phase == "choose"
    game._upgrade_card("zap+")  # already upgraded -- ignored
    assert run.deck == ["zap+", "rally"]


def test_study_is_unavailable_once_everything_is_upgraded(game):
    run = _rest(game)
    run.deck = ["zap+"]
    game._choose_rest_option(2)
    assert game.state == GameState.REST and game.rest_phase == "choose"
    game.render()


def test_deep_rewards_sometimes_offer_upgraded_spells(game):
    from run import rewards

    run = start_first_floor(game, seed=1)
    run.act = 2  # deep enough for the max upgrade chance
    seen = set()
    for seed in range(40):
        reward = rewards.build_combat_reward(random.Random(seed), run, is_elite=False)
        seen.update(spells.card_level(card) for card in reward.spell_choices)
    assert seen == {0, 1}


def test_upgraded_cards_survive_a_save_and_bad_ones_are_rejected(game):
    run = start_first_floor(game, seed=1)
    run.deck.append("zap+")
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert "zap+" in game.active_run.deck
    game.active_run.deck.append("zap++")
    game.save_run()
    assert save_state.load_run(game.save_path) is None


# --- Spell relics ---


def _floor_with_relics(game, held, seed=1):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "combat"], seed=seed, relics=list(held))
    game._enter_node("0-0")
    return game.combat_deck


def test_mana_crystal_and_grand_grimoire_raise_energy_and_hand_size(game):
    deck = _floor_with_relics(game, ["mana_crystal", "grand_grimoire"])
    assert deck.max_energy == deck.energy == MAX_ENERGY + 1
    assert deck.hand_size == HAND_SIZE + 1
    assert len(deck.hand) == HAND_SIZE + 1


def test_prepared_grimoire_draws_extra_cards_only_in_the_opening_hand(game):
    deck = _floor_with_relics(game, ["prepared_grimoire"])
    assert len(deck.hand) == HAND_SIZE + 1
    assert deck.energy == MAX_ENERGY + 1
    deck.new_turn()
    assert len(deck.hand) == HAND_SIZE and deck.energy == MAX_ENERGY


def test_arcane_tithe_pays_gold_per_spell(game):
    deck = _floor_with_relics(game, ["arcane_tithe"])
    deck.hand = ["rally"]
    gold = game.economy.gold
    game.play_card(0)
    assert game.economy.gold == gold + RELICS_BY_KEY["arcane_tithe"].gold_per_spell


def test_echo_chamber_casts_the_first_spell_each_wave_twice(game):
    deck = _floor_with_relics(game, ["echo_chamber"])
    deck.hand = ["prospect", "prospect"]
    deck.energy = MAX_ENERGY
    gold = game.economy.gold
    one = spells.prospect_gold(game.active_run.depth)
    game.play_card(0)
    assert game.economy.gold == gold + 2 * one
    game.play_card(0)
    assert game.economy.gold == gold + 3 * one
    deck.new_turn()
    assert deck.played_this_turn == 0


def test_echo_chamber_does_not_echo_onto_an_empty_field(game):
    deck = _floor_with_relics(game, ["echo_chamber"])
    deck.hand = ["chain_lightning"]
    enemy = _enemy()
    enemy.hp = 1
    game.enemies = [enemy]
    game.play_card(0)  # first cast kills it; the echo must not crash or hit anything
    assert enemy.is_dead


def test_runic_resonance_stacks_tower_damage_up_to_its_cap(game):
    deck = _floor_with_relics(game, ["runic_resonance"])
    relic = RELICS_BY_KEY["runic_resonance"]
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    tower = game.towers[0]
    damage = tower.effective_damage()
    for _ in range(20):
        deck.hand = ["prospect"]
        deck.energy = MAX_ENERGY
        game.play_card(0)
    game.update(dt=0.01)
    assert game.spell_resonance_bonus == pytest.approx(relic.spell_resonance_cap)
    assert tower.effective_damage() == pytest.approx(damage * (1 + relic.spell_resonance_cap))
    game.state = GameState.PAUSED
    game.reset()
    assert game.spell_resonance_bonus == 0.0


def test_spell_boss_relics_are_boss_relics():
    assert RELICS_BY_KEY["mana_crystal"].is_boss_relic and RELICS_BY_KEY["grand_grimoire"].is_boss_relic


def test_every_commander_signature_spell_is_real_and_joins_the_starting_deck(game):
    for key, commander in COMMANDERS.items():
        assert commander.signature_spell in SPELLS, key
    game.start_new_run(seed=1, commander="stormcaller")
    assert game.active_run.deck == list(STARTER_DECK) + ["chain_lightning"]
    game._enter_commander_select()
    game.render()
