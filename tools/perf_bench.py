"""Perf bench -- frame-time numbers for a deterministic late-game board (not part of the game).

Builds the heaviest board the game realistically reaches: the final act's
endless boss floor, a dense grid of towers of every type (upgraded, some
specialized), and the live enemy count topped up to a target (endless mode
grows it without bound). Then it measures `Game.update(dt)` and
`Game.render()` separately, frame by frame, and prints mean/p95 ms for each.

Every run is deterministic: the global `random` module is seeded and the run
itself has a fixed seed, so the same inputs always produce the same board.
The final line is a fingerprint of the simulation state (enemy hp/positions,
gold, kills, per-tower damage). Compare it across a code change -- an
optimization must leave it byte-identical. `--check` prints it alone.

    python tools/perf_bench.py                    # default scenario
    python tools/perf_bench.py --enemies 500 --frames 300
    python tools/perf_bench.py --profile update   # cProfile top functions (update|render|both)
    python tools/perf_bench.py --relics           # hold every non-curse relic (crits, chains, fires...)
    python tools/perf_bench.py --coverage         # also draw the V coverage overlay
    python tools/perf_bench.py --check            # just the determinism fingerprint

Writes nothing outside a temp directory.
"""

import argparse
import cProfile
import hashlib
import os
import pathlib
import pstats
import random
import statistics
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import pygame
from conftest import make_game, make_linear_run_map

from core.game import GameState
from entities.enemy import ENEMY_TYPES
from entities.tower import TOWER_TYPES
from run.relics import RELICS
from run.run_state import ACT_COUNT

SIM_STEP = 1 / 60
SEED = 12345
# Excluded from the top-up flood: one board-wide summoner is what a real
# endless tail has (see waves._ENDLESS_GROWTH_EXEMPT_SPECIES).
FLOOD_SPECIES = [name for name in ENEMY_TYPES if not name.startswith("final_boss")]


def _place_towers(game, count):
    """Round-robin every tower type over a coarse anchor sweep until `count`
    are down. Upgrades each placed tower to max, specializing every other
    one into its first option, so level/specialization drawing is exercised."""
    grid = game.grid
    names = list(TOWER_TYPES)
    path_points = [grid.tile_to_pixel_center(*cell) for cell in sorted(grid.path_cells)]
    anchors = [(col, row) for row in range(0, grid.sub_rows, 2) for col in range(0, grid.sub_cols, 2)]
    # Nearest-to-the-path first, so the towers actually engage.
    anchors.sort(key=lambda anchor: min(
        grid.anchor_to_pixel_center(*anchor).distance_squared_to(point) for point in path_points))
    path_anchors = [(col * grid.subtiles_per_tile, row * grid.subtiles_per_tile)
                    for col, row in sorted(grid.path_cells)]
    placed = 0
    index = 0
    misses = 0
    while placed < count and misses < len(names):
        name = names[index % len(names)]
        index += 1
        cls = TOWER_TYPES[name]
        game.selected_tower_name = name
        pool = path_anchors if cls.PLACEMENT == "path" else anchors
        before = len(game.towers)
        for anchor in pool:
            if game.try_place_tower(*anchor):
                break
        if len(game.towers) == before:
            misses += 1
            continue
        misses = 0
        placed += 1
        tower = game.towers[-1]
        while tower.upgrade_cost() is not None and game.try_upgrade_tower(tower):
            pass
        if tower.can_specialize and placed % 2 == 0:
            game.try_specialize_tower(tower, next(iter(tower.SPECIALIZATIONS)))
    game.selected_tower_name = None
    return placed


def _top_up(game, target, flood_index):
    """Spawn enemies straight onto the board until `target` are live,
    cycling FLOOD_SPECIES across every spawn cell (routes come from the
    WaveManager's own seeded rng, so this stays deterministic)."""
    manager = game.wave_manager
    spawns = sorted(manager.level.spawn_cells)
    while len(game.enemies) < target:
        cls = ENEMY_TYPES[FLOOD_SPECIES[flood_index % len(FLOOD_SPECIES)]]
        spawn = spawns[flood_index % len(spawns)]
        flood_index += 1
        game.enemies.append(manager._spawn_enemy(spawn, cls))
    return flood_index


def build_scenario(level, towers, enemies, warmup, with_relics=False):
    random.seed(SEED)
    game = make_game(pathlib.Path(tempfile.mkdtemp()), unlimited_gold=True)
    game.start_new_run(seed=SEED)
    run = game.active_run
    run.map = make_linear_run_map(["boss"], level_id=level)
    run.act = ACT_COUNT - 1
    run.unlocked_towers = list(TOWER_TYPES)
    if with_relics:
        # Every non-curse relic at once: exercises the crit/chain/overkill/
        # poison-spread/ground-fire paths an optimization could reorder.
        run.relics = [key for key, relic in RELICS.items() if not relic.is_curse]
    game._enter_node("0-0")
    game._rebuild_button_rects()
    assert game.wave_manager.endless, "the final act's boss floor should load endless"
    placed = _place_towers(game, towers)
    game.economy.lives = 10 ** 9
    flood_index = 0
    game.wave_manager.skip_delay()
    for _ in range(warmup):
        flood_index = _top_up(game, enemies, flood_index)
        game.wave_manager.skip_delay()
        game.update(SIM_STEP)
        game.render()
    return game, placed, flood_index


def fingerprint(game):
    """A hash of everything an optimization must not change."""
    parts = [
        f"gold={game.economy.gold} lives={game.economy.lives} wave={game.wave_manager.wave_index}",
        f"enemies={len(game.enemies)} projectiles={len(game.projectiles)}",
        f"rings={len(game.impact_effects)} texts={len(game.damage_numbers)} fires={len(game.ground_fires)}",
    ]
    for enemy in game.enemies:
        parts.append(f"{type(enemy).__name__} {enemy.hp!r} {enemy.pos.x!r} {enemy.pos.y!r}")
    for tower in game.towers:
        parts.append(f"{type(tower).__name__} {tower.damage_dealt!r} {tower.kills} {tower.shots_fired}")
    for projectile in game.projectiles:
        parts.append(f"p {projectile.pos.x!r} {projectile.pos.y!r}")
    random_state = repr(random.getstate()[1][:4])
    parts.append(random_state)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def frame_hash(game):
    """A hash of the last rendered frame's pixels -- a render cache must
    leave it unchanged too."""
    return hashlib.sha256(pygame.image.tobytes(game.screen, "RGBA")).hexdigest()[:16]


def _percentile(samples, fraction):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def measure(game, frames, enemies, flood_index, profile=None):
    update_ms, render_ms = [], []
    profiler = cProfile.Profile() if profile else None
    for _ in range(frames):
        flood_index = _top_up(game, enemies, flood_index)
        game.wave_manager.skip_delay()
        if profiler and profile in ("update", "both"):
            profiler.enable()
        start = time.perf_counter()
        game.update(SIM_STEP)
        if profiler and profile == "update":
            profiler.disable()
        if profiler and profile == "render":
            profiler.enable()
        mid = time.perf_counter()
        game.render()
        end = time.perf_counter()
        if profiler:
            profiler.disable()
        update_ms.append((mid - start) * 1000)
        render_ms.append((end - mid) * 1000)
        if game.state != GameState.PLAYING:
            raise SystemExit(f"left PLAYING after {len(update_ms)} frames: {game.state}")
    return update_ms, render_ms, profiler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--level", type=int, default=9, help="LEVELS id (default 9, three spawns)")
    parser.add_argument("--towers", type=int, default=80, help="towers to place, round-robin over every type")
    parser.add_argument("--enemies", type=int, default=300, help="live enemies kept on the board")
    parser.add_argument("--warmup", type=int, default=600, help="frames simulated before measuring")
    parser.add_argument("--frames", type=int, default=300, help="frames measured")
    parser.add_argument("--relics", action="store_true", help="hold every non-curse relic (proc-heavy)")
    parser.add_argument("--coverage", action="store_true", help="draw the V coverage overlay too")
    parser.add_argument("--profile", choices=("update", "render", "both"), help="cProfile the measured frames")
    parser.add_argument("--top", type=int, default=30, help="functions shown with --profile")
    parser.add_argument("--check", action="store_true", help="print only the determinism fingerprint")
    args = parser.parse_args(argv)

    game, placed, flood_index = build_scenario(args.level, args.towers, args.enemies, args.warmup, args.relics)
    game.show_coverage = args.coverage
    update_ms, render_ms, profiler = measure(game, args.frames, args.enemies, flood_index, args.profile)
    if args.check:
        print(f"fingerprint {fingerprint(game)}  frame {frame_hash(game)}")
        return
    print(f"level {args.level}, {placed} towers, {len(game.enemies)} enemies, "
          f"{len(game.projectiles)} projectiles, {len(game.impact_effects)} rings, "
          f"{len(game.damage_numbers)} damage numbers, {len(game.ground_fires)} ground fires, wave {game.wave_manager.current_wave_number}")
    for label, samples in (("update", update_ms), ("render", render_ms)):
        print(f"{label:7} mean {statistics.fmean(samples):7.2f} ms   median {statistics.median(samples):7.2f} ms   "
              f"p95 {_percentile(samples, 0.95):7.2f} ms")
    if profiler:
        pstats.Stats(profiler).sort_stats("cumulative").print_stats(args.top)
        pstats.Stats(profiler).sort_stats("tottime").print_stats(args.top)
    print(f"fingerprint {fingerprint(game)}  frame {frame_hash(game)}")


if __name__ == "__main__":
    main()
