"""Tower veterancy (run/veterancy.py): per-tower-type experience earned at
floor clears, ranks, how each tower class turns a rank into a bonus, the
three veterancy relics, and the UI readouts."""

import pytest
from conftest import find_buildable_anchor, finish_all_waves, start_first_floor

from core.game import GameState
from entities.tower import TOWER_TYPES
from persistence import save_state
from progression import achievements
from run import veterancy


def test_rank_for_and_names():
    assert veterancy.rank_for(0) == 0
    assert veterancy.rank_for(veterancy.RANKS[0].xp_required) == 1
    assert veterancy.rank_for(10_000) == veterancy.MAX_RANK
    assert veterancy.rank_name(0) == "Recruit"
    assert veterancy.rank_name(veterancy.MAX_RANK) == "Legendary"
    assert veterancy.next_rank_xp(0) == veterancy.RANKS[0].xp_required
    assert veterancy.next_rank_xp(10_000) is None
    thresholds = [rank.xp_required for rank in veterancy.RANKS]
    assert thresholds == sorted(thresholds)


def test_floor_xp_counts_kills_and_assists():
    xp = veterancy.floor_xp({"cannon": 30, "support": 0}, {"support": 0.25}, multiplier=2.0)
    assert xp == {"cannon": 60.0, "support": pytest.approx(15.0)}


def _place(game, name="basic"):
    game.selected_tower_name = name
    if name not in game.active_run.unlocked_towers:
        game.active_run.unlocked_towers.append(name)
        game._rebuild_button_rects()
    game.economy.gold = 10_000
    assert game.try_place_tower(*find_buildable_anchor(game))
    return game.towers[-1]


def test_clearing_a_floor_awards_experience_and_promotes_with_a_toast(game):
    run = start_first_floor(game, seed=1)
    tower = _place(game)
    tower.kills = veterancy.RANKS[0].xp_required
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.FLOOR_CLEARED
    assert run.tower_xp["basic"] == veterancy.RANKS[0].xp_required
    assert game.veterancy_rank("basic") == 1
    assert any("Basic promoted: Blooded" in toast.text for toast in game.achievement_toasts)


def test_sold_towers_count_and_support_earns_assists(game):
    run = start_first_floor(game, seed=1)
    basic = _place(game)
    basic.kills = 40
    game.try_sell_tower(basic)
    _place(game, "support")
    finish_all_waves(game)
    game.update(dt=0.01)
    assert run.tower_xp["basic"] == 40
    assert run.tower_xp["support"] == pytest.approx(40 * TOWER_TYPES["support"].VETERANCY_ASSIST_FRACTION)


def test_restarting_a_floor_earns_nothing(game):
    run = start_first_floor(game, seed=1)
    _place(game).kills = 50
    game.state = GameState.PAUSED
    game.reset()
    assert run.tower_xp == {}


def test_a_ranked_type_builds_stronger_towers(game):
    run = start_first_floor(game, seed=1)
    plain = _place(game)
    run.tower_xp["basic"] = veterancy.RANKS[1].xp_required  # Seasoned
    seasoned = _place(game)
    assert seasoned.veterancy_rank == 2
    assert seasoned.effective_damage() == pytest.approx(
        plain.effective_damage() * (1 + 2 * veterancy.DAMAGE_BONUS_PER_RANK))


def test_support_veterancy_strengthens_the_aura_bonus(game):
    run = start_first_floor(game, seed=1)
    run.tower_xp["support"] = veterancy.RANKS[-1].xp_required
    support = _place(game, "support")
    basic = _place(game)
    basic.pos = support.pos
    game.update(dt=0.01)
    scale = 1 + veterancy.AURA_BONUS_PER_RANK * veterancy.MAX_RANK
    assert basic.aura_damage_multiplier == pytest.approx(1 + (support.buff_damage_multiplier - 1) * scale)


def test_beacon_veterancy_strengthens_its_marks(game):
    run = start_first_floor(game, seed=1)
    plain = _place(game, "beacon")
    run.tower_xp["beacon"] = veterancy.RANKS[0].xp_required
    ranked = _place(game, "beacon")
    assert ranked.relic_beacon_mark_bonus_multiplier == pytest.approx(
        plain.relic_beacon_mark_bonus_multiplier * (1 + veterancy.MARK_BONUS_PER_RANK))


def test_practice_towers_have_no_veterancy(game):
    game._load_level_object(game.level, sandbox=True)
    assert game.veterancy_rank("basic") == 0
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*find_buildable_anchor(game))
    assert game.towers[0].veterancy_rank == 0


def test_drill_sergeant_multiplies_experience(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], relics=["drill_sergeant"])
    game._enter_node("0-0")
    _place(game).kills = 10
    finish_all_waves(game)
    game.update(dt=0.01)
    assert run.tower_xp["basic"] == pytest.approx(15)


def test_battlefield_commission_adds_a_rank_and_old_guard_needs_veteran(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "combat"], relics=["battlefield_commission", "old_guard"])
    game._enter_node("0-0")
    assert game.veterancy_rank("basic") == 1
    plain_rate = TOWER_TYPES["basic"].fire_rate
    tower = _place(game)
    assert tower.effective_fire_rate() == pytest.approx(plain_rate * game.relic_modifiers.tower_fire_rate_multiplier)
    run.tower_xp["basic"] = veterancy.RANKS[1].xp_required  # Seasoned + 1 = Veteran
    veteran = _place(game)
    assert veteran.veterancy_rank == veterancy.VETERAN_RANK
    assert veteran.effective_fire_rate() == pytest.approx(tower.effective_fire_rate() * 1.15)
    run.tower_xp["basic"] = 10_000
    assert game.veterancy_rank("basic") == veterancy.MAX_RANK  # never past the top


def test_veterancy_achievements(game):
    run = start_first_floor(game, seed=1)
    run.tower_xp["basic"] = veterancy.RANKS[2].xp_required - 1
    _place(game).kills = 1
    finish_all_waves(game)
    game.update(dt=0.01)
    unlocked = achievements.load_achievements(game.achievements_path)["unlocked"]
    assert "battle_hardened" in unlocked and "living_legend" not in unlocked


def test_tower_xp_survives_a_save_and_bad_values_are_rejected(game):
    run = start_first_floor(game, seed=1)
    run.tower_xp = {"cannon": 80.5}
    game.save_run()
    game.resume_saved_run(save_state.load_run(game.save_path))
    assert game.active_run.tower_xp == {"cannon": 80.5}
    for bad in ({"not_a_tower": 1}, {"cannon": -5}, {"cannon": "lots"}):
        game.active_run.tower_xp = bad
        game.save_run()
        assert save_state.load_run(game.save_path) is None, bad


def test_the_panel_and_build_menu_show_veterancy(game):
    run = start_first_floor(game, seed=1)
    assert game.renderer._veterancy_line(TOWER_TYPES["basic"]) == f"Recruit  0/{veterancy.RANKS[0].xp_required} xp"
    run.tower_xp["basic"] = 10_000
    tower = _place(game)
    assert game.renderer._veterancy_line(tower).startswith("Legendary +24% dmg")
    assert game.renderer._veterancy_line(tower).endswith("max rank")
    run.tower_xp["support"] = 100
    support = _place(game, "support")
    assert "aura" in game.renderer._veterancy_line(support)
    assert game.renderer._veterancy_line(None) is None
    game.selected_tower = tower
    game.render()


def test_floor_cleared_screen_summarizes_experience(game):
    from presentation import ui

    assert ui.veterancy_summary_line([]) is None
    assert ui.veterancy_summary_line([("basic", 0.2, None)]) is None
    line = ui.veterancy_summary_line([("basic", 12, None), ("cannon", 40, 2), ("frost", 5, None), ("poison", 1, None)])
    assert line == "Experience: Cannon +40 (Seasoned!), Basic +12, Frost +5"
    start_first_floor(game, seed=1)
    _place(game).kills = 30
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.floor_veterancy_gains == [("basic", 30, 1)]
    game.render()


def test_a_tower_built_before_a_promotion_says_new_ones_are_stronger(game):
    run = start_first_floor(game, seed=1)
    tower = _place(game)
    run.tower_xp["basic"] = veterancy.RANKS[0].xp_required
    assert game.renderer._veterancy_line(tower) == "Recruit, new ones Blooded"


def test_run_over_recap_names_the_top_crew_and_modules(game):
    from presentation import ui

    run = start_first_floor(game, seed=1)
    assert len(ui.run_summary_lines(run)) == 2  # nothing to say yet
    run.tower_xp = {"basic": 30, "cannon": 200}
    run.tower_modules = {"cannon": "long_barrel", "basic": "rapid_loader"}
    assert ui.run_summary_lines(run)[2] == "Top crew: Cannon (Veteran), 2 modules fitted"


# --- Outpost Drill ---


def _outpost(game):
    from test_run import _begin_run_with_map

    run = _begin_run_with_map(game, ["combat", "rest"], lives=5)
    game._enter_node("1-0")
    assert game.state == GameState.REST
    return run


def test_drill_trains_the_chosen_crew_and_resolves(game):
    from core import game as game_module

    run = _outpost(game)
    game._handle_rest_click(game.rest_option_rects[2].center)
    assert game.rest_phase == "drill"
    game.render()
    choices, rects = game.rest_picker()
    game._handle_rest_click(rects[choices.index("cannon")].center)
    assert run.tower_xp["cannon"] == game_module.OUTPOST_DRILL_XP
    assert game.rest_phase == "resolved" and run.visited_node_ids == ["1-0"]
    assert any("Cannon promoted: Blooded" in toast.text for toast in game.achievement_toasts)
    game.render()


def test_drill_back_returns_to_the_choice_and_move_on_is_last(game):
    run = _outpost(game)
    game._choose_rest_option(2)
    game._handle_rest_click(game.rest_back_rect.center)
    assert game.rest_phase == "choose"
    game._choose_rest_option(3)
    assert game.rest_moved_on and run.tower_xp == {}


def test_drill_text_matches_the_game_constant():
    from core import game as game_module
    from presentation import ui

    assert ui.OUTPOST_DRILL_XP_TEXT == game_module.OUTPOST_DRILL_XP
