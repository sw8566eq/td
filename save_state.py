"""Save/load a single in-progress run to/from disk as JSON.

Only ever one save slot (save_state.json), mirroring progress.py/player_
settings.py's own "one JSON file for this kind of data" convention. Saving
is only ever offered between waves (see Game.can_save_run()/save_run()) --
never mid-SPAWNING -- so there is no live enemy/projectile/effect state to
serialize at all; a resumed run always starts from a clean wave boundary,
same restriction WaveManager.restore() itself enforces on the way back in.

Reuses persistence.level_to_dict()/level_from_dict() for the level blob
(a Level is exactly as JSON-serializable here as it is for a saved custom
level, endless-appended waves included) rather than re-deriving that shape.

A roguelike run in progress (Game.active_run, see run_state.py) is captured
too, under an optional "run" key -- None for a save with no active run
(classic/Practice/editor-playtest play, or save_state.json files written
before this key existed), a plain dict for one taken mid-run. It's genuinely
optional rather than always-present specifically so an old save file
without it still loads cleanly: _parse_and_validate_save only reconstructs a
RunState when the key is both present and not None, same `.get()`-defaults
spirit save_state.py already applies to `sold_towers` on an even older save.
"""

import json
import os

from json_io import load_json_with_fallback, module_relative_path
from levels import LEVELS
from persistence import level_from_dict, level_to_dict
from relics import RELICS
from run_state import RunState
from tower import TOWER_TYPES
from waves import WaveState

SCHEMA_VERSION = 1
SAVE_PATH = module_relative_path(__file__, "save_state.json")


def _tower_type_name(tower):
    for name, cls in TOWER_TYPES.items():
        if type(tower) is cls:
            return name
    raise ValueError(f"{tower!r} is not an instance of a registered TOWER_TYPES class")


def _tower_to_dict(tower):
    """One Tower -> the plain-JSON dict Game._tower_from_save_data()
    reconstructs it from -- shared by both `towers` and `sold_towers`
    below, since a sold tower needs everything a placed one does (it's
    still shown in the post-level results table) except grid occupancy."""
    return {
        "type": _tower_type_name(tower),
        "anchor_col": tower.anchor_col,
        "anchor_row": tower.anchor_row,
        "level": tower.level,
        "specialization": tower.specialization,
        "targeting_mode": tower.targeting_mode,
        # Lifetime stats, purely for display (see CLAUDE.md's "Post-level
        # results") -- without these, every tower reconstructed on resume
        # would show 0 shots/damage/kills even after real combat history.
        "shots_fired": tower.shots_fired,
        "shots_hit": tower.shots_hit,
        "damage_dealt": tower.damage_dealt,
        "kills": tower.kills,
    }


def _run_to_dict(run):
    """One RunState -> the plain-JSON dict _run_from_dict() reconstructs it
    from. floor_sequence/unlocked_towers/relics are all plain lists on the
    way out -- RunState.floor_sequence is a tuple, the one field here JSON
    can't round-trip byte-for-byte, so _run_from_dict() converts it back."""
    return {
        "seed": run.seed,
        "floor_sequence": list(run.floor_sequence),
        "difficulty": run.difficulty,
        "unlocked_towers": list(run.unlocked_towers),
        "floor_index": run.floor_index,
        "lives": run.lives,
        "gold": run.gold,
        "relics": list(run.relics),
        "is_daily": run.is_daily,
    }


def _run_from_dict(data):
    return RunState(
        seed=data["seed"],
        floor_sequence=tuple(data["floor_sequence"]),
        difficulty=data["difficulty"],
        unlocked_towers=list(data["unlocked_towers"]),
        floor_index=data["floor_index"],
        lives=data["lives"],
        gold=data["gold"],
        relics=list(data["relics"]),
        is_daily=data["is_daily"],
    )


def save_run(game, path=SAVE_PATH):
    """Serialize `game`'s current in-progress run to `path`. The caller
    (Game.save_run()) is responsible for only ever calling this between
    waves -- see this module's own docstring for why."""
    data = {
        "schema_version": SCHEMA_VERSION,
        "current_level_id": game.current_level_id,
        "level": level_to_dict(game.level),
        "endless": game.endless,
        "sandbox": game.sandbox,
        # This run's own difficulty, not necessarily whatever
        # game.difficulty (a sticky, cross-session player preference) says
        # by the time it's resumed -- see Game.resume_saved_run().
        "difficulty": game.difficulty,
        "gold": game.economy.gold,
        "lives": game.economy.lives,
        "wave_index": game.wave_manager.wave_index,
        "wave_state": game.wave_manager.state,
        "between_wave_timer": game.wave_manager.between_wave_timer,
        "towers": [_tower_to_dict(tower) for tower in game.towers],
        # A tower sold before saving still belongs in this run's eventual
        # post-level results table (see Game._tower_results()) -- without
        # this, resuming would silently drop it from that table entirely.
        "sold_towers": [_tower_to_dict(tower) for tower in game.sold_towers],
        "run": _run_to_dict(game.active_run) if game.active_run is not None else None,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_run(path=SAVE_PATH):
    """The saved-run dict (its "level" entry already converted to a live
    Level via persistence.level_from_dict -- everything else stays plain
    JSON-safe data for Game.resume_saved_run() to interpret), or None if
    there's nothing valid to resume. A missing, corrupt, or semantically
    invalid file (a wave_state Game.resume_saved_run() can't actually
    restore into, a wave_index out of range, an unrecognized tower type)
    is all "nothing to resume," not a crash, same spirit as
    persistence.list_custom_levels() skipping a bad file -- every field
    resume_saved_run() goes on to read is validated here first, so it
    never has to guard against a malformed save itself."""
    return load_json_with_fallback(path, _parse_and_validate_save, lambda: None)


def _parse_and_validate_save(data):
    """The `transform` half of load_run()'s load_json_with_fallback() call
    -- converts the level blob to a live Level and raises ValueError (one
    of json_io's own fallback-triggering exceptions, so an invalid save is
    still just "nothing to resume") for anything semantically wrong that
    well-formed JSON can't rule out on its own."""
    data["level"] = level_from_dict(data["level"])
    if data["wave_state"] not in (WaveState.AWAITING_START, WaveState.BETWEEN_WAVES):
        raise ValueError(f"saved run's wave_state {data['wave_state']!r} is not resumable")
    if not 0 <= data["wave_index"] < len(data["level"].wave_specs):
        raise ValueError("saved run's wave_index is out of range for its own level")
    for tower_data in data["towers"] + data.get("sold_towers", []):
        if tower_data["type"] not in TOWER_TYPES:
            raise ValueError(f"saved run references an unrecognized tower type {tower_data['type']!r}")
    run_data = data.get("run")  # absent (older save) and explicit None both mean "no active run"
    data["run"] = _parse_and_validate_active_run(run_data) if run_data is not None else None
    return data


def _parse_and_validate_active_run(run_data):
    """The "run" key's own validation, split out of _parse_and_validate_save
    for the same reason the top-level checks aren't one giant function --
    same regression-guard spirit as the unrecognized-tower-type check
    above, just against run_state.py's own registries (LEVELS/TOWER_TYPES/
    relics.RELICS) instead of TOWER_TYPES alone."""
    for level_id in run_data["floor_sequence"]:
        if level_id not in LEVELS:
            raise ValueError(f"saved run's floor_sequence references an unrecognized level id {level_id!r}")
    if not 0 <= run_data["floor_index"] < len(run_data["floor_sequence"]):
        raise ValueError("saved run's floor_index is out of range for its own floor_sequence")
    for tower_name in run_data["unlocked_towers"]:
        if tower_name not in TOWER_TYPES:
            raise ValueError(f"saved run's unlocked_towers references an unrecognized tower type {tower_name!r}")
    for relic_key in run_data["relics"]:
        if relic_key not in RELICS:
            raise ValueError(f"saved run's relics references an unrecognized relic {relic_key!r}")
    return _run_from_dict(run_data)


def has_saved_run(path=SAVE_PATH):
    return os.path.isfile(path)


def delete_saved_run(path=SAVE_PATH):
    """Remove the save file if it exists -- a no-op otherwise. Called once
    a resumed run reaches GAME_OVER/VICTORY (see Game), so "Continue" only
    ever offers a genuinely resumable in-progress run."""
    if os.path.isfile(path):
        os.remove(path)
