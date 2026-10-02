"""Tests for curses (negative relics, relics.Relic.is_curse), the Events
that hand them out or lift them, the potion-granting Event option, and
the Shop's remove-a-curse service."""

import random

import pytest
from conftest import make_linear_run_map

from core.game import GameState
from run import events, potions, relics, shop
from run.card_pool import STARTER_TOWERS
from run.events import EVENTS, EventOption
from run.relics import CURSES, RELICS
from run.run_state import RunState


def _run(**overrides):
    kwargs = {"seed": 1, "map": make_linear_run_map(["combat"]), "difficulty": "normal",
              "unlocked_towers": list(STARTER_TOWERS), "lives": 10}
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_curses_exist_and_describe_themselves_as_curses():
    assert len(CURSES) >= 5
    for key in CURSES:
        assert RELICS[key].description.startswith("Curse: ")


def test_curses_are_never_offered_as_ordinary_relics(tmp_path):
    run = _run()
    for seed in range(30):
        offer = relics.relic_offer(random.Random(seed), run, count=10, meta_progression_path=str(tmp_path / "m.json"))
        assert not set(offer) & set(CURSES)


def test_curses_compose_as_downsides():
    mods = relics.compose_relic_modifiers(["rusted_gears", "warped_lenses", "bad_reputation"])
    assert mods.tower_upgrade_cost_multiplier > 1.0
    assert mods.tower_range_multiplier < 1.0
    assert mods.shop_price_multiplier > 1.0


def test_curse_offer_skips_held_curses_and_runs_dry():
    run = _run(relics=CURSES[:-1])
    assert relics.curse_offer(random.Random(1), run) == CURSES[-1]
    run.relics = list(CURSES)
    assert relics.curse_offer(random.Random(1), run) is None


def test_held_curses_keeps_acquisition_order():
    run = _run(relics=["warped_lenses", "lucky_strikes", "rusted_gears"])
    assert relics.held_curses(run) == ["warped_lenses", "rusted_gears"]


def test_add_curse_option_curses_the_run_alongside_its_reward(tmp_path):
    run = _run()
    option = EVENTS["forbidden_tome"].options[0]
    resolution = events.resolve_event_option(run, option, random.Random(2), meta_progression_path=str(tmp_path / "m"))
    assert resolution["curse"] in CURSES and resolution["relic"] in RELICS
    assert resolution["curse"] in run.relics and resolution["relic"] in run.relics


def test_add_curse_does_nothing_once_every_curse_is_held(tmp_path):
    run = _run(relics=list(CURSES))
    resolution = events.resolve_event_option(run, EventOption("x", "x", "x", add_curse=True), random.Random(1))
    assert "curse" not in resolution


def test_remove_curse_option_lifts_the_oldest_and_is_harmless_without_one():
    run = _run(relics=["lucky_strikes", "leaky_coffers", "warped_lenses"])
    bathe = EVENTS["cleansing_spring"].options[0]
    assert events.resolve_event_option(run, bathe, random.Random(1))["curse_removed"] == "leaky_coffers"
    assert run.relics == ["lucky_strikes", "warped_lenses"]

    clean = _run(relics=["lucky_strikes"])
    assert events.resolve_event_option(clean, bathe, random.Random(1)) == {}


def test_grant_potion_option_fills_a_free_slot_only(tmp_path):
    run = _run(shop_currency=20)
    buy = EVENTS["wandering_alchemist"].options[0]
    resolution = events.resolve_event_option(run, buy, random.Random(1))
    assert run.potions == [resolution["potion"]]
    assert run.shop_currency == 14

    full = _run(shop_currency=20, potions=["fire_bomb"] * potions.POTION_SLOTS)
    assert "potion" not in events.resolve_event_option(full, buy, random.Random(1))


@pytest.mark.parametrize("resolution", [
    {"curse": "rusted_gears"}, {"curse_removed": "rusted_gears"}, {"potion": "fire_bomb"},
])
def test_event_outcome_describes_curses_and_potions(resolution):
    from presentation import ui

    lines = ui._describe_event_outcome(EventOption("x", "x", "x"), resolution)
    assert lines != ["Nothing else happened."]


# --- The Shop's remove-a-curse service ---


def _shop_with(game, **run_overrides):
    from test_run import _enter_run_shop

    return _enter_run_shop(game, **run_overrides)


def test_remove_curse_at_the_shop(game):
    run = _shop_with(game, relics=["leaky_coffers", "lucky_strikes"])
    assert game.state == GameState.DRAFT
    run.shop_currency = 50
    game.render()

    game._handle_draft_click(game.shop_remove_curse_rect.center)

    assert run.relics == ["lucky_strikes"]
    assert run.shop_currency == 50 - shop.CURSE_REMOVAL_PRICE
    assert game.shop_curse_removed
    game.render()


def test_remove_curse_is_once_per_visit(game):
    run = _shop_with(game, relics=["leaky_coffers", "warped_lenses"])
    run.shop_currency = 100
    game._try_remove_curse()
    game._try_remove_curse()
    assert run.relics == ["warped_lenses"]


def test_remove_curse_needs_a_curse_and_the_currency(game):
    run = _shop_with(game, relics=["lucky_strikes"])
    run.shop_currency = 100
    game._try_remove_curse()
    assert run.shop_currency == 100

    run.relics = ["rusted_gears"]
    run.shop_currency = shop.CURSE_REMOVAL_PRICE - 1
    game.render()  # drawn, but dimmed
    game._try_remove_curse()
    assert run.relics == ["rusted_gears"]


def test_bad_reputation_raises_the_curse_removal_price_too(game):
    run = _shop_with(game, relics=["bad_reputation"])
    assert game._curse_removal_price() == round(shop.CURSE_REMOVAL_PRICE * 1.2)
    run.shop_currency = 100
    game._try_remove_curse()
    assert run.relics == []


def test_ancient_forge_forges_an_unforged_held_tower():
    run = _run(forged_towers=["basic"], lives=10)
    stoke = EVENTS["ancient_forge"].options[0]
    resolution = events.resolve_event_option(run, stoke, random.Random(3))
    assert resolution["forged"] in STARTER_TOWERS and resolution["forged"] != "basic"
    assert run.forged_towers == ["basic", resolution["forged"]]
    assert run.lives == 8

    done = _run(forged_towers=list(STARTER_TOWERS))
    assert "forged" not in events.resolve_event_option(done, stoke, random.Random(3))


def test_forge_outcome_is_described():
    from presentation import ui

    assert ui._describe_event_outcome(EventOption("x", "x", "x"), {"forged": "cannon"})[0].startswith("Forged: ")


# --- Events built on potions / boss relics ---


def test_potion_cost_needs_a_potion_and_takes_the_oldest():
    sell = EVENTS["potion_peddler"].options[1]
    assert not events.can_afford_option(sell, _run())
    run = _run(potions=["fire_bomb", "frost_flask"])
    assert events.can_afford_option(sell, run)
    resolution = events.resolve_event_option(run, sell, random.Random(1))
    assert resolution["potion_given_up"] == "fire_bomb"
    assert run.potions == ["frost_flask"] and run.shop_currency == 15


def test_fallen_champion_grants_a_boss_relic_and_a_curse(tmp_path):
    run = _run()
    resolution = events.resolve_event_option(run, EVENTS["fallen_champion"].options[0], random.Random(4),
                                             meta_progression_path=str(tmp_path / "m"))
    assert RELICS[resolution["boss_relic"]].is_boss_relic
    assert resolution["curse"] in CURSES


def test_field_hospital_lifts_a_curse_and_heals():
    run = _run(shop_currency=10, relics=["rusted_gears"], lives=5)
    resolution = events.resolve_event_option(run, EVENTS["field_hospital"].options[0], random.Random(1))
    assert resolution["curse_removed"] == "rusted_gears"
    assert run.lives == 7 and run.shop_currency == 0


def test_resolving_a_boss_relic_event_in_game_plays_the_relic_cue(game):
    from conftest import spy_on_audio
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "event"], lives=10)
    game.active_run.current_node_id = "1-0"
    game.current_event = EVENTS["fallen_champion"]
    game.event_options = list(game.current_event.options)
    played = spy_on_audio(game)
    game._resolve_event_choice(0)
    assert "relic_acquired" in played
    game.state = GameState.EVENT
    game.render()


@pytest.mark.parametrize("resolution", [{"boss_relic": "siege_engine"}, {"potion_given_up": "fire_bomb"}])
def test_new_event_outcomes_are_described(resolution):
    from presentation import ui

    assert ui._describe_event_outcome(EventOption("x", "x", "x"), resolution) != ["Nothing else happened."]


def test_event_screen_status_line_shows_what_options_cost(game):
    from test_run import _begin_run_with_map

    _begin_run_with_map(game, ["combat", "event"], lives=7, shop_currency=12, potions=["fire_bomb"])
    game._enter_node("1-0")
    assert game.renderer._run_status_line() == "Lives: 7   Shop currency: 12   Potions: 1/3   Relics: 0"
    game.render()
