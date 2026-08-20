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

Pass `--unlimited-gold` to run with a debug flag that makes every purchase (placing, upgrading, or
specializing a tower) always succeed without actually spending gold -- the HUD shows
"Gold: unlimited" while it's on. Pass `--editor` to launch straight into the map editor instead of
the main menu (see "Map editor" below).

Controls: press any key at the menu to start, `E` to open the map editor, or `L` to pick from the
built-in levels plus any you've saved from the editor. Click a tower button in the bottom bar, then click
a grass tile to place it -- the sidebar on the right shows that tower type's stats while it's
selected; right-click at any time to clear the current selection without placing anything. A
tower's required footprint is one tile's worth of space, but it isn't locked to the tile grid --
see "Tower placement" below for how that works and what the footprint outline that follows your
cursor is showing you.

Hover any placed tower to see its live stats and range in the sidebar; **click** it instead and
that stays pinned open even once the mouse moves away, until you click a different tower, pick a
build-menu type, or click empty ground with nothing selected. The pinned/hovered panel shows
**Upgrade** and **Sell** buttons (in addition to the small "+cost" badge in the tower's tile
corner, which still works too), and at max level, Upgrade is replaced by two **Specialize**
buttons -- see "Tower levels & specialization" below. Selling refunds a fraction of everything
spent on that tower (`settings.SELL_REFUND_FRACTION`) and frees its space immediately.

The HUD shows a countdown to the next wave and a button (bottom-right) that reads "Start" before
the first wave -- it waits for you rather than auto-starting, so you get a beat to place towers
first -- and "Skip" for every wave after that, forcing the between-wave delay to end early. `Space`
does the same thing as clicking it. `P` or `Esc` opens the pause menu; the same two keys close it
again, `R` restarts the current level, `Q` quits. `R` also restarts the level from the game-over
screen, or -- from the victory screen -- advances to the next level if there is one, otherwise
replays the level you just won. `Esc` quits from the main menu, game-over, or victory screens
(there's no pause menu to open there).

Run the test suite with `pytest` (from the venv) -- 350+ tests covering every module, including
`Game`'s full state machine, click/key handling, and update loop (`tests/test_game.py`) and
`AssetManager`'s placeholder fallback and caching (`tests/test_assets.py`). Both of those open a
real pygame window, so they force the SDL dummy video driver themselves
(`os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` at the top of the file) -- `pytest` runs
headless with no extra setup, in CI or anywhere else.

## Art

No art pack is bundled yet -- every sprite renders as a simple colored placeholder shape (see
`assets.py`). Drop a CC0 pixel-art pack's PNGs into `assets/towers/`, `assets/enemies/`,
`assets/tiles/`, `assets/projectiles/` using the filenames listed in `SPRITE_MANIFEST` (in
`assets.py`) and the real art will appear automatically -- no code changes needed. If the pack uses
different filenames, just edit the path strings in that manifest.

## Tower placement

Each tile is cut into an 8x8 grid of small tiles (`settings.SUBTILES_PER_TILE`), and a tower's
required footprint is exactly one tile's worth of area -- 8x8 small tiles -- but it can be
*anchored* at any small tile, not just where a tile boundary falls. Moving the build cursor shifts
the footprint preview (a colored outline: white/valid, red/blocked) in small-tile increments
rather than snapping a whole tile at a time, so a tower can straddle what used to be a tile
boundary, tuck up against a path bend more precisely, or line up a row of towers' ranges exactly.
Two footprints can never overlap even partially, regardless of whether their anchors happen to
line up on any particular grid (`Grid.is_buildable`/`occupy`/`remove` in `grid.py`), so this is
purely about placement *precision* -- it doesn't let you fit more towers into the same space.

The map itself renders each buildable tile as that same 8x8 mosaic of individually-drawn small
tiles with a thin, soft-edged gap between them (`Grid._build_background`, cached once per level
rather than redrawn every frame), so the placement grid is visible at a glance without being
visually harsh. The path renders as one unbroken tile -- no seams -- since it's never buildable
anyway.

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

## Tower levels & specialization

Every tower can be upgraded twice (level 1 -> 3) by clicking its "+cost" badge in-game, or the
sidebar's Upgrade button while it's pinned/hovered (`Tower.upgrade_badge_center`/
`contains_upgrade_badge` in `tower.py` own the badge's position and hit-testing, so drawing and
clicking can never disagree about where it is). Each level multiplies `damage` and `range` by a
fixed amount (see `Tower.LEVEL_STAT_MULTIPLIERS` in `tower.py`); the upgrade's gold cost is a
multiplier of that tower's base `cost` (`Tower.UPGRADE_COST_MULTIPLIERS`). This is generic on the
`Tower` base class, so new tower types get levels for free. A tower can opt its own special stat
into scaling too by extending `LEVEL_SCALED_STATS`, e.g. `LEVEL_SCALED_STATS =
Tower.LEVEL_SCALED_STATS + ("slow_duration",)` -- just make sure "bigger is better" actually holds
for that stat (it wouldn't for `FrostTower.slow_factor`, where lower is stronger).

A stat can also scale on its *own* curve instead of the shared one via
`LEVEL_STAT_MULTIPLIER_OVERRIDES`, e.g. `BasicTower` uses
`{"damage": {1: 1.0, 2: 1.7, 3: 2.6}}` so it hits much harder at level 2/3
than the generic curve would give it (10 -> 17 -> 26, vs. the ~10 -> 13.5
-> 18 the shared curve produces) while its `range` still scales normally
-- balance doesn't have to mean every tower's numbers grow at the same
rate to feel worth using.

Once a tower hits level 3, it can choose one of two named **specializations**
(`Tower.SPECIALIZATIONS`) instead of leveling further -- a one-time branching choice, separate
from `level` (`Tower.can_specialize`/`specialize()`). Every tower currently shares the same two
generic placeholder options ("Power": +30% damage, "Precision": +20% range and fire rate) defined
on the base class; a specific tower can override `SPECIALIZATIONS` to offer its own paths instead.
The numbers here are intentionally rough starting points, not tuned balance.

Selling a tower (the sidebar's Sell button) refunds `settings.SELL_REFUND_FRACTION` of
`Tower.total_invested` -- everything spent placing, upgrading, *and* specializing it, not just the
base cost -- and immediately frees its footprint.

## Layout

The window is `PLAY_WIDTH` (the grid + the HUD bar beneath it) plus a
fixed `PANEL_WIDTH` stats sidebar on the right (both in `settings.py`) --
the window was simply grown to fit the sidebar rather than shrinking the
grid. `ui.draw_tower_stats_panel()` reads a tower class's plain stats
(`cost`/`damage`/`range`/`fire_rate`) plus its `EXTRA_STATS` (see below)
to render the panel, so it needs no changes for new tower types. Its Upgrade/Specialize/Sell
buttons sit at fixed positions in the panel (`ui.py`'s `ACTION_AREA_TOP`/`SELL_BUTTON_TOP`)
regardless of which tower's stats are shown above them.

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

Two built in so far, both 5 waves: `LEVELS[1]` ("Winding Road") and `LEVELS[2]`
("Serpentine Pass", a tighter, more switchback-heavy path). Beating a
level's boss wave shows a "Level Complete!" screen; `R` advances to the
next level (`Game.advance_or_replay_level()`), starting that level's
economy fresh. Winning the last registered level shows "Victory!"
instead, and `R` there just replays it. `L` from the main menu opens a
level-select screen listing both of these and any custom levels you've
saved from the map editor.

## Map editor

`E` from the main menu (or `python main.py --editor`) opens a freeform
tile-paint editor: drag to paint or erase path tiles like a pixel brush,
and use the Spawn/Goal tools to mark where enemies start and where reaching
one costs a life. A path can **branch** (one lane fanning out into several)
and **merge** (several spawns converging on shared lanes toward a goal) --
junctions are detected automatically from the painted shape (any tile with
3+ path-neighbors), you never have to declare one yourself. Enemies pick a
direction at each branch point at random (evenly, by default).

The one rule the brush enforces is that the path can't loop back on itself
-- a lane splitting and later reconnecting downstream is a closed loop,
which is rejected the same as a literal roundabout would be. The sidebar
shows live feedback (in red) on whatever's wrong -- disconnected cells, a
missing spawn/goal, a loop -- and turns green once the path is valid, at
which point **Edit Waves** becomes clickable.

That opens the wave editor: numbered tabs across the bottom select which
wave you're editing, with **+**/**-** tabs to add or remove one (there's
always at least one). Within a wave, **+**/**-** next to each species in
the sidebar sets how many of that type spawn in it -- every wave needs at
least one unit before you can move on. **Playtest** loads the level you're
editing immediately, without saving; **Save** writes it to `custom_levels/`
(as JSON, via `persistence.py`) under a name slugged from the level's name,
where `L`'s level-select screen will find it from then on. Every wave
currently spawns its species together, one type fully before the next --
interleaving spawn order within a wave is a possible future refinement.

## Adding content

The game is built so new content is additive -- a new subclass or registry
entry, not a change to the systems that already work.

- **New tower**: subclass `Tower` in `tower.py`, set its stats
  (`cost`/`range`/`damage`/`fire_rate`/`sprite_name`) and implement
  `create_projectile()`, then add it to `TOWER_TYPES`. It shows up in the
  build menu automatically. If it has its own special mechanic (splash,
  slow, knockback, ...), list it in `EXTRA_STATS` as
  `(label, attribute_name, format_function)` and it shows up in the stats
  panel automatically too. Override `SPECIALIZATIONS` if it should offer its own two level-3
  choices instead of the generic Power/Precision placeholders.
- **New enemy**: subclass `Enemy` in `enemy.py`, override its stats
  (`base_hp`, `base_speed`, `base_reward`, etc. -- or `update()`/
  `take_damage()` too, for something like a shielded unit), then add it to
  `ENEMY_TYPES` under a short name. Reference that name from a level's
  `wave_specs` to use it.
- **New built-in level**: add a `Level(...)` entry to `LEVELS` in `levels.py` with its own path
  (`path_cells`/`spawn_cells`/`goal_cells` -- `pathing.path_cells_from_corners()` turns a terse
  ordered corner list into `path_cells` for a simple hand-written route, same as the two existing
  levels), wave composition (`wave_specs`, a list of `{enemy_type_name: count}` dicts -- one per
  wave, hand-authored or via `generate_default_waves()`), and starting gold/lives. `Grid`,
  `WaveManager`, and `Game` all consume whichever level is active generically, so this needs no
  other changes -- registering it is also what makes it reachable: winning the level before it in
  numeric order will offer to advance into it, and it's listed in `L`'s level-select screen. (All
  levels currently share the same map size, set in `settings.py` -- only the path/waves differ.)
  Give its final wave a `"boss": 1` entry to match every other level -- enforced by
  `tests/test_levels.py::test_every_levels_final_wave_includes_a_boss`. A player-made level doesn't
  need a registry entry at all -- see "Map editor" above.
