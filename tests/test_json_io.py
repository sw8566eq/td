import json
import os

from persistence.json_io import load_json_with_fallback, module_relative_path


def test_missing_file_returns_the_default():
    calls = []
    result = load_json_with_fallback(
        "/does/not/exist.json", transform=lambda data: data, default=lambda: calls.append(1) or "default",
    )
    assert result == "default"
    assert calls == [1]  # default() is called fresh, not memoized


def test_valid_file_is_parsed_and_transformed(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"n": 3}))

    result = load_json_with_fallback(path, transform=lambda data: data["n"] * 2, default=lambda: -1)

    assert result == 6


def test_corrupt_json_returns_the_default(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("{not valid json")

    result = load_json_with_fallback(path, transform=lambda data: data, default=lambda: "fallback")

    assert result == "fallback"


def test_transform_raising_a_fallback_error_returns_the_default(tmp_path):
    # A `transform` that finds the parsed JSON semantically invalid (not
    # just malformed) signals that by raising -- same as save_state.py's
    # own wave_state/wave_index/tower-type checks.
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"n": "not a number"}))

    def transform(data):
        return int(data["n"])  # raises ValueError on this input

    result = load_json_with_fallback(path, transform=transform, default=lambda: None)

    assert result is None


def test_default_is_a_fresh_value_each_call_not_a_shared_mutable():
    def make_default():
        return []

    first = load_json_with_fallback("/does/not/exist.json", transform=lambda data: data, default=make_default)
    second = load_json_with_fallback("/does/not/exist.json", transform=lambda data: data, default=make_default)
    first.append("mutated")

    assert second == []


def test_module_relative_path_walks_up_two_levels_not_one():
    # Every real caller lives one level under the project root now
    # (persistence/progress.py, presentation/assets.py, ...), inside one
    # of the repo's top-level package folders -- module_relative_path must
    # resolve relative to that package's own *parent* (the project root),
    # not the package folder itself, or every local JSON file/assets/
    # custom_levels/ path silently resolves one level too deep. Verified
    # here against a synthetic path, independent of this repo's own real
    # layout, so it can't accidentally pass by coincidence the way
    # recomputing the same formula the source uses always would.
    fake_module_file = os.path.join("/some/project/root", "a_package", "a_module.py")
    result = module_relative_path(fake_module_file, "data.json")
    assert result == os.path.join("/some/project/root", "data.json")


def test_every_real_on_disk_state_path_resolves_to_the_actual_project_root():
    # Independent check, not a recomputation of module_relative_path's own
    # formula (see that trap's own note in json_io.py's docstring, and the
    # test above for the synthetic-path unit check) -- this test derives
    # "the real project root" a completely different way, from this test
    # file's own location (tests/ is also exactly one level under the
    # project root), and confirms every real *_PATH/DEFAULT_ASSET_ROOT
    # constant across the codebase's persistence-backed modules lands
    # right next to it. A regression here (e.g. a module moved deeper, or
    # module_relative_path's own hop count drifting out of sync with the
    # actual folder depth) would otherwise ship silently: no test
    # constructs Game()/AssetManager()/SoundManager() with every path left
    # at its real default -- every fixture always overrides them to a
    # scratch/tmp location instead.
    import persistence.json_io as json_io_module
    import persistence.persistence as persistence_module
    import presentation.assets as assets_module
    from persistence import keybindings, player_settings, save_state
    from progression import achievements, meta_progression, progress, run_history

    expected_root = os.path.dirname(os.path.dirname(os.path.abspath(json_io_module.__file__)))
    assert os.path.isfile(os.path.join(expected_root, "pyproject.toml"))
    assert os.path.isfile(os.path.join(expected_root, "main.py"))

    real_paths = {
        "PROGRESS_PATH": progress.PROGRESS_PATH,
        "ACHIEVEMENTS_PATH": achievements.ACHIEVEMENTS_PATH,
        "SETTINGS_PATH": player_settings.SETTINGS_PATH,
        "SAVE_PATH": save_state.SAVE_PATH,
        "META_PROGRESSION_PATH": meta_progression.META_PROGRESSION_PATH,
        "RUN_HISTORY_PATH": run_history.RUN_HISTORY_PATH,
        "BINDINGS_PATH": keybindings.BINDINGS_PATH,
        "LEVELS_DIR": persistence_module.LEVELS_DIR,
        "DEFAULT_ASSET_ROOT": assets_module.DEFAULT_ASSET_ROOT,
    }
    for name, path in real_paths.items():
        assert os.path.dirname(path) == expected_root, f"{name} = {path!r} is not directly under {expected_root!r}"
