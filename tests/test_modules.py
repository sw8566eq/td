"""Tower modules (run/modules.py): one per tower type per run, offered by
Elite rewards pre-paired with a held tower type, applied at construction."""

import itertools
import random

import pytest
from conftest import find_buildable_anchor, start_first_floor

from entities.tower import TOWER_TYPES
from persistence import save_state
from progression import achievements
from run import modules, rewards
from run.modules import MODULES

DAMAGING = frozenset(name for name, cls in TOWER_TYPES.items() if not cls.IS_SUPPORT)


def test_every_module_is_well_formed():
    for key, module in MODULES.items():
        assert module.key == key and module.display_name and module.description


def test_module_offer_prefers_bare_types_and_skips_the_fitted_module(game):
    run = start_first_floor(game, seed=1)
    run.unlocked_towers = ["basic", "cannon"]
    run.tower_modules = {"basic": "long_barrel"}
    for seed in range(30):
        module_key, tower = modules.module_offer(random.Random(seed), run, DAMAGING)
        assert tower == "cannon" and module_key in MODULES
    run.tower_modules = {"basic": "long_barrel", "cannon": "long_barrel"}
    for seed in range(30):
        module_key, _tower = modules.module_offer(random.Random(seed), run, DAMAGING)
        assert module_key != "long_barrel"
    run.unlocked_towers = []
    assert modules.module_offer(random.Random(1), run, DAMAGING) is None


def test_support_is_only_offered_modules_that_help_it(game):
    run = start_first_floor(game, seed=1)
    run.unlocked_towers = ["support"]
    for seed in range(30):
        module_key, _tower = modules.module_offer(random.Random(seed), run, DAMAGING)
        assert not MODULES[module_key].needs_damage


def test_elite_rewards_offer_a_module_instead_of_a_potion(game):
    run = start_first_floor(game, seed=1)
    reward = rewards.build_combat_reward(random.Random(2), run, is_elite=True, damaging_types=DAMAGING)
    assert reward.module is not None and reward.potion is None
    plain = rewards.build_combat_reward(random.Random(2), run, is_elite=False, damaging_types=DAMAGING)
    assert plain.module is None


def test_taking_a_module_card_fits_it(game):
    from test_run import _clear_into_reward

    _clear_into_reward(game, node_types=("elite", "combat"))
    cards = game._reward_cards()
    index = [kind for kind, _key in cards].index("module")
    module_key, tower = cards[index][1]
    game.render()
    game._handle_reward_click(game.reward_rects[index].center)
    assert game.active_run.tower_modules == {tower: module_key}
    assert achievements.load_achievements(game.achievements_path)["counters"]["modules_fitted"] == 1


def _place(game, name="basic"):
    game.selected_tower_name = name
    if name not in game.active_run.unlocked_towers:
        game.active_run.unlocked_towers.append(name)
        game._rebuild_button_rects()
    game.economy.gold = 10_000
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def test_a_fitted_module_changes_new_towers_of_that_type(game):
    run = start_first_floor(game, seed=1)
    plain = _place(game)
    run.tower_modules["basic"] = "heavy_payload"
    heavy = _place(game)
    assert heavy.effective_damage() == pytest.approx(plain.effective_damage() * 1.35)
    assert heavy.effective_fire_rate() == pytest.approx(plain.effective_fire_rate() * 0.85)
    run.tower_modules["basic"] = "long_barrel"
    assert _place(game).effective_range() == pytest.approx(plain.effective_range() * 1.2)
    run.tower_modules["basic"] = "targeting_chip"
    assert _place(game).relic_crit_chance == pytest.approx(plain.relic_crit_chance + 0.12)


def test_on_hit_modules_set_the_towers_on_hit_fields(game):
    # Tower.update() copies these onto every projectile it fires.
    run = start_first_floor(game, seed=1)
    run.tower_modules["basic"] = "cryo_coil"
    tower = _place(game)
    assert tower.relic_slow_chance == 1.0 and tower.relic_slow_effect == MODULES["cryo_coil"].slow_on_hit
    run.tower_modules["basic"] = "venom_injector"
    tower = _place(game)
    assert tower.relic_poison_chance == 1.0 and tower.relic_poison_effect == MODULES["venom_injector"].poison_on_hit


def test_the_panel_names_the_fitted_module(game):
    run = start_first_floor(game, seed=1)
    tower = _place(game)
    assert game.renderer._module_line(tower) is None
    run.tower_modules["basic"] = "rapid_loader"
    assert game.renderer._module_line(TOWER_TYPES["basic"]) == "Module: Rapid Loader"
    assert game.renderer._module_line(None) is None
    game.selected_tower = tower
    game.render()


def test_modules_survive_a_save_and_bad_entries_are_rejected(game):
    run = start_first_floor(game, seed=1)
    run.tower_modules = {"cannon": "cryo_coil"}
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_run.tower_modules == {"cannon": "cryo_coil"}
    for bad in ({"cannon": "nope"}, {"nope": "cryo_coil"}):
        game.active_run.tower_modules = bad
        game.save_run()
        assert save_state.load_run(game.save_path) is None


def test_six_reward_cards_fit_the_screen():
    from presentation import ui

    rects = ui.build_draft_choice_rects(6)
    assert rects[0].left >= 0 and rects[-1].right <= ui.settings.SCREEN_WIDTH
    assert all(not a.colliderect(b) for a, b in itertools.pairwise(rects))


# --- The Shop's module stand ---


def _shop(game, currency=100):
    from test_run import _enter_run_shop

    run = _enter_run_shop(game)
    run.shop_currency = currency
    return run


def test_the_shop_sells_one_paired_module_per_visit(game):
    from run import shop

    run = _shop(game)
    module_key, tower = game.shop_module
    game.render()
    game._handle_draft_click(game.shop_module_rect.center)
    assert run.tower_modules == {tower: module_key}
    assert run.shop_currency == 100 - shop.MODULE_PRICE
    game._handle_draft_click(game.shop_module_rect.center)  # already bought
    assert run.shop_currency == 100 - shop.MODULE_PRICE
    game.render()


def test_the_module_stand_needs_currency(game):
    run = _shop(game, currency=0)
    game._try_buy_shop_module()
    assert run.tower_modules == {}


def test_the_module_stand_does_not_overlap_other_shop_buttons(game):
    _shop(game)
    others = [game.shop_potion_rect, game.shop_continue_button_rect, game.shop_remove_curse_rect,
              *game.draft_choice_rects]
    assert not any(game.shop_module_rect.colliderect(rect) for rect in others)
    assert game.shop_module_rect.right <= game.screen.get_width()


def test_preview_tower_carries_module_range_and_is_never_placed(game):
    run = start_first_floor(game, seed=1)
    run.tower_modules["basic"] = "long_barrel"
    probe = game.preview_tower(TOWER_TYPES["basic"], 0, 0)
    assert probe.effective_range() == pytest.approx(TOWER_TYPES["basic"].range * 1.2)
    assert probe not in game.towers and not game.grid.is_occupied(0, 0)
