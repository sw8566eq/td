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
from run_map import NODE_TYPES, MapNode, RunMap
from run_state import RunState
from tower import TOWER_TYPES
from waves import WaveState

# Bumped from 1 -- the "run" blob's own shape changed (floor_sequence/
# floor_index replaced by a branching map/current_node_id/visited_node_ids,
# see run_state.py) when the run loop grew a branching map. Nothing
# currently branches on this value; it's here purely for inspectability, the
# same "cheap to have, useful for future debugging" reasoning every other
# schema_version field in this codebase already follows.
SCHEMA_VERSION = 2
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


def _map_to_dict(run_map):
    """One RunMap -> the plain-JSON dict _map_from_dict() reconstructs it
    from -- every MapNode is already a flat, JSON-safe shape (str/int/None
    fields only), so this is just nested lists/dicts, no per-field
    conversion needed the way floor_sequence's tuple used to need."""
    return {
        "rows": [[
            {"id": node.id, "row": node.row, "col": node.col,
             "node_type": node.node_type, "level_id": node.level_id}
            for node in row
        ] for row in run_map.rows],
        "edges": {node_id: list(target_ids) for node_id, target_ids in run_map.edges.items()},
    }


def _map_from_dict(data):
    rows = tuple(tuple(MapNode(**node_data) for node_data in row) for row in data["rows"])
    edges = {node_id: tuple(target_ids) for node_id, target_ids in data["edges"].items()}
    return RunMap(rows=rows, edges=edges)


def _run_to_dict(run):
    """One RunState -> the plain-JSON dict _run_from_dict() reconstructs it
    from. unlocked_towers/relics/visited_node_ids are all plain lists on
    the way out (RunState.visited_node_ids already is one; kept as its own
    explicit list() call for the same "never accidentally alias the live
    run's own list" reasoning the others get). No "gold" key -- battle gold
    (Economy.gold) resets fresh every floor now and was never part of
    RunState to begin with (see run_state.py's own docstring); shop_currency
    is the field that persists here instead."""
    return {
        "seed": run.seed,
        "map": _map_to_dict(run.map),
        "difficulty": run.difficulty,
        "unlocked_towers": list(run.unlocked_towers),
        "current_node_id": run.current_node_id,
        "visited_node_ids": list(run.visited_node_ids),
        "lives": run.lives,
        "shop_currency": run.shop_currency,
        "relics": list(run.relics),
        "is_daily": run.is_daily,
        "has_spent_gold": run.has_spent_gold,
        "used_guardians_reprieve": run.used_guardians_reprieve,
    }


def _run_from_dict(data):
    return RunState(
        seed=data["seed"],
        map=_map_from_dict(data["map"]),
        difficulty=data["difficulty"],
        unlocked_towers=list(data["unlocked_towers"]),
        current_node_id=data["current_node_id"],
        visited_node_ids=list(data["visited_node_ids"]),
        lives=data["lives"],
        shop_currency=data.get("shop_currency", 0),
        relics=list(data["relics"]),
        is_daily=data["is_daily"],
        has_spent_gold=data["has_spent_gold"],
        used_guardians_reprieve=data["used_guardians_reprieve"],
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
        # The difficulty this save was actually played under -- a run's
        # own pinned difficulty (game.active_run.difficulty, already
        # snapshotted once at start_new_run() and possibly different from
        # the player's live sticky preference by save time), or plain
        # game.difficulty itself for a classic/Practice/playtest save,
        # which has no run of its own to pin one from. Game.resume_saved_
        # run() actually reads run.difficulty straight off the
        # reconstructed RunState rather than this field when one exists
        # (so its own correctness doesn't depend on this line), but this
        # field is still the one a save file's own top level shows for
        # "what difficulty was this played under," and should say so
        # honestly regardless of which reader ends up using it.
        "difficulty": game.active_run.difficulty if game.active_run is not None else game.difficulty,
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
    relics.RELICS/run_map.NODE_TYPES) instead of TOWER_TYPES alone.

    An older save (from before the run loop's branching map, schema_version
    1 -- still keyed by "floor_sequence"/"floor_index" rather than "map"/
    "current_node_id") has no meaningful way to become a map at all, so it's
    treated the same as any other semantically-invalid save: this raises
    KeyError reaching for a "map" key that was never written (one of
    json_io's own fallback-triggering exceptions), and load_run() falls all
    the way back to "nothing to resume" -- see this module's own docstring
    and CLAUDE.md's run-loop section for why a clean break, not a
    migration, is the right call here."""
    node_ids = {node_data["id"] for row in run_data["map"]["rows"] for node_data in row}
    for row in run_data["map"]["rows"]:
        for node_data in row:
            if node_data["node_type"] not in NODE_TYPES:
                raise ValueError(f"saved run's map references an unrecognized node type {node_data['node_type']!r}")
            if node_data["level_id"] is not None and node_data["level_id"] not in LEVELS:
                raise ValueError(f"saved run's map references an unrecognized level id {node_data['level_id']!r}")
    for target_ids in run_data["map"]["edges"].values():
        for target_id in target_ids:
            if target_id not in node_ids:
                raise ValueError(f"saved run's map has an edge to an unrecognized node id {target_id!r}")
    # A resumable save is always mid-PLAYING (see Game.can_save_run()) --
    # structurally always a combat/elite node, never a Shop/Event/Rest/
    # Treasure screen, none of which are reachable while WaveManager is
    # between waves.
    current_node = next(
        (node_data for row in run_data["map"]["rows"] for node_data in row if node_data["id"] == run_data["current_node_id"]),
        None,
    )
    if current_node is None:
        raise ValueError(f"saved run's current_node_id {run_data['current_node_id']!r} is not in its own map")
    if current_node["node_type"] not in ("combat", "elite"):
        raise ValueError(f"saved run's current node is a {current_node['node_type']!r} node, not resumable mid-PLAYING")
    for node_id in run_data["visited_node_ids"]:
        if node_id not in node_ids:
            raise ValueError(f"saved run's visited_node_ids references an unrecognized node id {node_id!r}")
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
