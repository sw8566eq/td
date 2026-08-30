import json

from json_io import load_json_with_fallback


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
