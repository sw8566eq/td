import json

import save_state
import settings
from levels import Level
from tower import BasicTower, LightningTower
from waves import WaveState


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
                 wave_index=0, wave_state=WaveState.BETWEEN_WAVES, between_wave_timer=3.0):
        self.current_level_id = current_level_id
        self.level = level
        self.endless = endless
        self.sandbox = sandbox
        self.difficulty = difficulty
        self.economy = _FakeEconomy(gold, lives)
        self.wave_manager = _FakeWaveManager(wave_index, wave_state, between_wave_timer)
        self.towers = towers


def test_save_and_load_run_round_trips(tmp_path):
    path = tmp_path / "save_state.json"
    level = make_level()
    tower = make_tower(BasicTower, anchor_col=2, anchor_row=3)
    tower.upgrade()
    tower.targeting_mode = "strongest"
    game = _FakeGame(level, [tower], current_level_id=1, gold=222, lives=17,
                      wave_index=2, wave_state=WaveState.BETWEEN_WAVES, between_wave_timer=1.5)

    save_state.save_run(game, path=path)
    loaded = save_state.load_run(path=path)

    assert loaded["current_level_id"] == 1
    assert loaded["level"].path_cells == level.path_cells
    assert loaded["endless"] is False
    assert loaded["sandbox"] is False
    assert loaded["difficulty"] == "normal"
    assert loaded["gold"] == 222
    assert loaded["lives"] == 17
    assert loaded["wave_index"] == 2
    assert loaded["wave_state"] == WaveState.BETWEEN_WAVES
    assert loaded["between_wave_timer"] == 1.5
    assert loaded["towers"] == [{
        "type": "basic", "anchor_col": 2, "anchor_row": 3,
        "level": 2, "specialization": None, "targeting_mode": "strongest",
    }]


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
