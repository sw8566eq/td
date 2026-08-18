# Tower Defense

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
pressing `Space`. `P` pauses. `R` restarts from the game-over/victory
screen. `Esc` quits.

Run the test suite with `pytest` (from the venv).

## Art

No art pack is bundled yet -- every sprite renders as a simple colored
placeholder shape (see `assets.py`). Drop a CC0 pixel-art pack's PNGs into
`assets/towers/`, `assets/enemies/`, `assets/tiles/`, `assets/projectiles/`
using the filenames listed in `SPRITE_MANIFEST` (in `assets.py`) and the
real art will appear automatically -- no code changes needed. If the pack
uses different filenames, just edit the path strings in that manifest.

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

## Layout

The window is `PLAY_WIDTH` (the grid + the HUD bar beneath it) plus a
fixed `PANEL_WIDTH` stats sidebar on the right (both in `settings.py`) --
the window was simply grown to fit the sidebar rather than shrinking the
grid. `ui.draw_tower_stats_panel()` reads a tower class's plain stats
(`cost`/`damage`/`range`/`fire_rate`) plus its `EXTRA_STATS` (see below)
to render the panel, so it needs no changes for new tower types.

## Enemies

Three species: `GruntEnemy` (baseline), `ScoutEnemy` (fast, low HP --
also the one that gets shoved back furthest by the knockback tower, since
its knockback distance scales with the target's own speed), and
`TankEnemy` (slow, high HP -- an easy target to keep in range, and frost's
slow hits especially hard on something already slow). Level 1's
`LEVEL_1_WAVE_SPECS` (in `levels.py`) introduces them gradually: grunts
only through wave 2, scouts join at wave 3, tanks at wave 5.

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
  generically, so this needs no other changes. (All levels currently share
  the same map size, set in `settings.py` -- only the path/waves differ.)
