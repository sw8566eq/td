"""Tower bench -- a quick, repeatable balance check (not part of the game).

Gives every attacking tower type the same gold on the same floor at Act 1,
2 and 3 depth, places as many as it can afford greedily by path coverage
(path traps on path tiles, everything else beside the path), runs every
wave headless, and prints leaks and total damage per act. Optionally pairs
each type with one "extra" piece placed first (e.g. a Barricade).

It's a crude, mono-tower, no-upgrades, no-relics model -- good for spotting
outliers (a tower that holds a wave forever, one that never connects), not
for tuning exact numbers. Writes nothing outside a temp directory.

    python tools/tower_bench.py                 # each floor's real starting gold
    python tools/tower_bench.py --budget 300    # a fixed budget
    python tools/tower_bench.py --level 5 --towers basic mortar --extra barricade
"""

import argparse
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from conftest import make_game, make_linear_run_map

from core.game import GameState
from entities.tower import TOWER_TYPES

SIM_STEP = 1 / 30
SIM_LIMIT_SECONDS = 900


def _candidate_anchors(game, cls):
    grid = game.grid
    per_tile = grid.subtiles_per_tile
    if cls.PLACEMENT == "path":
        return [(col * per_tile, row * per_tile) for col, row in grid.path_cells]
    step = max(1, per_tile // 2)
    return [(col, row) for row in range(0, grid.sub_rows, step) for col in range(0, grid.sub_cols, step)]


def _coverage(game, cls, anchor, path_points):
    pos = game.grid.anchor_to_pixel_center(*anchor, footprint_subtiles=game._footprint_for(cls))
    reach = max(cls.range, 40)
    return sum(1 for point in path_points if cls.MIN_RANGE <= pos.distance_to(point) <= reach)


def run_bench(tower, act, budget=0, level=3, extra=None, seed=1):
    """One floor: returns {gold, placed, leaked ("DEAD" on a loss), damage}."""
    game = make_game(pathlib.Path(tempfile.mkdtemp()))
    game.start_new_run(seed=seed)
    run = game.active_run
    run.map = make_linear_run_map(["combat", "combat"], level_id=level)
    run.act = act
    run.unlocked_towers = list(TOWER_TYPES)
    game._enter_node("0-0")
    game._rebuild_button_rects()
    if budget:
        game.economy.gold = budget
    start_gold = game.economy.gold
    path_points = [game.grid.tile_to_pixel_center(*cell) for cell in game.grid.path_cells]
    placed = 0
    for name in ([extra] if extra else []) + [tower]:
        cls = TOWER_TYPES[name]
        game.selected_tower_name = name
        ranked = sorted(_candidate_anchors(game, cls), key=lambda anchor: -_coverage(game, cls, anchor, path_points))
        for anchor in ranked:
            if game.economy.gold < cls.cost:
                break
            if game.try_place_tower(*anchor):
                placed += 1
                if name == extra:
                    break  # one extra piece only
    lives = game.economy.lives
    elapsed = 0.0
    while game.state == GameState.PLAYING and elapsed < SIM_LIMIT_SECONDS:
        game.wave_manager.skip_delay()
        game.update(SIM_STEP)
        elapsed += SIM_STEP
    damage = sum(t.damage_dealt for t in game.towers + game.sold_towers)
    leaked = "DEAD" if game.state == GameState.GAME_OVER else lives - game.economy.lives
    return {"gold": start_gold, "placed": placed, "leaked": leaked, "damage": round(damage)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget", type=int, default=0, help="fixed gold (default: the floor's own)")
    parser.add_argument("--level", type=int, default=3)
    parser.add_argument("--towers", nargs="*", help="tower types (default: every attacking type)")
    parser.add_argument("--extra", help="one extra piece placed first, e.g. barricade")
    args = parser.parse_args(argv)
    towers = args.towers or [name for name, cls in TOWER_TYPES.items() if cls.ATTACKS and not cls.IS_SUPPORT]
    print(f"{'tower':18}" + "".join(f"{'act ' + str(act + 1):<18}" for act in range(3)))
    for tower in towers:
        cells = []
        for act in range(3):
            result = run_bench(tower, act, args.budget, args.level, args.extra)
            cells.append(f"{result['leaked']!s:>4} lk {result['damage']:>7} dmg")
        print(f"{tower:18}" + "  ".join(cells))


if __name__ == "__main__":
    main()
