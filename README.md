# Tower Defense

[![Tests](https://github.com/sw8566eq/td/actions/workflows/tests.yml/badge.svg)](https://github.com/sw8566eq/td/actions/workflows/tests.yml)

A minimal, extensible tower defense game built with Python + Pygame.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Controls: press any key at the menu to start. Click a tower button in the
bottom bar, then click a grass tile to place it -- the sidebar on the
right shows that tower type's stats while it's selected; right-click at
any time to clear the current selection without placing anything. Hover
any placed
tower to see its live stats and range in the sidebar; it also shows a
small "+cost" badge in its tile's top-right corner -- click *that*
specifically to upgrade it (caps at level 3 -- see "Tower levels" below
-- hovering shows what the upgrade would change). The badge disappears
once a tower is maxed. The HUD shows a countdown to the next wave and a
"Skip" button (bottom-right) to force it to start early -- same effect as
pressing `Space`. `P` or `Esc` opens the pause menu; the same two keys
close it again, `R` restarts the current level, `Q` quits. `R` also
restarts the level from the game-over screen, or -- from the victory
screen -- advances to the next level if there is one, otherwise replays
the level you just won. `Esc` quits from the main menu, game-over, or
victory screens (there's no pause menu to open there).

Run the test suite with `pytest` (from the venv) -- ~200 tests covering
every module, including `Game`'s full state machine, click/key handling,
and update loop (`tests/test_game.py`) and `AssetManager`'s placeholder
fallback and caching (`tests/test_assets.py`). Both of those open a real
pygame window, so they force the SDL dummy video driver themselves
(`os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` at the top of the
file) -- `pytest` runs headless with no extra setup, in CI or anywhere
else.

## Art

No art pack is bundled yet -- every sprite renders as a simple colored
placeholder shape (see `assets.py`). Drop a CC0 pixel-art pack's PNGs into
`assets/towers/`, `assets/enemies/`, `assets/tiles/`, `assets/projectiles/`
using the filenames listed in `SPRITE_MANIFEST` (in `assets.py`) and the
real art will appear automatically -- no code changes needed. If the pack
uses different filenames, just edit the path strings in that manifest.

## Towers

Five so far: `BasicTower` (cheap single-target), `CannonTower` (splash
damage), `FrostTower` (slows), `KnockbackTower` (AoE + a light shove back
along the path), and `LightningTower` -- hits its target, then arcs to
the *nearest enemy it hasn't already hit this shot* within `chain_range`
(50px -- short, since nothing else bounds the chain) of wherever the bolt
currently is (not the tower), repeating for as long as there's an
unvisited enemy left in range -- `max_chain_targets` is `float("inf")`,
so a dense enough cluster gets fully chained through, not capped at some
fixed count. That's genuinely different from Cannon's splash: splash hits
everyone within a radius of one impact point simultaneously, chain hits a
*sequence* of individual enemies, each becoming the next jump's origin,
so it can reach targets strung out along the path rather than just
clustered together. See `Projectile._resolve_chain()` in `projectile.py`.

## Tower levels

Every tower can be upgraded twice (level 1 -> 3) by clicking its "+cost"
badge in-game (`Tower.upgrade_badge_center`/`contains_upgrade_badge` in
`tower.py` own the badge's position and hit-testing, so drawing and
clicking can never disagree about where it is).
Each level multiplies `damage` and `range` by a fixed amount (see
`Tower.LEVEL_STAT_MULTIPLIERS` in `tower.py`); the upgrade's gold cost is a
multiplier of that tower's base `cost` (`Tower.UPGRADE_COST_MULTIPLIERS`).
This is generic on the `Tower` base class, so new tower types get levels
for free. A tower can opt its own special stat into scaling too by
extending `LEVEL_SCALED_STATS`, e.g. `LEVEL_SCALED_STATS = Tower.LEVEL_SCALED_STATS
+ ("slow_duration",)` -- just make sure "bigger is better" actually holds
for that stat (it wouldn't for `FrostTower.slow_factor`, where lower is
stronger).

A stat can also scale on its *own* curve instead of the shared one via
`LEVEL_STAT_MULTIPLIER_OVERRIDES`, e.g. `BasicTower` uses
`{"damage": {1: 1.0, 2: 1.7, 3: 2.6}}` so it hits much harder at level 2/3
than the generic curve would give it (10 -> 17 -> 26, vs. the ~10 -> 13.5
-> 18 the shared curve produces) while its `range` still scales normally
-- balance doesn't have to mean every tower's numbers grow at the same
rate to feel worth using.

## Layout

The window is `PLAY_WIDTH` (the grid + the HUD bar beneath it) plus a
fixed `PANEL_WIDTH` stats sidebar on the right (both in `settings.py`) --
the window was simply grown to fit the sidebar rather than shrinking the
grid. `ui.draw_tower_stats_panel()` reads a tower class's plain stats
(`cost`/`damage`/`range`/`fire_rate`) plus its `EXTRA_STATS` (see below)
to render the panel, so it needs no changes for new tower types.

## Enemies

Four species: `GruntEnemy` (baseline), `ScoutEnemy` (fast, low HP -- also
the one that gets shoved back furthest by the knockback tower, since its
knockback distance scales with the target's own speed), `TankEnemy` (slow,
high HP -- an easy target to keep in range, and frost's slow hits
especially hard on something already slow), and `BossEnemy` (a level's
one-off final-wave heavyweight: dramatically more HP and gold reward,
moving at a deliberate crawl). Each level's `wave_specs` introduces the
regular species gradually and puts exactly one boss in the final wave --
see `test_every_levels_final_wave_includes_a_boss` in
`tests/test_levels.py` for that as an enforced invariant, not just a
convention.

## Levels

Two so far, both 5 waves: `LEVELS[1]` ("Winding Road") and `LEVELS[2]`
("Serpentine Pass", a tighter, more switchback-heavy path). Beating a
level's boss wave shows a "Level Complete!" screen; `R` advances to the
next level (`Game.advance_or_replay_level()`), starting that level's
economy fresh. Winning the last registered level shows "Victory!"
instead, and `R` there just replays it.

## Adding content

The game is built so new content is additive -- a new subclass or registry
entry, not a change to the systems that already work.

- **New tower**: subclass `Tower` in `tower.py`, set its stats
  (`cost`/`range`/`damage`/`fire_rate`/`sprite_name`) and implement
  `create_projectile()`, then add it to `TOWER_TYPES`. It shows up in the
  build menu automatically. If it has its own special mechanic (splash,
  slow, knockback, ...), list it in `EXTRA_STATS` as
  `(label, attribute_name, format_function)` and it shows up in the stats
  panel automatically too.
- **New enemy**: subclass `Enemy` in `enemy.py`, override its stats
  (`base_hp`, `base_speed`, `base_reward`, etc. -- or `update()`/
  `take_damage()` too, for something like a shielded unit), then add it to
  `ENEMY_TYPES` under a short name. Reference that name from a level's
  `wave_specs` to use it.
- **New level**: add a `Level(...)` entry to `LEVELS` in `levels.py` with
  its own path (`waypoints_tiles`), wave composition (`wave_specs`, a list
  of `{enemy_type_name: count}` dicts -- one per wave, hand-authored or via
  `generate_default_waves()`), and starting gold/lives. `Grid`,
  `WaveManager`, and `Game` all consume whichever level is active
  generically, so this needs no other changes -- registering it is also
  what makes it reachable: winning the level before it in numeric order
  will offer to advance into it. (All levels currently share the same map
  size, set in `settings.py` -- only the path/waves differ.) Give its
  final wave a `"boss": 1` entry to match every other level -- enforced by
  `tests/test_levels.py::test_every_levels_final_wave_includes_a_boss`.
