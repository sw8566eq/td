import json

import save_state
import settings
from levels import Level
from run_map import MapNode, RunMap
from run_state import RunState
from tower import BasicTower, LightningTower
from waves import WaveState

# A small, hand-built map (not a real generate_run_map() output) shared by
# every test below that needs a real RunState -- combat node "0-0" (level 1)
# -> shop node "1-0" -> boss combat node "2-0" (level 2, the final row).
# Deliberately includes one non-combat node (the shop) so tests can exercise
# _parse_and_validate_active_run's "current_node_id must be a combat/elite
# node" check.
_MAP = RunMap(
    rows=(
        (MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),),
        (MapNode("1-0", row=1, col=0, node_type="shop"),),
        (MapNode("2-0", row=2, col=0, node_type="combat", level_id=2),),
    ),
    edges={"0-0": ("1-0",), "1-0": ("2-0",)},
)


def make_run(**overrides):
    kwargs = dict(
        seed=1, map=_MAP, difficulty="normal", unlocked_towers=["basic"], current_node_id="0-0",
    )
    kwargs.update(overrides)
    return RunState(**kwargs)


def make_level(name="Test Level", **overrides):
    kwargs = dict(
        id=1,
        name=name,
        path_cells=frozenset({(0, 0), (1, 0)}),
        spawn_cells=((0, 0),),
        goal_cells=((1, 0),),
        wave_specs=[{(0, 0): {"grunt": 3}}, {(0, 0): {"grunt": 4}}],
        starting_gold=150,
        starting_lives=20,
    )
    kwargs.update(overrides)
    return Level(**kwargs)


def make_tower(tower_cls, anchor_col=0, anchor_row=0):
    pixel_pos = (
        anchor_col * settings.SUBTILE_SIZE + settings.TILE_SIZE / 2,
        anchor_row * settings.SUBTILE_SIZE + settings.TILE_SIZE / 2,
    )
    return tower_cls(anchor_col=anchor_col, anchor_row=anchor_row, pixel_pos=pixel_pos)


class _FakeEconomy:
    def __init__(self, gold, lives):
        self.gold = gold
        self.lives = lives


class _FakeWaveManager:
    def __init__(self, wave_index, state, between_wave_timer):
        self.wave_index = wave_index
        self.state = state
        self.between_wave_timer = between_wave_timer


class _FakeGame:
    """A minimal stand-in for Game carrying only what save_run() actually
    reads -- keeps this module's tests focused on save_state.py's own
    (de)serialization logic, not on constructing a real pygame-backed Game.
    Game-level integration (the real save_run()/resume_saved_run() methods)
    is covered separately in test_game.py."""

    def __init__(self, level, towers, current_level_id=1, endless=False, sandbox=False,
                 difficulty="normal", gold=150, lives=20,
                 wave_index=0, wave_state=WaveState.BETWEEN_WAVES, between_wave_timer=3.0,
                 sold_towers=None, active_run=None):
        self.current_level_id = current_level_id
        self.level = level
        self.endless = endless
        self.sandbox = sandbox
        self.difficulty = difficulty
        self.economy = _FakeEconomy(gold, lives)
        self.wave_manager = _FakeWaveManager(wave_index, wave_state, between_wave_timer)
        self.towers = towers
        self.sold_towers = sold_towers or []
        self.active_run = active_run


def test_save_and_load_run_round_trips(tmp_path):
    path = tmp_path / "save_state.json"
    level = make_level()
    tower = make_tower(BasicTower, anchor_col=2, anchor_row=3)
    tower.upgrade()
    tower.targeting_mode = "strongest"
    game = _FakeGame(level, [tower], current_level_id=1, gold=222, lives=17,
                      wave_index=1, wave_state=WaveState.BETWEEN_WAVES, between_wave_timer=1.5)

    save_state.save_run(game, path=path)
    loaded = save_state.load_run(path=path)

    assert loaded["current_level_id"] == 1
    assert loaded["level"].path_cells == level.path_cells
    assert loaded["endless"] is False
    assert loaded["sandbox"] is False
    assert loaded["difficulty"] == "normal"
    assert loaded["gold"] == 222
    assert loaded["lives"] == 17
    assert loaded["wave_index"] == 1
    assert loaded["wave_state"] == WaveState.BETWEEN_WAVES
    assert loaded["between_wave_timer"] == 1.5
    assert loaded["towers"] == [{
        "type": "basic", "anchor_col": 2, "anchor_row": 3,
        "level": 2, "specialization": None, "targeting_mode": "strongest",
        "shots_fired": 0, "shots_hit": 0, "damage_dealt": 0.0, "kills": 0,
    }]
    assert loaded["sold_towers"] == []
    assert loaded["run"] is None


def test_save_and_load_run_round_trips_an_active_run(tmp_path):
    path = tmp_path / "save_state.json"
    level = make_level()
    run = make_run(
        seed=42, difficulty="hard", unlocked_towers=["basic", "cannon", "frost"],
        visited_node_ids=["0-0", "1-0"], current_node_id="2-0",
        lives=15, shop_currency=80, relics=["prospectors_charm"], is_daily=True,
        has_spent_gold=True, used_guardians_reprieve=True,
    )
    game = _FakeGame(level, [], active_run=run)

    save_state.save_run(game, path=path)
    loaded = save_state.load_run(path=path)

    loaded_run = loaded["run"]
    assert loaded_run.seed == 42
    assert loaded_run.map == _MAP
    assert loaded_run.difficulty == "hard"
    assert loaded_run.unlocked_towers == ["basic", "cannon", "frost"]
    assert loaded_run.current_node_id == "2-0"
    assert loaded_run.visited_node_ids == ["0-0", "1-0"]
    assert loaded_run.lives == 15
    assert loaded_run.shop_currency == 80
    assert loaded_run.relics == ["prospectors_charm"]
    assert loaded_run.is_daily is True
    assert loaded_run.has_spent_gold is True
    assert loaded_run.used_guardians_reprieve is True


def test_load_run_with_a_saved_run_predating_the_run_key_still_resumes(tmp_path):
    # An older save file (written before save_state.py gained the "run"
    # key) has no such key at all, not an explicit null -- must load as
    # cleanly as one with "run": null, same .get()-defaults spirit already
    # applied to sold_towers on an even older save.
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [])
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    del data["run"]
    path.write_text(json.dumps(data))

    loaded = save_state.load_run(path=path)

    assert loaded["run"] is None


def test_load_run_with_an_old_pre_map_run_format_returns_none(tmp_path):
    # Clean break, not a migration (see save_state.py's own docstring on
    # _parse_and_validate_active_run): a save from before the run loop's
    # branching map (schema_version 1 -- "floor_sequence"/"floor_index",
    # no "map"/"current_node_id" at all) has no meaningful way to become a
    # map, so the whole save is treated as "nothing to resume," same as
    # any other corrupt/incompatible file.
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    del data["run"]["map"]
    del data["run"]["current_node_id"]
    del data["run"]["visited_node_ids"]
    data["run"]["floor_sequence"] = [1]
    data["run"]["floor_index"] = 0
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_run_predating_shop_currency_still_resumes(tmp_path):
    # An older save's own "run" dict (written back when "gold" was its
    # carried-currency key instead of "shop_currency") has no such key at
    # all -- must still load, defaulting to 0, same .get()-defaults spirit
    # as the "run"-key-itself precedent just above.
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    del data["run"]["shop_currency"]
    path.write_text(json.dumps(data))

    loaded = save_state.load_run(path=path)

    assert loaded["run"].shop_currency == 0


def test_load_run_with_a_run_referencing_an_unrecognized_level_id_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["map"]["rows"][0][0]["level_id"] = 999999
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_run_referencing_an_unrecognized_node_type_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["map"]["rows"][0][0]["node_type"] = "no_such_type"
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_current_node_id_not_in_its_own_map_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["current_node_id"] = "9-9"
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_current_node_that_isnt_combat_or_elite_returns_none(tmp_path):
    # A resumable save is always mid-PLAYING (see Game.can_save_run()) --
    # the current node should structurally always be combat/elite, never a
    # Shop/Event/Rest/Treasure screen -- this proves the defensive check
    # catches it if a hand-edited (or otherwise corrupted) save claims
    # otherwise.
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["current_node_id"] = "1-0"  # the shop node in _MAP
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_run_referencing_an_unrecognized_visited_node_id_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["visited_node_ids"] = ["9-9"]
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_run_referencing_an_unrecognized_edge_target_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["map"]["edges"]["0-0"] = ["9-9"]
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_run_referencing_an_unrecognized_tower_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["unlocked_towers"] = ["no_such_tower"]
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_run_referencing_an_unrecognized_relic_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], active_run=make_run())
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["run"]["relics"] = ["no_such_relic"]
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_save_run_captures_endless_appended_waves():
    # An endless run's escalation waves live directly on game.level.
    # wave_specs by the time a save happens (see waves.py) -- saving
    # game.level itself (not re-deriving from the LEVELS registry) must
    # capture them for free.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/save_state.json"
        level = make_level()
        level.wave_specs.append({(0, 0): {"grunt": 99}})  # simulate an endless-generated wave
        game = _FakeGame(level, [], endless=True)

        save_state.save_run(game, path=path)
        loaded = save_state.load_run(path=path)

        assert len(loaded["level"].wave_specs) == 3
        assert loaded["endless"] is True


def test_save_run_captures_specialization_and_multiple_towers(tmp_path):
    path = tmp_path / "save_state.json"
    level = make_level()
    basic = make_tower(BasicTower, anchor_col=0, anchor_row=0)
    lightning = make_tower(LightningTower, anchor_col=1, anchor_row=0)
    for _ in range(BasicTower.MAX_LEVEL - 1):
        basic.upgrade()
    basic.specialize("power")
    game = _FakeGame(level, [basic, lightning])

    save_state.save_run(game, path=path)
    loaded = save_state.load_run(path=path)

    by_type = {t["type"]: t for t in loaded["towers"]}
    assert by_type["basic"]["level"] == BasicTower.MAX_LEVEL
    assert by_type["basic"]["specialization"] == "power"
    assert by_type["lightning"]["specialization"] is None


def test_save_run_captures_tower_lifetime_stats_and_sold_towers(tmp_path):
    path = tmp_path / "save_state.json"
    level = make_level()
    placed = make_tower(BasicTower, anchor_col=0, anchor_row=0)
    placed.shots_fired, placed.shots_hit, placed.damage_dealt, placed.kills = 10, 8, 123.5, 3
    sold = make_tower(BasicTower, anchor_col=1, anchor_row=0)
    sold.shots_fired, sold.shots_hit, sold.damage_dealt, sold.kills = 5, 5, 50.0, 1
    game = _FakeGame(level, [placed], sold_towers=[sold])

    save_state.save_run(game, path=path)
    loaded = save_state.load_run(path=path)

    assert loaded["towers"][0]["shots_fired"] == 10
    assert loaded["towers"][0]["shots_hit"] == 8
    assert loaded["towers"][0]["damage_dealt"] == 123.5
    assert loaded["towers"][0]["kills"] == 3
    assert len(loaded["sold_towers"]) == 1
    assert loaded["sold_towers"][0]["kills"] == 1


def test_to_dict_shape_is_plain_json_serializable(tmp_path):
    path = tmp_path / "save_state.json"
    level = make_level()
    tower = make_tower(BasicTower)
    game = _FakeGame(level, [tower])

    save_state.save_run(game, path=path)
    # Must not raise -- confirms the file on disk really is plain JSON,
    # not something that only happened to work via json.dump's own encoder
    # tolerances.
    json.loads(path.read_text())


def test_load_run_on_a_missing_file_returns_none():
    assert save_state.load_run(path="/does/not/exist.json") is None


def test_load_run_on_a_corrupt_file_returns_none_instead_of_raising(tmp_path):
    path = tmp_path / "save_state.json"
    path.write_text("{not valid json")

    assert save_state.load_run(path=path) is None


def test_load_run_on_an_unparseable_level_returns_none_instead_of_raising(tmp_path):
    path = tmp_path / "save_state.json"
    path.write_text(json.dumps({"schema_version": 1, "level": {"missing": "required keys"}}))

    assert save_state.load_run(path=path) is None


def test_load_run_with_a_wave_state_that_cannot_be_resumed_into_returns_none(tmp_path):
    # Regression guard: WaveManager.restore() only accepts AWAITING_START/
    # BETWEEN_WAVES -- a save file with any other wave_state used to sail
    # straight through load_run() and crash resume_saved_run() with an
    # uncaught ValueError instead of leaving the player on the menu.
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], wave_state=WaveState.SPAWNING)
    save_state.save_run(game, path=path)

    assert save_state.load_run(path=path) is None


def test_load_run_with_an_out_of_range_wave_index_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], wave_index=5)  # make_level() only has 2 waves
    save_state.save_run(game, path=path)

    assert save_state.load_run(path=path) is None


def test_load_run_with_an_unrecognized_tower_type_returns_none(tmp_path):
    # Regression guard: a stale/renamed/hand-edited tower type name used
    # to sail through load_run() and crash resume_saved_run() with an
    # uncaught KeyError on TOWER_TYPES[tower_data["type"]].
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [make_tower(BasicTower)])
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["towers"][0]["type"] = "no_such_tower"
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_load_run_with_an_unrecognized_sold_tower_type_returns_none(tmp_path):
    path = tmp_path / "save_state.json"
    game = _FakeGame(make_level(), [], sold_towers=[make_tower(BasicTower)])
    save_state.save_run(game, path=path)
    data = json.loads(path.read_text())
    data["sold_towers"][0]["type"] = "no_such_tower"
    path.write_text(json.dumps(data))

    assert save_state.load_run(path=path) is None


def test_has_saved_run_reflects_whether_the_file_exists(tmp_path):
    path = tmp_path / "save_state.json"
    assert save_state.has_saved_run(path=path) is False

    path.write_text("{}")
    assert save_state.has_saved_run(path=path) is True


def test_delete_saved_run_removes_the_file(tmp_path):
    path = tmp_path / "save_state.json"
    path.write_text("{}")

    save_state.delete_saved_run(path=path)

    assert not path.exists()


def test_delete_saved_run_on_a_missing_file_is_a_no_op(tmp_path):
    path = tmp_path / "save_state.json"
    save_state.delete_saved_run(path=path)  # must not raise
    assert not path.exists()
