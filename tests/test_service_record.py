"""Tests for the Service Record (progression/service_record.py): the pure
record/load/save shape, every Game hook that writes it, sandbox recording
nothing, a resumed save never double counting, and the menu screen."""

import json

import pygame
import pytest
from conftest import (
    find_buildable_anchor,
    finish_all_waves,
    make_linear_run_map,
    start_first_floor,
)

from core.game import GameState
from entities.enemy import ENEMY_TYPES
from entities.tower import TOWER_TYPE_NAMES, TOWER_TYPES
from entities.waves import WaveState
from presentation import ui
from progression import service_record as sr
from run.card_pool import STARTER_TOWERS
from run.commanders import COMMANDERS, DEFAULT_COMMANDER
from run.run_map import ACT_COUNT
from run.run_state import RunState
from run.veterancy import RANKS as VETERANCY_RANKS
from support import settings

# --- Pure module ---


def test_missing_file_loads_an_empty_record(tmp_path):
    assert sr.load_service_record(str(tmp_path / "nope.json")) == sr.ServiceRecord()


@pytest.mark.parametrize("contents", ["{not json", "[1, 2]", '"text"'])
def test_corrupt_file_falls_back_to_an_empty_record(tmp_path, contents):
    path = tmp_path / "service_record.json"
    path.write_text(contents)
    assert sr.load_service_record(str(path)) == sr.ServiceRecord()


def test_damaged_values_drop_out_without_losing_the_rest(tmp_path):
    path = tmp_path / "service_record.json"
    path.write_text(json.dumps({
        "overall": {"floors_cleared": 4, "bad": "x", "neg": -1, "flag": True},
        "towers": {"basic": {"damage": 12.5, "kills": None}, "broken": 7},
        "enemies": "not a dict",
        "commanders": {"warden": {"runs": 2}},
    }))
    record = sr.load_service_record(str(path))
    assert record.overall == {"floors_cleared": 4}
    assert record.towers == {"basic": {"damage": 12.5}}
    assert record.enemies == {}
    assert record.commanders == {"warden": {"runs": 2}}


def test_a_non_object_section_reads_as_empty(tmp_path):
    path = tmp_path / "service_record.json"
    path.write_text(json.dumps({"overall": [1, 2], "towers": {"basic": {"built": 1}}}))
    record = sr.load_service_record(str(path))
    assert record.overall == {}
    assert record.towers == {"basic": {"built": 1}}


def test_record_adds_raises_and_round_trips(tmp_path):
    path = str(tmp_path / "service_record.json")
    sr.record(path, adds=[sr.overall("floors_cleared", 2), sr.tower("basic", "damage", 10.5)],
              raises=[sr.overall("deepest_depth", 3), sr.commander("warden", "best_depth", 3)])
    record = sr.record(path, adds=[sr.overall("floors_cleared", 1), sr.enemy("grunt", "kills", 4)],
                       raises=[sr.overall("deepest_depth", 2)])
    assert record == sr.load_service_record(path)
    assert record.get(sr.OVERALL, "", "floors_cleared") == 3
    assert record.get(sr.OVERALL, "", "deepest_depth") == 3  # a lower best never lowers it
    assert record.get(sr.TOWERS, "basic", "damage") == 10.5
    assert record.get(sr.ENEMIES, "grunt", "kills") == 4
    assert record.get(sr.COMMANDERS, "warden", "best_depth") == 3
    assert record.get(sr.TOWERS, "never", "damage") == 0
    assert json.loads((tmp_path / "service_record.json").read_text())["schema_version"] == sr.SCHEMA_VERSION


def test_zero_adds_and_non_raising_bests_create_no_rows():
    record = sr.apply(sr.ServiceRecord(), adds=[sr.tower("basic", "damage", 0)],
                      raises=[sr.tower("cannon", "best_rank", 0)])
    assert record.towers == {}


def test_unknown_section_is_rejected():
    with pytest.raises(ValueError):
        sr.apply(sr.ServiceRecord(), adds=[("bogus", "x", "y", 1)])


def test_tower_floor_entries_sum_per_type():
    entries = sr.tower_floor_entries([("basic", 10.0, 1), ("basic", 5.0, 2), ("cannon", 3.0, 0)])
    assert sorted(entries) == sorted([
        sr.tower("basic", "damage", 15.0), sr.tower("basic", "kills", 3),
        sr.tower("cannon", "damage", 3.0), sr.tower("cannon", "kills", 0),
    ])


def test_floor_tally_entries():
    tally = sr.FloorTally()
    tally.add_kill("grunt")
    tally.add_kill("grunt")
    tally.add_kill(None)  # an unregistered class still counts toward the total
    tally.lives_lost = 2
    assert sorted(tally.entries(gold_earned=30)) == sorted([
        sr.overall("enemies_killed", 3), sr.overall("lives_lost", 2), sr.overall("gold_earned", 30),
        sr.enemy("grunt", "kills", 2),
    ])


def test_display_rows_sort_by_their_headline_stat():
    record = sr.apply(sr.ServiceRecord(), adds=[
        sr.tower("basic", "damage", 5), sr.tower("cannon", "damage", 50),
        sr.enemy("grunt", "kills", 1), sr.enemy("tank", "kills", 9),
        sr.commander("warden", "runs", 1), sr.commander("engineer", "runs", 3),
    ])
    assert [name for name, _ in sr.tower_rows(record)] == ["cannon", "basic"]
    assert [name for name, _ in sr.enemy_rows(record)] == ["tank", "grunt"]
    assert [name for name, _ in sr.commander_rows(record)] == ["engineer", "warden"]


# --- Game hooks ---


def _load(game):
    return sr.load_service_record(game.service_record_path)


def _spawn_one_enemy(game):
    game.wave_manager.skip_delay()
    game.update(dt=0.01)
    game.update(dt=0.1)
    assert game.enemies
    return game.enemies[0]


def _place_tower(game):
    anchor = find_buildable_anchor(game)
    game.selected_tower_name = game.active_run.unlocked_towers[0]
    assert game.try_place_tower(*anchor)
    return game.grid.get_tower(*anchor)


def test_starting_a_run_records_the_run_and_its_commander(game):
    game.start_new_run(seed=3)
    record = _load(game)
    assert record.get(sr.OVERALL, "", "runs_started") == 1
    assert record.get(sr.COMMANDERS, DEFAULT_COMMANDER, "runs") == 1


def test_placing_a_tower_records_it_per_type(game):
    start_first_floor(game)
    tower = _place_tower(game)
    record = _load(game)
    assert record.get(sr.OVERALL, "", "towers_built") == 1
    assert record.get(sr.TOWERS, TOWER_TYPE_NAMES[type(tower)], "built") == 1


def test_a_floor_clear_records_floor_kills_lives_gold_and_tower_results(game):
    run = start_first_floor(game)
    first, second = _place_tower(game), _place_tower(game)
    first.damage_dealt, first.kills = 100.0, 3
    second.damage_dealt, second.kills = 40.0, 1
    assert game.try_sell_tower(second)  # sold towers still count; the refund isn't "earned"
    enemy = _spawn_one_enemy(game)
    enemy_key = next(key for key, cls in ENEMY_TYPES.items() if type(enemy) is cls)
    enemy.take_damage(enemy.max_hp)
    game.update(dt=0.01)
    game._lose_a_life()  # the one place a leak costs a life
    gold_earned = game.economy.gold_earned
    damage = {}
    for tower in game.towers + game.sold_towers:
        name = TOWER_TYPE_NAMES[type(tower)]
        damage[name] = damage.get(name, 0.0) + tower.damage_dealt

    finish_all_waves(game)
    game.update(dt=0.01)

    assert game.state == GameState.FLOOR_CLEARED
    record = _load(game)
    assert record.get(sr.OVERALL, "", "floors_cleared") == 1
    assert record.get(sr.OVERALL, "", "deepest_depth") == 1
    assert record.get(sr.COMMANDERS, run.commander, "best_depth") == 1
    assert record.get(sr.OVERALL, "", "enemies_killed") >= 1
    assert record.get(sr.ENEMIES, enemy_key, "kills") >= 1
    assert record.get(sr.OVERALL, "", "lives_lost") == 1
    assert record.get(sr.OVERALL, "", "gold_earned") == gold_earned > 0
    for name, dealt in damage.items():
        assert record.get(sr.TOWERS, name, "damage") == pytest.approx(dealt)
    assert record.get(sr.TOWERS, TOWER_TYPE_NAMES[type(first)], "kills") >= 4
    # Veterancy from this floor's kills reaches the per-type best rank.
    name = TOWER_TYPE_NAMES[type(first)]
    assert record.get(sr.TOWERS, name, "best_rank") == game.veterancy_rank(name)


def test_sandbox_records_nothing(game, tmp_path):
    game.load_level(1, sandbox=True)
    game.state = GameState.PLAYING
    anchor = find_buildable_anchor(game)
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*anchor)
    enemy = _spawn_one_enemy(game)
    enemy.take_damage(enemy.max_hp)
    game.update(dt=0.01)
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.VICTORY
    assert not (tmp_path / "service_record.json").exists()


def test_a_non_sandbox_victory_folds_in_its_towers(game):
    game.load_level(1)
    game.state = GameState.PLAYING
    anchor = find_buildable_anchor(game)
    game.selected_tower_name = "basic"
    assert game.try_place_tower(*anchor)
    game.grid.get_tower(*anchor).damage_dealt = 25.0
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.VICTORY
    assert _load(game).get(sr.TOWERS, "basic", "damage") == 25.0


def test_resuming_a_save_never_double_counts(game):
    start_first_floor(game)
    tower = _place_tower(game)
    name = TOWER_TYPE_NAMES[type(tower)]
    tower.damage_dealt, tower.kills = 100.0, 2
    # Play wave 1 out for real (killing everything) to a saveable boundary.
    game.wave_manager.skip_delay()
    for _ in range(2000):
        game.update(dt=0.05)
        for enemy in game.enemies:
            enemy.take_damage(enemy.max_hp)
        if game.wave_manager.state == WaveState.BETWEEN_WAVES:
            break
    tower.damage_dealt = 100.0
    assert game.save_run()
    killed_before_save = _load(game).get(sr.OVERALL, "", "enemies_killed")
    assert killed_before_save >= 1  # the save flushed the tally

    # Continue, quit without saving, Continue again -- the same save twice.
    game.state = GameState.MENU
    game._continue_saved_run()
    assert game.state == GameState.PLAYING
    assert game.service_tally == sr.FloorTally()
    game.state = GameState.MENU
    game._continue_saved_run()
    assert game.state == GameState.PLAYING
    assert _load(game).get(sr.OVERALL, "", "enemies_killed") == killed_before_save

    resumed = game.towers[0]
    assert resumed.damage_dealt == 100.0  # the save restores the floor's tower stats
    finish_all_waves(game)
    game.update(dt=0.01)

    record = _load(game)
    assert record.get(sr.TOWERS, name, "damage") == pytest.approx(resumed.damage_dealt)
    assert record.get(sr.OVERALL, "", "floors_cleared") == 1
    assert record.get(sr.OVERALL, "", "enemies_killed") == killed_before_save
    # The clear deleted the save, so the floor can't be replayed for credit.
    assert not game.has_saved_run or not game.save_path.exists()


def test_permadeath_records_the_runs_end_and_its_depth(game):
    run = start_first_floor(game)
    tower = _place_tower(game)
    tower.damage_dealt = 7.0
    game.economy.lives = 0
    game.update(dt=0.01)
    assert game.state == GameState.GAME_OVER
    record = _load(game)
    assert record.get(sr.OVERALL, "", "runs_ended") == 1
    assert record.get(sr.OVERALL, "", "deepest_depth") == 1
    assert record.get(sr.COMMANDERS, run.commander, "best_depth") == 1
    assert record.get(sr.OVERALL, "", "best_endless_score") == 0
    assert record.get(sr.TOWERS, TOWER_TYPE_NAMES[type(tower)], "damage") == 7.0


def _run_on(game, node_types, act=0):
    game.active_run = RunState(
        seed=1, map=make_linear_run_map(node_types), difficulty="normal",
        unlocked_towers=list(STARTER_TOWERS), act=act, lives=15, lives_captured=True,
    )
    game.active_run.visited_node_ids = ["0-0"]
    game._enter_node("1-0")
    return game.active_run


def test_an_earlier_acts_boss_counts_an_act_cleared(game):
    _run_on(game, ["combat", "boss"])
    finish_all_waves(game)
    game.update(dt=0.01)
    record = _load(game)
    assert record.get(sr.OVERALL, "", "acts_cleared") == 1
    assert record.get(sr.OVERALL, "", "deepest_depth") == 2


def test_the_final_boss_counts_an_act_and_endless_waves_set_the_best_score(game):
    run = _run_on(game, ["combat", "boss"], act=ACT_COUNT - 1)
    wave_manager = game.wave_manager
    wave_manager.wave_index = wave_manager.total_waves - 1
    wave_manager.state = WaveState.SPAWNING
    wave_manager._spawn_queues = []
    game.enemies = []
    game.update(dt=0.01)
    assert run.boss_defeated
    assert _load(game).get(sr.OVERALL, "", "acts_cleared") == 1

    run.endless_waves_cleared = 0
    game.wave_manager.wave_index += 3
    game._update_endless_score()
    assert _load(game).get(sr.OVERALL, "", "best_endless_score") == run.endless_waves_cleared > 0


def test_relics_and_potions_are_recorded(game):
    run = start_first_floor(game)
    game._grant_relic("spyglass_array")
    run.potions = ["liquid_gold"]
    game.use_potion(0)
    record = _load(game)
    assert record.get(sr.OVERALL, "", "relics_collected") == 1
    assert record.get(sr.OVERALL, "", "potions_used") == 1


# --- Screen ---


def test_t_opens_the_service_record_and_it_scrolls_and_goes_back(game):
    sr.record(game.service_record_path, adds=(
        [sr.tower(name, "damage", 1000 + i) for i, name in enumerate(TOWER_TYPES)]
        + [sr.enemy(name, "kills", 5) for name in ENEMY_TYPES]
        + [sr.commander(key, "runs", 1) for key in COMMANDERS]
    ))
    game._handle_keydown(pygame.K_t)
    assert game.state == GameState.SERVICE_RECORD
    headers = [cells[0] for kind, cells, _bar in game.service_record_rows if kind == "header"]
    assert headers == ["Overall", "Towers", "Enemies", "Commanders"]
    tower_rows = [cells for kind, cells, bar in game.service_record_rows if kind == "row" and bar > 0]
    assert tower_rows[0][0] == list(TOWER_TYPES.values())[-1].display_name  # most damage first
    game.render()

    game._scroll_service_record(1)
    assert game.service_record_scroll_offset == 0
    for _ in range(1000):
        game._scroll_service_record(-1)
    assert game.service_record_scroll_offset == ui.unlocks_max_scroll(len(game.service_record_rows)) > 0
    game.render()

    real_get = pygame.event.get
    try:
        pygame.event.get = lambda: [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)]
        game.handle_events()
        assert game.service_record_scroll_offset < ui.unlocks_max_scroll(len(game.service_record_rows))
        pygame.event.get = lambda: [pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=game.unlocks_back_rect.center, button=1)]
        game.handle_events()
    finally:
        pygame.event.get = real_get
    assert game.state == GameState.MENU
    game._enter_service_record()
    assert game.service_record_scroll_offset == 0
    game._handle_keydown(pygame.K_ESCAPE)
    assert game.state == GameState.MENU


def test_empty_sections_show_a_note(game):
    game._enter_service_record()
    kinds = [kind for kind, _cells, _bar in game.service_record_rows]
    assert kinds.count("note") == 3
    game.render()


def test_service_record_columns_fit_on_screen(game):
    font = game.small_font
    longest = max(
        [cls.display_name for cls in TOWER_TYPES.values()]
        + [cls.display_name for cls in ENEMY_TYPES.values()]
        + [c.display_name for c in COMMANDERS.values()],
        key=lambda name: font.size(name)[0],
    )
    assert ui.SERVICE_RECORD_NAME_X + font.size(longest)[0] < ui.SERVICE_RECORD_COLUMN_XS[0]
    # Damage gets the widest column; kills/built a little less.
    damage_x, kills_x, built_x, rank_x = ui.SERVICE_RECORD_COLUMN_XS
    assert damage_x + font.size("999,999,999")[0] < kills_x
    assert kills_x + font.size("9,999,999")[0] < built_x
    assert built_x + font.size("Best rank")[0] < rank_x
    longest_rank = max([rank.name for rank in VETERANCY_RANKS] + ["Recruit"], key=lambda n: font.size(n)[0])
    assert rank_x + font.size(longest_rank)[0] < ui.SERVICE_RECORD_BAR_X
    assert ui.SERVICE_RECORD_BAR_X + ui.SERVICE_RECORD_BAR_WIDTH <= settings.SCREEN_WIDTH
    for label in sr.OVERALL_STATS.values():
        assert ui.SERVICE_RECORD_NAME_X + font.size(label)[0] < ui.SERVICE_RECORD_OVERALL_VALUE_X
